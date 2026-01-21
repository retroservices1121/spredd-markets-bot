"""
ACP Job Handlers.

Implements the business logic for each job type offered through ACP.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from src.utils.logging import get_logger
from src.services.acp.schemas import JobType, validate_service_requirements
from src.platforms import get_platform, Platform
from src.platforms.base import Outcome, OrderSide

logger = get_logger(__name__)


class ACPJobHandler:
    """Handles ACP job requests by routing to appropriate platform services."""

    def __init__(self):
        self._wallet_manager = None

    def set_wallet_manager(self, wallet_manager):
        """Set the wallet manager for fund tracking."""
        self._wallet_manager = wallet_manager

    async def handle_job(
        self,
        job_type: JobType,
        agent_id: str,
        service_requirements: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Route a job to the appropriate handler.
        Returns the deliverable dict.
        """
        # Validate requirements
        is_valid, error = validate_service_requirements(job_type, service_requirements)
        if not is_valid:
            return {"success": False, "error": error}

        handlers = {
            JobType.EXECUTE_TRADE: self._handle_execute_trade,
            JobType.GET_QUOTE: self._handle_get_quote,
            JobType.SEARCH_MARKETS: self._handle_search_markets,
            JobType.GET_PORTFOLIO: self._handle_get_portfolio,
            JobType.BRIDGE_USDC: self._handle_bridge_usdc,
        }

        handler = handlers.get(job_type)
        if not handler:
            return {"success": False, "error": f"Unknown job type: {job_type}"}

        try:
            return await handler(agent_id, service_requirements)
        except Exception as e:
            logger.error("ACP job handler error", job_type=job_type.value, error=str(e))
            return {"success": False, "error": str(e)}

    async def _handle_execute_trade(
        self,
        agent_id: str,
        req: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a prediction market trade."""
        from src.services.acp.wallet_manager import acp_wallet_manager

        platform_str = req["platform"]
        market_id = req["market_id"]
        outcome_str = req["outcome"]
        side_str = req["side"]
        amount = Decimal(str(req["amount"]))
        max_slippage_bps = req.get("max_slippage_bps", 100)

        # Map strings to enums
        try:
            platform = Platform(platform_str)
        except ValueError:
            return {"success": False, "error": f"Invalid platform: {platform_str}"}

        outcome = Outcome.YES if outcome_str.lower() == "yes" else Outcome.NO
        side = OrderSide.BUY if side_str.lower() == "buy" else OrderSide.SELL

        # Get platform client
        platform_client = get_platform(platform)
        chain = self._get_chain_for_platform(platform)

        # Check if we have liquidity on the target chain (USDC/USDT + gas)
        has_liquidity, liquidity_error = acp_wallet_manager.check_chain_liquidity(chain, amount)
        if not has_liquidity:
            return {
                "success": False,
                "error": f"Platform temporarily unavailable: {liquidity_error}"
            }

        # For buy orders, check agent has sufficient balance
        if side == OrderSide.BUY:
            agent_balance = await acp_wallet_manager.get_agent_balance(agent_id, chain)
            if agent_balance < amount:
                return {
                    "success": False,
                    "error": f"Insufficient balance. Have: ${agent_balance}, Need: ${amount}"
                }

        try:
            # Get quote first
            quote = await platform_client.get_quote(
                market_id=market_id,
                outcome=outcome,
                side=side,
                amount=amount,
            )

            if not quote:
                return {"success": False, "error": "Failed to get quote"}

            # Get agent's private key for this chain
            private_key = await acp_wallet_manager.get_agent_private_key(
                agent_id,
                self._get_chain_for_platform(platform)
            )

            if not private_key:
                return {"success": False, "error": "Agent wallet not configured"}

            # Execute the trade
            result = await platform_client.execute_trade(quote, private_key)

            if result.success:
                # Deduct from agent balance for buys
                if side == OrderSide.BUY:
                    chain = self._get_chain_for_platform(platform)
                    await acp_wallet_manager.deduct_for_trade(agent_id, amount, chain)

                # Track volume for analytics
                await self._track_trade_volume(
                    agent_id=agent_id,
                    platform=platform,
                    amount=amount,
                    side=side,
                    tx_hash=result.tx_hash,
                )

                return {
                    "success": True,
                    "tx_hash": result.tx_hash or "",
                    "input_amount": float(result.input_amount or amount),
                    "output_amount": float(result.output_amount or 0),
                    "price": float(quote.price) if quote.price else 0,
                    "explorer_url": platform_client.get_explorer_url(result.tx_hash) if result.tx_hash else "",
                }
            else:
                return {
                    "success": False,
                    "error": result.error_message or "Trade execution failed"
                }

        except Exception as e:
            logger.error("Trade execution failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def _handle_get_quote(
        self,
        agent_id: str,
        req: dict[str, Any],
    ) -> dict[str, Any]:
        """Get a trade quote without executing."""
        platform_str = req["platform"]
        market_id = req["market_id"]
        outcome_str = req["outcome"]
        side_str = req["side"]
        amount = Decimal(str(req["amount"]))

        try:
            platform = Platform(platform_str)
        except ValueError:
            return {"success": False, "error": f"Invalid platform: {platform_str}"}

        outcome = Outcome.YES if outcome_str.lower() == "yes" else Outcome.NO
        side = OrderSide.BUY if side_str.lower() == "buy" else OrderSide.SELL

        platform_client = get_platform(platform)

        try:
            quote = await platform_client.get_quote(
                market_id=market_id,
                outcome=outcome,
                side=side,
                amount=amount,
            )

            if not quote:
                return {"success": False, "error": "Failed to get quote"}

            return {
                "input_amount": float(quote.input_amount),
                "expected_output": float(quote.expected_output),
                "price": float(quote.price) if quote.price else 0,
                "price_impact_bps": int(quote.price_impact_bps) if quote.price_impact_bps else 0,
                "fee_amount": float(quote.fee_amount) if quote.fee_amount else 0,
                "expires_at": quote.expires_at.isoformat() if quote.expires_at else datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error("Quote failed", error=str(e))
            return {"success": False, "error": str(e)}

    async def _handle_search_markets(
        self,
        agent_id: str,
        req: dict[str, Any],
    ) -> dict[str, Any]:
        """Search markets across platforms."""
        query = req["query"]
        platforms_filter = req.get("platforms", [])
        limit = min(req.get("limit", 10), 50)

        # Determine which platforms to search
        if platforms_filter:
            platforms = []
            for p in platforms_filter:
                try:
                    platforms.append(Platform(p))
                except ValueError:
                    continue
        else:
            platforms = [Platform.KALSHI, Platform.POLYMARKET, Platform.OPINION, Platform.LIMITLESS]

        all_markets = []

        for platform in platforms:
            try:
                platform_client = get_platform(platform)
                markets = await platform_client.search_markets(query, limit=limit)

                for market in markets:
                    all_markets.append({
                        "platform": platform.value,
                        "market_id": market.id,
                        "title": market.title,
                        "yes_price": float(market.yes_price) if market.yes_price else 0.5,
                        "no_price": float(market.no_price) if market.no_price else 0.5,
                        "volume_24h": float(market.volume_24h) if market.volume_24h else 0,
                        "end_date": market.end_date.isoformat() if market.end_date else "",
                    })

            except Exception as e:
                logger.warning(f"Search failed for {platform.value}", error=str(e))
                continue

        # Sort by volume and limit
        all_markets.sort(key=lambda m: m.get("volume_24h", 0), reverse=True)
        all_markets = all_markets[:limit]

        return {"markets": all_markets}

    async def _handle_get_portfolio(
        self,
        agent_id: str,
        req: dict[str, Any],
    ) -> dict[str, Any]:
        """Get agent's current positions."""
        from src.services.acp.wallet_manager import acp_wallet_manager

        platforms_filter = req.get("platforms", [])

        # Get agent's positions from database
        positions = await acp_wallet_manager.get_agent_positions(agent_id)

        # Filter by platform if specified
        if platforms_filter:
            positions = [p for p in positions if p.get("platform") in platforms_filter]

        total_value = Decimal(0)
        total_pnl = Decimal(0)

        formatted_positions = []
        for pos in positions:
            entry_price = Decimal(str(pos.get("entry_price", 0)))
            current_price = Decimal(str(pos.get("current_price", entry_price)))
            amount = Decimal(str(pos.get("amount", 0)))

            # Calculate P&L
            pnl = (current_price - entry_price) * amount
            value = current_price * amount

            total_value += value
            total_pnl += pnl

            formatted_positions.append({
                "platform": pos.get("platform", ""),
                "market_id": pos.get("market_id", ""),
                "market_title": pos.get("market_title", ""),
                "outcome": pos.get("outcome", ""),
                "amount": float(amount),
                "entry_price": float(entry_price),
                "current_price": float(current_price),
                "pnl": float(pnl),
            })

        return {
            "positions": formatted_positions,
            "total_value": float(total_value),
            "total_pnl": float(total_pnl),
        }

    async def _handle_bridge_usdc(
        self,
        agent_id: str,
        req: dict[str, Any],
    ) -> dict[str, Any]:
        """Bridge USDC between chains."""
        from src.services.bridge import bridge_service, BridgeChain
        from src.services.acp.wallet_manager import acp_wallet_manager

        source_chain = req["source_chain"]
        dest_chain = req["dest_chain"]
        amount = Decimal(str(req["amount"]))

        if source_chain == dest_chain:
            return {"success": False, "error": "Source and destination chains must be different"}

        # Map string to BridgeChain enum
        chain_map = {
            "base": BridgeChain.BASE,
            "polygon": BridgeChain.POLYGON,
            "arbitrum": BridgeChain.ARBITRUM,
            "optimism": BridgeChain.OPTIMISM,
            "ethereum": BridgeChain.ETHEREUM,
        }

        src_chain = chain_map.get(source_chain.lower())
        dst_chain = chain_map.get(dest_chain.lower())

        if not src_chain or not dst_chain:
            return {"success": False, "error": "Invalid chain specified"}

        # Check agent has sufficient balance on source chain
        agent_balance = await acp_wallet_manager.get_agent_balance(agent_id, source_chain)
        if agent_balance < amount:
            return {
                "success": False,
                "error": f"Insufficient balance on {source_chain}. Have: ${agent_balance}, Need: ${amount}"
            }

        # Get agent's private key
        private_key = await acp_wallet_manager.get_agent_private_key(agent_id, source_chain)
        if not private_key:
            return {"success": False, "error": "Agent wallet not configured"}

        try:
            # Initialize bridge service
            if not bridge_service._initialized:
                bridge_service.initialize()

            # Execute bridge
            result = bridge_service.bridge_usdc(
                private_key=private_key,
                amount=amount,
                source_chain=src_chain,
                dest_chain=dst_chain,
            )

            if result.success:
                # Update balances
                await acp_wallet_manager.deduct_for_trade(agent_id, amount, source_chain)

                # Track bridge volume for analytics
                await self._track_bridge_volume(
                    agent_id=agent_id,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    tx_hash=result.source_tx_hash,
                )

                return {
                    "success": True,
                    "source_tx_hash": result.source_tx_hash or "",
                    "dest_tx_hash": result.dest_tx_hash or "",
                    "amount_sent": float(amount),
                    "amount_received": float(result.received_amount or amount),
                    "explorer_url": result.explorer_url or "",
                }
            else:
                return {
                    "success": False,
                    "error": result.error_message or "Bridge failed"
                }

        except Exception as e:
            logger.error("Bridge failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _get_chain_for_platform(self, platform: Platform) -> str:
        """Get the chain name for a platform."""
        chain_map = {
            Platform.KALSHI: "solana",
            Platform.POLYMARKET: "polygon",
            Platform.OPINION: "bsc",
            Platform.LIMITLESS: "base",
        }
        return chain_map.get(platform, "polygon")

    async def _track_trade_volume(
        self,
        agent_id: str,
        platform: Platform,
        amount: Decimal,
        side: OrderSide,
        tx_hash: Optional[str] = None,
    ) -> None:
        """Track trade volume for ACP analytics."""
        from src.db.database import record_acp_trade_volume

        try:
            await record_acp_trade_volume(
                agent_id=agent_id,
                platform=platform.value,
                amount=amount,
                side=side.value,
                tx_hash=tx_hash,
            )
        except Exception as e:
            logger.warning("Failed to track ACP volume", error=str(e))

    async def _track_bridge_volume(
        self,
        agent_id: str,
        source_chain: str,
        dest_chain: str,
        amount: Decimal,
        tx_hash: Optional[str] = None,
    ) -> None:
        """Track bridge volume for ACP analytics."""
        from src.db.database import record_acp_bridge_volume

        try:
            await record_acp_bridge_volume(
                agent_id=agent_id,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                tx_hash=tx_hash,
            )
        except Exception as e:
            logger.warning("Failed to track ACP bridge volume", error=str(e))


# Singleton instance
acp_job_handler = ACPJobHandler()
