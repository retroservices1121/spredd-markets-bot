"""
Cross-chain bridge service using Circle CCTP.
Enables USDC transfers between supported chains (Base, Polygon, Solana, etc.)
"""

import asyncio
import time
from decimal import Decimal
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from eth_account.signers.local import LocalAccount
from web3 import Web3

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class BridgeChain(Enum):
    """Supported chains for bridging."""
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    BASE = "base"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    AVALANCHE = "avalanche"
    MONAD = "monad"
    BSC = "bsc"  # Binance Smart Chain (for Opinion Labs)
    SOLANA = "solana"  # Supported via LI.FI only
    ABSTRACT = "abstract"  # Supported via LI.FI (for Myriad)
    LINEA = "linea"  # Supported via LI.FI (for Myriad)


# Chain configurations for CCTP
CHAIN_CONFIG = {
    BridgeChain.ETHEREUM: {
        "chain_id": 1,
        "domain": 0,  # CCTP domain
        "usdc": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "token_messenger": "0xBd3fa81B58Ba92a82136038B25aDec7066af3155",
        "message_transmitter": "0x0a992d191DEeC32aFe36203Ad87D7d289a738F81",
        "rpc_env": "ETHEREUM_RPC_URL",
    },
    BridgeChain.POLYGON: {
        "chain_id": 137,
        "domain": 7,  # CCTP domain for Polygon
        "usdc": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # Native USDC on Polygon
        "token_messenger": "0x9daF8c91AEFAE50b9c0E69629D3F6Ca40cA3B3FE",
        "message_transmitter": "0xF3be9355363857F3e001be68856A2f96b4C39Ba9",
        "rpc_env": "POLYGON_RPC_URL",
    },
    BridgeChain.BASE: {
        "chain_id": 8453,
        "domain": 6,  # CCTP domain for Base
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "token_messenger": "0x1682Ae6375C4E4A97e4B583BC394c861A46D8962",
        "message_transmitter": "0xAD09780d193884d503182aD4588450C416D6F9D4",
        "rpc_env": "BASE_RPC_URL",
    },
    BridgeChain.ARBITRUM: {
        "chain_id": 42161,
        "domain": 3,  # CCTP domain for Arbitrum
        "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "token_messenger": "0x19330d10D9Cc8751218eaf51E8885D058642E08A",
        "message_transmitter": "0xC30362313FBBA5cf9163F0bb16a0e01f01A896ca",
        "rpc_env": "ARBITRUM_RPC_URL",
    },
    BridgeChain.OPTIMISM: {
        "chain_id": 10,
        "domain": 2,  # CCTP domain for Optimism
        "usdc": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
        "token_messenger": "0x2B4069517957735bE00ceE0fadAE88a26365528f",
        "message_transmitter": "0x4D41f22c5a0e5c74090899E5a8Fb597a8842b3e8",
        "rpc_env": "OPTIMISM_RPC_URL",
    },
    BridgeChain.AVALANCHE: {
        "chain_id": 43114,
        "domain": 1,  # CCTP domain for Avalanche
        "usdc": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "token_messenger": "0x6B25532e1060CE10cc3B0A99e5683b91BFDe6982",
        "message_transmitter": "0x8186359aF5F57FbB40c6b14A588d2A59C0C29880",
        "rpc_env": "AVALANCHE_RPC_URL",
    },
    BridgeChain.MONAD: {
        "chain_id": 143,
        "domain": 15,  # CCTP domain for Monad
        "usdc": "0x754704Bc059F8C67012fEd69BC8A327a5aafb603",  # Native USDC on Monad
        "token_messenger": "0x28b5a0e9C621a5BadaA536219b3a228C8168cf5d",  # TokenMessengerV2
        "message_transmitter": "0x81D40F21F12A8F0E3252Bccb954D722d4c464B64",  # MessageTransmitterV2
        "rpc_env": "MONAD_RPC_URL",
    },
    BridgeChain.BSC: {
        "chain_id": 56,
        "domain": None,  # BSC doesn't support CCTP - use LI.FI
        "usdc": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",  # USDC on BSC
        "usdt": "0x55d398326f99059fF775485246999027B3197955",  # USDT on BSC (for Opinion)
        "token_messenger": None,  # No CCTP
        "message_transmitter": None,  # No CCTP
        "rpc_env": "BSC_RPC_URL",
    },
    BridgeChain.ABSTRACT: {
        "chain_id": 2741,
        "domain": None,  # Abstract doesn't support CCTP - use LI.FI
        "usdc": "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",  # USDC.e on Abstract
        "token_messenger": None,  # No CCTP
        "message_transmitter": None,  # No CCTP
        "rpc_env": "ABSTRACT_RPC_URL",
    },
    BridgeChain.LINEA: {
        "chain_id": 59144,
        "domain": None,  # Linea CCTP coming soon - use LI.FI for now
        "usdc": "0x176211869cA2b568f2A7D4EE941E073a821EE1ff",  # USDC on Linea
        "token_messenger": None,  # No CCTP yet
        "message_transmitter": None,  # No CCTP yet
        "rpc_env": "LINEA_RPC_URL",
    },
}


# ERC20 ABI for USDC operations
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
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

# TokenMessenger ABI for CCTP
TOKEN_MESSENGER_ABI = [
    {
        "inputs": [
            {"name": "amount", "type": "uint256"},
            {"name": "destinationDomain", "type": "uint32"},
            {"name": "mintRecipient", "type": "bytes32"},
            {"name": "burnToken", "type": "address"}
        ],
        "name": "depositForBurn",
        "outputs": [{"name": "nonce", "type": "uint64"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# MessageTransmitter ABI for receiving
MESSAGE_TRANSMITTER_ABI = [
    {
        "inputs": [
            {"name": "message", "type": "bytes"},
            {"name": "attestation", "type": "bytes"}
        ],
        "name": "receiveMessage",
        "outputs": [{"name": "success", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


@dataclass
class BridgeResult:
    """Result of a bridge operation."""
    success: bool
    source_chain: BridgeChain
    dest_chain: BridgeChain
    amount: Decimal
    burn_tx_hash: Optional[str] = None
    mint_tx_hash: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class FastBridgeQuote:
    """Quote for fast bridge via Relay.link."""
    input_amount: Decimal  # Amount user sends
    output_amount: Decimal  # Amount user receives
    fee_amount: Decimal  # Total fee
    fee_percent: float  # Fee as percentage
    gas_fee: Decimal  # Gas portion of fee
    relay_fee: Decimal  # Relayer fee
    estimated_time_seconds: int  # ~20-60 seconds
    quote_id: Optional[str] = None  # For executing the quote
    error: Optional[str] = None


@dataclass
class LiFiBridgeQuote:
    """Quote for LI.FI bridge (supports Solana)."""
    input_amount: Decimal
    output_amount: Decimal
    fee_amount: Decimal
    fee_percent: float
    estimated_time_seconds: int
    tool_name: str  # Bridge being used (e.g., "allbridge", "meson")
    quote_data: Optional[dict] = None  # Full quote for execution
    error: Optional[str] = None


# Chain ID mapping for Relay
RELAY_CHAIN_IDS = {
    BridgeChain.ETHEREUM: 1,
    BridgeChain.POLYGON: 137,
    BridgeChain.BASE: 8453,
    BridgeChain.ARBITRUM: 42161,
    BridgeChain.OPTIMISM: 10,
    BridgeChain.MONAD: 143,
}

# USDC addresses for Relay
RELAY_USDC = {
    BridgeChain.ETHEREUM: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    BridgeChain.POLYGON: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    BridgeChain.BASE: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    BridgeChain.ARBITRUM: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    BridgeChain.OPTIMISM: "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
    BridgeChain.MONAD: "0x754704Bc059F8C67012fEd69BC8A327a5aafb603",
}


# LI.FI Configuration for cross-chain bridging
# LI.FI uses chain names/IDs differently
LIFI_CHAIN_IDS = {
    BridgeChain.ETHEREUM: 1,
    BridgeChain.POLYGON: 137,
    BridgeChain.BASE: 8453,
    BridgeChain.ARBITRUM: 42161,
    BridgeChain.OPTIMISM: 10,
    BridgeChain.AVALANCHE: 43114,
    BridgeChain.BSC: 56,  # Binance Smart Chain
    BridgeChain.SOLANA: 1151111081099710,  # LI.FI's Solana chain ID
    BridgeChain.ABSTRACT: 2741,  # Abstract (for Myriad)
    BridgeChain.LINEA: 59144,  # Linea (for Myriad)
}

# USDC/stablecoin addresses for LI.FI
LIFI_USDC = {
    BridgeChain.ETHEREUM: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    BridgeChain.POLYGON: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    BridgeChain.BASE: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    BridgeChain.ARBITRUM: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    BridgeChain.OPTIMISM: "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
    BridgeChain.AVALANCHE: "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
    BridgeChain.BSC: "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",  # USDC on BSC
    BridgeChain.SOLANA: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # Native USDC on Solana
    BridgeChain.ABSTRACT: "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",  # USDC.e on Abstract
    BridgeChain.LINEA: "0x176211869cA2b568f2A7D4EE941E073a821EE1ff",  # USDC on Linea
}

# USDT address for BSC (Opinion Labs uses USDT)
LIFI_USDT_BSC = "0x55d398326f99059fF775485246999027B3197955"

# Native token address (used for swaps)
NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# Valid bridge routes - (source, dest) pairs that work with LI.FI
# Based on actual LI.FI support - Abstract is only reachable from certain chains
VALID_BRIDGE_ROUTES: set[tuple[BridgeChain, BridgeChain]] = {
    # Standard CCTP/LI.FI routes
    (BridgeChain.POLYGON, BridgeChain.BASE),
    (BridgeChain.POLYGON, BridgeChain.ARBITRUM),
    (BridgeChain.POLYGON, BridgeChain.OPTIMISM),
    (BridgeChain.POLYGON, BridgeChain.ETHEREUM),
    (BridgeChain.POLYGON, BridgeChain.SOLANA),
    (BridgeChain.BASE, BridgeChain.POLYGON),
    (BridgeChain.BASE, BridgeChain.ARBITRUM),
    (BridgeChain.BASE, BridgeChain.OPTIMISM),
    (BridgeChain.BASE, BridgeChain.ETHEREUM),
    (BridgeChain.BASE, BridgeChain.SOLANA),
    (BridgeChain.BASE, BridgeChain.ABSTRACT),  # Base → Abstract works via LI.FI
    (BridgeChain.ABSTRACT, BridgeChain.POLYGON),  # Abstract → Polygon via LI.FI
    (BridgeChain.ABSTRACT, BridgeChain.BASE),  # Abstract → Base via LI.FI
    (BridgeChain.ARBITRUM, BridgeChain.POLYGON),
    (BridgeChain.ARBITRUM, BridgeChain.BASE),
    (BridgeChain.ARBITRUM, BridgeChain.OPTIMISM),
    (BridgeChain.ARBITRUM, BridgeChain.ETHEREUM),
    (BridgeChain.ETHEREUM, BridgeChain.POLYGON),
    (BridgeChain.ETHEREUM, BridgeChain.BASE),
    (BridgeChain.ETHEREUM, BridgeChain.ARBITRUM),
    (BridgeChain.ETHEREUM, BridgeChain.OPTIMISM),
    (BridgeChain.ETHEREUM, BridgeChain.ABSTRACT),  # ETH → Abstract
    # BSC routes (USDT)
    (BridgeChain.BSC, BridgeChain.POLYGON),
    (BridgeChain.BSC, BridgeChain.BASE),
    (BridgeChain.POLYGON, BridgeChain.BSC),
    (BridgeChain.BASE, BridgeChain.BSC),
}

# Chains that support swapping native token to USDC
SWAP_SUPPORTED_CHAINS = {
    BridgeChain.POLYGON,  # POL → USDC
    BridgeChain.BASE,     # ETH → USDC
    BridgeChain.ARBITRUM, # ETH → USDC
    BridgeChain.BSC,      # BNB → USDC/USDT
    BridgeChain.ABSTRACT, # ETH → USDC.e (for Myriad trading)
    BridgeChain.LINEA,    # ETH → USDC
}

# Native token symbols per chain
NATIVE_TOKEN_SYMBOLS = {
    BridgeChain.POLYGON: "POL",
    BridgeChain.BASE: "ETH",
    BridgeChain.ARBITRUM: "ETH",
    BridgeChain.BSC: "BNB",
    BridgeChain.ETHEREUM: "ETH",
    BridgeChain.OPTIMISM: "ETH",
    BridgeChain.ABSTRACT: "ETH",
    BridgeChain.LINEA: "ETH",
    BridgeChain.MONAD: "MON",
}

# Valid routes for native token (gas) bridging via LI.FI
# Format: (source_chain, dest_chain) - bridges native token (ETH/POL/BNB)
VALID_NATIVE_BRIDGE_ROUTES: set[tuple[BridgeChain, BridgeChain]] = {
    # ETH bridges to Abstract (for Myriad gas)
    (BridgeChain.ETHEREUM, BridgeChain.ABSTRACT),
    (BridgeChain.BASE, BridgeChain.ABSTRACT),
    (BridgeChain.ARBITRUM, BridgeChain.ABSTRACT),
    (BridgeChain.OPTIMISM, BridgeChain.ABSTRACT),
    # ETH bridges to Linea
    (BridgeChain.ETHEREUM, BridgeChain.LINEA),
    (BridgeChain.BASE, BridgeChain.LINEA),
    (BridgeChain.ARBITRUM, BridgeChain.LINEA),
    # ETH bridges between L2s
    (BridgeChain.BASE, BridgeChain.ARBITRUM),
    (BridgeChain.ARBITRUM, BridgeChain.BASE),
    (BridgeChain.BASE, BridgeChain.OPTIMISM),
    (BridgeChain.OPTIMISM, BridgeChain.BASE),
    # Polygon POL bridges (limited - mostly stays on Polygon)
    (BridgeChain.POLYGON, BridgeChain.ETHEREUM),  # POL → ETH on Ethereum
    # ETH to Polygon (arrives as WETH, not POL)
    (BridgeChain.ETHEREUM, BridgeChain.POLYGON),
    (BridgeChain.BASE, BridgeChain.POLYGON),
}


# Type alias for progress callback
# Callback receives (status_message: str, elapsed_seconds: int, estimated_total_seconds: int)
ProgressCallback = Optional[callable]


class BridgeService:
    """
    Service for bridging USDC between chains using Circle CCTP.
    """

    def __init__(self):
        self._web3_clients: dict[BridgeChain, Web3] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Initialize Web3 clients for supported chains."""
        for chain, config in CHAIN_CONFIG.items():
            rpc_url = getattr(settings, config["rpc_env"].lower(), None)
            if rpc_url:
                try:
                    self._web3_clients[chain] = Web3(Web3.HTTPProvider(rpc_url))
                    logger.debug(f"Initialized Web3 for {chain.value}")
                except Exception as e:
                    logger.warning(f"Failed to initialize {chain.value}", error=str(e))

        self._initialized = True
        logger.info(
            "Bridge service initialized",
            supported_chains=[c.value for c in self._web3_clients.keys()]
        )

    def get_supported_chains(self) -> list[BridgeChain]:
        """Get list of chains with configured RPC."""
        return list(self._web3_clients.keys())

    def get_usdc_balance(self, chain: BridgeChain, wallet_address: str) -> Decimal:
        """Get USDC balance on a specific chain."""
        if chain not in self._web3_clients:
            return Decimal(0)

        try:
            w3 = self._web3_clients[chain]
            config = CHAIN_CONFIG[chain]

            usdc_contract = w3.eth.contract(
                address=Web3.to_checksum_address(config["usdc"]),
                abi=ERC20_ABI
            )

            balance_raw = usdc_contract.functions.balanceOf(
                Web3.to_checksum_address(wallet_address)
            ).call()

            # BSC USDC has 18 decimals, others have 6
            decimals = 18 if chain == BridgeChain.BSC else 6
            return Decimal(balance_raw) / Decimal(10 ** decimals)

        except Exception as e:
            logger.warning(f"Failed to get balance on {chain.value}", error=str(e))
            return Decimal(0)

    def get_native_balance(self, chain: BridgeChain, wallet_address: str) -> Decimal:
        """Get native token balance (ETH/BNB/MATIC) on a specific chain."""
        if chain not in self._web3_clients:
            return Decimal(0)

        try:
            w3 = self._web3_clients[chain]
            balance_raw = w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
            return Decimal(balance_raw) / Decimal(10**18)
        except Exception as e:
            logger.warning(f"Failed to get native balance on {chain.value}", error=str(e))
            return Decimal(0)

    def get_all_usdc_balances(self, wallet_address: str) -> dict[BridgeChain, Decimal]:
        """Get USDC balances across all supported chains in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        balances = {}
        chains = list(self._web3_clients.keys())

        # Fetch all balances in parallel for speed
        with ThreadPoolExecutor(max_workers=len(chains)) as executor:
            future_to_chain = {
                executor.submit(self.get_usdc_balance, chain, wallet_address): chain
                for chain in chains
            }
            for future in as_completed(future_to_chain):
                chain = future_to_chain[future]
                try:
                    balances[chain] = future.result()
                except Exception:
                    balances[chain] = Decimal(0)

        return balances

    def get_bsc_usdt_balance(self, wallet_address: str) -> Decimal:
        """Get USDT balance on BSC (for Opinion Labs)."""
        if BridgeChain.BSC not in self._web3_clients:
            return Decimal(0)

        try:
            w3 = self._web3_clients[BridgeChain.BSC]
            config = CHAIN_CONFIG[BridgeChain.BSC]

            usdt_contract = w3.eth.contract(
                address=Web3.to_checksum_address(config["usdt"]),
                abi=ERC20_ABI
            )

            balance_raw = usdt_contract.functions.balanceOf(
                Web3.to_checksum_address(wallet_address)
            ).call()

            # USDT on BSC has 18 decimals
            return Decimal(balance_raw) / Decimal(10 ** 18)

        except Exception as e:
            logger.warning("Failed to get BSC USDT balance", error=str(e))
            return Decimal(0)

    def swap_bsc_usdc_to_usdt(
        self,
        private_key: LocalAccount,
        amount: Decimal,
        progress_callback: ProgressCallback = None,
    ) -> "BridgeResult":
        """
        Swap USDC to USDT on BSC using LI.FI.
        This is a same-chain swap for Opinion Labs trading.
        """
        import httpx

        if BridgeChain.BSC not in self._web3_clients:
            return BridgeResult(
                success=False,
                source_chain=BridgeChain.BSC,
                dest_chain=BridgeChain.BSC,
                amount=amount,
                error_message="BSC not configured"
            )

        try:
            source_w3 = self._web3_clients[BridgeChain.BSC]
            wallet = Web3.to_checksum_address(private_key.address)

            # Check native BNB balance for gas
            native_balance = source_w3.eth.get_balance(wallet)
            min_gas_wei = int(0.001 * 10**18)  # 0.001 BNB for swap
            if native_balance < min_gas_wei:
                return BridgeResult(
                    success=False,
                    source_chain=BridgeChain.BSC,
                    dest_chain=BridgeChain.BSC,
                    amount=amount,
                    error_message="Insufficient BNB for gas. Need at least 0.001 BNB."
                )

            if progress_callback:
                progress_callback("💱 Getting swap quote...", 0, 60)

            # USDC on BSC has 18 decimals (not 6 like native USDC!)
            amount_raw = int(amount * Decimal(10**18))

            # LI.FI Quote for same-chain swap
            url = "https://li.quest/v1/quote"
            params = {
                "fromChain": 56,  # BSC
                "toChain": 56,  # BSC (same chain)
                "fromToken": LIFI_USDC[BridgeChain.BSC],  # USDC on BSC
                "toToken": LIFI_USDT_BSC,  # USDT on BSC
                "fromAmount": str(amount_raw),
                "fromAddress": wallet,
                "toAddress": wallet,
                "slippage": "0.005",  # 0.5% slippage for same-chain swap
            }

            headers = {}
            if settings.lifi_api_key:
                headers["x-lifi-api-key"] = settings.lifi_api_key

            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params, headers=headers)

                if resp.status_code != 200:
                    error_msg = resp.text[:300]
                    return BridgeResult(
                        success=False,
                        source_chain=BridgeChain.BSC,
                        dest_chain=BridgeChain.BSC,
                        amount=amount,
                        error_message=f"Swap quote failed: {error_msg}"
                    )

                quote_data = resp.json()

            estimate = quote_data.get("estimate", {})
            to_amount_raw = int(estimate.get("toAmount", "0"))
            output_amount = Decimal(to_amount_raw) / Decimal(10**18)  # USDT has 18 decimals on BSC

            logger.info(
                "BSC USDC->USDT swap quote",
                input=f"{amount} USDC",
                output=f"{output_amount} USDT",
            )

            if progress_callback:
                progress_callback(f"📋 Swapping {amount} USDC → {output_amount:.2f} USDT", 10, 60)

            # Execute the swap
            tx_request = quote_data.get("transactionRequest", {})
            if not tx_request:
                return BridgeResult(
                    success=False,
                    source_chain=BridgeChain.BSC,
                    dest_chain=BridgeChain.BSC,
                    amount=amount,
                    error_message="No transaction data in quote"
                )

            # Check and approve USDC if needed
            usdc_address = LIFI_USDC[BridgeChain.BSC]
            spender = tx_request.get("to")

            if spender:
                usdc_contract = source_w3.eth.contract(
                    address=Web3.to_checksum_address(usdc_address),
                    abi=ERC20_ABI
                )
                allowance = usdc_contract.functions.allowance(
                    wallet, Web3.to_checksum_address(spender)
                ).call()

                if allowance < amount_raw:
                    if progress_callback:
                        progress_callback("🔐 Approving USDC...", 15, 60)

                    approve_tx = usdc_contract.functions.approve(
                        Web3.to_checksum_address(spender),
                        2**256 - 1  # Max approval
                    ).build_transaction({
                        "from": wallet,
                        "nonce": source_w3.eth.get_transaction_count(wallet),
                        "gas": 100000,
                        "gasPrice": source_w3.eth.gas_price,
                        "chainId": 56,
                    })

                    signed_approve = private_key.sign_transaction(approve_tx)
                    approve_hash = source_w3.eth.send_raw_transaction(signed_approve.raw_transaction)
                    source_w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
                    logger.info("USDC approved for swap", tx_hash=approve_hash.hex())

            if progress_callback:
                progress_callback("💱 Executing swap...", 30, 60)

            # Build and send swap transaction
            tx = {
                "from": wallet,
                "to": Web3.to_checksum_address(tx_request["to"]),
                "data": tx_request["data"],
                "value": int(tx_request.get("value", "0"), 16) if isinstance(tx_request.get("value"), str) else int(tx_request.get("value", 0)),
                "nonce": source_w3.eth.get_transaction_count(wallet),
                "gas": int(tx_request.get("gasLimit", 500000)),
                "gasPrice": source_w3.eth.gas_price,
                "chainId": 56,
            }

            signed_tx = private_key.sign_transaction(tx)
            tx_hash = source_w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            if progress_callback:
                progress_callback("⏳ Waiting for confirmation...", 50, 60)

            receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] == 1:
                logger.info("BSC USDC->USDT swap completed", tx_hash=tx_hash.hex())
                return BridgeResult(
                    success=True,
                    source_chain=BridgeChain.BSC,
                    dest_chain=BridgeChain.BSC,
                    amount=amount,
                    received_amount=output_amount,
                    tx_hash=tx_hash.hex(),
                    explorer_url=f"https://bscscan.com/tx/{tx_hash.hex()}",
                )
            else:
                return BridgeResult(
                    success=False,
                    source_chain=BridgeChain.BSC,
                    dest_chain=BridgeChain.BSC,
                    amount=amount,
                    tx_hash=tx_hash.hex(),
                    error_message="Swap transaction failed",
                )

        except Exception as e:
            logger.error("BSC USDC->USDT swap failed", error=str(e))
            return BridgeResult(
                success=False,
                source_chain=BridgeChain.BSC,
                dest_chain=BridgeChain.BSC,
                amount=amount,
                error_message=str(e)
            )

    def find_chain_with_balance(
        self,
        wallet_address: str,
        required_amount: Decimal,
        dest_chain: Optional[BridgeChain] = None,
        exclude_chain: Optional[BridgeChain] = None,
    ) -> Optional[Tuple[BridgeChain, Decimal]]:
        """
        Find a chain that has sufficient USDC balance and a valid bridge route.

        Args:
            wallet_address: User's wallet address
            required_amount: Amount of USDC needed
            dest_chain: Destination chain (to validate bridge route exists)
            exclude_chain: Chain to exclude (usually the destination chain)

        Returns:
            Tuple of (chain, balance) if found, None otherwise
        """
        balances = self.get_all_usdc_balances(wallet_address)

        # Sort by balance descending so we pick the chain with most funds
        sorted_balances = sorted(balances.items(), key=lambda x: x[1], reverse=True)

        for chain, balance in sorted_balances:
            if chain == exclude_chain:
                continue
            if chain == dest_chain:
                continue
            if balance >= required_amount:
                # Validate a bridge route exists to destination
                if dest_chain and (chain, dest_chain) not in VALID_BRIDGE_ROUTES:
                    continue
                return (chain, balance)

        return None

    def bridge_usdc(
        self,
        private_key: LocalAccount,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        amount: Decimal,
        progress_callback: ProgressCallback = None,
    ) -> BridgeResult:
        """
        Bridge USDC from source chain to destination chain using CCTP.

        This is a synchronous operation that:
        1. Approves TokenMessenger to spend USDC
        2. Calls depositForBurn on source chain
        3. Waits for Circle attestation
        4. Calls receiveMessage on destination chain

        Args:
            private_key: User's EVM account
            source_chain: Chain to bridge FROM
            dest_chain: Chain to bridge TO
            amount: Amount of USDC to bridge
            progress_callback: Optional callback for progress updates
                              Called with (message, elapsed_sec, total_sec)

        Returns:
            BridgeResult with transaction details
        """
        if source_chain not in self._web3_clients:
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message=f"Source chain {source_chain.value} not configured"
            )

        if dest_chain not in self._web3_clients:
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message=f"Destination chain {dest_chain.value} not configured"
            )

        try:
            source_w3 = self._web3_clients[source_chain]
            dest_w3 = self._web3_clients[dest_chain]
            source_config = CHAIN_CONFIG[source_chain]
            dest_config = CHAIN_CONFIG[dest_chain]

            wallet = Web3.to_checksum_address(private_key.address)
            amount_raw = int(amount * Decimal(10 ** 6))

            # Step 1: Check native balance for gas
            native_balance = source_w3.eth.get_balance(wallet)
            # Need at least ~0.0001 ETH for gas on L2s (very low fees)
            # For Ethereum mainnet, need more
            if source_chain == BridgeChain.ETHEREUM:
                min_gas_wei = int(0.005 * 10**18)  # 0.005 ETH for mainnet
            else:
                min_gas_wei = int(0.00005 * 10**18)  # 0.00005 ETH for L2s (~$0.15)

            if native_balance < min_gas_wei:
                native_name = "ETH"
                min_eth = min_gas_wei / 10**18
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message=f"Insufficient {native_name} for gas on {source_chain.value}. Need at least {min_eth:.6f} ETH. Current balance: {native_balance / 10**18:.6f} ETH"
                )

            # Step 2: Check USDC balance
            usdc_contract = source_w3.eth.contract(
                address=Web3.to_checksum_address(source_config["usdc"]),
                abi=ERC20_ABI
            )

            balance = usdc_contract.functions.balanceOf(wallet).call()
            if balance < amount_raw:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message=f"Insufficient USDC balance on {source_chain.value}"
                )

            # Notify: Starting bridge
            if progress_callback:
                progress_callback(
                    f"🔄 Starting bridge: {source_chain.value} → {dest_chain.value}",
                    0, 900  # 0 of ~15 min
                )

            # Step 3: Approve TokenMessenger
            token_messenger = Web3.to_checksum_address(source_config["token_messenger"])
            allowance = usdc_contract.functions.allowance(wallet, token_messenger).call()

            if allowance < amount_raw:
                logger.info(
                    "Approving TokenMessenger for USDC",
                    chain=source_chain.value,
                    amount=str(amount)
                )

                nonce = source_w3.eth.get_transaction_count(wallet, 'pending')
                gas_price = int(source_w3.eth.gas_price * 1.5)

                approve_tx = usdc_contract.functions.approve(
                    token_messenger,
                    2 ** 256 - 1  # Max approval
                ).build_transaction({
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                    "gas": 100000,
                    "chainId": source_config["chain_id"],
                })

                signed_approve = source_w3.eth.account.sign_transaction(
                    approve_tx, private_key.key
                )
                approve_hash = source_w3.eth.send_raw_transaction(
                    signed_approve.raw_transaction
                )
                source_w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
                logger.info("TokenMessenger approval confirmed", tx_hash=approve_hash.hex())

            # Step 4: Call depositForBurn
            messenger_contract = source_w3.eth.contract(
                address=token_messenger,
                abi=TOKEN_MESSENGER_ABI
            )

            # Convert destination address to bytes32 (padded)
            mint_recipient = Web3.to_bytes(hexstr=wallet).rjust(32, b'\x00')

            nonce = source_w3.eth.get_transaction_count(wallet, 'pending')
            gas_price = int(source_w3.eth.gas_price * 1.5)

            burn_tx = messenger_contract.functions.depositForBurn(
                amount_raw,
                dest_config["domain"],
                mint_recipient,
                Web3.to_checksum_address(source_config["usdc"])
            ).build_transaction({
                "from": wallet,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": 300000,
                "chainId": source_config["chain_id"],
            })

            signed_burn = source_w3.eth.account.sign_transaction(burn_tx, private_key.key)
            burn_hash = source_w3.eth.send_raw_transaction(signed_burn.raw_transaction)
            burn_hash_hex = burn_hash.hex()

            logger.info(
                "CCTP burn initiated",
                source=source_chain.value,
                dest=dest_chain.value,
                amount=str(amount),
                tx_hash=burn_hash_hex
            )

            # Wait for burn confirmation
            burn_receipt = source_w3.eth.wait_for_transaction_receipt(burn_hash, timeout=120)
            if burn_receipt.status != 1:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    burn_tx_hash=burn_hash_hex,
                    error_message="Burn transaction failed on-chain"
                )

            logger.info("CCTP burn confirmed", tx_hash=burn_hash_hex)

            if progress_callback:
                progress_callback(
                    "🔥 USDC burned on source chain. Waiting for Circle attestation...",
                    30, 900  # ~30 sec in
                )

            # Step 5: Wait for attestation and mint
            # This uses Circle's attestation API
            attestation_result = self._wait_for_attestation_and_mint(
                burn_hash_hex,
                source_chain,
                dest_chain,
                private_key,
                progress_callback=progress_callback,
            )

            if attestation_result:
                return BridgeResult(
                    success=True,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    burn_tx_hash=burn_hash_hex,
                    mint_tx_hash=attestation_result,
                )
            else:
                # Attestation pending - bridge will complete later
                return BridgeResult(
                    success=True,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    burn_tx_hash=burn_hash_hex,
                    mint_tx_hash=None,  # Will be minted automatically
                )

        except Exception as e:
            import traceback
            error_msg = str(e) if str(e) else type(e).__name__
            logger.error(
                "Bridge failed",
                source=source_chain.value,
                dest=dest_chain.value,
                error=error_msg,
                traceback=traceback.format_exc()
            )
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message=error_msg
            )

    def _wait_for_attestation_and_mint(
        self,
        burn_tx_hash: str,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        private_key: LocalAccount,
        max_wait_seconds: int = 900,  # 15 minutes
        poll_interval: int = 15,
        progress_callback: ProgressCallback = None,
    ) -> Optional[str]:
        """
        Wait for Circle attestation and mint on destination chain.

        Returns mint tx hash if successful, None if still pending.
        """
        import httpx

        attestation_url = "https://iris-api.circle.com/attestations"
        message_hash = None

        # Get message hash from burn transaction logs
        source_w3 = self._web3_clients[source_chain]
        source_config = CHAIN_CONFIG[source_chain]

        try:
            receipt = source_w3.eth.get_transaction_receipt(burn_tx_hash)

            # Find MessageSent event log
            # Topic0 for MessageSent: 0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036
            message_sent_topic = "0x8c5261668696ce22758910d05bab8f186d6eb247ceac2af2e82c7dc17669b036"

            for log in receipt.logs:
                if log.topics and log.topics[0].hex() == message_sent_topic:
                    # The message is in the data field
                    message = log.data
                    message_hash = Web3.keccak(message).hex()
                    break

            if not message_hash:
                logger.warning("Could not find MessageSent event in burn tx")
                return None

        except Exception as e:
            logger.warning("Failed to get message hash", error=str(e))
            return None

        # Poll for attestation
        start_time = time.time()
        attestation = None
        message_bytes = None

        logger.info("Waiting for Circle attestation...", message_hash=message_hash)

        poll_count = 0
        while time.time() - start_time < max_wait_seconds:
            elapsed = int(time.time() - start_time)
            remaining = max(0, max_wait_seconds - elapsed)
            remaining_min = remaining // 60
            remaining_sec = remaining % 60

            # Update progress every poll
            if progress_callback:
                progress_callback(
                    f"⏳ Waiting for Circle attestation... (~{remaining_min}m {remaining_sec}s remaining)",
                    elapsed + 30,  # +30 for burn phase
                    max_wait_seconds + 30
                )

            try:
                with httpx.Client(timeout=30) as client:
                    response = client.get(f"{attestation_url}/{message_hash}")

                    if response.status_code == 200:
                        data = response.json()
                        if data.get("status") == "complete":
                            attestation = data.get("attestation")
                            message_bytes = data.get("message")
                            logger.info("Attestation received!")
                            if progress_callback:
                                progress_callback(
                                    "✅ Attestation received! Minting on destination chain...",
                                    max_wait_seconds,
                                    max_wait_seconds + 30
                                )
                            break

            except Exception as e:
                logger.debug("Attestation poll error", error=str(e))

            poll_count += 1
            time.sleep(poll_interval)

        if not attestation or not message_bytes:
            logger.info(
                "Attestation not ready yet, bridge will complete automatically",
                elapsed=int(time.time() - start_time)
            )
            return None

        # Mint on destination chain
        try:
            dest_w3 = self._web3_clients[dest_chain]
            dest_config = CHAIN_CONFIG[dest_chain]
            wallet = Web3.to_checksum_address(private_key.address)

            transmitter_contract = dest_w3.eth.contract(
                address=Web3.to_checksum_address(dest_config["message_transmitter"]),
                abi=MESSAGE_TRANSMITTER_ABI
            )

            nonce = dest_w3.eth.get_transaction_count(wallet, 'pending')
            gas_price = int(dest_w3.eth.gas_price * 1.5)

            mint_tx = transmitter_contract.functions.receiveMessage(
                bytes.fromhex(message_bytes.replace("0x", "")),
                bytes.fromhex(attestation.replace("0x", ""))
            ).build_transaction({
                "from": wallet,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": 300000,
                "chainId": dest_config["chain_id"],
            })

            signed_mint = dest_w3.eth.account.sign_transaction(mint_tx, private_key.key)
            mint_hash = dest_w3.eth.send_raw_transaction(signed_mint.raw_transaction)
            mint_hash_hex = mint_hash.hex()

            # Wait for confirmation
            mint_receipt = dest_w3.eth.wait_for_transaction_receipt(mint_hash, timeout=120)

            if mint_receipt.status == 1:
                logger.info(
                    "CCTP mint confirmed",
                    dest=dest_chain.value,
                    tx_hash=mint_hash_hex
                )
                return mint_hash_hex
            else:
                logger.warning("Mint transaction failed on-chain")
                return None

        except Exception as e:
            logger.error("Mint failed", error=str(e))
            return None


    def get_fast_bridge_quote(
        self,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        amount: Decimal,
        wallet_address: str,
    ) -> FastBridgeQuote:
        """
        Get a quote for fast bridging via Relay.link.
        Returns fee information and estimated time.
        """
        import httpx

        if source_chain not in RELAY_CHAIN_IDS or dest_chain not in RELAY_CHAIN_IDS:
            return FastBridgeQuote(
                input_amount=amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                gas_fee=Decimal(0),
                relay_fee=Decimal(0),
                estimated_time_seconds=0,
                error=f"Fast bridge not supported for {source_chain.value} -> {dest_chain.value}"
            )

        try:
            amount_raw = int(amount * Decimal(10**6))

            # Relay.link quote API v2 - uses POST with JSON body
            url = "https://api.relay.link/quote/v2"
            payload = {
                "user": wallet_address,
                "originChainId": RELAY_CHAIN_IDS[source_chain],
                "destinationChainId": RELAY_CHAIN_IDS[dest_chain],
                "originCurrency": RELAY_USDC[source_chain],
                "destinationCurrency": RELAY_USDC[dest_chain],
                "amount": str(amount_raw),
                "tradeType": "EXACT_INPUT",
            }

            with httpx.Client(timeout=30) as client:
                resp = client.post(url, json=payload)

                if resp.status_code != 200:
                    logger.warning("Relay quote failed", status=resp.status_code, body=resp.text[:200])
                    return FastBridgeQuote(
                        input_amount=amount,
                        output_amount=Decimal(0),
                        fee_amount=Decimal(0),
                        fee_percent=0,
                        gas_fee=Decimal(0),
                        relay_fee=Decimal(0),
                        estimated_time_seconds=0,
                        error=f"Quote failed: {resp.status_code}"
                    )

                data = resp.json()

                # Parse the quote response
                # Relay returns fees in the response
                details = data.get("details", {})
                fees = details.get("totalFees", {})

                output_raw = int(data.get("details", {}).get("currencyOut", {}).get("amount", "0"))
                output_amount = Decimal(output_raw) / Decimal(10**6)

                fee_raw = int(fees.get("amount", "0"))
                fee_amount = Decimal(fee_raw) / Decimal(10**6) if fee_raw else amount - output_amount

                gas_raw = int(fees.get("gas", "0"))
                gas_fee = Decimal(gas_raw) / Decimal(10**6)

                relay_raw = int(fees.get("relayer", "0"))
                relay_fee = Decimal(relay_raw) / Decimal(10**6)

                fee_percent = float(fee_amount / amount * 100) if amount > 0 else 0

                return FastBridgeQuote(
                    input_amount=amount,
                    output_amount=output_amount,
                    fee_amount=fee_amount,
                    fee_percent=fee_percent,
                    gas_fee=gas_fee,
                    relay_fee=relay_fee,
                    estimated_time_seconds=30,  # Relay is typically ~20-30 seconds
                    quote_id=data.get("requestId"),
                )

        except Exception as e:
            logger.error("Failed to get fast bridge quote", error=str(e))
            return FastBridgeQuote(
                input_amount=amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                gas_fee=Decimal(0),
                relay_fee=Decimal(0),
                estimated_time_seconds=0,
                error=str(e)
            )

    def bridge_usdc_fast(
        self,
        private_key: LocalAccount,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        amount: Decimal,
        progress_callback: ProgressCallback = None,
    ) -> BridgeResult:
        """
        Fast bridge USDC via Relay.link (~30 seconds, small fee).
        Uses relayers to front the funds for instant bridging.
        """
        import httpx

        if source_chain not in self._web3_clients:
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message=f"Source chain {source_chain.value} not configured"
            )

        try:
            source_w3 = self._web3_clients[source_chain]
            wallet = Web3.to_checksum_address(private_key.address)
            amount_raw = int(amount * Decimal(10**6))

            # Check native balance for gas
            native_balance = source_w3.eth.get_balance(wallet)
            min_gas_wei = int(0.0001 * 10**18)  # 0.0001 ETH for fast bridge
            if native_balance < min_gas_wei:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message=f"Insufficient ETH for gas. Need at least 0.0001 ETH."
                )

            if progress_callback:
                progress_callback("🚀 Getting fast bridge quote...", 0, 30)

            # Step 1: Get quote from Relay v2 API (POST with JSON body)
            url = "https://api.relay.link/quote/v2"
            payload = {
                "user": wallet,
                "originChainId": RELAY_CHAIN_IDS[source_chain],
                "destinationChainId": RELAY_CHAIN_IDS[dest_chain],
                "originCurrency": RELAY_USDC[source_chain],
                "destinationCurrency": RELAY_USDC[dest_chain],
                "amount": str(amount_raw),
                "tradeType": "EXACT_INPUT",
            }

            with httpx.Client(timeout=30) as client:
                quote_resp = client.post(url, json=payload)

                if quote_resp.status_code != 200:
                    return BridgeResult(
                        success=False,
                        source_chain=source_chain,
                        dest_chain=dest_chain,
                        amount=amount,
                        error_message=f"Failed to get quote: {quote_resp.text[:100]}"
                    )

                quote_data = quote_resp.json()
                logger.info("Relay quote received", steps_count=len(quote_data.get("steps", [])))

            if progress_callback:
                progress_callback("📝 Preparing transaction...", 5, 30)

            # Step 2: Get the execution steps
            steps = quote_data.get("steps", [])
            if not steps:
                logger.error("No bridge steps in quote", quote_keys=list(quote_data.keys()))
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message="No bridge steps returned"
                )

            tx_hash = None

            # Execute each step (usually approve + deposit)
            for i, step in enumerate(steps):
                logger.info(f"Processing step {i}", step_id=step.get("id"), step_kind=step.get("kind"))
                items = step.get("items", [])
                for item in items:
                    tx_data = item.get("data", {})

                    if not tx_data:
                        logger.warning("No tx_data in item", item_keys=list(item.keys()))
                        continue

                    to_address = tx_data.get("to")
                    data = tx_data.get("data")
                    # Handle value as string or int
                    value_raw = tx_data.get("value", "0")
                    try:
                        value = int(value_raw) if isinstance(value_raw, str) else value_raw
                    except (ValueError, TypeError):
                        value = 0

                    if not to_address or not data:
                        logger.warning("Missing to_address or data", to=to_address, has_data=bool(data))
                        continue

                    logger.info("Building tx", to=to_address, value=value, data_len=len(data) if data else 0)

                    # Build transaction - use higher gas multiplier to avoid underpriced errors
                    nonce = source_w3.eth.get_transaction_count(wallet, 'pending')
                    base_gas_price = source_w3.eth.gas_price
                    gas_price = int(base_gas_price * 2.0)  # 2x base gas price
                    logger.info("Transaction params", nonce=nonce, base_gas=base_gas_price, gas_price=gas_price)

                    tx = {
                        "from": wallet,
                        "to": Web3.to_checksum_address(to_address),
                        "data": data,
                        "value": value,
                        "nonce": nonce,
                        "gasPrice": gas_price,
                        "chainId": RELAY_CHAIN_IDS[source_chain],
                    }

                    # Estimate gas
                    try:
                        gas_estimate = source_w3.eth.estimate_gas(tx)
                        tx["gas"] = int(gas_estimate * 1.3)
                        logger.info("Gas estimated", gas=tx["gas"])
                    except Exception as e:
                        logger.warning("Gas estimation failed, using default", error=str(e), tx_to=to_address)
                        tx["gas"] = 300000

                    if progress_callback:
                        step_name = step.get("id", f"Step {i+1}")
                        progress_callback(f"✍️ Signing {step_name}...", 10 + i * 5, 30)

                    # Sign and send
                    signed_tx = source_w3.eth.account.sign_transaction(tx, private_key.key)
                    try:
                        tx_hash = source_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                        tx_hash_hex = tx_hash.hex()
                    except Exception as send_error:
                        error_str = str(send_error)
                        logger.error("Failed to send transaction", error=error_str, nonce=nonce, gas_price=gas_price)
                        # Check for specific errors
                        if "underpriced" in error_str.lower() or "replacement" in error_str.lower():
                            return BridgeResult(
                                success=False,
                                source_chain=source_chain,
                                dest_chain=dest_chain,
                                amount=amount,
                                error_message="Transaction failed: You have a pending transaction. Please wait a few minutes and try again."
                            )
                        elif "nonce too low" in error_str.lower():
                            return BridgeResult(
                                success=False,
                                source_chain=source_chain,
                                dest_chain=dest_chain,
                                amount=amount,
                                error_message="Transaction failed: Nonce conflict. Please try again."
                            )
                        raise

                    logger.info(f"Fast bridge tx sent", step=step.get("id"), tx_hash=tx_hash_hex)

                    # Wait for confirmation
                    if progress_callback:
                        progress_callback(f"⏳ Confirming transaction...", 15 + i * 5, 30)

                    receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

                    if receipt.status != 1:
                        return BridgeResult(
                            success=False,
                            source_chain=source_chain,
                            dest_chain=dest_chain,
                            amount=amount,
                            burn_tx_hash=tx_hash_hex,
                            error_message="Transaction failed on-chain"
                        )

            if progress_callback:
                progress_callback("✅ Bridge complete! Funds arriving shortly...", 30, 30)

            # Get output amount from quote
            try:
                output_raw_str = quote_data.get("details", {}).get("currencyOut", {}).get("amount", "0")
                output_raw = int(output_raw_str) if output_raw_str else int(amount * Decimal(10**6))
                output_amount = Decimal(output_raw) / Decimal(10**6)
            except (ValueError, TypeError) as e:
                logger.warning("Failed to parse output amount", error=str(e))
                output_amount = amount

            # Get tx_hash as string
            tx_hash_str = None
            if tx_hash:
                tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)

            logger.info(
                "Fast bridge completed",
                source=source_chain.value,
                dest=dest_chain.value,
                input=str(amount),
                output=str(output_amount),
                tx_hash=tx_hash_str
            )

            return BridgeResult(
                success=True,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=output_amount,  # Amount received after fees
                burn_tx_hash=tx_hash_str,
                mint_tx_hash=None,  # Relay handles the mint
            )

        except Exception as e:
            import traceback
            error_msg = str(e) if str(e) else type(e).__name__
            logger.error(
                "Fast bridge failed",
                source=source_chain.value,
                dest=dest_chain.value,
                error=error_msg,
                traceback=traceback.format_exc()
            )
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message=error_msg
            )

    def get_lifi_quote(
        self,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        amount: Decimal,
        from_address: str,
        to_address: str,
    ) -> LiFiBridgeQuote:
        """
        Get a quote for bridging via LI.FI.
        Supports EVM <-> Solana routes.

        Args:
            source_chain: Source chain
            dest_chain: Destination chain
            amount: Amount of USDC to bridge
            from_address: Source wallet address (EVM or Solana)
            to_address: Destination wallet address (EVM or Solana)
        """
        import httpx

        if source_chain not in LIFI_CHAIN_IDS or dest_chain not in LIFI_CHAIN_IDS:
            return LiFiBridgeQuote(
                input_amount=amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                estimated_time_seconds=0,
                tool_name="",
                error=f"LI.FI bridge not supported for {source_chain.value} -> {dest_chain.value}"
            )

        try:
            amount_raw = int(amount * Decimal(10**6))

            # Determine destination token - BSC uses USDT (for Opinion Labs), others use USDC
            if dest_chain == BridgeChain.BSC:
                to_token = LIFI_USDT_BSC
                to_decimals = 18  # USDT on BSC has 18 decimals
            else:
                to_token = LIFI_USDC[dest_chain]
                to_decimals = 6  # USDC has 6 decimals

            # LI.FI Quote API
            url = "https://li.quest/v1/quote"
            params = {
                "fromChain": LIFI_CHAIN_IDS[source_chain],
                "toChain": LIFI_CHAIN_IDS[dest_chain],
                "fromToken": LIFI_USDC[source_chain],
                "toToken": to_token,
                "fromAmount": str(amount_raw),
                "fromAddress": from_address,
                "toAddress": to_address,
                "slippage": "0.01",  # 1% slippage for cross-chain
            }
            # Don't filter bridges - let LI.FI find the best route

            # Add API key header if configured
            headers = {}
            if settings.lifi_api_key:
                headers["x-lifi-api-key"] = settings.lifi_api_key

            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params, headers=headers)

                if resp.status_code != 200:
                    try:
                        error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                        error_msg = error_data.get("message", resp.text[:500])
                    except Exception:
                        error_msg = resp.text[:500]
                    logger.warning("LI.FI quote failed", status=resp.status_code, error=error_msg, url=str(resp.url))
                    return LiFiBridgeQuote(
                        input_amount=amount,
                        output_amount=Decimal(0),
                        fee_amount=Decimal(0),
                        fee_percent=0,
                        estimated_time_seconds=0,
                        tool_name="",
                        error=f"Quote failed: {error_msg}"
                    )

                data = resp.json()

                # Parse estimate
                estimate = data.get("estimate", {})
                to_amount_raw = int(estimate.get("toAmount", "0"))
                # Use correct decimals: BSC USDT has 18 decimals, USDC has 6
                output_amount = Decimal(to_amount_raw) / Decimal(10**to_decimals)

                fee_costs = estimate.get("feeCosts", [])
                gas_costs = estimate.get("gasCosts", [])

                # Calculate total fees
                total_fee = Decimal(0)
                for fee in fee_costs:
                    fee_usd = Decimal(str(fee.get("amountUSD", "0")))
                    total_fee += fee_usd
                for gas in gas_costs:
                    gas_usd = Decimal(str(gas.get("amountUSD", "0")))
                    total_fee += gas_usd

                fee_amount = amount - output_amount
                fee_percent = float(fee_amount / amount * 100) if amount > 0 else 0

                # Get bridge tool being used
                tool_name = data.get("toolDetails", {}).get("name", "unknown")
                execution_duration = estimate.get("executionDuration", 180)
                dest_token_symbol = "USDT" if dest_chain == BridgeChain.BSC else "USDC"

                logger.info(
                    "LI.FI quote received",
                    tool=tool_name,
                    input=f"{amount} USDC",
                    output=f"{output_amount} {dest_token_symbol}",
                    fee_percent=f"{fee_percent:.2f}%",
                    duration=execution_duration,
                    route=f"{source_chain.value} -> {dest_chain.value}"
                )

                return LiFiBridgeQuote(
                    input_amount=amount,
                    output_amount=output_amount,
                    fee_amount=fee_amount,
                    fee_percent=fee_percent,
                    estimated_time_seconds=execution_duration,
                    tool_name=tool_name,
                    quote_data=data,
                )

        except Exception as e:
            logger.error("Failed to get LI.FI quote", error=str(e))
            return LiFiBridgeQuote(
                input_amount=amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                estimated_time_seconds=0,
                tool_name="",
                error=str(e)
            )

    def bridge_usdc_lifi(
        self,
        private_key: LocalAccount,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        amount: Decimal,
        to_address: str,
        progress_callback: ProgressCallback = None,
    ) -> BridgeResult:
        """
        Bridge USDC via LI.FI. Supports EVM -> Solana routes.

        Args:
            private_key: EVM account (source must be EVM chain)
            source_chain: Source chain (must be EVM for now)
            dest_chain: Destination chain (can be Solana)
            amount: Amount of USDC to bridge
            to_address: Destination address (Solana address if dest is Solana)
            progress_callback: Optional callback for progress updates
        """
        import httpx

        # Validate source is EVM (we can only sign EVM transactions)
        if source_chain == BridgeChain.SOLANA:
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message="Bridging FROM Solana not yet supported. Only EVM -> Solana is available."
            )

        if source_chain not in self._web3_clients:
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message=f"Source chain {source_chain.value} not configured"
            )

        try:
            source_w3 = self._web3_clients[source_chain]
            wallet = Web3.to_checksum_address(private_key.address)

            # Check native balance for gas
            native_balance = source_w3.eth.get_balance(wallet)
            min_gas_wei = int(0.0005 * 10**18)  # 0.0005 ETH for LI.FI bridge
            if native_balance < min_gas_wei:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message=f"Insufficient ETH for gas. Need at least 0.0005 ETH."
                )

            if progress_callback:
                progress_callback("🔗 Getting LI.FI bridge quote...", 0, 120)

            # Step 1: Get quote from LI.FI
            quote = self.get_lifi_quote(
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                from_address=wallet,
                to_address=to_address,
            )

            if quote.error:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message=quote.error
                )

            if not quote.quote_data:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message="No quote data received from LI.FI"
                )

            if progress_callback:
                progress_callback(
                    f"📋 Using {quote.tool_name} bridge (~{quote.estimated_time_seconds}s)",
                    10, 120
                )

            # Step 2: Extract transaction data from quote
            tx_request = quote.quote_data.get("transactionRequest", {})
            if not tx_request:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    error_message="No transaction data in LI.FI quote"
                )

            # Step 3: Check if approval is needed
            action = quote.quote_data.get("action", {})
            approval_address = action.get("fromToken", {}).get("address")

            if approval_address and approval_address.lower() != "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee":
                # Check allowance for LI.FI contract
                usdc_contract = source_w3.eth.contract(
                    address=Web3.to_checksum_address(approval_address),
                    abi=ERC20_ABI
                )

                lifi_contract = tx_request.get("to")
                if lifi_contract:
                    allowance = usdc_contract.functions.allowance(
                        wallet, Web3.to_checksum_address(lifi_contract)
                    ).call()

                    amount_raw = int(amount * Decimal(10**6))

                    if allowance < amount_raw:
                        if progress_callback:
                            progress_callback("✍️ Approving USDC for LI.FI...", 15, 120)

                        logger.info("Approving LI.FI contract for USDC", contract=lifi_contract)

                        nonce = source_w3.eth.get_transaction_count(wallet, 'pending')
                        gas_price = int(source_w3.eth.gas_price * 1.5)

                        approve_tx = usdc_contract.functions.approve(
                            Web3.to_checksum_address(lifi_contract),
                            2 ** 256 - 1  # Max approval
                        ).build_transaction({
                            "from": wallet,
                            "nonce": nonce,
                            "gasPrice": gas_price,
                            "gas": 100000,
                            "chainId": LIFI_CHAIN_IDS[source_chain],
                        })

                        signed_approve = source_w3.eth.account.sign_transaction(
                            approve_tx, private_key.key
                        )
                        approve_hash = source_w3.eth.send_raw_transaction(
                            signed_approve.raw_transaction
                        )
                        source_w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
                        logger.info("LI.FI approval confirmed", tx_hash=approve_hash.hex())

            if progress_callback:
                progress_callback("🚀 Executing bridge transaction...", 30, 120)

            # Step 4: Build and send the bridge transaction
            nonce = source_w3.eth.get_transaction_count(wallet, 'pending')
            gas_price = int(source_w3.eth.gas_price * 1.8)

            # Parse value (might be string)
            value_raw = tx_request.get("value", "0")
            try:
                value = int(value_raw, 16) if isinstance(value_raw, str) and value_raw.startswith("0x") else int(value_raw)
            except (ValueError, TypeError):
                value = 0

            tx = {
                "from": wallet,
                "to": Web3.to_checksum_address(tx_request["to"]),
                "data": tx_request["data"],
                "value": value,
                "nonce": nonce,
                "gasPrice": gas_price,
                "chainId": LIFI_CHAIN_IDS[source_chain],
            }

            # Estimate gas
            try:
                gas_estimate = source_w3.eth.estimate_gas(tx)
                tx["gas"] = int(gas_estimate * 1.3)
                logger.info("Gas estimated for LI.FI tx", gas=tx["gas"])
            except Exception as e:
                logger.warning("Gas estimation failed for LI.FI tx", error=str(e), error_type=type(e).__name__)
                # Gas estimation failure often means the tx will revert - log more details
                logger.warning("TX details for failed estimation", to=tx.get("to"), value=tx.get("value"), data_len=len(tx.get("data", "")) if tx.get("data") else 0)
                tx["gas"] = int(tx_request.get("gasLimit", 500000))

            # Sign and send
            logger.info("Signing LI.FI tx", nonce=tx["nonce"], gas=tx["gas"], gas_price=tx["gasPrice"])
            signed_tx = source_w3.eth.account.sign_transaction(tx, private_key.key)
            logger.info("Sending LI.FI tx...")
            tx_hash = source_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            logger.info(
                "LI.FI bridge transaction sent",
                source=source_chain.value,
                dest=dest_chain.value,
                tool=quote.tool_name,
                tx_hash=tx_hash_hex
            )

            if progress_callback:
                progress_callback("⏳ Waiting for confirmation...", 50, 120)

            # Wait for confirmation
            receipt = source_w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

            if receipt.status != 1:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=amount,
                    burn_tx_hash=tx_hash_hex,
                    error_message="Bridge transaction failed on-chain"
                )

            if progress_callback:
                est_time = quote.estimated_time_seconds
                progress_callback(
                    f"✅ Bridge initiated! Funds arriving in ~{est_time//60}m {est_time%60}s",
                    120, 120
                )

            logger.info(
                "LI.FI bridge completed",
                source=source_chain.value,
                dest=dest_chain.value,
                input=str(amount),
                output=str(quote.output_amount),
                tool=quote.tool_name,
                tx_hash=tx_hash_hex
            )

            return BridgeResult(
                success=True,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=quote.output_amount,
                burn_tx_hash=tx_hash_hex,
                mint_tx_hash=None,  # LI.FI handles the cross-chain delivery
            )

        except Exception as e:
            import traceback
            error_msg = str(e) if str(e) else type(e).__name__
            tb = traceback.format_exc()
            logger.error(f"LI.FI bridge failed: {error_msg}")
            logger.error(f"LI.FI bridge traceback: {tb}")
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=amount,
                error_message=error_msg
            )

    def requires_lifi(self, source_chain: BridgeChain, dest_chain: BridgeChain) -> bool:
        """Check if the bridge route requires LI.FI (no CCTP support)."""
        lifi_only_chains = {BridgeChain.SOLANA, BridgeChain.BSC, BridgeChain.ABSTRACT, BridgeChain.LINEA}
        return source_chain in lifi_only_chains or dest_chain in lifi_only_chains

    def involves_solana(self, source_chain: BridgeChain, dest_chain: BridgeChain) -> bool:
        """Check if the bridge route involves Solana."""
        return source_chain == BridgeChain.SOLANA or dest_chain == BridgeChain.SOLANA

    def get_best_bridge_method(
        self,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
    ) -> str:
        """
        Determine the best bridge method for a given route.

        Returns:
            "lifi" - For Solana/BSC routes (no CCTP support)
            "relay" - For fast EVM-to-EVM
            "cctp" - For standard EVM-to-EVM
        """
        if self.requires_lifi(source_chain, dest_chain):
            return "lifi"
        elif source_chain in RELAY_CHAIN_IDS and dest_chain in RELAY_CHAIN_IDS:
            return "relay"  # Default to fast bridge for EVM
        else:
            return "cctp"

    def is_valid_bridge_route(self, source_chain: BridgeChain, dest_chain: BridgeChain) -> bool:
        """Check if a bridge route is valid/supported."""
        if source_chain == dest_chain:
            return False
        return (source_chain, dest_chain) in VALID_BRIDGE_ROUTES

    def get_valid_source_chains(self, dest_chain: BridgeChain) -> list[BridgeChain]:
        """Get list of valid source chains that can bridge to the destination."""
        valid_sources = []
        for source, dest in VALID_BRIDGE_ROUTES:
            if dest == dest_chain:
                valid_sources.append(source)
        return valid_sources

    def get_valid_dest_chains(self, source_chain: BridgeChain) -> list[BridgeChain]:
        """Get list of valid destination chains from the source."""
        valid_dests = []
        for source, dest in VALID_BRIDGE_ROUTES:
            if source == source_chain:
                valid_dests.append(dest)
        return valid_dests

    def is_valid_native_bridge_route(self, source_chain: BridgeChain, dest_chain: BridgeChain) -> bool:
        """Check if native token bridging is supported between these chains."""
        return (source_chain, dest_chain) in VALID_NATIVE_BRIDGE_ROUTES

    def get_valid_native_dest_chains(self, source_chain: BridgeChain) -> list[BridgeChain]:
        """Get list of valid destination chains for native token bridging from the source."""
        valid_dests = []
        for source, dest in VALID_NATIVE_BRIDGE_ROUTES:
            if source == source_chain:
                valid_dests.append(dest)
        return valid_dests

    def get_native_bridge_quote(
        self,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        native_amount: Decimal,
        wallet_address: str,
    ) -> LiFiBridgeQuote:
        """
        Get quote for bridging native token (ETH/POL/BNB) to another chain.

        Args:
            source_chain: Source chain
            dest_chain: Destination chain
            native_amount: Amount of native token (in whole units, e.g., 0.01 ETH)
            wallet_address: User's wallet address
        """
        import httpx

        if not self.is_valid_native_bridge_route(source_chain, dest_chain):
            return LiFiBridgeQuote(
                input_amount=native_amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                estimated_time_seconds=0,
                tool_name="",
                error=f"Native bridge not supported: {source_chain.value} → {dest_chain.value}"
            )

        try:
            source_chain_id = LIFI_CHAIN_IDS.get(source_chain)
            dest_chain_id = LIFI_CHAIN_IDS.get(dest_chain)

            if not source_chain_id or not dest_chain_id:
                return LiFiBridgeQuote(
                    input_amount=native_amount,
                    output_amount=Decimal(0),
                    fee_amount=Decimal(0),
                    fee_percent=0,
                    estimated_time_seconds=0,
                    tool_name="",
                    error=f"Chain not configured for LI.FI"
                )

            amount_raw = int(native_amount * Decimal(10**18))  # Native tokens have 18 decimals

            url = "https://li.quest/v1/quote"
            params = {
                "fromChain": source_chain_id,
                "toChain": dest_chain_id,
                "fromToken": NATIVE_TOKEN,  # Native token address
                "toToken": NATIVE_TOKEN,    # Receive native token on dest
                "fromAmount": str(amount_raw),
                "fromAddress": wallet_address,
                "toAddress": wallet_address,
                "slippage": "0.01",  # 1% slippage for cross-chain
            }

            headers = {}
            if settings.lifi_api_key:
                headers["x-lifi-api-key"] = settings.lifi_api_key

            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params, headers=headers)

                if resp.status_code != 200:
                    try:
                        error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                        error_msg = error_data.get("message", resp.text[:200])
                    except Exception:
                        error_msg = resp.text[:200]
                    return LiFiBridgeQuote(
                        input_amount=native_amount,
                        output_amount=Decimal(0),
                        fee_amount=Decimal(0),
                        fee_percent=0,
                        estimated_time_seconds=0,
                        tool_name="",
                        error=f"Quote failed: {error_msg}"
                    )

                data = resp.json()
                estimate = data.get("estimate", {})
                to_amount_raw = int(estimate.get("toAmount", "0"))
                output_amount = Decimal(to_amount_raw) / Decimal(10**18)

                # Calculate fees
                fee_costs = estimate.get("feeCosts", [])
                gas_costs = estimate.get("gasCosts", [])
                total_fee_usd = Decimal(0)
                for fee in fee_costs:
                    total_fee_usd += Decimal(str(fee.get("amountUSD", "0")))
                for gas in gas_costs:
                    total_fee_usd += Decimal(str(gas.get("amountUSD", "0")))

                tool_name = data.get("toolDetails", {}).get("name", "Bridge")
                execution_duration = estimate.get("executionDuration", 60)

                source_symbol = NATIVE_TOKEN_SYMBOLS.get(source_chain, "TOKEN")
                dest_symbol = NATIVE_TOKEN_SYMBOLS.get(dest_chain, "TOKEN")

                logger.info(
                    "Native bridge quote received",
                    tool=tool_name,
                    input=f"{native_amount} {source_symbol}",
                    output=f"{output_amount} {dest_symbol}",
                    route=f"{source_chain.value} → {dest_chain.value}"
                )

                return LiFiBridgeQuote(
                    input_amount=native_amount,
                    output_amount=output_amount,
                    fee_amount=total_fee_usd,
                    fee_percent=float(total_fee_usd) / (float(native_amount) * 2000) * 100 if native_amount > 0 else 0,  # Rough ETH price estimate
                    estimated_time_seconds=execution_duration,
                    tool_name=tool_name,
                    quote_data=data,
                )

        except Exception as e:
            logger.error("Failed to get native bridge quote", error=str(e))
            return LiFiBridgeQuote(
                input_amount=native_amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                estimated_time_seconds=0,
                tool_name="",
                error=str(e)
            )

    def execute_native_bridge(
        self,
        private_key: LocalAccount,
        source_chain: BridgeChain,
        dest_chain: BridgeChain,
        native_amount: Decimal,
        progress_callback: ProgressCallback = None,
    ) -> BridgeResult:
        """
        Execute a native token bridge between chains.

        Args:
            private_key: EVM account for signing
            source_chain: Source chain
            dest_chain: Destination chain
            native_amount: Amount of native token to bridge
            progress_callback: Optional progress callback
        """
        import httpx

        if source_chain not in self._web3_clients:
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=native_amount,
                error_message=f"Chain {source_chain.value} not configured"
            )

        try:
            w3 = self._web3_clients[source_chain]
            wallet = Web3.to_checksum_address(private_key.address)
            source_symbol = NATIVE_TOKEN_SYMBOLS.get(source_chain, "TOKEN")
            dest_symbol = NATIVE_TOKEN_SYMBOLS.get(dest_chain, "TOKEN")

            if progress_callback:
                progress_callback(f"🌉 Getting bridge quote...", 0, 120)

            # Get quote
            quote = self.get_native_bridge_quote(source_chain, dest_chain, native_amount, wallet)
            if quote.error:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=native_amount,
                    error_message=quote.error
                )

            if not quote.quote_data:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=native_amount,
                    error_message="No quote data received"
                )

            if progress_callback:
                progress_callback(f"📋 Bridging {native_amount} {source_symbol} → {dest_chain.value}", 10, 120)

            # Extract transaction data
            tx_request = quote.quote_data.get("transactionRequest", {})
            if not tx_request:
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=native_amount,
                    error_message="No transaction data in quote"
                )

            # Build transaction
            to_address = Web3.to_checksum_address(tx_request.get("to", ""))
            data = tx_request.get("data", "0x")
            value = int(tx_request.get("value", "0"), 16) if isinstance(tx_request.get("value"), str) else int(tx_request.get("value", 0))
            gas_limit = int(tx_request.get("gasLimit", "500000"), 16) if isinstance(tx_request.get("gasLimit"), str) else int(tx_request.get("gasLimit", 500000))

            # Get nonce with retry
            nonce = None
            for attempt in range(3):
                try:
                    nonce = w3.eth.get_transaction_count(wallet)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise Exception(f"Failed to get nonce after 3 attempts: {e}")
                    import time
                    time.sleep(1)

            chain_id = CHAIN_CONFIG[source_chain]["chain_id"]

            # Use EIP-1559 for Ethereum mainnet (chain 1), legacy for others
            if chain_id == 1:
                # Get EIP-1559 gas parameters
                try:
                    latest_block = w3.eth.get_block('latest')
                    base_fee = latest_block.get('baseFeePerGas', 0)
                    max_priority_fee = w3.eth.max_priority_fee
                    max_fee = base_fee * 2 + max_priority_fee

                    tx = {
                        "from": wallet,
                        "to": to_address,
                        "data": data,
                        "value": value,
                        "gas": gas_limit,
                        "maxFeePerGas": max_fee,
                        "maxPriorityFeePerGas": max_priority_fee,
                        "nonce": nonce,
                        "chainId": chain_id,
                        "type": 2,  # EIP-1559
                    }
                except Exception as e:
                    # Fallback to legacy if EIP-1559 fails
                    logger.warning(f"EIP-1559 gas fetch failed, using legacy: {e}")
                    gas_price = w3.eth.gas_price
                    tx = {
                        "from": wallet,
                        "to": to_address,
                        "data": data,
                        "value": value,
                        "gas": gas_limit,
                        "gasPrice": gas_price,
                        "nonce": nonce,
                        "chainId": chain_id,
                    }
            else:
                # Legacy transaction for L2s
                gas_price = w3.eth.gas_price
                tx = {
                    "from": wallet,
                    "to": to_address,
                    "data": data,
                    "value": value,
                    "gas": gas_limit,
                    "gasPrice": gas_price,
                    "nonce": nonce,
                    "chainId": chain_id,
                }

            if progress_callback:
                progress_callback(f"✍️ Signing transaction...", 20, 120)

            # Sign and send
            signed_tx = w3.eth.account.sign_transaction(tx, private_key.key)

            if progress_callback:
                progress_callback(f"📤 Sending bridge transaction...", 30, 120)

            # Send with retry
            tx_hash = None
            last_error = None
            for attempt in range(3):
                try:
                    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    break
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    logger.warning(f"Send transaction attempt {attempt + 1} failed: {error_str}")

                    # Don't retry if it's a nonce or already known error
                    if "nonce" in error_str.lower() or "already known" in error_str.lower():
                        break

                    if attempt < 2:
                        import time
                        time.sleep(2)  # Wait before retry

            if tx_hash is None:
                error_msg = str(last_error) if last_error else "Failed to send transaction"
                # Make error message more user-friendly
                if "no response" in error_msg.lower() or "-32603" in error_msg:
                    error_msg = "RPC node not responding. The Ethereum network may be congested. Please try again in a few minutes."
                return BridgeResult(
                    success=False,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=native_amount,
                    error_message=error_msg
                )

            tx_hash_hex = tx_hash.hex()

            logger.info(
                "Native bridge transaction sent",
                tx_hash=tx_hash_hex,
                route=f"{source_chain.value} → {dest_chain.value}",
                amount=str(native_amount)
            )

            if progress_callback:
                progress_callback(f"⏳ Waiting for confirmation...", 40, 120)

            # Get explorer URL
            explorer_base = CHAIN_CONFIG[source_chain].get("explorer", "")
            explorer_url = f"{explorer_base}/tx/{tx_hash_hex}" if explorer_base else None

            # Wait for receipt with error handling
            # Even if this fails, the tx was already sent successfully
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

                if receipt["status"] != 1:
                    return BridgeResult(
                        success=False,
                        source_chain=source_chain,
                        dest_chain=dest_chain,
                        amount=native_amount,
                        tx_hash=tx_hash_hex,
                        explorer_url=explorer_url,
                        error_message="Transaction failed on-chain"
                    )
            except Exception as receipt_error:
                # Transaction was sent but we couldn't confirm it
                # This is still a success - user should check explorer
                logger.warning(
                    "Could not confirm transaction receipt, but tx was sent",
                    tx_hash=tx_hash_hex,
                    error=str(receipt_error)
                )
                if progress_callback:
                    progress_callback(f"✅ Transaction sent! Check explorer for confirmation.", 100, 120)

                return BridgeResult(
                    success=True,
                    source_chain=source_chain,
                    dest_chain=dest_chain,
                    amount=native_amount,
                    received_amount=quote.output_amount,
                    tx_hash=tx_hash_hex,
                    explorer_url=explorer_url,
                )

            if progress_callback:
                progress_callback(f"✅ Bridge initiated! Funds arriving on {dest_chain.value} soon.", 100, 120)

            return BridgeResult(
                success=True,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=native_amount,
                received_amount=quote.output_amount,
                tx_hash=tx_hash_hex,
                explorer_url=explorer_url,
            )

        except Exception as e:
            logger.error("Native bridge execution failed", error=str(e))
            error_msg = str(e)
            # Make common errors more user-friendly
            if "too many requests" in error_msg.lower() or "rate limit" in error_msg.lower():
                error_msg = "Too many requests. Please wait a moment and try again."
            elif "insufficient funds" in error_msg.lower():
                error_msg = "Insufficient ETH balance for this bridge + gas fees."
            return BridgeResult(
                success=False,
                source_chain=source_chain,
                dest_chain=dest_chain,
                amount=native_amount,
                error_message=error_msg
            )

    def supports_swap(self, chain: BridgeChain) -> bool:
        """Check if a chain supports native → USDC swap."""
        return chain in SWAP_SUPPORTED_CHAINS

    def get_swap_quote(
        self,
        chain: BridgeChain,
        native_amount: Decimal,
        wallet_address: str,
    ) -> LiFiBridgeQuote:
        """
        Get quote for swapping native token to USDC on the same chain.

        Args:
            chain: Chain to swap on
            native_amount: Amount of native token (in whole units, e.g., 0.5 ETH)
            wallet_address: User's wallet address
        """
        import httpx

        if chain not in SWAP_SUPPORTED_CHAINS:
            return LiFiBridgeQuote(
                input_amount=native_amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                estimated_time_seconds=0,
                tool_name="",
                error=f"Swap not supported on {chain.value}"
            )

        try:
            chain_id = LIFI_CHAIN_IDS[chain]
            amount_raw = int(native_amount * Decimal(10**18))  # Native tokens have 18 decimals

            # Get USDC address for output
            to_token = LIFI_USDC.get(chain)
            if not to_token:
                return LiFiBridgeQuote(
                    input_amount=native_amount,
                    output_amount=Decimal(0),
                    fee_amount=Decimal(0),
                    fee_percent=0,
                    estimated_time_seconds=0,
                    tool_name="",
                    error=f"USDC not configured for {chain.value}"
                )

            # Use BSC USDT if on BSC
            to_decimals = 18 if chain == BridgeChain.BSC else 6
            if chain == BridgeChain.BSC:
                to_token = LIFI_USDT_BSC

            url = "https://li.quest/v1/quote"
            params = {
                "fromChain": chain_id,
                "toChain": chain_id,  # Same chain for swap
                "fromToken": NATIVE_TOKEN,
                "toToken": to_token,
                "fromAmount": str(amount_raw),
                "fromAddress": wallet_address,
                "toAddress": wallet_address,
                "slippage": "0.005",  # 0.5% slippage for same-chain swap
            }

            headers = {}
            if settings.lifi_api_key:
                headers["x-lifi-api-key"] = settings.lifi_api_key

            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params, headers=headers)

                if resp.status_code != 200:
                    try:
                        error_data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                        error_msg = error_data.get("message", resp.text[:200])
                    except Exception:
                        error_msg = resp.text[:200]
                    return LiFiBridgeQuote(
                        input_amount=native_amount,
                        output_amount=Decimal(0),
                        fee_amount=Decimal(0),
                        fee_percent=0,
                        estimated_time_seconds=0,
                        tool_name="",
                        error=f"Quote failed: {error_msg}"
                    )

                data = resp.json()
                estimate = data.get("estimate", {})
                to_amount_raw = int(estimate.get("toAmount", "0"))
                output_amount = Decimal(to_amount_raw) / Decimal(10**to_decimals)

                # Calculate fees
                fee_costs = estimate.get("feeCosts", [])
                gas_costs = estimate.get("gasCosts", [])
                total_fee_usd = Decimal(0)
                for fee in fee_costs:
                    total_fee_usd += Decimal(str(fee.get("amountUSD", "0")))
                for gas in gas_costs:
                    total_fee_usd += Decimal(str(gas.get("amountUSD", "0")))

                tool_name = data.get("toolDetails", {}).get("name", "DEX")
                execution_duration = estimate.get("executionDuration", 30)

                native_symbol = NATIVE_TOKEN_SYMBOLS.get(chain, "TOKEN")
                out_symbol = "USDT" if chain == BridgeChain.BSC else "USDC"

                logger.info(
                    "Swap quote received",
                    tool=tool_name,
                    input=f"{native_amount} {native_symbol}",
                    output=f"{output_amount} {out_symbol}",
                    chain=chain.value
                )

                return LiFiBridgeQuote(
                    input_amount=native_amount,
                    output_amount=output_amount,
                    fee_amount=total_fee_usd,
                    fee_percent=float(total_fee_usd / output_amount * 100) if output_amount > 0 else 0,
                    estimated_time_seconds=execution_duration,
                    tool_name=tool_name,
                    quote_data=data,
                )

        except Exception as e:
            logger.error("Failed to get swap quote", error=str(e))
            return LiFiBridgeQuote(
                input_amount=native_amount,
                output_amount=Decimal(0),
                fee_amount=Decimal(0),
                fee_percent=0,
                estimated_time_seconds=0,
                tool_name="",
                error=str(e)
            )

    def execute_swap(
        self,
        private_key: LocalAccount,
        chain: BridgeChain,
        native_amount: Decimal,
        progress_callback: ProgressCallback = None,
    ) -> BridgeResult:
        """
        Execute a native token → USDC swap on the same chain.

        Args:
            private_key: EVM account for signing
            chain: Chain to swap on
            native_amount: Amount of native token to swap
            progress_callback: Optional progress callback
        """
        import httpx

        if chain not in self._web3_clients:
            return BridgeResult(
                success=False,
                source_chain=chain,
                dest_chain=chain,
                amount=native_amount,
                error_message=f"Chain {chain.value} not configured"
            )

        try:
            w3 = self._web3_clients[chain]
            wallet = Web3.to_checksum_address(private_key.address)

            if progress_callback:
                progress_callback("💱 Getting swap quote...", 0, 60)

            # Get quote
            quote = self.get_swap_quote(chain, native_amount, wallet)
            if quote.error:
                return BridgeResult(
                    success=False,
                    source_chain=chain,
                    dest_chain=chain,
                    amount=native_amount,
                    error_message=quote.error
                )

            if not quote.quote_data:
                return BridgeResult(
                    success=False,
                    source_chain=chain,
                    dest_chain=chain,
                    amount=native_amount,
                    error_message="No quote data received"
                )

            if progress_callback:
                native_symbol = NATIVE_TOKEN_SYMBOLS.get(chain, "TOKEN")
                progress_callback(f"📋 Swapping {native_amount} {native_symbol} → USDC", 10, 60)

            # Extract transaction data
            tx_request = quote.quote_data.get("transactionRequest", {})
            if not tx_request:
                return BridgeResult(
                    success=False,
                    source_chain=chain,
                    dest_chain=chain,
                    amount=native_amount,
                    error_message="No transaction data in quote"
                )

            # Build and sign transaction
            nonce = w3.eth.get_transaction_count(wallet, 'pending')
            gas_price = int(w3.eth.gas_price * 1.2)

            tx = {
                "from": wallet,
                "to": Web3.to_checksum_address(tx_request.get("to")),
                "value": int(tx_request.get("value", "0"), 16) if isinstance(tx_request.get("value"), str) else int(tx_request.get("value", 0)),
                "data": tx_request.get("data"),
                "nonce": nonce,
                "gasPrice": gas_price,
                "chainId": LIFI_CHAIN_IDS[chain],
            }

            # Estimate gas
            try:
                gas_estimate = w3.eth.estimate_gas(tx)
                tx["gas"] = int(gas_estimate * 1.3)
            except Exception as e:
                logger.warning("Gas estimation failed, using default", error=str(e))
                tx["gas"] = 300000

            if progress_callback:
                progress_callback("✍️ Signing transaction...", 20, 60)

            signed_tx = w3.eth.account.sign_transaction(tx, private_key.key)

            if progress_callback:
                progress_callback("🚀 Executing swap...", 30, 60)

            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            logger.info("Swap transaction sent", tx_hash=tx_hash_hex, chain=chain.value)

            if progress_callback:
                progress_callback("⏳ Waiting for confirmation...", 45, 60)

            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt["status"] != 1:
                return BridgeResult(
                    success=False,
                    source_chain=chain,
                    dest_chain=chain,
                    amount=native_amount,
                    burn_tx_hash=tx_hash_hex,
                    error_message="Swap transaction failed"
                )

            if progress_callback:
                progress_callback("✅ Swap complete!", 60, 60)

            return BridgeResult(
                success=True,
                source_chain=chain,
                dest_chain=chain,
                amount=quote.output_amount,
                burn_tx_hash=tx_hash_hex,
            )

        except Exception as e:
            error_msg = str(e) if str(e) else type(e).__name__
            logger.error(f"Swap failed: {error_msg}")
            return BridgeResult(
                success=False,
                source_chain=chain,
                dest_chain=chain,
                amount=native_amount,
                error_message=error_msg
            )


# Singleton instance
bridge_service = BridgeService()
