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
    """Supported chains for CCTP bridging."""
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    BASE = "base"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    AVALANCHE = "avalanche"


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


# Chain ID mapping for Relay
RELAY_CHAIN_IDS = {
    BridgeChain.ETHEREUM: 1,
    BridgeChain.POLYGON: 137,
    BridgeChain.BASE: 8453,
    BridgeChain.ARBITRUM: 42161,
    BridgeChain.OPTIMISM: 10,
}

# USDC addresses for Relay
RELAY_USDC = {
    BridgeChain.ETHEREUM: "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    BridgeChain.POLYGON: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    BridgeChain.BASE: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    BridgeChain.ARBITRUM: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    BridgeChain.OPTIMISM: "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",
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

            # USDC has 6 decimals
            return Decimal(balance_raw) / Decimal(10 ** 6)

        except Exception as e:
            logger.warning(f"Failed to get balance on {chain.value}", error=str(e))
            return Decimal(0)

    def get_all_usdc_balances(self, wallet_address: str) -> dict[BridgeChain, Decimal]:
        """Get USDC balances across all supported chains."""
        balances = {}
        for chain in self._web3_clients.keys():
            balances[chain] = self.get_usdc_balance(chain, wallet_address)
        return balances

    def find_chain_with_balance(
        self,
        wallet_address: str,
        required_amount: Decimal,
        exclude_chain: Optional[BridgeChain] = None,
    ) -> Optional[Tuple[BridgeChain, Decimal]]:
        """
        Find a chain that has sufficient USDC balance.

        Args:
            wallet_address: User's wallet address
            required_amount: Amount of USDC needed
            exclude_chain: Chain to exclude (usually the destination chain)

        Returns:
            Tuple of (chain, balance) if found, None otherwise
        """
        balances = self.get_all_usdc_balances(wallet_address)

        for chain, balance in balances.items():
            if chain == exclude_chain:
                continue
            if balance >= required_amount:
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

                    # Build transaction
                    nonce = source_w3.eth.get_transaction_count(wallet, 'pending')
                    gas_price = int(source_w3.eth.gas_price * 1.5)

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
                    tx_hash = source_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                    tx_hash_hex = tx_hash.hex()

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


# Singleton instance
bridge_service = BridgeService()
