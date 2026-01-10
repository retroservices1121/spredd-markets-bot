"""
Polymarket platform implementation using CLOB API.
World's largest prediction market on Polygon.
"""

from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional, Tuple
from datetime import datetime
import json

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3

from src.config import settings
from src.db.models import Chain, Outcome, Platform
from src.platforms.base import (
    BasePlatform,
    Market,
    Quote,
    TradeResult,
    OrderBook,
    PlatformError,
    MarketNotFoundError,
    RateLimitError,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

# ERC20 ABI for USDC transfers
ERC20_TRANSFER_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]

# Polymarket contract addresses on Polygon
POLYMARKET_CONTRACTS = {
    "exchange": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "neg_risk_exchange": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "collateral": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC.e (bridged)
    "ctf": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",  # Conditional Tokens
}

# Token addresses on Polygon
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # Native USDC
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e (bridged)

# Uniswap V3 SwapRouter on Polygon
UNISWAP_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

# Minimum balance threshold for auto-swap (in USDC)
MIN_USDC_BALANCE = Decimal("5")

# Uniswap V3 SwapRouter ABI (exactInputSingle)
UNISWAP_SWAP_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"},
                ],
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function",
    }
]

# ERC20 Approve ABI
ERC20_APPROVE_ABI = [
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    }
]


class PolymarketPlatform(BasePlatform):
    """
    Polymarket prediction market platform.
    Uses CLOB (Central Limit Order Book) API on Polygon.
    """
    
    platform = Platform.POLYMARKET
    chain = Chain.POLYGON
    
    name = "Polymarket"
    description = "World's largest prediction market on Polygon"
    website = "https://polymarket.com"
    
    collateral_symbol = "USDC"
    collateral_decimals = 6
    
    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._gamma_client: Optional[httpx.AsyncClient] = None  # For market data
        self._web3: Optional[AsyncWeb3] = None
        self._sync_web3: Optional[Web3] = None  # Sync Web3 for fee collection
        self._api_creds: Optional[dict] = None
        self._fee_account = settings.evm_fee_account
        self._fee_bps = settings.evm_fee_bps

    async def initialize(self) -> None:
        """Initialize Polymarket API clients."""
        # CLOB API client
        self._http_client = httpx.AsyncClient(
            base_url=settings.polymarket_api_url,
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

        # Gamma API for market data
        self._gamma_client = httpx.AsyncClient(
            base_url="https://gamma-api.polymarket.com",
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

        # Async Web3 for Polygon
        self._web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.polygon_rpc_url)
        )

        # Sync Web3 for fee collection (py-clob-client uses sync)
        self._sync_web3 = Web3(Web3.HTTPProvider(settings.polygon_rpc_url))

        fee_enabled = bool(self._fee_account and Web3.is_address(self._fee_account))
        logger.info(
            "Polymarket platform initialized",
            fee_collection=fee_enabled,
            fee_bps=self._fee_bps if fee_enabled else 0,
        )
    
    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()
        if self._gamma_client:
            await self._gamma_client.aclose()

    # ===================
    # USDC Balance & Auto-Swap
    # ===================

    def get_usdc_balances(self, wallet_address: str) -> Tuple[Decimal, Decimal]:
        """
        Get both native USDC and USDC.e balances for a wallet.

        Returns:
            Tuple of (native_usdc_balance, bridged_usdc_balance) in USDC units
        """
        if not self._sync_web3:
            raise RuntimeError("Web3 not initialized")

        wallet = Web3.to_checksum_address(wallet_address)

        # Get native USDC balance
        native_contract = self._sync_web3.eth.contract(
            address=Web3.to_checksum_address(USDC_NATIVE),
            abi=ERC20_TRANSFER_ABI
        )
        native_balance_raw = native_contract.functions.balanceOf(wallet).call()
        native_balance = Decimal(native_balance_raw) / Decimal(10 ** 6)

        # Get USDC.e balance
        bridged_contract = self._sync_web3.eth.contract(
            address=Web3.to_checksum_address(USDC_BRIDGED),
            abi=ERC20_TRANSFER_ABI
        )
        bridged_balance_raw = bridged_contract.functions.balanceOf(wallet).call()
        bridged_balance = Decimal(bridged_balance_raw) / Decimal(10 ** 6)

        return native_balance, bridged_balance

    def swap_native_to_bridged_usdc(
        self,
        private_key: Any,
        amount: Decimal,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Swap native USDC to USDC.e using Uniswap V3.

        Args:
            private_key: User's EVM account for signing
            amount: Amount of native USDC to swap

        Returns:
            Tuple of (success, tx_hash, error_message)
        """
        from eth_account.signers.local import LocalAccount
        import time

        if not isinstance(private_key, LocalAccount):
            return False, None, "Invalid private key type"

        if not self._sync_web3:
            return False, None, "Web3 not initialized"

        try:
            wallet = private_key.address
            amount_raw = int(amount * Decimal(10 ** 6))

            # Check native USDC balance
            native_contract = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(USDC_NATIVE),
                abi=ERC20_TRANSFER_ABI + ERC20_APPROVE_ABI
            )
            balance = native_contract.functions.balanceOf(wallet).call()
            if balance < amount_raw:
                return False, None, f"Insufficient native USDC (have {Decimal(balance)/Decimal(10**6)}, need {amount})"

            # Check and set allowance for Uniswap router
            router_address = Web3.to_checksum_address(UNISWAP_V3_ROUTER)
            allowance = native_contract.functions.allowance(wallet, router_address).call()

            if allowance < amount_raw:
                logger.info("Approving Uniswap router for native USDC", amount=str(amount))
                nonce = self._sync_web3.eth.get_transaction_count(wallet)
                # Use 1.5x gas price for faster confirmation on Polygon
                base_gas_price = self._sync_web3.eth.gas_price
                gas_price = int(base_gas_price * 1.5)

                approve_tx = native_contract.functions.approve(
                    router_address,
                    2 ** 256 - 1  # Max approval
                ).build_transaction({
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                    "gas": 100000,
                    "chainId": 137,
                })

                signed_approve = self._sync_web3.eth.account.sign_transaction(approve_tx, private_key.key)
                approve_hash = self._sync_web3.eth.send_raw_transaction(signed_approve.raw_transaction)

                # Wait for approval
                self._sync_web3.eth.wait_for_transaction_receipt(approve_hash, timeout=60)
                logger.info("Approval confirmed", tx_hash=approve_hash.hex())

            # Execute swap via Uniswap V3
            router_contract = self._sync_web3.eth.contract(
                address=router_address,
                abi=UNISWAP_SWAP_ABI
            )

            # Allow 1% slippage for stablecoin swap
            min_amount_out = int(amount_raw * 99 // 100)
            deadline = int(time.time()) + 300  # 5 minutes

            swap_params = (
                Web3.to_checksum_address(USDC_NATIVE),   # tokenIn
                Web3.to_checksum_address(USDC_BRIDGED),  # tokenOut
                500,                                      # fee tier (0.05% for stablecoins)
                wallet,                                   # recipient
                deadline,                                 # deadline
                amount_raw,                               # amountIn
                min_amount_out,                           # amountOutMinimum
                0,                                        # sqrtPriceLimitX96 (0 = no limit)
            )

            nonce = self._sync_web3.eth.get_transaction_count(wallet)
            # Use 1.5x gas price for faster confirmation on Polygon
            base_gas_price = self._sync_web3.eth.gas_price
            gas_price = int(base_gas_price * 1.5)

            swap_tx = router_contract.functions.exactInputSingle(swap_params).build_transaction({
                "from": wallet,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": 200000,
                "chainId": 137,
                "value": 0,
            })

            signed_swap = self._sync_web3.eth.account.sign_transaction(swap_tx, private_key.key)
            swap_hash = self._sync_web3.eth.send_raw_transaction(signed_swap.raw_transaction)
            swap_hash_hex = swap_hash.hex()

            logger.info("Swap transaction sent", tx_hash=swap_hash_hex, amount=str(amount))

            # Wait for confirmation (120s timeout for Polygon congestion)
            receipt = self._sync_web3.eth.wait_for_transaction_receipt(swap_hash, timeout=120)
            if receipt.status != 1:
                return False, swap_hash_hex, "Swap transaction failed on-chain"

            logger.info("Swap confirmed", tx_hash=swap_hash_hex)
            return True, swap_hash_hex, None

        except Exception as e:
            logger.error("Swap failed", error=str(e))
            return False, None, str(e)

    async def ensure_usdc_balance(
        self,
        private_key: Any,
        required_amount: Decimal = MIN_USDC_BALANCE,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Ensure wallet has sufficient USDC.e for trading.

        If USDC.e < required_amount and native USDC > required_amount,
        automatically swaps native USDC to USDC.e.

        Args:
            private_key: User's EVM account
            required_amount: Minimum USDC.e balance required

        Returns:
            Tuple of (ready_to_trade, message, tx_hash)
            - ready_to_trade: True if wallet has sufficient USDC.e
            - message: Human-readable status message
            - tx_hash: Swap transaction hash if swap was performed
        """
        from eth_account.signers.local import LocalAccount

        if not isinstance(private_key, LocalAccount):
            return False, "Invalid wallet", None

        try:
            native_balance, bridged_balance = self.get_usdc_balances(private_key.address)

            logger.info(
                "USDC balance check",
                wallet=private_key.address[:10] + "...",
                native_usdc=str(native_balance),
                bridged_usdc=str(bridged_balance),
                required=str(required_amount),
            )

            # If already have enough USDC.e, good to go
            if bridged_balance >= required_amount:
                return True, f"USDC.e balance: {bridged_balance:.2f}", None

            # If not enough USDC.e but have native USDC, swap it
            if native_balance >= required_amount:
                swap_amount = native_balance  # Swap all native USDC
                message = f"Swapping {swap_amount:.2f} USDC → USDC.e..."

                success, tx_hash, error = self.swap_native_to_bridged_usdc(
                    private_key, swap_amount
                )

                if success:
                    # Check new balance
                    _, new_bridged = self.get_usdc_balances(private_key.address)
                    return True, f"Swapped! New USDC.e balance: {new_bridged:.2f}", tx_hash
                else:
                    return False, f"Swap failed: {error}", tx_hash

            # Neither has enough
            total = native_balance + bridged_balance
            return False, f"Insufficient USDC. You have {total:.2f} total (need {required_amount:.2f}). Please deposit more USDC to your wallet.", None

        except Exception as e:
            logger.error("Balance check failed", error=str(e))
            return False, f"Error checking balance: {str(e)}", None

    async def _clob_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to CLOB API."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        
        try:
            response = await self._http_client.request(method, endpoint, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.POLYMARKET)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"CLOB API error: {e.response.status_code}",
                Platform.POLYMARKET,
                str(e.response.status_code),
            )
    
    async def _gamma_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> Any:
        """Make request to Gamma API for market data."""
        if not self._gamma_client:
            raise RuntimeError("Gamma client not initialized")
        
        try:
            response = await self._gamma_client.request(method, endpoint, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.POLYMARKET)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"Gamma API error: {e.response.status_code}",
                Platform.POLYMARKET,
                str(e.response.status_code),
            )
    
    def _parse_market(self, data: dict, market_data: dict = None) -> Market:
        """Parse Polymarket market data into Market object.

        Args:
            data: Event data from Gamma API
            market_data: Optional specific market within an event (for multi-market events)
        """
        # If market_data is provided, use it (for multi-market events)
        # Otherwise, try to get the first/only market from the event
        if market_data:
            m = market_data
            title = m.get("question") or m.get("groupItemTitle") or data.get("title", "")
        else:
            markets = data.get("markets", [])
            m = markets[0] if markets else data
            title = data.get("title") or m.get("question", "")

        # Extract prices from outcomePrices - may be JSON string or list
        outcome_prices_raw = m.get("outcomePrices", [])
        yes_price = None
        no_price = None

        # Parse JSON string if needed
        outcome_prices = outcome_prices_raw
        if isinstance(outcome_prices_raw, str):
            try:
                outcome_prices = json.loads(outcome_prices_raw)
            except:
                outcome_prices = []

        if outcome_prices and len(outcome_prices) >= 2:
            try:
                yes_price = Decimal(str(outcome_prices[0]))
                no_price = Decimal(str(outcome_prices[1]))
            except:
                pass

        # Fallback to lastTradePrice if outcomePrices not available
        if yes_price is None:
            last_price = m.get("lastTradePrice")
            if last_price is not None:
                try:
                    yes_price = Decimal(str(last_price))
                    no_price = Decimal("1") - yes_price
                except:
                    pass

        # Extract token IDs from clobTokenIds - may be JSON string or list
        tokens_raw = m.get("clobTokenIds", [])
        tokens = tokens_raw
        if isinstance(tokens_raw, str):
            try:
                tokens = json.loads(tokens_raw)
            except:
                tokens = []

        yes_token = tokens[0] if len(tokens) > 0 else None
        no_token = tokens[1] if len(tokens) > 1 else None

        # Get condition ID (market identifier)
        market_id = m.get("conditionId") or data.get("conditionId") or str(m.get("id") or data.get("id"))

        # Volume - try multiple fields
        volume = m.get("volume") or m.get("volumeNum") or data.get("volume") or data.get("volume24hr") or 0
        liquidity = m.get("liquidity") or data.get("liquidity") or data.get("liquidityClob") or 0

        return Market(
            platform=Platform.POLYMARKET,
            chain=Chain.POLYGON,
            market_id=market_id,
            event_id=str(data.get("id") or data.get("slug", "")),
            title=title,
            description=m.get("description") or data.get("description"),
            category=(data.get("tags", [{}])[0].get("label") if data.get("tags") else None),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(volume)),
            liquidity=Decimal(str(liquidity)),
            is_active=m.get("active", True) and not m.get("closed", False),
            close_time=m.get("endDate") or m.get("endDateIso") or data.get("endDate"),
            yes_token=yes_token,
            no_token=no_token,
            raw_data={"event": data, "market": m},
        )
    
    # ===================
    # Market Discovery
    # ===================

    async def get_markets(
        self,
        limit: int = 50,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Gamma API.

        Args:
            limit: Maximum number of markets to return
            offset: Number of events to skip (for pagination)
            active_only: Only return active, non-closed markets
        """
        # Fetch more events than limit to account for multi-market events
        fetch_limit = min(limit + 20, 100)

        params = {
            "limit": fetch_limit,
            "offset": offset,
            "order": "volume24hr",
            "ascending": "false",
        }
        if active_only:
            params["active"] = "true"
            params["closed"] = "false"

        data = await self._gamma_request("GET", "/events", params=params)

        markets = []
        for event in data if isinstance(data, list) else []:
            try:
                event_markets = event.get("markets", [])

                if len(event_markets) <= 1:
                    # Single market event - parse as one market
                    markets.append(self._parse_market(event))
                else:
                    # Multi-market event - expand each market as separate entry
                    for market_data in event_markets:
                        if market_data.get("active", True) and not market_data.get("closed", False):
                            markets.append(self._parse_market(event, market_data))

                # Stop if we have enough markets
                if len(markets) >= limit:
                    break

            except Exception as e:
                logger.warning("Failed to parse market", error=str(e), event_id=event.get("id"))

        return markets[:limit]
    
    async def search_markets(
        self,
        query: str,
        limit: int = 20,
    ) -> list[Market]:
        """Search markets by query."""
        # Fetch events and filter by query
        try:
            data = await self._gamma_request("GET", "/events", params={
                "active": "true",
                "closed": "false",
                "limit": 100,
            })
        except Exception as e:
            logger.error("Failed to fetch events for search", error=str(e))
            return []

        # Filter by query
        query_lower = query.lower()
        filtered_events = []
        for event in data if isinstance(data, list) else []:
            title = event.get("title", "").lower()
            desc = event.get("description", "").lower()
            if query_lower in title or query_lower in desc:
                filtered_events.append(event)
            else:
                # Also check market questions within the event
                for m in event.get("markets", []):
                    if query_lower in m.get("question", "").lower():
                        filtered_events.append(event)
                        break

        markets = []
        for event in filtered_events:
            try:
                event_markets = event.get("markets", [])
                if len(event_markets) <= 1:
                    markets.append(self._parse_market(event))
                else:
                    for market_data in event_markets:
                        if market_data.get("active", True) and not market_data.get("closed", False):
                            markets.append(self._parse_market(event, market_data))

                if len(markets) >= limit:
                    break
            except Exception as e:
                logger.warning("Failed to parse market in search", error=str(e))

        return markets[:limit]
    
    async def get_market(self, market_id: str) -> Optional[Market]:
        """Get a specific market by condition ID, event ID, or slug.

        Supports partial matching for truncated condition IDs (Telegram callback limit).
        """
        try:
            # Fetch events ordered by volume (same as get_markets) to maximize chance of finding
            data = await self._gamma_request("GET", "/events", params={
                "active": "true",
                "closed": "false",
                "limit": 200,  # Fetch more to increase coverage
                "order": "volume24hr",
                "ascending": "false",
            })

            for event in data if isinstance(data, list) else []:
                # Check event-level condition ID (exact or partial match)
                event_cond = event.get("conditionId", "")
                if event_cond and (event_cond == market_id or event_cond.startswith(market_id)):
                    return self._parse_market(event)

                # Check event ID
                if str(event.get("id")) == market_id:
                    return self._parse_market(event)

                # Check each market's condition ID (exact or partial match)
                for m in event.get("markets", []):
                    m_cond = m.get("conditionId", "")
                    m_id = str(m.get("id", ""))
                    if m_cond and (m_cond == market_id or m_cond.startswith(market_id)):
                        return self._parse_market(event, m)
                    if m_id == market_id:
                        return self._parse_market(event, m)

            # Fallback: try by slug (unlikely to work with truncated IDs)
            data = await self._gamma_request("GET", "/events", params={"slug": market_id})
            if data and len(data) > 0:
                return self._parse_market(data[0])

        except Exception as e:
            logger.warning("Failed to get market", market_id=market_id, error=str(e))

        return None

    async def get_trending_markets(self, limit: int = 20) -> list[Market]:
        """Get trending markets by volume."""
        return await self.get_markets(limit=limit, active_only=True)
    
    # ===================
    # Order Book
    # ===================
    
    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
    ) -> OrderBook:
        """Get order book from CLOB API."""
        # Need token ID for orderbook
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.POLYMARKET)
        
        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.POLYMARKET)
        
        data = await self._clob_request("GET", f"/book?token_id={token_id}")
        
        bids = []
        asks = []
        
        for bid in data.get("bids", []):
            bids.append((
                Decimal(str(bid.get("price", 0))),
                Decimal(str(bid.get("size", 0))),
            ))
        
        for ask in data.get("asks", []):
            asks.append((
                Decimal(str(ask.get("price", 0))),
                Decimal(str(ask.get("size", 0))),
            ))
        
        return OrderBook(
            market_id=market_id,
            outcome=outcome,
            bids=bids,
            asks=asks,
        )
    
    # ===================
    # Trading
    # ===================
    
    async def get_quote(
        self,
        market_id: str,
        outcome: Outcome,
        side: str,
        amount: Decimal,
    ) -> Quote:
        """Get a quote for a trade."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.POLYMARKET)
        
        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.POLYMARKET)
        
        # Get current price from orderbook
        orderbook = await self.get_orderbook(market_id, outcome)
        
        if side == "buy":
            # Buying - use ask price
            price = orderbook.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price
            input_token = POLYMARKET_CONTRACTS["collateral"]
            output_token = token_id
        else:
            # Selling - use bid price
            price = orderbook.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price
            input_token = token_id
            output_token = POLYMARKET_CONTRACTS["collateral"]
        
        return Quote(
            platform=Platform.POLYMARKET,
            chain=Chain.POLYGON,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token,
            input_amount=amount,
            output_token=output_token,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=Decimal("0.01"),  # Estimate
            platform_fee=(amount * Decimal(self._fee_bps) / Decimal(10000)),
            network_fee_estimate=Decimal("0.01"),  # MATIC
            expires_at=None,
            quote_data={
                "token_id": token_id,
                "condition_id": market_id,
                "price": str(price),
                "market": market.raw_data,
            },
        )

    def _collect_platform_fee(
        self,
        private_key: LocalAccount,
        amount_usdc: Decimal,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Collect platform fee by transferring USDC from user to fee account.

        Args:
            private_key: User's EVM account for signing
            amount_usdc: Fee amount in USDC

        Returns:
            Tuple of (success, tx_hash, error_message)
        """
        if not self._fee_account or not self._sync_web3:
            return True, None, None  # No fee collection configured

        if not Web3.is_address(self._fee_account):
            logger.warning("Invalid fee account address", fee_account=self._fee_account)
            return True, None, None

        try:
            fee_account = Web3.to_checksum_address(self._fee_account)
            amount_raw = int(amount_usdc * Decimal(10 ** self.collateral_decimals))

            if amount_raw <= 0:
                return True, None, None

            # Get USDC contract
            usdc_contract = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(POLYMARKET_CONTRACTS["collateral"]),
                abi=ERC20_TRANSFER_ABI
            )

            # Check user balance
            user_balance = usdc_contract.functions.balanceOf(
                private_key.address
            ).call()

            if user_balance < amount_raw:
                return False, None, f"Insufficient USDC balance for fee (need {amount_usdc}, have {Decimal(user_balance) / Decimal(10**6)})"

            # Build transaction
            nonce = self._sync_web3.eth.get_transaction_count(private_key.address)
            # Use 1.5x gas price for faster confirmation on Polygon
            base_gas_price = self._sync_web3.eth.gas_price
            gas_price = int(base_gas_price * 1.5)

            tx = usdc_contract.functions.transfer(
                fee_account,
                amount_raw
            ).build_transaction({
                "from": private_key.address,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": 100000,
                "chainId": 137,  # Polygon
            })

            # Sign and send
            signed_tx = self._sync_web3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = self._sync_web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            logger.info(
                "Platform fee collected",
                amount=str(amount_usdc),
                fee_account=fee_account[:10] + "...",
                tx_hash=tx_hash_hex,
            )

            # Wait for confirmation
            try:
                receipt = self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                if receipt.status != 1:
                    return False, tx_hash_hex, "Fee transfer failed on-chain"
            except Exception:
                pass  # Continue even if confirmation times out

            return True, tx_hash_hex, None

        except Exception as e:
            logger.error("Fee collection failed", error=str(e))
            return False, None, str(e)

    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
    ) -> TradeResult:
        """
        Execute a trade on Polymarket.

        Collects platform fee AFTER successful trade execution.
        """
        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount",
                Platform.POLYMARKET,
            )

        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.POLYMARKET)

        try:
            # Import the official Polymarket client for order execution
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            # Initialize CLOB client
            client = ClobClient(
                settings.polymarket_api_url,
                key=private_key.key.hex(),
                chain_id=137,  # Polygon
                signature_type=0,  # EOA
            )

            # Set API credentials
            creds = client.create_or_derive_api_creds()
            client.set_api_creds(creds)

            token_id = quote.quote_data["token_id"]

            # Create market order
            side = BUY if quote.side == "buy" else SELL

            order_args = MarketOrderArgs(
                token_id=token_id,
                amount=float(quote.input_amount),
                side=side,
            )

            signed_order = client.create_market_order(order_args)
            result = client.post_order(signed_order, OrderType.FOK)

            tx_hash = result.get("transactionHash") or result.get("orderID", "")

            logger.info(
                "Trade executed",
                platform="polymarket",
                market_id=quote.market_id,
                order_id=tx_hash,
            )

            # Collect platform fee AFTER successful trade
            if self._fee_account and self._fee_bps > 0:
                fee_amount = (quote.input_amount * Decimal(self._fee_bps) / Decimal(10000)).quantize(
                    Decimal("0.000001"), rounding=ROUND_DOWN
                )
                if fee_amount > 0:
                    fee_success, fee_tx, fee_error = self._collect_platform_fee(
                        private_key, fee_amount
                    )
                    if fee_success:
                        logger.debug("Fee collected", fee_amount=str(fee_amount), fee_tx=fee_tx)
                    else:
                        logger.warning("Fee collection failed after trade", error=fee_error)

            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash) if tx_hash.startswith("0x") else None,
            )
            
        except ImportError:
            # py-clob-client not installed
            logger.error("py-clob-client not installed for Polymarket trading")
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message="Polymarket SDK not installed. Install with: pip install py-clob-client",
                explorer_url=None,
            )
            
        except Exception as e:
            logger.error("Trade execution failed", error=str(e))
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message=str(e),
                explorer_url=None,
            )


# Singleton instance
polymarket_platform = PolymarketPlatform()
