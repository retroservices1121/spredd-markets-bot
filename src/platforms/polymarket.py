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
    RedemptionResult,
    MarketResolution,
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
    "neg_risk_adapter": "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
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

# CTF (Conditional Token Framework) ABI for redemption
CTF_ABI = [
    {
        "constant": True,
        "inputs": [
            {"name": "conditionId", "type": "bytes32"},
            {"name": "index", "type": "uint256"}
        ],
        "name": "payoutNumerators",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "conditionId", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"}
        ],
        "name": "redeemPositions",
        "outputs": [],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"}
        ],
        "name": "balanceOf",
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
        # Caches for performance optimization
        self._approval_cache: dict[str, set[str]] = {}  # wallet_address -> set of approved contracts
        self._ctf_approval_cache: dict[str, set[str]] = {}  # wallet_address -> set of approved CTF contracts
        self._clob_client_cache: dict[str, Any] = {}  # wallet_address -> ClobClient

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
        progress_callback: Optional[callable] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Ensure wallet has sufficient USDC.e for trading on Polygon.

        Checks balances in order:
        1. Polygon USDC.e - if sufficient, ready to trade
        2. Polygon native USDC - if sufficient, swap to USDC.e
        3. Other chains (Base, etc.) - if sufficient, bridge to Polygon via CCTP

        Args:
            private_key: User's EVM account
            required_amount: Minimum USDC.e balance required
            progress_callback: Optional callback for progress updates during bridging
                              Called with (message, elapsed_sec, total_sec)

        Returns:
            Tuple of (ready_to_trade, message, tx_hash)
            - ready_to_trade: True if wallet has sufficient USDC.e
            - message: Human-readable status message
            - tx_hash: Transaction hash if swap/bridge was performed
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

            # Step 1: If already have enough USDC.e, good to go
            if bridged_balance >= required_amount:
                return True, f"USDC.e balance: {bridged_balance:.2f}", None

            # Step 2: If not enough USDC.e but have native USDC on Polygon, swap it
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

            # Step 3: Check other chains for USDC and bridge if available
            bridge_result = await self._try_bridge_from_other_chains(
                private_key, required_amount, progress_callback
            )
            if bridge_result[0]:
                # Bridge succeeded, now swap native USDC to USDC.e
                native_balance, bridged_balance = self.get_usdc_balances(private_key.address)
                if native_balance >= required_amount:
                    success, tx_hash, error = self.swap_native_to_bridged_usdc(
                        private_key, native_balance
                    )
                    if success:
                        _, new_bridged = self.get_usdc_balances(private_key.address)
                        return True, f"Bridged and swapped! USDC.e balance: {new_bridged:.2f}", tx_hash
                return bridge_result

            # Step 4: Neither Polygon nor other chains have enough
            total = native_balance + bridged_balance
            return False, f"Insufficient USDC. You have {total:.2f} on Polygon (need {required_amount:.2f}). Please deposit more USDC to your wallet.", None

        except Exception as e:
            logger.error("Balance check failed", error=str(e))
            return False, f"Error checking balance: {str(e)}", None

    async def _try_bridge_from_other_chains(
        self,
        private_key: Any,
        required_amount: Decimal,
        progress_callback: Optional[callable] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check other chains for USDC and bridge to Polygon if found.

        Args:
            private_key: User's EVM account
            required_amount: Amount needed
            progress_callback: Optional callback for progress updates

        Returns:
            Tuple of (success, message, tx_hash)
        """
        import asyncio
        from src.config import settings

        if not settings.auto_bridge_enabled:
            return False, "Auto-bridge disabled", None

        try:
            from src.services.bridge import bridge_service, BridgeChain

            # Initialize bridge service if needed
            if not bridge_service._initialized:
                bridge_service.initialize()

            # Check which chains have sufficient balance (run in thread to avoid blocking)
            source_chain_with_balance = await asyncio.to_thread(
                bridge_service.find_chain_with_balance,
                private_key.address,
                required_amount,
                BridgeChain.POLYGON,  # exclude_chain
            )

            if not source_chain_with_balance:
                return False, "No other chains have sufficient USDC", None

            source_chain, balance = source_chain_with_balance

            # Only bridge from enabled chains
            enabled_chains = settings.enabled_bridge_chains
            if source_chain.value not in enabled_chains:
                logger.info(
                    f"Found USDC on {source_chain.value} but bridging not enabled",
                    balance=str(balance)
                )
                return False, f"Found {balance:.2f} USDC on {source_chain.value} but auto-bridge not enabled for this chain", None

            logger.info(
                "Bridging USDC via CCTP",
                source=source_chain.value,
                dest="polygon",
                amount=str(required_amount),
            )

            # Bridge the required amount (plus a small buffer)
            bridge_amount = min(balance, required_amount + Decimal("1"))

            # Run the blocking bridge operation in a thread pool to avoid blocking event loop
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc,
                private_key,
                source_chain,
                BridgeChain.POLYGON,
                bridge_amount,
                progress_callback,
            )

            if result.success:
                return True, f"Bridged {bridge_amount:.2f} USDC from {source_chain.value} to Polygon", result.burn_tx_hash
            else:
                return False, f"Bridge failed: {result.error_message}", None

        except ImportError:
            logger.warning("Bridge service not available")
            return False, "Bridge service not configured", None
        except Exception as e:
            logger.error("Bridge attempt failed", error=str(e), exc_info=True)
            return False, f"Bridge error: {str(e)}", None

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

        from datetime import datetime, timezone

        def is_market_expired(event_data: dict, market_data: dict = None) -> bool:
            """Check if a market has expired based on end date."""
            end_date_str = None
            if market_data:
                end_date_str = market_data.get("endDate") or market_data.get("endDateIso")
            if not end_date_str:
                end_date_str = event_data.get("endDate") or event_data.get("endDateIso")

            if not end_date_str:
                return False  # No end date, assume active

            try:
                if end_date_str.endswith("Z"):
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                elif "T" in end_date_str:
                    end_date = datetime.fromisoformat(end_date_str)
                else:
                    end_date = datetime.fromisoformat(end_date_str + "T23:59:59+00:00")

                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)

                return datetime.now(timezone.utc) > end_date
            except:
                return False  # Parse error, assume not expired

        markets = []
        for event in data if isinstance(data, list) else []:
            try:
                event_markets = event.get("markets", [])

                if len(event_markets) <= 1:
                    # Single market event - check expiration
                    if not is_market_expired(event):
                        markets.append(self._parse_market(event))
                else:
                    # Multi-market event - expand each market as separate entry
                    for market_data in event_markets:
                        if market_data.get("active", True) and not market_data.get("closed", False):
                            if not is_market_expired(event, market_data):
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

        from datetime import datetime, timezone

        def is_market_expired(event_data: dict, market_data: dict = None) -> bool:
            """Check if a market has expired based on end date."""
            end_date_str = None
            if market_data:
                end_date_str = market_data.get("endDate") or market_data.get("endDateIso")
            if not end_date_str:
                end_date_str = event_data.get("endDate") or event_data.get("endDateIso")
            if not end_date_str:
                return False
            try:
                if end_date_str.endswith("Z"):
                    end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                elif "T" in end_date_str:
                    end_date = datetime.fromisoformat(end_date_str)
                else:
                    end_date = datetime.fromisoformat(end_date_str + "T23:59:59+00:00")
                if end_date.tzinfo is None:
                    end_date = end_date.replace(tzinfo=timezone.utc)
                return datetime.now(timezone.utc) > end_date
            except:
                return False

        markets = []
        for event in filtered_events:
            try:
                event_markets = event.get("markets", [])
                if len(event_markets) <= 1:
                    if not is_market_expired(event):
                        markets.append(self._parse_market(event))
                else:
                    for market_data in event_markets:
                        if market_data.get("active", True) and not market_data.get("closed", False):
                            if not is_market_expired(event, market_data):
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

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 20,
    ) -> list[Market]:
        """Get markets filtered by category/tag.

        Args:
            category: Category slug (e.g., 'sports', 'politics', 'crypto')
            limit: Maximum number of markets to return
        """
        try:
            # Fetch more events to filter locally by tag
            params = {
                "limit": 200,  # Fetch many to find matching tags
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
            }

            data = await self._gamma_request("GET", "/events", params=params)

            from datetime import datetime, timezone

            def is_market_expired(event_data: dict, market_data: dict = None) -> bool:
                """Check if a market has expired based on end date."""
                end_date_str = None
                if market_data:
                    end_date_str = market_data.get("endDate") or market_data.get("endDateIso")
                if not end_date_str:
                    end_date_str = event_data.get("endDate") or event_data.get("endDateIso")
                if not end_date_str:
                    return False
                try:
                    if end_date_str.endswith("Z"):
                        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    elif "T" in end_date_str:
                        end_date = datetime.fromisoformat(end_date_str)
                    else:
                        end_date = datetime.fromisoformat(end_date_str + "T23:59:59+00:00")
                    if end_date.tzinfo is None:
                        end_date = end_date.replace(tzinfo=timezone.utc)
                    return datetime.now(timezone.utc) > end_date
                except:
                    return False

            category_lower = category.lower().replace("-", " ")

            # Category aliases for better matching
            entertainment_tags = ["entertainment", "pop culture", "pop-culture", "celebrities", "celebrity", "movies", "movie", "tv", "television", "music", "awards", "oscars", "grammys", "emmys", "streaming", "youtube", "tiktok", "influencer"]
            category_aliases = {
                "entertainment": entertainment_tags,
                "pop-culture": entertainment_tags,
                "pop culture": entertainment_tags,
                "sports": ["sports", "sport", "nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball", "baseball", "hockey", "tennis", "golf", "mma", "ufc", "boxing", "f1", "formula 1"],
                "politics": ["politics", "political", "election", "elections", "government", "congress", "senate", "president", "presidential", "trump", "biden", "us politics"],
                "crypto": ["crypto", "cryptocurrency", "bitcoin", "btc", "ethereum", "eth", "defi", "nft", "web3", "blockchain"],
                "business": ["business", "economy", "economics", "finance", "financial", "markets", "stock", "stocks", "fed", "federal reserve", "inflation"],
                "science": ["science", "tech", "technology", "ai", "artificial intelligence", "space", "nasa", "climate", "health", "medical"],
            }

            # Get all terms to match for this category
            match_terms = category_aliases.get(category_lower, [category_lower])

            markets = []

            for event in data if isinstance(data, list) else []:
                try:
                    # Check if event has matching tag
                    event_tags = event.get("tags", [])
                    tag_matches = False

                    for tag in event_tags:
                        tag_label = (tag.get("label") or tag.get("slug") or "").lower()
                        tag_slug = (tag.get("slug") or "").lower()
                        # Match by any alias term
                        for term in match_terms:
                            if term in tag_label or term in tag_slug or tag_slug == term:
                                tag_matches = True
                                break
                        if tag_matches:
                            break

                    if not tag_matches:
                        continue

                    event_markets = event.get("markets", [])

                    if len(event_markets) <= 1:
                        if not is_market_expired(event):
                            markets.append(self._parse_market(event))
                    else:
                        for market_data in event_markets:
                            if market_data.get("active", True) and not market_data.get("closed", False):
                                if not is_market_expired(event, market_data):
                                    markets.append(self._parse_market(event, market_data))

                    if len(markets) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Skipping event due to parse error: {e}")
                    continue

            return markets[:limit]
        except Exception as e:
            logger.error("Failed to get markets by category", category=category, error=str(e))
            return []

    def get_available_categories(self) -> list[dict]:
        """Get list of available market categories.

        Returns list of dicts with 'id', 'label', and 'emoji' keys.
        """
        return [
            {"id": "sports", "label": "Sports", "emoji": "🏆"},
            {"id": "politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "entertainment", "label": "Entertainment", "emoji": "🎬"},
            {"id": "business", "label": "Business", "emoji": "💼"},
            {"id": "science", "label": "Science", "emoji": "🔬"},
        ]

    # ===================
    # Order Book
    # ===================
    
    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
        token_id: str = None,
    ) -> OrderBook:
        """Get order book from CLOB API.

        Args:
            market_id: The market identifier
            outcome: YES or NO
            token_id: Optional token ID to use (for sells with stored position token)
        """
        # Use provided token_id if given, otherwise get from market
        if not token_id:
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

        # Sort bids descending (highest first) - best_bid = highest price buyers will pay
        bids.sort(key=lambda x: x[0], reverse=True)
        # Sort asks ascending (lowest first) - best_ask = lowest price sellers will accept
        asks.sort(key=lambda x: x[0])

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
        token_id: str = None,
        order_type: str = "market",
    ) -> Quote:
        """Get a quote for a trade.

        Args:
            market_id: The market identifier
            outcome: YES or NO
            side: "buy" or "sell"
            amount: Amount to trade
            token_id: Optional token ID to use (required for sells to use position's stored token)
            order_type: "market" or "limit" (Polymarket only supports market orders via this interface)
        """
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.POLYMARKET)

        # Use provided token_id for sells (from stored position), otherwise get from market
        if not token_id:
            token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.POLYMARKET)

        # Get current price from orderbook (pass token_id for sells)
        orderbook = await self.get_orderbook(market_id, outcome, token_id=token_id)
        
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

            # Debug: Log wallet info for fee collection
            pol_balance = self._sync_web3.eth.get_balance(private_key.address)
            logger.debug(
                "Fee collection wallet info",
                wallet=private_key.address,
                pol_balance_wei=pol_balance,
                pol_balance=str(Decimal(pol_balance) / Decimal(10**18)),
                gas_price=gas_price,
                estimated_gas_cost=gas_price * 100000,
            )

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

    async def _ensure_exchange_approval(self, private_key: Any) -> None:
        """Ensure USDC.e and CTF tokens are approved for Polymarket exchange contracts.

        Uses caching to avoid repeated blockchain calls for already-approved wallets.
        """
        import asyncio
        from eth_account.signers.local import LocalAccount

        if not isinstance(private_key, LocalAccount):
            return

        if not self._sync_web3:
            return

        wallet = Web3.to_checksum_address(private_key.address)

        # Check cache - if wallet has all approvals cached, skip entirely
        cached_usdc = self._approval_cache.get(wallet, set())
        cached_ctf = self._ctf_approval_cache.get(wallet, set())

        contracts_to_approve = [
            ("exchange", POLYMARKET_CONTRACTS["exchange"]),
            ("neg_risk_exchange", POLYMARKET_CONTRACTS["neg_risk_exchange"]),
            ("neg_risk_adapter", POLYMARKET_CONTRACTS["neg_risk_adapter"]),
        ]

        all_contracts = {name for name, _ in contracts_to_approve}

        # Fast path: if all approvals are cached, skip blockchain checks
        if cached_usdc >= all_contracts and cached_ctf >= all_contracts:
            logger.debug("All approvals cached, skipping checks", wallet=wallet[:10])
            return

        # Run approval checks in thread to avoid blocking
        def sync_check_and_approve():
            usdc_address = Web3.to_checksum_address(USDC_BRIDGED)
            usdc_contract = self._sync_web3.eth.contract(
                address=usdc_address,
                abi=ERC20_APPROVE_ABI
            )

            # Check and approve USDC.e for uncached contracts
            for contract_name, contract_addr in contracts_to_approve:
                if contract_name in cached_usdc:
                    continue  # Skip if cached

                exchange_address = Web3.to_checksum_address(contract_addr)

                # Check current allowance
                allowance = usdc_contract.functions.allowance(wallet, exchange_address).call()

                # If allowance is sufficient, cache it
                if allowance >= 10 ** 12:  # 1M+ USDC already approved
                    self._approval_cache.setdefault(wallet, set()).add(contract_name)
                    continue

                # Need to approve
                logger.info(f"Approving Polymarket {contract_name} for USDC.e")

                nonce = self._sync_web3.eth.get_transaction_count(wallet)
                base_gas_price = self._sync_web3.eth.gas_price
                gas_price = int(base_gas_price * 1.5)

                approve_tx = usdc_contract.functions.approve(
                    exchange_address,
                    2 ** 256 - 1  # Max approval
                ).build_transaction({
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                    "gas": 100000,
                    "chainId": 137,
                })

                signed_tx = self._sync_web3.eth.account.sign_transaction(approve_tx, private_key.key)
                tx_hash = self._sync_web3.eth.send_raw_transaction(signed_tx.raw_transaction)

                # Wait for confirmation
                self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                logger.info(f"Polymarket {contract_name} approval confirmed", tx_hash=tx_hash.hex())

                # Cache the approval
                self._approval_cache.setdefault(wallet, set()).add(contract_name)

            # Check and approve CTF tokens for uncached contracts
            ctf_address = Web3.to_checksum_address(POLYMARKET_CONTRACTS["ctf"])

            set_approval_abi = [{
                "inputs": [
                    {"name": "operator", "type": "address"},
                    {"name": "approved", "type": "bool"}
                ],
                "name": "setApprovalForAll",
                "outputs": [],
                "type": "function"
            }, {
                "inputs": [
                    {"name": "account", "type": "address"},
                    {"name": "operator", "type": "address"}
                ],
                "name": "isApprovedForAll",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            }]

            ctf_contract = self._sync_web3.eth.contract(
                address=ctf_address,
                abi=set_approval_abi
            )

            for contract_name, contract_addr in contracts_to_approve:
                if contract_name in cached_ctf:
                    continue  # Skip if cached

                exchange_address = Web3.to_checksum_address(contract_addr)

                is_approved = ctf_contract.functions.isApprovedForAll(wallet, exchange_address).call()

                if is_approved:
                    self._ctf_approval_cache.setdefault(wallet, set()).add(contract_name)
                    continue

                logger.info(f"Approving Polymarket {contract_name} for CTF tokens")

                nonce = self._sync_web3.eth.get_transaction_count(wallet)
                base_gas_price = self._sync_web3.eth.gas_price
                gas_price = int(base_gas_price * 1.5)

                approve_tx = ctf_contract.functions.setApprovalForAll(
                    exchange_address,
                    True
                ).build_transaction({
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                    "gas": 100000,
                    "chainId": 137,
                })

                signed_tx = self._sync_web3.eth.account.sign_transaction(approve_tx, private_key.key)
                tx_hash = self._sync_web3.eth.send_raw_transaction(signed_tx.raw_transaction)

                self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                logger.info(f"Polymarket {contract_name} CTF approval confirmed", tx_hash=tx_hash.hex())

                # Cache the approval
                self._ctf_approval_cache.setdefault(wallet, set()).add(contract_name)

        # Run blocking checks in thread pool
        await asyncio.to_thread(sync_check_and_approve)

    def _get_clob_client(self, private_key: Any) -> Any:
        """Get or create a cached CLOB client for the given private key.

        Caching the client avoids repeated credential derivation which can be slow.
        """
        from py_clob_client.client import ClobClient

        wallet = private_key.address
        cached = self._clob_client_cache.get(wallet)

        if cached:
            logger.debug("Using cached CLOB client", wallet=wallet[:10])
            return cached

        # Set up builder config if credentials are configured
        builder_config = None
        if (settings.polymarket_builder_key and
            settings.polymarket_builder_secret and
            settings.polymarket_builder_passphrase):
            try:
                from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds

                builder_creds = BuilderApiKeyCreds(
                    key=settings.polymarket_builder_key,
                    secret=settings.polymarket_builder_secret,
                    passphrase=settings.polymarket_builder_passphrase,
                )
                builder_config = BuilderConfig(local_builder_creds=builder_creds)
                logger.info("Builder attribution enabled for Polymarket", wallet=wallet[:10])
            except ImportError as e:
                logger.warning("Builder SDK not available", error=str(e))

        # Create new client with optional builder config
        client = ClobClient(
            settings.polymarket_api_url,
            key=private_key.key.hex(),
            chain_id=137,  # Polygon
            signature_type=0,  # EOA
            funder=private_key.address,  # Required for balance operations
            builder_config=builder_config,
        )

        # Derive API credentials from user's wallet for signing orders
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)

        # Cache the client
        self._clob_client_cache[wallet] = client
        logger.info("Created and cached CLOB client", wallet=wallet[:10])

        return client

    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
    ) -> TradeResult:
        """
        Execute a trade on Polymarket.

        Collects platform fee AFTER successful trade execution.
        Uses caching for approval checks and CLOB client to speed up execution.
        """
        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount",
                Platform.POLYMARKET,
            )

        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.POLYMARKET)

        try:
            # For BUY orders, ensure we have enough USDC.e (auto-swap from native USDC if needed)
            if quote.side == "buy":
                success, message, swap_tx = await self.ensure_usdc_balance(
                    private_key, quote.input_amount
                )
                if not success:
                    return TradeResult(
                        success=False,
                        tx_hash=None,
                        input_amount=quote.input_amount,
                        output_amount=None,
                        error_message=message,
                        explorer_url=None,
                    )
                if swap_tx:
                    logger.info("Auto-swapped USDC to USDC.e", tx_hash=swap_tx)

            # Ensure USDC.e and CTF are approved for Polymarket exchange contracts
            # This is now cached for repeat trades
            await self._ensure_exchange_approval(private_key)

            # Import order types
            from py_clob_client.clob_types import MarketOrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL

            # Get cached CLOB client (creates if first time)
            client = self._get_clob_client(private_key)

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

    async def get_market_resolution(self, market_id: str) -> MarketResolution:
        """
        Check if a Polymarket market has resolved and what the outcome is.

        Uses the CTF contract to check payoutNumerators.
        """
        try:
            if not self._sync_web3:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            # Get condition ID - market_id might be truncated
            market = await self.get_market(market_id)
            if not market or not market.raw_data:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            # Get the full condition ID from market data
            condition_id = market.raw_data.get("conditionId")
            if not condition_id:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            # Check if market is closed/resolved from API data
            closed = market.raw_data.get("closed", False)
            resolved = market.raw_data.get("resolved", False)

            if not closed and not resolved:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            # Get resolution from raw_data if available
            resolution_data = market.raw_data.get("resolution")
            if resolution_data:
                winning = "yes" if resolution_data == "Yes" else "no" if resolution_data == "No" else None
                return MarketResolution(
                    is_resolved=True,
                    winning_outcome=winning,
                    resolution_time=market.raw_data.get("resolutionTime"),
                )

            # Otherwise check CTF contract for payout numerators
            ctf_contract = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(POLYMARKET_CONTRACTS["ctf"]),
                abi=CTF_ABI,
            )

            # Convert condition ID to bytes32
            if condition_id.startswith("0x"):
                condition_bytes = bytes.fromhex(condition_id[2:])
            else:
                condition_bytes = bytes.fromhex(condition_id)

            # Check payout denominator (if 0, not resolved)
            payout_denom = ctf_contract.functions.payoutDenominator(condition_bytes).call()
            if payout_denom == 0:
                return MarketResolution(
                    is_resolved=False,
                    winning_outcome=None,
                    resolution_time=None,
                )

            # Check payout numerators for each outcome (0 = YES, 1 = NO)
            yes_payout = ctf_contract.functions.payoutNumerators(condition_bytes, 0).call()
            no_payout = ctf_contract.functions.payoutNumerators(condition_bytes, 1).call()

            winning_outcome = None
            if yes_payout > 0 and no_payout == 0:
                winning_outcome = "yes"
            elif no_payout > 0 and yes_payout == 0:
                winning_outcome = "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning_outcome,
                resolution_time=None,
            )

        except Exception as e:
            logger.error("Failed to check market resolution", error=str(e), market_id=market_id)
            return MarketResolution(
                is_resolved=False,
                winning_outcome=None,
                resolution_time=None,
            )

    async def redeem_position(
        self,
        market_id: str,
        outcome: Outcome,
        token_amount: Decimal,
        private_key: Any,
    ) -> RedemptionResult:
        """
        Redeem winning tokens from a resolved Polymarket market.

        Calls redeemPositions on the CTF contract.
        """
        if not isinstance(private_key, LocalAccount):
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message="Invalid private key type, expected EVM LocalAccount",
                explorer_url=None,
            )

        try:
            if not self._sync_web3:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Web3 not initialized",
                    explorer_url=None,
                )

            # Get market to find condition ID
            market = await self.get_market(market_id)
            if not market or not market.raw_data:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Market not found",
                    explorer_url=None,
                )

            condition_id = market.raw_data.get("conditionId")
            if not condition_id:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Condition ID not found",
                    explorer_url=None,
                )

            # Check if market is actually resolved
            resolution = await self.get_market_resolution(market_id)
            if not resolution.is_resolved:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="Market has not resolved yet",
                    explorer_url=None,
                )

            # Check if user holds winning outcome
            if resolution.winning_outcome and resolution.winning_outcome.lower() != outcome.value.lower():
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message=f"Your {outcome.value.upper()} tokens lost. The market resolved to {resolution.winning_outcome.upper()}.",
                    explorer_url=None,
                )

            # Build CTF contract
            ctf_contract = self._sync_web3.eth.contract(
                address=Web3.to_checksum_address(POLYMARKET_CONTRACTS["ctf"]),
                abi=CTF_ABI,
            )

            # Convert condition ID to bytes32
            if condition_id.startswith("0x"):
                condition_bytes = bytes.fromhex(condition_id[2:])
            else:
                condition_bytes = bytes.fromhex(condition_id)

            # Index sets: 1 for YES (binary 01), 2 for NO (binary 10)
            index_set = 1 if outcome == Outcome.YES else 2

            # Parent collection ID is null bytes32 for Polymarket
            parent_collection_id = bytes(32)

            # Build transaction
            wallet_address = private_key.address

            tx = ctf_contract.functions.redeemPositions(
                Web3.to_checksum_address(POLYMARKET_CONTRACTS["collateral"]),
                parent_collection_id,
                condition_bytes,
                [index_set],
            ).build_transaction({
                "from": wallet_address,
                "nonce": self._sync_web3.eth.get_transaction_count(wallet_address),
                "gas": 200000,
                "gasPrice": self._sync_web3.eth.gas_price,
                "chainId": 137,  # Polygon
            })

            # Sign and send transaction
            signed_tx = self._sync_web3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = self._sync_web3.eth.send_raw_transaction(signed_tx.raw_transaction)

            logger.info(
                "Redemption transaction sent",
                tx_hash=tx_hash.hex(),
                market_id=market_id,
                outcome=outcome.value,
            )

            # Wait for confirmation
            receipt = self._sync_web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            if receipt.status == 1:
                # Calculate redeemed amount (winning tokens are worth $1 each)
                amount_redeemed = token_amount

                logger.info(
                    "Redemption confirmed",
                    tx_hash=tx_hash.hex(),
                    amount_redeemed=str(amount_redeemed),
                )

                return RedemptionResult(
                    success=True,
                    tx_hash=tx_hash.hex(),
                    amount_redeemed=amount_redeemed,
                    error_message=None,
                    explorer_url=self.get_explorer_url(tx_hash.hex()),
                )
            else:
                return RedemptionResult(
                    success=False,
                    tx_hash=tx_hash.hex(),
                    amount_redeemed=None,
                    error_message="Transaction failed",
                    explorer_url=self.get_explorer_url(tx_hash.hex()),
                )

        except Exception as e:
            logger.error("Redemption failed", error=str(e), market_id=market_id)
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message=str(e),
                explorer_url=None,
            )


# Singleton instance
polymarket_platform = PolymarketPlatform()
