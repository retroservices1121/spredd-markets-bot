"""
Trading service that coordinates platforms and wallets.
Handles quote fetching, trade execution, and position tracking.
"""

from decimal import Decimal
from typing import Optional

from src.config import settings
from src.db.database import (
    create_order,
    update_order,
    create_position,
    get_user_by_telegram_id,
)
from src.db.models import (
    Platform,
    Chain,
    ChainFamily,
    Outcome,
    OrderStatus,
)
from src.platforms import get_platform, get_chain_family_for_platform
from src.platforms.base import Quote, TradeResult, PlatformError
from src.services.wallet import wallet_service
from src.utils.logging import get_logger, LoggerMixin

logger = get_logger(__name__)


class TradingService(LoggerMixin):
    """
    Service for executing trades across platforms.
    Coordinates between platform APIs and user wallets.
    """
    
    async def get_quote(
        self,
        telegram_id: int,
        platform: Platform,
        market_id: str,
        outcome: str,
        side: str,
        amount: Decimal,
    ) -> Quote:
        """
        Get a quote for a potential trade.
        
        Args:
            telegram_id: User's Telegram ID
            platform: Target platform
            market_id: Market identifier
            outcome: "yes" or "no"
            side: "buy" or "sell"
            amount: Amount in collateral tokens
            
        Returns:
            Quote with expected output and fees
        """
        platform_client = get_platform(platform)
        outcome_enum = Outcome(outcome.lower())
        
        quote = await platform_client.get_quote(
            market_id=market_id,
            outcome=outcome_enum,
            side=side,
            amount=amount,
        )
        
        self.log.info(
            "Quote fetched",
            platform=platform.value,
            market_id=market_id,
            outcome=outcome,
            side=side,
            amount=str(amount),
            expected_output=str(quote.expected_output),
        )
        
        return quote
    
    async def execute_trade(
        self,
        telegram_id: int,
        quote: Quote,
    ) -> TradeResult:
        """
        Execute a trade from a quote.
        
        Args:
            telegram_id: User's Telegram ID
            quote: Quote obtained from get_quote
            
        Returns:
            TradeResult with transaction details
        """
        # Get user
        user = await get_user_by_telegram_id(telegram_id)
        if not user:
            raise ValueError("User not found")
        
        # Determine chain family for this platform
        chain_family = get_chain_family_for_platform(quote.platform)
        
        # Get appropriate private key
        if chain_family == ChainFamily.SOLANA:
            private_key = await wallet_service.get_solana_keypair(
                user.id, telegram_id
            )
        else:
            private_key = await wallet_service.get_evm_account(
                user.id, telegram_id
            )
        
        if not private_key:
            raise ValueError(f"No wallet found for {chain_family.value}")

        # Get market title from quote data
        market_title = None
        if quote.quote_data and "market" in quote.quote_data:
            market_data = quote.quote_data["market"]
            market_title = market_data.get("title") or market_data.get("market_title") or market_data.get("question")

        # Create order record
        order = await create_order(
            user_id=user.id,
            platform=quote.platform,
            chain=quote.chain,
            market_id=quote.market_id,
            outcome=quote.outcome.value,
            side=quote.side,
            input_token=quote.input_token,
            input_amount=str(int(quote.input_amount * Decimal(10**6))),
            output_token=quote.output_token,
            expected_output=str(int(quote.expected_output * Decimal(10**6))),
            price=float(quote.price_per_token),
            market_title=market_title,
        )
        
        try:
            # Execute on platform
            platform_client = get_platform(quote.platform)
            result = await platform_client.execute_trade(quote, private_key)
            
            if result.success:
                # Update order as confirmed
                await update_order(
                    order.id,
                    status=OrderStatus.CONFIRMED,
                    tx_hash=result.tx_hash,
                    actual_output=str(int(result.output_amount * Decimal(10**6))) if result.output_amount else None,
                )
                
                # Create position record for buys
                if quote.side == "buy":
                    # Get market for title
                    market = await platform_client.get_market(quote.market_id)
                    market_title = market.title if market else quote.market_id
                    
                    await create_position(
                        user_id=user.id,
                        platform=quote.platform,
                        chain=quote.chain,
                        market_id=quote.market_id,
                        market_title=market_title,
                        outcome=quote.outcome.value,
                        token_id=quote.output_token,
                        token_amount=str(int(result.output_amount * Decimal(10**6))) if result.output_amount else "0",
                        entry_price=float(quote.price_per_token),
                    )
                
                self.log.info(
                    "Trade executed successfully",
                    order_id=order.id,
                    tx_hash=result.tx_hash,
                )
                
            else:
                # Update order as failed
                await update_order(
                    order.id,
                    status=OrderStatus.FAILED,
                    error_message=result.error_message,
                )
                
                self.log.error(
                    "Trade execution failed",
                    order_id=order.id,
                    error=result.error_message,
                )
            
            return result
            
        except Exception as e:
            # Update order as failed
            await update_order(
                order.id,
                status=OrderStatus.FAILED,
                error_message=str(e),
            )
            
            self.log.error(
                "Trade execution error",
                order_id=order.id,
                error=str(e),
            )
            
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message=str(e),
                explorer_url=None,
            )
    
    async def check_balance(
        self,
        telegram_id: int,
        platform: Platform,
        amount: Decimal,
    ) -> tuple[bool, str]:
        """
        Check if user has sufficient balance for a trade.
        
        Returns:
            Tuple of (has_sufficient_balance, message)
        """
        user = await get_user_by_telegram_id(telegram_id)
        if not user:
            return False, "User not found"
        
        chain_family = get_chain_family_for_platform(platform)
        balances = await wallet_service.get_all_balances(user.id)
        
        # Find collateral balance
        chain_balances = balances.get(chain_family, [])
        
        # Map platform to expected collateral
        collateral_symbols = {
            Platform.KALSHI: "USDC",
            Platform.POLYMARKET: "USDC",
            Platform.OPINION: "USDT",
        }
        
        expected_symbol = collateral_symbols.get(platform, "USDC")
        
        for bal in chain_balances:
            if bal.symbol == expected_symbol:
                if bal.amount >= amount:
                    return True, f"Balance: {bal.formatted}"
                else:
                    return False, f"Insufficient {expected_symbol}. Have: {bal.formatted}, Need: {amount}"
        
        return False, f"No {expected_symbol} balance found"


# Singleton instance
trading_service = TradingService()
