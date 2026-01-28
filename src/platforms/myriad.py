"""
Myriad Protocol platform implementation.
Multi-chain prediction market using Polkamarkets smart contracts.

Supported chains:
- Abstract (primary) - uses ZKsync transaction format
- Linea
- BNB Chain (BSC)
- Celo (coming soon)
"""

import asyncio
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional
from datetime import datetime

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3

# ZKsync SDK for Abstract chain
try:
    from zksync2.module.module_builder import ZkSyncBuilder
    from zksync2.core.types import EthBlockParams
    from zksync2.signer.eth_signer import PrivateKeyEthSigner
    from zksync2.transaction.transaction_builders import TxFunctionCall
    ZKSYNC_AVAILABLE = True
except ImportError:
    ZKSYNC_AVAILABLE = False

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

# Allowed collateral tokens per network (filter out PTS/PENGU markets)
# Only USDC/USDT markets are tradeable through Spredd
ALLOWED_COLLATERAL_TOKENS = {
    # Abstract mainnet - only USDC.e (exclude PTS and PENGU)
    2741: [
        "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",  # USDC.e
    ],
    # Abstract testnet
    11124: [
        "0x8820c84FD53663C2e2EA26e7a4c2b79dCc479765",  # USDC testnet
    ],
    # Linea mainnet - USDC only
    59144: [
        "0x176211869cA2b568f2A7D4EE941E073a821EE1ff",  # USDC
    ],
    # BNB Chain mainnet - USDT only
    56: [
        "0x55d398326f99059fF775485246999027B3197955",  # USDT
    ],
    # BNB Chain testnet
    97: [
        "0x49Ff827F0C8835ebd8109Cc3b51b80435ce44F09",  # USDT testnet
    ],
}

# Network configurations
MYRIAD_NETWORKS = {
    # Abstract mainnet
    2741: {
        "name": "Abstract",
        "chain": Chain.ABSTRACT,
        "rpc": "https://api.mainnet.abs.xyz",
        "prediction_market": "0x3e0F5F8F5Fb043aBFA475C0308417Bf72c463289",
        "querier": "0x1d5773Cd0dC74744C1F7a19afEeECfFE64f233Ff",
        "collateral": "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",  # USDC.e
        "collateral_symbol": "USDC.e",
        "collateral_decimals": 6,
        "explorer": "https://abscan.org",
    },
    # Abstract testnet (staging) - network ID from staging API
    11124: {
        "name": "Abstract Testnet",
        "chain": Chain.ABSTRACT,
        "rpc": "https://api.testnet.abs.xyz",
        "prediction_market": "0x6c44Abf72085E5e71EeB7C951E3079073B1E7312",
        "querier": "0xa30c60107f9011dd49fc9e04ebe15963064eecc1",
        "collateral": "0x8820c84FD53663C2e2EA26e7a4c2b79dCc479765",  # USDC testnet
        "collateral_symbol": "USDC",
        "collateral_decimals": 6,
        "explorer": "https://sepolia.abscan.org",
    },
    # BNB Chain testnet (staging)
    97: {
        "name": "BNB Testnet",
        "chain": Chain.BSC,
        "rpc": "https://data-seed-prebsc-1-s1.binance.org:8545",
        "prediction_market": "0xb5625db4777262460589724693e6E032999FCCd5",
        "querier": "0x289E3908ECDc3c8CcceC5b6801E758549846Ab19",
        "collateral": "0x49Ff827F0C8835ebd8109Cc3b51b80435ce44F09",  # USDT testnet
        "collateral_symbol": "USDT",
        "collateral_decimals": 18,
        "explorer": "https://testnet.bscscan.com",
    },
    # Linea mainnet
    59144: {
        "name": "Linea",
        "chain": Chain.LINEA,
        "rpc": "https://rpc.linea.build",
        "prediction_market": "0x39e66ee6b2ddaf4defded3038e0162180dbef340",
        "querier": "0x503c9f98398dc3433ABa819BF3eC0b97e02B8D04",
        "collateral": "0x176211869cA2b568f2A7D4EE941E073a821EE1ff",  # USDC
        "collateral_symbol": "USDC",
        "collateral_decimals": 6,
        "explorer": "https://lineascan.build",
    },
    # BNB Chain mainnet
    56: {
        "name": "BNB Chain",
        "chain": Chain.BSC,
        "rpc": "https://bsc-dataseed.binance.org",
        "prediction_market": "0x39E66eE6b2ddaf4DEfDEd3038E0162180dbeF340",
        "querier": "0xDeFb36c47754D2e37d44b8b8C647D4D643e03bAd",
        "collateral": "0x55d398326f99059fF775485246999027B3197955",  # USDT
        "collateral_symbol": "USDT",
        "collateral_decimals": 18,
        "explorer": "https://bscscan.com",
    },
}

# ERC20 ABI for approvals
ERC20_ABI = [
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
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]


class MyriadPlatform(BasePlatform):
    """
    Myriad Protocol prediction market platform.
    Multi-chain support via REST API + on-chain execution.
    """

    platform = Platform.MYRIAD
    chain = Chain.ABSTRACT  # Default chain, can be changed per market

    name = "Myriad"
    description = "Multi-chain prediction markets on Abstract, Linea, and BNB Chain"
    website = "https://myriad.markets"

    collateral_symbol = "USDC.e"
    collateral_decimals = 6

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._web3_clients: dict[int, AsyncWeb3] = {}  # network_id -> web3
        self._network_id = settings.myriad_network_id
        self._network_config = MYRIAD_NETWORKS.get(self._network_id, MYRIAD_NETWORKS[2741])

    async def initialize(self) -> None:
        """Initialize HTTP client and Web3 connections."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if settings.myriad_api_key:
            headers["x-api-key"] = settings.myriad_api_key

        self._http_client = httpx.AsyncClient(
            base_url=settings.myriad_api_url,
            headers=headers,
            timeout=30.0,
        )

        # Initialize Web3 for default network
        await self._ensure_web3(self._network_id)

        logger.info(
            "Myriad platform initialized",
            api_url=settings.myriad_api_url,
            network_id=self._network_id,
            network_name=self._network_config["name"],
        )

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()

    async def _ensure_web3(self, network_id: int) -> AsyncWeb3:
        """Get or create Web3 client for network."""
        if network_id not in self._web3_clients:
            config = MYRIAD_NETWORKS.get(network_id)
            if not config:
                raise PlatformError(f"Unknown network ID: {network_id}", Platform.MYRIAD)

            rpc_url = config["rpc"]
            # Use configured RPC for Abstract if available
            if network_id in (2741, 11124) and settings.abstract_rpc_url:
                rpc_url = settings.abstract_rpc_url

            self._web3_clients[network_id] = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))

        return self._web3_clients[network_id]

    def _is_zksync_network(self, network_id: int) -> bool:
        """Check if network uses ZKsync transaction format (Abstract)."""
        # Abstract mainnet and testnet use ZKsync
        return network_id in (2741, 11124)

    async def _send_zksync_transaction(
        self,
        network_id: int,
        private_key: LocalAccount,
        to_address: str,
        data: str,
        value: int = 0,
    ) -> str:
        """
        Send a transaction on Abstract chain using EIP-1559 format.
        Abstract is ZKsync-based but accepts standard EIP-1559 transactions.
        Returns transaction hash.
        """
        config = MYRIAD_NETWORKS.get(network_id)
        if not config:
            raise PlatformError(f"Unknown network ID: {network_id}", Platform.MYRIAD)

        rpc_url = config["rpc"]
        if settings.abstract_rpc_url:
            rpc_url = settings.abstract_rpc_url

        # Use synchronous Web3 for simpler transaction handling
        def send_tx():
            from web3 import Web3 as SyncWeb3

            w3 = SyncWeb3(SyncWeb3.HTTPProvider(rpc_url))
            user_address = private_key.address
            chain_id = w3.eth.chain_id

            # Get nonce
            nonce = w3.eth.get_transaction_count(user_address)

            # Get EIP-1559 gas parameters
            try:
                latest_block = w3.eth.get_block('latest')
                base_fee = latest_block.get('baseFeePerGas', w3.eth.gas_price)
                max_priority_fee = w3.to_wei(0.1, 'gwei')  # Low priority fee for L2
                max_fee = base_fee * 2 + max_priority_fee

                tx = {
                    "from": user_address,
                    "to": Web3.to_checksum_address(to_address),
                    "data": data if data.startswith("0x") else f"0x{data}",
                    "value": value,
                    "chainId": chain_id,
                    "nonce": nonce,
                    "maxFeePerGas": max_fee,
                    "maxPriorityFeePerGas": max_priority_fee,
                    "gas": 500000,
                    "type": 2,  # EIP-1559
                }
            except Exception as e:
                # Fallback to legacy transaction
                logger.warning(f"EIP-1559 failed, using legacy: {e}")
                gas_price = w3.eth.gas_price
                tx = {
                    "from": user_address,
                    "to": Web3.to_checksum_address(to_address),
                    "data": data if data.startswith("0x") else f"0x{data}",
                    "value": value,
                    "chainId": chain_id,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                    "gas": 500000,
                }

            # Estimate gas
            try:
                gas_estimate = w3.eth.estimate_gas(tx)
                tx["gas"] = int(gas_estimate * 1.3)  # 30% buffer
            except Exception as e:
                logger.warning(f"Gas estimation failed: {e}, using default 500000")
                tx["gas"] = 500000

            # Sign and send
            signed = w3.eth.account.sign_transaction(tx, private_key.key)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            return tx_hash.hex()

        # Run in thread pool
        tx_hash = await asyncio.to_thread(send_tx)
        return tx_hash

    async def _wait_for_zksync_receipt(
        self,
        network_id: int,
        tx_hash: str,
        timeout: int = 120,
    ) -> dict:
        """Wait for transaction receipt on Abstract chain."""
        config = MYRIAD_NETWORKS.get(network_id)
        if not config:
            raise PlatformError(f"Unknown network ID: {network_id}", Platform.MYRIAD)

        rpc_url = config["rpc"]
        if settings.abstract_rpc_url:
            rpc_url = settings.abstract_rpc_url

        def wait_receipt():
            from web3 import Web3 as SyncWeb3
            w3 = SyncWeb3(SyncWeb3.HTTPProvider(rpc_url))
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
            return dict(receipt)

        return await asyncio.to_thread(wait_receipt)

    async def _api_request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
    ) -> dict:
        """Make API request to Myriad."""
        if not self._http_client:
            await self.initialize()

        try:
            response = await self._http_client.request(
                method=method,
                url=path,
                params=params,
                json=json_data,
            )

            if response.status_code == 401:
                raise PlatformError("Invalid or missing API key", Platform.MYRIAD)
            elif response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.MYRIAD)
            elif response.status_code == 404:
                raise MarketNotFoundError("Resource not found", Platform.MYRIAD)

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            raise PlatformError("API request timed out", Platform.MYRIAD)
        except httpx.HTTPStatusError as e:
            raise PlatformError(f"API error: {e.response.status_code}", Platform.MYRIAD)

    def _is_usdc_market(self, data: dict) -> bool:
        """Check if market uses USDC/USDT collateral (filter out PTS/PENGU markets)."""
        network_id = data.get("networkId", self._network_id)
        allowed_tokens = ALLOWED_COLLATERAL_TOKENS.get(network_id, [])

        if not allowed_tokens:
            # If no filter defined for this network, allow all markets
            return True

        # Extract token address - API may return it as string or as object
        token_data = data.get("token") or data.get("tokenAddress") or data.get("collateral")

        # If token is a dict (object), extract the address field
        if isinstance(token_data, dict):
            token_address = token_data.get("address") or token_data.get("id")
        else:
            token_address = token_data

        if not token_address:
            # If no token field, check if it's Abstract network
            # Abstract has PTS/PENGU markets, so be conservative and skip unknown markets
            if network_id in [2741, 11124]:  # Abstract mainnet/testnet
                logger.debug("Skipping market without token address on Abstract", market_id=data.get("id"))
                return False
            # For other networks, allow (they only have USDC/USDT)
            return True

        # Normalize addresses for comparison (lowercase)
        token_address_lower = str(token_address).lower()
        allowed_lower = [addr.lower() for addr in allowed_tokens]

        is_allowed = token_address_lower in allowed_lower
        if not is_allowed:
            logger.debug(
                "Filtering out non-USDC market",
                market_id=data.get("id"),
                token=token_address,
                network_id=network_id
            )
        return is_allowed

    def _parse_market(self, data: dict) -> Market:
        """Parse Myriad API market response into Market object."""
        network_id = data.get("networkId", self._network_id)
        network_config = MYRIAD_NETWORKS.get(network_id, self._network_config)

        # Get outcomes - Myriad uses outcome array with id, title, price
        outcomes = data.get("outcomes", [])
        yes_price = None
        no_price = None
        yes_token = None
        no_token = None
        yes_outcome_name = None
        no_outcome_name = None

        for outcome in outcomes:
            outcome_id = outcome.get("id")
            price = Decimal(str(outcome.get("price", 0)))
            outcome_title = outcome.get("title", "")

            # Outcome 0 is typically YES, 1 is NO
            if outcome_id == 0:
                yes_price = price
                yes_token = str(outcome_id)
                yes_outcome_name = outcome_title
            elif outcome_id == 1:
                no_price = price
                no_token = str(outcome_id)
                no_outcome_name = outcome_title

        # If no_price not set, derive from yes_price
        if yes_price and not no_price:
            no_price = Decimal("1") - yes_price

        # Parse state
        state = data.get("state", "open").lower()
        is_active = state == "open"

        # Parse volume (convert from token decimals)
        volume = data.get("volume24h") or data.get("volume", 0)
        volume_decimal = Decimal(str(volume)) if volume else Decimal("0")

        # Parse liquidity
        liquidity = data.get("liquidity", 0)
        liquidity_decimal = Decimal(str(liquidity)) if liquidity else Decimal("0")

        # Parse expiry
        expires_at = data.get("expiresAt")

        # Topics/categories
        topics = data.get("topics", [])
        category = topics[0] if topics else None

        return Market(
            platform=Platform.MYRIAD,
            chain=network_config["chain"],
            market_id=str(data.get("id", "")),
            event_id=data.get("slug"),
            title=data.get("title", ""),
            description=data.get("description"),
            category=category,
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=volume_decimal,
            liquidity=liquidity_decimal,
            is_active=is_active,
            close_time=expires_at,
            yes_token=yes_token,
            no_token=no_token,
            yes_outcome_name=yes_outcome_name,
            no_outcome_name=no_outcome_name,
            raw_data=data,
        )

    # ===================
    # Market Discovery
    # ===================

    async def get_markets(
        self,
        limit: int = 20,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Myriad."""
        params = {
            "limit": min(limit, 100),
            "page": (offset // limit) + 1 if limit > 0 else 1,
            "sort": "volume_24h",
            "order": "desc",
            "network_id": self._network_id,
        }

        if active_only:
            params["state"] = "open"

        try:
            data = await self._api_request("GET", "/markets", params=params)

            markets = []
            items = data.get("data", data.get("markets", []))

            for item in items:
                try:
                    # Filter out non-USDC markets (PTS, PENGU on Abstract)
                    if not self._is_usdc_market(item):
                        continue
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            return markets

        except Exception as e:
            logger.error("Failed to get markets", error=str(e))
            raise

    async def search_markets(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Market]:
        """Search markets by keyword."""
        params = {
            "keyword": query,
            "limit": min(limit, 100),
            "network_id": self._network_id,
        }

        try:
            data = await self._api_request("GET", "/markets", params=params)

            markets = []
            items = data.get("data", data.get("markets", []))

            for item in items:
                try:
                    # Filter out non-USDC markets (PTS, PENGU on Abstract)
                    if not self._is_usdc_market(item):
                        continue
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market in search", error=str(e))

            return markets[:limit]

        except Exception as e:
            logger.error("Failed to search markets", error=str(e))
            return []

    async def get_market(
        self,
        market_id: str,
        search_title: Optional[str] = None,
        include_closed: bool = False,
    ) -> Optional[Market]:
        """Get a specific market by ID or slug.

        Note: Myriad API uses slugs for single market lookups, not numeric IDs.
        The market_id parameter can be either the slug (preferred) or numeric ID.
        """
        # First try as slug (more likely to work)
        try:
            data = await self._api_request("GET", f"/markets/{market_id}")
            # For direct lookups, still filter non-USDC markets
            if not self._is_usdc_market(data):
                logger.info("Market uses non-USDC collateral, not supported", market_id=market_id)
                return None
            return self._parse_market(data)
        except MarketNotFoundError:
            pass
        except Exception as e:
            logger.debug("Market lookup as slug failed", market_id=market_id, error=str(e))

        # If market_id looks like a number, search for it in the market list
        if market_id.isdigit():
            try:
                # Fetch markets and find by numeric ID
                params = {"state": "open" if not include_closed else None, "limit": 100}
                params = {k: v for k, v in params.items() if v is not None}
                data = await self._api_request("GET", "/markets", params=params)

                items = data.get("data", data.get("markets", []))
                for item in items:
                    if str(item.get("id")) == market_id:
                        if not self._is_usdc_market(item):
                            logger.info("Market uses non-USDC collateral", market_id=market_id)
                            return None
                        return self._parse_market(item)

                # Also check closed markets if needed
                if include_closed:
                    params["state"] = "closed"
                    data = await self._api_request("GET", "/markets", params=params)
                    items = data.get("data", data.get("markets", []))
                    for item in items:
                        if str(item.get("id")) == market_id:
                            if not self._is_usdc_market(item):
                                return None
                            return self._parse_market(item)

            except Exception as e:
                logger.debug("Market search by numeric ID failed", market_id=market_id, error=str(e))

        return None

    async def get_trending_markets(self, limit: int = 10) -> list[Market]:
        """Get trending markets sorted by 24h volume."""
        return await self.get_markets(limit=limit, active_only=True)

    # ===================
    # Categories
    # ===================

    def get_available_categories(self) -> list[dict]:
        """Get list of available market categories (topics).

        Returns list of dicts with 'id', 'label', and 'emoji' keys.
        """
        return [
            {"id": "Sports", "label": "Sports", "emoji": "🏆"},
            {"id": "Politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "Crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "Economy", "label": "Economy", "emoji": "📈"},
            {"id": "Culture", "label": "Culture", "emoji": "🎭"},
            {"id": "Sentiment", "label": "Sentiment", "emoji": "💭"},
        ]

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 20,
    ) -> list[Market]:
        """Get markets filtered by category (topic).

        Args:
            category: Topic name (e.g., 'Sports', 'Politics', 'Crypto')
            limit: Maximum number of markets to return
        """
        params = {
            "topics": category,  # API uses 'topics' (plural)
            "limit": min(limit, 100),
            "sort": "volume_24h",
            "order": "desc",
            "state": "open",
            "network_id": self._network_id,
        }

        try:
            data = await self._api_request("GET", "/markets", params=params)

            markets = []
            items = data.get("data", data.get("markets", []))

            for item in items:
                try:
                    # Filter out non-USDC markets (PTS, PENGU on Abstract)
                    if not self._is_usdc_market(item):
                        continue
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            return markets

        except Exception as e:
            logger.error("Failed to get markets by category", category=category, error=str(e))
            return []

    # ===================
    # Order Book
    # ===================

    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
        slug: Optional[str] = None,  # Ignored - for API compatibility
    ) -> OrderBook:
        """
        Get order book for a market outcome.

        Note: Myriad uses AMM, so we derive orderbook from current prices.
        The slug parameter is ignored (used by other platforms like Limitless).
        """
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.MYRIAD)

        # For AMM-based markets, create synthetic orderbook from market price
        if outcome == Outcome.YES:
            price = market.yes_price or Decimal("0.5")
        else:
            price = market.no_price or Decimal("0.5")

        # Create synthetic spread around the price
        spread = Decimal("0.01")  # 1 cent spread
        best_bid = max(price - spread / 2, Decimal("0.01"))
        best_ask = min(price + spread / 2, Decimal("0.99"))

        # Use liquidity as depth
        liquidity = market.liquidity or Decimal("1000")

        return OrderBook(
            market_id=market_id,
            outcome=outcome,
            bids=[(best_bid, liquidity)],
            asks=[(best_ask, liquidity)],
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
    ) -> Quote:
        """Get a quote for a trade using Myriad's quote API."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.MYRIAD)

        network_id = market.raw_data.get("networkId", self._network_id)
        network_config = MYRIAD_NETWORKS.get(network_id, self._network_config)

        # Determine outcome ID (0=YES, 1=NO)
        outcome_id = 0 if outcome == Outcome.YES else 1

        # Get market slug from raw_data (API requires slug, not numeric ID)
        market_slug = market.raw_data.get("slug") or market.event_id
        if not market_slug:
            raise PlatformError(f"Market {market_id} has no slug", Platform.MYRIAD)

        # Build quote request - API uses market_slug, not market_id
        quote_request = {
            "market_slug": market_slug,
            "outcome_id": outcome_id,
            "action": side,  # "buy" or "sell"
            "slippage": 0.01,  # 1% slippage
        }

        # Add builder code for revenue sharing (triggers referralBuy calldata)
        if settings.myriad_referral_code:
            quote_request["builder"] = settings.myriad_referral_code

        # For buy: specify value (amount to spend)
        # For sell: can specify value (amount to receive) or shares
        if side == "buy":
            quote_request["value"] = float(amount)
        else:
            # For sells, use shares if we know token amount, else use value
            quote_request["value"] = float(amount)

        try:
            data = await self._api_request("POST", "/markets/quote", json_data=quote_request)

            # Parse quote response
            value = Decimal(str(data.get("value", amount)))
            shares = Decimal(str(data.get("shares", 0)))
            price_avg = Decimal(str(data.get("price_average", 0.5)))
            price_after = Decimal(str(data.get("price_after", price_avg)))
            calldata = data.get("calldata")

            # Calculate fees
            fees = data.get("fees", {})
            total_fee = Decimal(str(fees.get("treasury", 0))) + \
                       Decimal(str(fees.get("distributor", 0))) + \
                       Decimal(str(fees.get("fee", 0)))

            # Determine input/output based on side
            if side == "buy":
                input_amount = value
                expected_output = shares
                input_token = network_config["collateral"]
                output_token = f"{market_id}:{outcome_id}"
            else:
                input_amount = amount
                expected_output = value
                input_token = f"{market_id}:{outcome_id}"
                output_token = network_config["collateral"]

            # Calculate price impact
            price_before = Decimal(str(data.get("price_before", price_avg)))
            price_impact = abs(price_after - price_before) / price_before if price_before > 0 else Decimal("0")

            return Quote(
                platform=Platform.MYRIAD,
                chain=network_config["chain"],
                market_id=market_id,
                outcome=outcome,
                side=side,
                input_token=input_token,
                input_amount=input_amount,
                output_token=output_token,
                expected_output=expected_output,
                price_per_token=price_avg,
                price_impact=price_impact,
                platform_fee=total_fee,
                network_fee_estimate=Decimal("0.001"),  # Estimate
                expires_at=None,
                quote_data={
                    "calldata": calldata,
                    "network_id": network_id,
                    "market_id": market_id,
                    "outcome_id": outcome_id,
                    "shares_threshold": data.get("shares_threshold"),
                    "prediction_market_contract": network_config["prediction_market"],
                    "collateral_token": network_config["collateral"],
                    "collateral_decimals": network_config["collateral_decimals"],
                },
            )

        except Exception as e:
            logger.error("Failed to get quote", market_id=market_id, error=str(e))
            raise PlatformError(f"Quote failed: {str(e)}", Platform.MYRIAD)

    async def _ensure_approval(
        self,
        private_key: LocalAccount,
        network_id: int,
        token_address: str,
        spender_address: str,
        amount: int,
    ) -> Optional[str]:
        """Ensure token approval for spender, return tx hash if approval was needed."""
        web3 = await self._ensure_web3(network_id)

        token = web3.eth.contract(
            address=Web3.to_checksum_address(token_address),
            abi=ERC20_ABI,
        )

        user_address = private_key.address

        # Check current allowance
        current_allowance = await token.functions.allowance(
            Web3.to_checksum_address(user_address),
            Web3.to_checksum_address(spender_address),
        ).call()

        if current_allowance >= amount:
            logger.debug("Sufficient allowance", allowance=current_allowance, needed=amount)
            return None

        # Approve max amount
        max_approval = 2**256 - 1

        logger.info("Approving token spend", token=token_address, spender=spender_address)

        # Use ZKsync SDK for Abstract chain
        if self._is_zksync_network(network_id):
            # Build approval calldata using synchronous Web3 for encoding
            sync_token = Web3().eth.contract(
                address=Web3.to_checksum_address(token_address),
                abi=ERC20_ABI,
            )
            # web3.py v7 uses encode_abi method
            approve_data = sync_token.encode_abi(
                "approve",
                [Web3.to_checksum_address(spender_address), max_approval]
            )
            logger.info("Using ZKsync transaction for Abstract chain approval")
            tx_hash = await self._send_zksync_transaction(
                network_id=network_id,
                private_key=private_key,
                to_address=token_address,
                data=approve_data,
            )

            # Wait for confirmation
            receipt = await self._wait_for_zksync_receipt(network_id, tx_hash, timeout=60)
            if receipt.get("status") != 1:
                raise PlatformError("Approval transaction failed", Platform.MYRIAD)

            logger.info("ZKsync approval confirmed", tx_hash=tx_hash)
            return tx_hash

        # Standard EVM transaction for other chains
        nonce = await web3.eth.get_transaction_count(user_address)
        gas_price = await web3.eth.gas_price

        tx = await token.functions.approve(
            Web3.to_checksum_address(spender_address),
            max_approval,
        ).build_transaction({
            "from": user_address,
            "nonce": nonce,
            "gasPrice": gas_price,
            "gas": 100000,
        })

        # Sign and send
        signed = private_key.sign_transaction(tx)
        tx_hash = await web3.eth.send_raw_transaction(signed.raw_transaction)

        # Wait for confirmation
        receipt = await web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        if receipt["status"] != 1:
            raise PlatformError("Approval transaction failed", Platform.MYRIAD)

        logger.info("Approval confirmed", tx_hash=tx_hash.hex())
        return tx_hash.hex()

    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
    ) -> TradeResult:
        """Execute a trade using the calldata from the quote."""
        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount",
                Platform.MYRIAD,
            )

        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.MYRIAD)

        calldata = quote.quote_data.get("calldata")
        if not calldata:
            raise PlatformError("Calldata missing from quote", Platform.MYRIAD)

        network_id = quote.quote_data.get("network_id", self._network_id)
        network_config = MYRIAD_NETWORKS.get(network_id, self._network_config)
        prediction_market = quote.quote_data.get("prediction_market_contract")
        collateral_token = quote.quote_data.get("collateral_token")
        collateral_decimals = quote.quote_data.get("collateral_decimals", 6)

        try:
            web3 = await self._ensure_web3(network_id)
            user_address = private_key.address

            # For buy orders, ensure collateral approval
            if quote.side == "buy":
                # Convert amount to token units
                amount_units = int(quote.input_amount * (10 ** collateral_decimals))

                approval_tx = await self._ensure_approval(
                    private_key=private_key,
                    network_id=network_id,
                    token_address=collateral_token,
                    spender_address=prediction_market,
                    amount=amount_units,
                )

                if approval_tx:
                    logger.info("Token approval completed", tx_hash=approval_tx)

            # Build transaction with calldata
            nonce = await web3.eth.get_transaction_count(user_address)
            gas_price = await web3.eth.gas_price

            # Estimate gas
            tx_params = {
                "from": user_address,
                "to": Web3.to_checksum_address(prediction_market),
                "data": calldata,
                "nonce": nonce,
                "gasPrice": gas_price,
            }

            try:
                gas_estimate = await web3.eth.estimate_gas(tx_params)
                gas_limit = int(gas_estimate * 1.2)  # 20% buffer
            except Exception as e:
                error_str = str(e)
                logger.warning("Gas estimation failed", error=error_str)

                # Check if this is an actual execution error vs just gas estimation
                if "execution reverted" in error_str.lower():
                    # Try to extract revert reason
                    if "insufficient" in error_str.lower():
                        raise PlatformError(
                            f"Insufficient balance for this trade. Check your USDC.e balance.",
                            Platform.MYRIAD
                        )
                    raise PlatformError(f"Transaction would fail: {error_str[:200]}", Platform.MYRIAD)

                # Use default gas limit if estimation just failed
                gas_limit = 500000

            tx_params["gas"] = gas_limit

            logger.info(
                "Executing trade",
                market_id=quote.market_id,
                side=quote.side,
                outcome=quote.outcome.value,
                amount=str(quote.input_amount),
                is_zksync=self._is_zksync_network(network_id),
            )

            # Use ZKsync SDK for Abstract chain
            if self._is_zksync_network(network_id):
                logger.info("Using ZKsync transaction for Abstract chain trade")
                tx_hash_hex = await self._send_zksync_transaction(
                    network_id=network_id,
                    private_key=private_key,
                    to_address=prediction_market,
                    data=calldata,
                )

                logger.info("ZKsync trade submitted", tx_hash=tx_hash_hex)

                # Wait for confirmation
                receipt = await self._wait_for_zksync_receipt(network_id, tx_hash_hex, timeout=120)

                if receipt.get("status") != 1:
                    return TradeResult(
                        success=False,
                        tx_hash=tx_hash_hex,
                        input_amount=quote.input_amount,
                        output_amount=None,
                        error_message="Transaction reverted",
                        explorer_url=f"{network_config['explorer']}/tx/{tx_hash_hex}",
                    )

                logger.info("ZKsync trade confirmed", tx_hash=tx_hash_hex, gas_used=receipt.get("gasUsed"))

                return TradeResult(
                    success=True,
                    tx_hash=tx_hash_hex,
                    input_amount=quote.input_amount,
                    output_amount=quote.expected_output,
                    error_message=None,
                    explorer_url=f"{network_config['explorer']}/tx/{tx_hash_hex}",
                )

            # Standard EVM transaction for other chains
            tx_params["gas"] = gas_limit

            # Sign and send
            signed = private_key.sign_transaction(tx_params)
            tx_hash = await web3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            logger.info("Trade submitted", tx_hash=tx_hash_hex)

            # Wait for confirmation
            receipt = await web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] != 1:
                return TradeResult(
                    success=False,
                    tx_hash=tx_hash_hex,
                    input_amount=quote.input_amount,
                    output_amount=None,
                    error_message="Transaction reverted",
                    explorer_url=f"{network_config['explorer']}/tx/{tx_hash_hex}",
                )

            logger.info("Trade confirmed", tx_hash=tx_hash_hex, gas_used=receipt["gasUsed"])

            return TradeResult(
                success=True,
                tx_hash=tx_hash_hex,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
                error_message=None,
                explorer_url=f"{network_config['explorer']}/tx/{tx_hash_hex}",
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

    # ===================
    # Redemption
    # ===================

    async def get_market_resolution(self, market_id: str) -> MarketResolution:
        """Check if a market has resolved."""
        try:
            market = await self.get_market(market_id, include_closed=True)
            if not market or not market.raw_data:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            raw = market.raw_data
            state = raw.get("state", "").lower()

            # Check if resolved
            if state not in ("resolved", "closed"):
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            # Get winning outcome
            resolved_outcome_id = raw.get("resolvedOutcomeId")
            winning_outcome = None

            if resolved_outcome_id is not None:
                winning_outcome = "yes" if resolved_outcome_id == 0 else "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning_outcome,
                resolution_time=raw.get("resolvedAt"),
            )

        except Exception as e:
            logger.warning("Failed to check resolution", market_id=market_id, error=str(e))
            return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

    async def redeem_position(
        self,
        market_id: str,
        outcome: Outcome,
        token_amount: Decimal,
        private_key: Any,
    ) -> RedemptionResult:
        """Redeem winning tokens from a resolved market."""
        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount",
                Platform.MYRIAD,
            )

        try:
            # Get claim calldata from API
            market = await self.get_market(market_id)
            if not market:
                raise MarketNotFoundError(f"Market {market_id} not found", Platform.MYRIAD)

            network_id = market.raw_data.get("networkId", self._network_id)
            network_config = MYRIAD_NETWORKS.get(network_id, self._network_config)

            outcome_id = 0 if outcome == Outcome.YES else 1

            claim_request = {
                "market_id": int(market_id),
                "network_id": network_id,
                "outcome_id": outcome_id,
            }

            data = await self._api_request("POST", "/markets/claim", json_data=claim_request)

            calldata = data.get("calldata")
            if not calldata:
                return RedemptionResult(
                    success=False,
                    tx_hash=None,
                    amount_redeemed=None,
                    error_message="No calldata returned for claim",
                    explorer_url=None,
                )

            # Execute claim transaction
            web3 = await self._ensure_web3(network_id)
            user_address = private_key.address
            prediction_market = network_config["prediction_market"]

            nonce = await web3.eth.get_transaction_count(user_address)
            gas_price = await web3.eth.gas_price

            tx_params = {
                "from": user_address,
                "to": Web3.to_checksum_address(prediction_market),
                "data": calldata,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": 300000,
            }

            signed = private_key.sign_transaction(tx_params)
            tx_hash = await web3.eth.send_raw_transaction(signed.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            receipt = await web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] != 1:
                return RedemptionResult(
                    success=False,
                    tx_hash=tx_hash_hex,
                    amount_redeemed=None,
                    error_message="Claim transaction reverted",
                    explorer_url=f"{network_config['explorer']}/tx/{tx_hash_hex}",
                )

            return RedemptionResult(
                success=True,
                tx_hash=tx_hash_hex,
                amount_redeemed=token_amount,  # Approximate
                error_message=None,
                explorer_url=f"{network_config['explorer']}/tx/{tx_hash_hex}",
            )

        except Exception as e:
            logger.error("Redemption failed", market_id=market_id, error=str(e))
            return RedemptionResult(
                success=False,
                tx_hash=None,
                amount_redeemed=None,
                error_message=str(e),
                explorer_url=None,
            )

    # ===================
    # Portfolio
    # ===================

    async def get_positions(self, wallet_address: str) -> list[dict]:
        """Get user's positions from Myriad API."""
        try:
            params = {
                "network_id": self._network_id,
                "limit": 100,
            }

            data = await self._api_request(
                "GET",
                f"/users/{wallet_address}/portfolio",
                params=params,
            )

            positions = []
            items = data.get("data", data.get("positions", []))

            for item in items:
                positions.append({
                    "market_id": str(item.get("marketId", "")),
                    "outcome_id": item.get("outcomeId"),
                    "network_id": item.get("networkId", self._network_id),
                    "shares": Decimal(str(item.get("shares", 0))),
                    "price": Decimal(str(item.get("price", 0))),
                    "value": Decimal(str(item.get("value", 0))),
                    "profit": Decimal(str(item.get("profit", 0))),
                    "status": item.get("status", "ongoing"),
                    "winnings_to_claim": item.get("winningsToClaim", False),
                    "winnings_claimed": item.get("winningsClaimed", False),
                })

            return positions

        except Exception as e:
            logger.error("Failed to get positions", wallet=wallet_address[:10], error=str(e))
            return []


# Singleton instance
myriad_platform = MyriadPlatform()
