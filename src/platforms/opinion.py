"""
Opinion Labs platform implementation using CLOB SDK.
AI-oracle powered prediction market on BNB Chain.
"""

import asyncio
from decimal import Decimal
from typing import Any, Optional
from datetime import datetime

import httpx
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3
from web3.middleware import ExtraDataToPOAMiddleware

from src.services.signer import EVMSigner, LegacyEVMSigner

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
    MarketResolution,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)


class OpinionPlatform(BasePlatform):
    """
    Opinion Labs prediction market platform.
    Uses CLOB SDK on BNB Chain with AI oracles.
    """

    platform = Platform.OPINION
    chain = Chain.BSC

    name = "Opinion Labs"
    description = "AI-oracle powered prediction markets on BNB Chain"
    website = "https://opinion.trade"

    collateral_symbol = "USDT"
    collateral_decimals = 18  # USDT on BSC has 18 decimals

    # Contract addresses for BSC mainnet
    USDT_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"
    # Default CTF exchange (will be fetched from API)
    DEFAULT_CTF_EXCHANGE = "0x5F45344126D6488025B0b84A3A8189F2487a7246"
    # Conditional tokens contract
    CONDITIONAL_TOKENS = "0xbB5f35D40132A0478f6aa91e79962e9F752167EA"

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._web3: Optional[AsyncWeb3] = None
        self._sdk_client: Any = None
        # Read-only SDK client for orderbook queries (no trading)
        self._readonly_sdk_client: Any = None
        # Cache SDK clients per wallet address for faster repeat trades
        self._sdk_client_cache: dict[str, Any] = {}
        # Track wallets that have already enabled trading (approved tokens)
        self._trading_enabled_wallets: set[str] = set()
        # Cache for CTF exchange address
        self._ctf_exchange_address: Optional[str] = None
        # Markets cache
        self._markets_cache: list[Market] = []
        self._markets_cache_time: float = 0
        self.CACHE_TTL = 300  # 5 minutes
    
    async def initialize(self) -> None:
        """Initialize Opinion Labs API client."""
        headers = {
            "Content-Type": "application/json",
        }
        # Opinion uses 'apikey' header, not Bearer token
        # Strip whitespace to handle env vars with trailing spaces
        if settings.opinion_api_key:
            headers["apikey"] = settings.opinion_api_key.strip()

        self._http_client = httpx.AsyncClient(
            base_url=settings.opinion_api_url,
            timeout=30.0,
            headers=headers,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30),
        )

        # Web3 for BSC
        self._web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(settings.bsc_rpc_url)
        )
        self._web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

        # Initialize read-only SDK client for orderbook queries
        # Uses a dummy key since we only need read access
        try:
            from opinion_clob_sdk import Client

            # Generate dummy values for read-only operations
            # These won't be used for signing transactions
            dummy_key = "0x" + "1" * 64  # Valid 32-byte hex key
            # Use configured multi_sig_addr or a dummy address if not set
            multi_sig = settings.opinion_multi_sig_addr or "0x" + "0" * 40
            self._readonly_sdk_client = Client(
                host=settings.opinion_api_url,
                apikey=(settings.opinion_api_key or "").strip(),
                chain_id=56,  # BNB Chain mainnet
                rpc_url=settings.bsc_rpc_url,
                private_key=dummy_key,
                multi_sig_addr=multi_sig,
            )
            logger.info("Opinion SDK read-only client initialized")
        except ImportError:
            logger.warning("opinion-clob-sdk not installed, orderbook queries will use fallback")
            self._readonly_sdk_client = None
        except Exception as e:
            logger.warning("Failed to initialize Opinion SDK read-only client", error=str(e))
            self._readonly_sdk_client = None

        logger.info("Opinion Labs platform initialized")

    async def _get_ctf_exchange_address(self) -> str:
        """Get the CTF exchange address from the Opinion API."""
        if self._ctf_exchange_address:
            return self._ctf_exchange_address

        try:
            # Fetch quote tokens to get the CTF exchange address
            data = await self._api_request("GET", "/openapi/quoteToken", params={"chainId": "56"})
            quote_tokens = data.get("result", {}).get("list", [])

            for token in quote_tokens:
                if token.get("quoteTokenAddress", "").lower() == self.USDT_ADDRESS.lower():
                    self._ctf_exchange_address = token.get("ctfExchangeAddress", self.DEFAULT_CTF_EXCHANGE)
                    logger.info("Found CTF exchange address", address=self._ctf_exchange_address)
                    return self._ctf_exchange_address

            # Fallback to default
            self._ctf_exchange_address = self.DEFAULT_CTF_EXCHANGE
            return self._ctf_exchange_address
        except Exception as e:
            logger.warning("Failed to get CTF exchange address, using default", error=str(e))
            return self.DEFAULT_CTF_EXCHANGE

    async def _enable_trading_eoa(self, private_key: "LocalAccount") -> bool:
        """
        Manually enable trading for an EOA (Externally Owned Account) wallet.

        The Opinion SDK's enable_trading() uses Gnosis Safe multi-sig contracts,
        which doesn't work for regular EOA wallets created by the bot. This method
        does the token approvals directly via web3.

        Args:
            private_key: EVM LocalAccount with the wallet's private key

        Returns:
            True if approvals were successful, False otherwise
        """
        from web3 import Web3
        from web3.middleware import ExtraDataToPOAMiddleware

        wallet_address = private_key.address
        wallet_lower = wallet_address.lower()

        # Skip if already enabled
        if wallet_lower in self._trading_enabled_wallets:
            logger.debug("Trading already enabled for wallet", wallet=wallet_address[:10])
            return True

        try:
            # Create web3 instance
            w3 = Web3(Web3.HTTPProvider(settings.bsc_rpc_url))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

            # ERC20 ABI for approve
            erc20_abi = [
                {
                    "inputs": [
                        {"name": "spender", "type": "address"},
                        {"name": "amount", "type": "uint256"}
                    ],
                    "name": "approve",
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "nonpayable",
                    "type": "function"
                },
                {
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function"
                }
            ]

            # Conditional tokens ABI for setApprovalForAll
            ct_abi = [
                {
                    "inputs": [
                        {"name": "operator", "type": "address"},
                        {"name": "approved", "type": "bool"}
                    ],
                    "name": "setApprovalForAll",
                    "outputs": [],
                    "stateMutability": "nonpayable",
                    "type": "function"
                },
                {
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "operator", "type": "address"}
                    ],
                    "name": "isApprovedForAll",
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "view",
                    "type": "function"
                }
            ]

            # Get CTF exchange address
            ctf_exchange = await self._get_ctf_exchange_address()
            ctf_exchange = Web3.to_checksum_address(ctf_exchange)
            usdt_address = Web3.to_checksum_address(self.USDT_ADDRESS)
            conditional_tokens = Web3.to_checksum_address(self.CONDITIONAL_TOKENS)
            wallet_checksum = Web3.to_checksum_address(wallet_address)

            usdt_contract = w3.eth.contract(address=usdt_address, abi=erc20_abi)
            ct_contract = w3.eth.contract(address=conditional_tokens, abi=ct_abi)

            # Unlimited approval amount
            max_uint256 = 2**256 - 1
            # Minimum threshold (1 billion USDT with 18 decimals)
            min_threshold = 1_000_000_000 * 10**18

            # Check current nonce
            nonce = w3.eth.get_transaction_count(wallet_checksum)

            # 1. Approve USDT for CTF exchange
            allowance_ctf = usdt_contract.functions.allowance(wallet_checksum, ctf_exchange).call()
            if allowance_ctf < min_threshold:
                logger.info("Approving USDT for CTF exchange", wallet=wallet_address[:10], ctf_exchange=ctf_exchange[:10])
                tx = usdt_contract.functions.approve(ctf_exchange, max_uint256).build_transaction({
                    "from": wallet_checksum,
                    "nonce": nonce,
                    "gas": 100000,
                    "gasPrice": w3.eth.gas_price,
                })
                signed = w3.eth.account.sign_transaction(tx, private_key.key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt["status"] != 1:
                    raise Exception(f"USDT approval for CTF exchange failed: {tx_hash.hex()}")
                logger.info("USDT approved for CTF exchange", tx_hash=tx_hash.hex())
                nonce += 1

            # 2. Approve USDT for Conditional Tokens contract
            allowance_ct = usdt_contract.functions.allowance(wallet_checksum, conditional_tokens).call()
            if allowance_ct < min_threshold:
                logger.info("Approving USDT for Conditional Tokens", wallet=wallet_address[:10])
                tx = usdt_contract.functions.approve(conditional_tokens, max_uint256).build_transaction({
                    "from": wallet_checksum,
                    "nonce": nonce,
                    "gas": 100000,
                    "gasPrice": w3.eth.gas_price,
                })
                signed = w3.eth.account.sign_transaction(tx, private_key.key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt["status"] != 1:
                    raise Exception(f"USDT approval for Conditional Tokens failed: {tx_hash.hex()}")
                logger.info("USDT approved for Conditional Tokens", tx_hash=tx_hash.hex())
                nonce += 1

            # 3. SetApprovalForAll on Conditional Tokens for CTF exchange
            is_approved = ct_contract.functions.isApprovedForAll(wallet_checksum, ctf_exchange).call()
            if not is_approved:
                logger.info("Setting approval for all on Conditional Tokens", wallet=wallet_address[:10])
                tx = ct_contract.functions.setApprovalForAll(ctf_exchange, True).build_transaction({
                    "from": wallet_checksum,
                    "nonce": nonce,
                    "gas": 100000,
                    "gasPrice": w3.eth.gas_price,
                })
                signed = w3.eth.account.sign_transaction(tx, private_key.key)
                tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt["status"] != 1:
                    raise Exception(f"SetApprovalForAll failed: {tx_hash.hex()}")
                logger.info("SetApprovalForAll completed", tx_hash=tx_hash.hex())

            # Mark wallet as enabled
            self._trading_enabled_wallets.add(wallet_lower)
            logger.info("Trading enabled for EOA wallet", wallet=wallet_address[:10])
            return True

        except Exception as e:
            logger.error("Failed to enable trading for EOA wallet", error=str(e), wallet=wallet_address[:10])
            raise PlatformError(
                f"Failed to approve tokens on Opinion. Ensure wallet has BNB for gas. Error: {str(e)[:100]}",
                Platform.OPINION,
            )

    async def _enable_trading_eoa_with_signer(self, signer: EVMSigner) -> bool:
        """Enable trading for a Privy wallet by approving USDT and CT on BSC.

        Same approvals as _enable_trading_eoa but uses Privy signer for signing.
        """
        wallet_address = signer.address
        wallet_lower = wallet_address.lower()

        if wallet_lower in self._trading_enabled_wallets:
            logger.debug("Trading already enabled for Privy wallet", wallet=wallet_address[:10])
            return True

        try:
            # Use sync web3 in thread for read-only calls, Privy signer for signing
            from web3.middleware import ExtraDataToPOAMiddleware as POA

            w3 = Web3(Web3.HTTPProvider(settings.bsc_rpc_url))
            w3.middleware_onion.inject(POA, layer=0)

            erc20_abi = [
                {
                    "inputs": [
                        {"name": "spender", "type": "address"},
                        {"name": "amount", "type": "uint256"}
                    ],
                    "name": "approve",
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "nonpayable",
                    "type": "function"
                },
                {
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function"
                }
            ]

            ct_abi = [
                {
                    "inputs": [
                        {"name": "operator", "type": "address"},
                        {"name": "approved", "type": "bool"}
                    ],
                    "name": "setApprovalForAll",
                    "outputs": [],
                    "stateMutability": "nonpayable",
                    "type": "function"
                },
                {
                    "inputs": [
                        {"name": "owner", "type": "address"},
                        {"name": "operator", "type": "address"}
                    ],
                    "name": "isApprovedForAll",
                    "outputs": [{"name": "", "type": "bool"}],
                    "stateMutability": "view",
                    "type": "function"
                }
            ]

            ctf_exchange = await self._get_ctf_exchange_address()
            ctf_exchange = Web3.to_checksum_address(ctf_exchange)
            usdt_address = Web3.to_checksum_address(self.USDT_ADDRESS)
            conditional_tokens = Web3.to_checksum_address(self.CONDITIONAL_TOKENS)
            wallet_checksum = Web3.to_checksum_address(wallet_address)

            usdt_contract = w3.eth.contract(address=usdt_address, abi=erc20_abi)
            ct_contract = w3.eth.contract(address=conditional_tokens, abi=ct_abi)

            max_uint256 = 2**256 - 1
            min_threshold = 1_000_000_000 * 10**18

            sync_usdt = Web3().eth.contract(address=usdt_address, abi=erc20_abi)
            sync_ct = Web3().eth.contract(address=conditional_tokens, abi=ct_abi)

            # Helper to sign, send, and wait
            async def send_approval_tx(to_addr, data_hex):
                nonce = await asyncio.to_thread(lambda: w3.eth.get_transaction_count(wallet_checksum))
                gas_price = await asyncio.to_thread(lambda: w3.eth.gas_price)
                tx_params = {
                    "to": to_addr,
                    "data": data_hex,
                    "nonce": nonce,
                    "gas": 100000,
                    "gasPrice": gas_price,
                    "chainId": 56,
                    "value": 0,
                }
                signed_raw = await signer.sign_transaction(tx_params)

                def send_and_wait(raw_tx):
                    tx_hash = w3.eth.send_raw_transaction(raw_tx)
                    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                    if receipt["status"] != 1:
                        raise Exception(f"Approval failed: {tx_hash.hex()}")
                    return tx_hash.hex()

                return await asyncio.to_thread(send_and_wait, signed_raw)

            # 1. Approve USDT for CTF exchange
            allowance_ctf = await asyncio.to_thread(
                lambda: usdt_contract.functions.allowance(wallet_checksum, ctf_exchange).call()
            )
            if allowance_ctf < min_threshold:
                logger.info("Approving USDT for CTF exchange (signer)", wallet=wallet_address[:10])
                data = sync_usdt.encode_abi("approve", [ctf_exchange, max_uint256])
                await send_approval_tx(usdt_address, data)

            # 2. Approve USDT for Conditional Tokens contract
            allowance_ct = await asyncio.to_thread(
                lambda: usdt_contract.functions.allowance(wallet_checksum, conditional_tokens).call()
            )
            if allowance_ct < min_threshold:
                logger.info("Approving USDT for Conditional Tokens (signer)", wallet=wallet_address[:10])
                data = sync_usdt.encode_abi("approve", [conditional_tokens, max_uint256])
                await send_approval_tx(usdt_address, data)

            # 3. SetApprovalForAll on Conditional Tokens for CTF exchange
            is_approved = await asyncio.to_thread(
                lambda: ct_contract.functions.isApprovedForAll(wallet_checksum, ctf_exchange).call()
            )
            if not is_approved:
                logger.info("Setting approval for all on Conditional Tokens (signer)", wallet=wallet_address[:10])
                data = sync_ct.encode_abi("setApprovalForAll", [ctf_exchange, True])
                await send_approval_tx(conditional_tokens, data)

            self._trading_enabled_wallets.add(wallet_lower)
            logger.info("Trading enabled for Privy wallet", wallet=wallet_address[:10])
            return True

        except Exception as e:
            logger.error("Failed to enable trading for Privy wallet", error=str(e), wallet=wallet_address[:10])
            raise PlatformError(
                f"Failed to approve tokens on Opinion. Ensure wallet has BNB for gas. Error: {str(e)[:100]}",
                Platform.OPINION,
            )

    async def close(self) -> None:
        """Close connections."""
        if self._http_client:
            await self._http_client.aclose()

    def _init_sdk_client(self, private_key: str) -> Any:
        """Initialize the Opinion CLOB SDK client."""
        try:
            from opinion_clob_sdk import Client
            
            return Client(
                host=settings.opinion_api_url,
                apikey=(settings.opinion_api_key or "").strip(),
                chain_id=56,  # BNB Chain mainnet
                rpc_url=settings.bsc_rpc_url,
                private_key=private_key,
                multi_sig_addr=settings.opinion_multi_sig_addr,
            )
        except ImportError:
            logger.warning("opinion-clob-sdk not installed")
            return None
    
    async def _api_request(
        self,
        method: str,
        endpoint: str,
        **kwargs,
    ) -> dict:
        """Make request to Opinion API."""
        if not self._http_client:
            raise RuntimeError("Client not initialized")
        
        try:
            response = await self._http_client.request(method, endpoint, **kwargs)
            
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded", Platform.OPINION)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            raise PlatformError(
                f"API error: {e.response.status_code}",
                Platform.OPINION,
                str(e.response.status_code),
            )
    
    def _parse_market(self, data: dict) -> Market:
        """Parse Opinion market data into Market object."""
        # Opinion API uses camelCase field names
        market_id = str(data.get("marketId") or data.get("market_id") or data.get("id"))

        # Token IDs
        yes_token = data.get("yesTokenId") or data.get("yes_token_id")
        no_token = data.get("noTokenId") or data.get("no_token_id")

        # Extract pricing and custom outcome names from tokens array if present
        tokens = data.get("tokens", [])
        yes_price = None
        no_price = None
        yes_outcome_name = None
        no_outcome_name = None

        for token in tokens:
            outcome = token.get("outcome", "").lower()
            token_name = token.get("title") or token.get("name") or token.get("outcome", "")
            if outcome == "yes" or token.get("index") == 0:
                if not yes_token:
                    yes_token = token.get("tokenId") or token.get("token_id")
                yes_price = Decimal(str(token.get("price", 0.5)))
                if token_name and token_name.strip().lower() not in ("yes", "no"):
                    yes_outcome_name = token_name.strip()
            elif outcome == "no" or token.get("index") == 1:
                if not no_token:
                    no_token = token.get("tokenId") or token.get("token_id")
                no_price = Decimal(str(token.get("price", 0.5)))
                if token_name and token_name.strip().lower() not in ("yes", "no"):
                    no_outcome_name = token_name.strip()

        # Fallback to top-level prices (default to 0.5 if not available)
        if yes_price is None:
            yes_price = Decimal(str(data.get("yesPrice") or data.get("yes_price") or "0.5"))
        if no_price is None:
            no_price = Decimal(str(data.get("noPrice") or data.get("no_price") or "0.5"))

        # Status - Opinion uses statusEnum or numeric status
        status_enum = data.get("statusEnum", "").lower()
        status_num = data.get("status")
        is_active = status_enum in ("activated", "active", "open") or status_num == 2

        # End time - Opinion uses cutoffAt (Unix timestamp)
        close_time = data.get("cutoffAt") or data.get("close_time") or data.get("endTime")
        if close_time and isinstance(close_time, (int, float)):
            close_time = datetime.fromtimestamp(close_time).isoformat()

        # Resolution criteria - Opinion uses 'rules' field for settlement rules
        resolution_criteria = data.get("rules") or data.get("resolutionRules") or data.get("description")

        return Market(
            platform=Platform.OPINION,
            chain=Chain.BSC,
            market_id=market_id,
            event_id=data.get("eventId") or data.get("event_id"),
            title=data.get("marketTitle") or data.get("market_title") or data.get("title") or "",
            description=data.get("rules") or data.get("description"),
            category=data.get("category") or data.get("topicType"),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume24h") or data.get("volume_24h") or data.get("volume") or 0)),
            liquidity=Decimal(str(data.get("liquidity") or data.get("openInterest") or 0)),
            is_active=is_active,
            close_time=close_time,
            yes_token=yes_token,
            no_token=no_token,
            raw_data=data,
            resolution_criteria=resolution_criteria,
            yes_outcome_name=yes_outcome_name,
            no_outcome_name=no_outcome_name,
        )
    
    # ===================
    # Orderbook Price Enrichment
    # ===================

    async def _fetch_orderbook_price(self, market: Market) -> tuple[str, Decimal | None, Decimal | None]:
        """Fetch best bid/ask prices for a single market from orderbook."""
        try:
            if not market.yes_token:
                return (market.market_id, None, None)

            # Fetch YES orderbook
            yes_orderbook = await self.get_orderbook(market.market_id, Outcome.YES)
            yes_price = yes_orderbook.best_ask  # Price to buy YES

            # Calculate NO price as 1 - YES price (for binary markets)
            no_price = Decimal("1") - yes_price if yes_price else None

            return (market.market_id, yes_price, no_price)
        except Exception as e:
            logger.debug("Failed to fetch orderbook price", market_id=market.market_id, error=str(e))
            return (market.market_id, None, None)

    async def _enrich_markets_with_orderbook_prices(self, markets: list[Market], max_markets: int = 30) -> list[Market]:
        """
        Enrich markets with real orderbook prices.
        Fetches orderbooks in parallel for efficiency.

        Args:
            markets: List of markets to enrich
            max_markets: Maximum number of markets to fetch orderbooks for (to limit API calls)
        """
        if not self._readonly_sdk_client:
            # SDK not available, return markets as-is
            return markets

        # Only fetch orderbooks for the first N markets to limit API calls
        markets_to_enrich = markets[:max_markets]

        # Fetch orderbook prices in parallel
        tasks = [self._fetch_orderbook_price(m) for m in markets_to_enrich]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build a map of market_id -> (yes_price, no_price)
        price_map: dict[str, tuple[Decimal | None, Decimal | None]] = {}
        for result in results:
            if isinstance(result, tuple) and len(result) == 3:
                market_id, yes_price, no_price = result
                if yes_price is not None:
                    price_map[market_id] = (yes_price, no_price)

        # Update market prices
        enriched_count = 0
        for market in markets:
            if market.market_id in price_map:
                yes_price, no_price = price_map[market.market_id]
                if yes_price is not None:
                    market.yes_price = yes_price
                    market.no_price = no_price or Decimal("1") - yes_price
                    enriched_count += 1

        logger.info("Enriched markets with orderbook prices", total=len(markets), enriched=enriched_count)
        return markets

    # ===================
    # Market Discovery
    # ===================

    async def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = True,
    ) -> list[Market]:
        """Get list of markets from Opinion.

        Fetches all markets and caches for 5 minutes to avoid
        repeated API calls.
        """
        import time

        # Check if cache is still valid
        now = time.time()
        if self._markets_cache and (now - self._markets_cache_time) < self.CACHE_TTL:
            return self._markets_cache[offset:offset + limit]

        # Paginate through API (200 per page, fetch all available)
        api_page_size = 200
        max_pages = 15

        all_data = []
        seen_ids = set()
        for page_num in range(max_pages):
            params = {
                "limit": api_page_size,
                "offset": page_num * api_page_size,
                "sortBy": 5,  # Sort by 24h volume
            }
            if active_only:
                params["status"] = "activated"

            try:
                data = await self._api_request("GET", "/openapi/market", params=params)
                markets_data = data.get("result", {}).get("list", [])
                if not markets_data and isinstance(data, list):
                    markets_data = data
                if not markets_data:
                    break  # No more pages

                # Deduplicate: stop if this page is all duplicates (API recycling)
                new_count = 0
                for item in markets_data:
                    mid = str(item.get("marketId") or item.get("market_id") or item.get("id"))
                    if mid not in seen_ids:
                        seen_ids.add(mid)
                        all_data.append(item)
                        new_count += 1
                if new_count == 0:
                    break  # All duplicates — no more unique markets
            except Exception as e:
                logger.error("Failed to fetch markets page", page=page_num, error=str(e))
                break

        markets = []
        for item in all_data:
            try:
                markets.append(self._parse_market(item))
            except Exception as e:
                logger.warning("Failed to parse market", error=str(e))

        # Enrich with orderbook prices
        markets = await self._enrich_markets_with_orderbook_prices(markets)

        # Update cache
        self._markets_cache = markets
        self._markets_cache_time = now

        return markets[offset:offset + limit]

    async def search_markets(
        self,
        query: str,
        limit: int = 50,
    ) -> list[Market]:
        """Search markets by query."""
        # Opinion API uses keyword parameter for search
        params = {
            "keyword": query,
            "limit": min(limit, 100),
            "status": "activated",
        }

        try:
            data = await self._api_request("GET", "/openapi/market", params=params)

            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data

            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            # Enrich with orderbook prices
            markets = await self._enrich_markets_with_orderbook_prices(markets)

            return markets

        except Exception as e:
            # Fallback: use cached markets and filter client-side
            logger.warning("Search failed, falling back to filter", error=str(e))
            all_markets = await self.get_markets(limit=600)
            query_lower = query.lower()
            return [
                m for m in all_markets
                if query_lower in m.title.lower() or
                   (m.description and query_lower in m.description.lower())
            ][:limit]

    async def get_market(self, market_id: str, search_title: Optional[str] = None, include_closed: bool = False) -> Optional[Market]:
        """Get a specific market by ID.

        Note: search_title and include_closed are accepted for API compatibility but not used.
        """
        try:
            # Opinion uses /openapi/market/{market_id} or /openapi/market?marketId=X
            data = await self._api_request("GET", f"/openapi/market/{market_id}")

            market_data = data.get("result", {}).get("data", data)
            market = None
            if isinstance(market_data, dict) and market_data:
                market = self._parse_market(market_data)
            else:
                # Fallback: try with query param
                data = await self._api_request("GET", "/openapi/market", params={"marketId": market_id})
                market_data = data.get("result", {}).get("list", [])
                if market_data:
                    market = self._parse_market(market_data[0])

            # Enrich with orderbook prices (API often omits prices, defaulting to 0.5)
            if market:
                enriched = await self._enrich_markets_with_orderbook_prices([market])
                market = enriched[0] if enriched else market

            return market

        except PlatformError:
            return None

    async def get_trending_markets(self, limit: int = 50) -> list[Market]:
        """Get trending markets by volume."""
        # sortBy: 5 = 24h volume descending
        params = {
            "limit": min(limit, 100),
            "sortBy": 5,
            "status": "activated",
        }

        try:
            data = await self._api_request("GET", "/openapi/market", params=params)

            markets_data = data.get("result", {}).get("list", [])
            if not markets_data and isinstance(data, list):
                markets_data = data

            markets = []
            for item in markets_data:
                try:
                    markets.append(self._parse_market(item))
                except Exception as e:
                    logger.warning("Failed to parse market", error=str(e))

            # Enrich with orderbook prices
            markets = await self._enrich_markets_with_orderbook_prices(markets)

            return markets

        except Exception as e:
            logger.error("Failed to get trending markets", error=str(e))
            return []

    # ===================
    # Categories
    # ===================

    # Keywords to match in market titles for each category
    CATEGORY_KEYWORDS = {
        "crypto": [
            "bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
            "binance", "token", "defi", "nft", "blockchain", "altcoin",
        ],
        "politics": [
            "trump", "biden", "election", "president", "congress", "senate",
            "governor", "democrat", "republican", "vote", "political", "government",
        ],
        "sports": [
            "nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball",
            "baseball", "championship", "super bowl", "playoffs", "world cup",
        ],
        "economics": [
            "fed", "interest rate", "inflation", "gdp", "recession", "tariff",
            "economy", "stock", "market", "s&p", "nasdaq", "dow",
        ],
        "world": [
            "war", "ukraine", "russia", "china", "israel", "iran", "military",
            "conflict", "peace", "nato", "un", "sanctions",
        ],
        "entertainment": [
            "movie", "oscar", "grammy", "album", "netflix", "spotify",
            "celebrity", "music", "film", "tv", "streaming",
        ],
    }

    def get_available_categories(self) -> list[dict]:
        """Get list of available market categories.

        Returns list of dicts with 'id', 'label', and 'emoji' keys.
        """
        return [
            {"id": "hourly", "label": "Hourly", "emoji": "⏰"},
            {"id": "crypto", "label": "Crypto", "emoji": "🪙"},
            {"id": "politics", "label": "Politics", "emoji": "🏛️"},
            {"id": "sports", "label": "Sports", "emoji": "🏆"},
            {"id": "economics", "label": "Economics", "emoji": "📊"},
            {"id": "world", "label": "World", "emoji": "🌍"},
            {"id": "entertainment", "label": "Entertainment", "emoji": "🎬"},
        ]

    async def get_markets_by_category(
        self,
        category: str,
        limit: int = 50,
    ) -> list[Market]:
        """Get markets filtered by category.

        Categories are inferred from market title keywords since Opinion API
        doesn't have a categories field. "Hourly" is a special category that
        filters by markets ending within the next 2 hours (short-duration).
        """
        # Hourly: filter by cutoffAt to find short-duration markets
        if category.lower() == "hourly":
            try:
                # Fetch markets sorted by ending soon
                params = {
                    "limit": 200,
                    "sortBy": 2,  # EndingSoon
                    "status": "activated",
                }
                data = await self._api_request("GET", "/openapi/market", params=params)
                markets_data = data.get("result", {}).get("list", [])
                if not markets_data and isinstance(data, list):
                    markets_data = data

                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)

                markets = []
                for item in markets_data:
                    try:
                        cutoff = item.get("cutoffAt")
                        if not cutoff:
                            continue
                        # cutoffAt is Unix timestamp
                        end_time = datetime.fromtimestamp(cutoff, tz=timezone.utc)
                        hours_remaining = (end_time - now).total_seconds() / 3600
                        # Include markets ending within next 2 hours
                        if 0 < hours_remaining <= 2:
                            markets.append(self._parse_market(item))
                    except Exception as e:
                        logger.debug(f"Skipping market in hourly filter: {e}")

                markets = await self._enrich_markets_with_orderbook_prices(markets)
                return markets[:limit]

            except Exception as e:
                logger.error("Failed to get hourly markets", error=str(e))
                return []

        # Get all active markets for filtering
        all_markets = await self.get_markets(limit=600, offset=0, active_only=True)

        # Get keywords for this category
        keywords = self.CATEGORY_KEYWORDS.get(category.lower(), [])
        if not keywords:
            return []

        # Filter markets by title keywords
        filtered = []
        for market in all_markets:
            title_lower = market.title.lower()
            if any(keyword in title_lower for keyword in keywords):
                filtered.append(market)

        return filtered[:limit]

    # ===================
    # Order Book
    # ===================
    
    async def get_orderbook(
        self,
        market_id: str,
        outcome: Outcome,
        slug: str = None,  # Accepted for API compatibility, not used
    ) -> OrderBook:
        """Get order book from Opinion SDK or API."""
        market = await self.get_market(market_id)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.OPINION)

        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.OPINION)

        try:
            bids = []
            asks = []

            # Try SDK method first (preferred)
            if self._readonly_sdk_client:
                logger.info("Fetching Opinion orderbook via SDK", token_id=token_id[:20] + "...", market_id=market_id, outcome=outcome.value)
                # Run synchronous SDK call in thread pool to avoid blocking
                result = await asyncio.to_thread(
                    self._readonly_sdk_client.get_orderbook,
                    token_id=token_id,
                )

                if result.errno == 0 and result.result:
                    # Handle different response structures - try result.result directly first
                    orderbook_data = result.result
                    # If result.result has a data attribute, use that instead
                    if hasattr(orderbook_data, 'data') and orderbook_data.data:
                        orderbook_data = orderbook_data.data

                    # Get bids and asks from the response
                    raw_bids = getattr(orderbook_data, 'bids', None) or []
                    raw_asks = getattr(orderbook_data, 'asks', None) or []

                    logger.info(
                        "Opinion SDK orderbook response",
                        response_type=type(orderbook_data).__name__,
                        has_bids=len(raw_bids),
                        has_asks=len(raw_asks),
                    )

                    for bid in raw_bids:
                        if isinstance(bid, dict):
                            price = bid.get('price', 0)
                            size = bid.get('size') or bid.get('quantity', 0)
                        else:
                            price = getattr(bid, 'price', 0)
                            size = getattr(bid, 'size', None) or getattr(bid, 'quantity', 0)
                        bids.append((Decimal(str(price)), Decimal(str(size or 0))))

                    for ask in raw_asks:
                        if isinstance(ask, dict):
                            price = ask.get('price', 0)
                            size = ask.get('size') or ask.get('quantity', 0)
                        else:
                            price = getattr(ask, 'price', 0)
                            size = getattr(ask, 'size', None) or getattr(ask, 'quantity', 0)
                        asks.append((Decimal(str(price)), Decimal(str(size or 0))))
                else:
                    logger.warning(
                        "Opinion SDK orderbook returned error",
                        errno=result.errno,
                        errmsg=getattr(result, 'errmsg', 'unknown'),
                    )
                    raise PlatformError(f"SDK error: {getattr(result, 'errmsg', 'unknown')}", Platform.OPINION)
            else:
                # Fallback to REST API
                logger.info("Fetching Opinion orderbook via REST API", token_id=token_id[:20] + "...", market_id=market_id)
                data = await self._api_request("GET", f"/openapi/orderbook/{token_id}")

                orderbook_data = data.get("result", data)
                logger.info("Opinion REST orderbook response", has_bids=len(orderbook_data.get("bids", [])), has_asks=len(orderbook_data.get("asks", [])))

                for bid in orderbook_data.get("bids", []):
                    bids.append((
                        Decimal(str(bid.get("price", 0))),
                        Decimal(str(bid.get("size") or bid.get("quantity", 0))),
                    ))

                for ask in orderbook_data.get("asks", []):
                    asks.append((
                        Decimal(str(ask.get("price", 0))),
                        Decimal(str(ask.get("size") or ask.get("quantity", 0))),
                    ))

            # Sort bids descending (highest first) - best_bid = highest price buyers will pay
            bids.sort(key=lambda x: x[0], reverse=True)
            # Sort asks ascending (lowest first) - best_ask = lowest price sellers will accept
            asks.sort(key=lambda x: x[0])

            logger.info(
                "Opinion orderbook parsed",
                market_id=market_id,
                outcome=outcome.value,
                num_bids=len(bids),
                num_asks=len(asks),
                best_bid=str(bids[0][0]) if bids else "none",
                best_ask=str(asks[0][0]) if asks else "none",
            )

            return OrderBook(
                market_id=market_id,
                outcome=outcome,
                bids=bids,
                asks=asks,
            )

        except Exception as e:
            logger.warning("Failed to get Opinion orderbook, using market prices", error=str(e), market_id=market_id)
            # Return empty orderbook with market prices
            fallback_price = market.yes_price if outcome == Outcome.YES else market.no_price
            return OrderBook(
                market_id=market_id,
                outcome=outcome,
                bids=[(fallback_price, Decimal(100))] if fallback_price else [],
                asks=[(fallback_price, Decimal(100))] if fallback_price else [],
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
        """Get a quote for a trade.

        Note: token_id is accepted for API compatibility but ignored -
        Opinion determines tokens from market data.
        """
        # include_closed so sells work on near-expiry markets
        market = await self.get_market(market_id, include_closed=True)
        if not market:
            raise MarketNotFoundError(f"Market {market_id} not found", Platform.OPINION)

        token_id = market.yes_token if outcome == Outcome.YES else market.no_token
        if not token_id:
            raise PlatformError(f"Token not found for {outcome.value}", Platform.OPINION)

        # Get current price from orderbook
        orderbook = await self.get_orderbook(market_id, outcome)

        # Update market prices from orderbook so displayed price matches
        # execution price (avoids misleading "differs from mid-price" warning
        # when _parse_market defaulted to 0.5)
        if orderbook.best_ask and outcome == Outcome.YES:
            market.yes_price = orderbook.best_ask
            market.no_price = Decimal("1") - orderbook.best_ask
        elif orderbook.best_ask and outcome == Outcome.NO:
            market.no_price = orderbook.best_ask
            market.yes_price = Decimal("1") - orderbook.best_ask

        # USDT on BSC
        usdt_address = "0x55d398326f99059fF775485246999027B3197955"

        if side == "buy":
            price = orderbook.best_ask or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount / price
            input_token = usdt_address
            output_token = token_id
            logger.info(
                "Opinion quote (buy)",
                market_id=market_id,
                outcome=outcome.value,
                orderbook_best_ask=str(orderbook.best_ask) if orderbook.best_ask else "none",
                market_price=str(market.yes_price if outcome == Outcome.YES else market.no_price),
                final_price=str(price),
            )
        else:
            price = orderbook.best_bid or (market.yes_price if outcome == Outcome.YES else market.no_price) or Decimal("0.5")
            expected_output = amount * price
            input_token = token_id
            output_token = usdt_address
            logger.info(
                "Opinion quote (sell)",
                market_id=market_id,
                outcome=outcome.value,
                orderbook_best_bid=str(orderbook.best_bid) if orderbook.best_bid else "none",
                market_price=str(market.yes_price if outcome == Outcome.YES else market.no_price),
                final_price=str(price),
            )
        
        return Quote(
            platform=Platform.OPINION,
            chain=Chain.BSC,
            market_id=market_id,
            outcome=outcome,
            side=side,
            input_token=input_token,
            input_amount=amount,
            output_token=output_token,
            expected_output=expected_output,
            price_per_token=price,
            price_impact=Decimal("0.01"),
            platform_fee=amount * Decimal("0.01"),  # 1% estimate
            network_fee_estimate=Decimal("0.001"),  # BNB
            expires_at=None,
            quote_data={
                "token_id": token_id,
                "market_id": market_id,
                "price": str(price),
                "market": market.raw_data,
            },
        )
    
    async def execute_trade(
        self,
        quote: Quote,
        private_key: Any,
        order_type: str = "market",  # "market" or "limit"
        limit_price: Optional[Decimal] = None,
    ) -> TradeResult:
        """
        Execute a trade on Opinion Labs.
        Uses the opinion-clob-sdk for order execution.

        Args:
            quote: Quote object with trade details
            private_key: EVM LocalAccount with private key
            order_type: "market" for market order, "limit" for limit order
            limit_price: Price for limit orders (required if order_type="limit")
        """
        # Handle EVMSigner types
        if isinstance(private_key, EVMSigner):
            if isinstance(private_key, LegacyEVMSigner):
                private_key = private_key.local_account
            else:
                return TradeResult(
                    success=False,
                    tx_hash=None,
                    input_amount=quote.input_amount,
                    output_amount=None,
                    error_message="Unsupported EVM signer type for Opinion.",
                    explorer_url=None,
                )

        if not isinstance(private_key, LocalAccount):
            raise PlatformError(
                "Invalid private key type, expected EVM LocalAccount or EVMSigner",
                Platform.OPINION,
            )

        if not quote.quote_data:
            raise PlatformError("Quote data missing", Platform.OPINION)

        try:
            # Import Opinion SDK
            from opinion_clob_sdk import Client
            from opinion_clob_sdk.chain.py_order_utils.model.order import PlaceOrderDataInput
            from opinion_clob_sdk.chain.py_order_utils.model.sides import OrderSide
            from opinion_clob_sdk.chain.py_order_utils.model.order_type import MARKET_ORDER, LIMIT_ORDER

            wallet_address = private_key.address.lower()

            # Enable trading (token approvals) using direct web3 transactions
            # This is required because the SDK's enable_trading() uses Gnosis Safe,
            # which doesn't work for regular EOA wallets created by the bot.
            await self._enable_trading_eoa(private_key)

            # Use cached SDK client or create new one
            if wallet_address in self._sdk_client_cache:
                client = self._sdk_client_cache[wallet_address]
                logger.debug("Using cached Opinion SDK client", wallet=wallet_address[:10])
            else:
                # Initialize SDK client
                # Use the user's wallet address as multi_sig_addr (SDK requirement)
                # Private key needs "0x" prefix for the SDK
                pk_hex = private_key.key.hex()
                if not pk_hex.startswith("0x"):
                    pk_hex = "0x" + pk_hex
                client = Client(
                    host=settings.opinion_api_url,
                    apikey=(settings.opinion_api_key or "").strip(),
                    chain_id=56,  # BNB Chain mainnet
                    rpc_url=settings.bsc_rpc_url,
                    private_key=pk_hex,
                    multi_sig_addr=private_key.address,
                )
                self._sdk_client_cache[wallet_address] = client
                logger.debug("Created new Opinion SDK client", wallet=wallet_address[:10])

            token_id = quote.quote_data["token_id"]
            market_id = int(quote.quote_data["market_id"])

            # Create order
            order_side = OrderSide.BUY if quote.side == "buy" else OrderSide.SELL
            sdk_order_type = LIMIT_ORDER if order_type == "limit" else MARKET_ORDER

            # Price: use limit_price for limit orders, "0" for market orders
            price = str(limit_price) if order_type == "limit" and limit_price else "0"

            # Amount should be passed as string per SDK docs
            amount_str = str(quote.input_amount)
            order = PlaceOrderDataInput(
                marketId=market_id,
                tokenId=token_id,
                side=order_side,
                orderType=sdk_order_type,
                price=price,
                makerAmountInQuoteToken=amount_str if quote.side == "buy" else None,
                makerAmountInBaseToken=amount_str if quote.side == "sell" else None,
            )

            logger.info(
                "Placing Opinion order",
                market_id=market_id,
                token_id=token_id,
                side=quote.side,
                order_type=order_type,
                amount=amount_str,
            )

            # check_approval=False because we already did manual approvals via _enable_trading_eoa()
            # The SDK's check_approval uses Gnosis Safe which doesn't work for EOA wallets
            result = client.place_order(order, check_approval=False)

            if result.errno != 0:
                raise PlatformError(
                    f"Order failed: {result.errmsg}",
                    Platform.OPINION,
                )

            order_id = result.result.data.order_id if result.result and result.result.data else None
            tx_hash = str(order_id) if order_id else None

            logger.info(
                "Trade executed",
                platform="opinion",
                market_id=quote.market_id,
                order_id=order_id,
            )

            return TradeResult(
                success=True,
                tx_hash=tx_hash,
                input_amount=quote.input_amount,
                output_amount=quote.expected_output,
                error_message=None,
                explorer_url=self.get_explorer_url(tx_hash) if tx_hash and tx_hash.startswith("0x") else None,
            )

        except ImportError:
            logger.error("opinion-clob-sdk not installed")
            return TradeResult(
                success=False,
                tx_hash=None,
                input_amount=quote.input_amount,
                output_amount=None,
                error_message="Opinion SDK not installed. Install with: pip install opinion-clob-sdk",
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
        """Check if market has resolved.

        Opinion uses statusEnum field for resolution:
        - "settled" or "resolved" = market has resolved
        - "expired" = deadline passed
        - The winning outcome can be in 'resolution' or 'winningOutcome' fields
        """
        try:
            market = await self.get_market(market_id, include_closed=True)
            if not market or not market.raw_data:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            raw = market.raw_data

            # Check status for resolution indicators
            status_enum = str(raw.get("statusEnum", "")).lower()
            status_num = raw.get("status")

            # Market is resolved if status indicates settled/resolved/expired
            resolved = status_enum in ("settled", "resolved", "expired") or status_num in (3, 4, 5)

            if not resolved:
                return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)

            # Determine winning outcome
            winning = None

            # Check various fields for winning outcome
            resolution = (
                raw.get("resolution") or
                raw.get("winningOutcome") or
                raw.get("winning_outcome") or
                raw.get("outcome")
            )

            if resolution is not None:
                resolution_str = str(resolution).lower()
                if resolution_str in ["yes", "0", "true", "y"]:
                    winning = "yes"
                elif resolution_str in ["no", "1", "false", "n"]:
                    winning = "no"

            # Also check winning_index if available
            winning_index = raw.get("winning_index") or raw.get("winningIndex")
            if winning_index is not None and winning is None:
                winning = "yes" if winning_index == 0 else "no"

            return MarketResolution(
                is_resolved=True,
                winning_outcome=winning,
                resolution_time=raw.get("resolvedAt") or raw.get("settledAt"),
            )
        except Exception as e:
            logger.warning("Failed to check market resolution", market_id=market_id, error=str(e))
            return MarketResolution(is_resolved=False, winning_outcome=None, resolution_time=None)


# Singleton instance
opinion_platform = OpinionPlatform()
