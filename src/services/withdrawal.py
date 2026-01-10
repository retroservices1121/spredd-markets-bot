"""
Withdrawal service for processing referral earnings payouts.

Supports:
- EVM (Polygon): Sends USDC from treasury wallet to user's EVM wallet
- Solana: Sends USDC from treasury wallet to user's Solana wallet
"""

from decimal import Decimal
from typing import Optional, Tuple
from web3 import Web3
from eth_account import Account

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# USDC has 6 decimals on both chains
USDC_DECIMALS = 6

# Minimal ERC20 ABI for transfer
ERC20_ABI = [
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


class EVMWithdrawalService:
    """Service for processing USDC withdrawals on Polygon (EVM)."""

    def __init__(self):
        self._web3: Optional[Web3] = None
        self._account: Optional[Account] = None
        self._usdc_contract = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the EVM withdrawal service."""
        if not settings.treasury_evm_private_key:
            logger.warning("EVM treasury private key not configured - EVM withdrawals disabled")
            return False

        try:
            self._web3 = Web3(Web3.HTTPProvider(settings.treasury_evm_rpc_url))

            if not self._web3.is_connected():
                logger.error("Failed to connect to Polygon RPC")
                return False

            # Load treasury account
            private_key = settings.treasury_evm_private_key
            if not private_key.startswith("0x"):
                private_key = "0x" + private_key

            self._account = Account.from_key(private_key)

            # Load USDC contract
            self._usdc_contract = self._web3.eth.contract(
                address=Web3.to_checksum_address(settings.usdc_contract_polygon),
                abi=ERC20_ABI
            )

            self._initialized = True
            logger.info(
                "EVM withdrawal service initialized",
                treasury_address=self._account.address,
                chain="polygon",
            )
            return True

        except Exception as e:
            logger.error("Failed to initialize EVM withdrawal service", error=str(e))
            return False

    @property
    def is_available(self) -> bool:
        """Check if withdrawal service is available."""
        return self._initialized and self._account is not None

    @property
    def treasury_address(self) -> Optional[str]:
        """Get treasury wallet address."""
        return self._account.address if self._account else None

    async def get_treasury_balance(self) -> Decimal:
        """Get USDC balance of treasury wallet."""
        if not self.is_available:
            return Decimal("0")

        try:
            balance_raw = self._usdc_contract.functions.balanceOf(
                self._account.address
            ).call()
            return Decimal(balance_raw) / Decimal(10 ** USDC_DECIMALS)
        except Exception as e:
            logger.error("Failed to get treasury balance", error=str(e))
            return Decimal("0")

    async def send_usdc(
        self,
        to_address: str,
        amount_usdc: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Send USDC from treasury to user's wallet.

        Args:
            to_address: Recipient's EVM wallet address
            amount_usdc: Amount to send in USDC (as string)

        Returns:
            Tuple of (success, tx_hash, error_message)
        """
        if not self.is_available:
            return False, None, "Withdrawal service not available"

        try:
            # Validate address
            if not Web3.is_address(to_address):
                return False, None, "Invalid wallet address"

            to_address = Web3.to_checksum_address(to_address)
            amount = Decimal(amount_usdc)
            amount_raw = int(amount * Decimal(10 ** USDC_DECIMALS))

            # Check treasury balance
            balance = await self.get_treasury_balance()
            if balance < amount:
                logger.warning(
                    "Insufficient treasury balance",
                    required=str(amount),
                    available=str(balance),
                )
                return False, None, f"Insufficient treasury balance (need {amount}, have {balance})"

            # Build transaction
            nonce = self._web3.eth.get_transaction_count(self._account.address)
            gas_price = self._web3.eth.gas_price

            tx = self._usdc_contract.functions.transfer(
                to_address,
                amount_raw
            ).build_transaction({
                "from": self._account.address,
                "nonce": nonce,
                "gasPrice": gas_price,
                "gas": 100000,  # USDC transfer typically uses ~65k gas
                "chainId": 137,  # Polygon mainnet
            })

            # Sign and send
            signed_tx = self._web3.eth.account.sign_transaction(tx, self._account.key)
            tx_hash = self._web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = tx_hash.hex()

            logger.info(
                "EVM USDC withdrawal sent",
                to=to_address,
                amount=amount_usdc,
                tx_hash=tx_hash_hex,
                chain="polygon",
            )

            # Wait for confirmation (optional, can timeout)
            try:
                receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt.status == 1:
                    logger.info("EVM withdrawal confirmed", tx_hash=tx_hash_hex)
                    return True, tx_hash_hex, None
                else:
                    logger.error("EVM withdrawal failed on-chain", tx_hash=tx_hash_hex)
                    return False, tx_hash_hex, "Transaction failed on-chain"
            except Exception as wait_error:
                # Transaction sent but confirmation timed out
                logger.warning("EVM withdrawal sent but confirmation timed out", tx_hash=tx_hash_hex)
                return True, tx_hash_hex, None

        except Exception as e:
            logger.error("EVM withdrawal failed", error=str(e))
            return False, None, str(e)

    def get_explorer_url(self, tx_hash: str) -> str:
        """Get PolygonScan URL for transaction."""
        return f"https://polygonscan.com/tx/{tx_hash}"


class SolanaWithdrawalService:
    """Service for processing USDC withdrawals on Solana."""

    def __init__(self):
        self._client = None
        self._keypair = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the Solana withdrawal service."""
        if not settings.treasury_solana_private_key:
            logger.warning("Solana treasury private key not configured - Solana withdrawals disabled")
            return False

        try:
            from solana.rpc.async_api import AsyncClient as SolanaClient
            from solders.keypair import Keypair
            import base58

            self._client = SolanaClient(settings.treasury_solana_rpc_url)

            # Load treasury keypair (base58 encoded private key)
            try:
                # Try base58 decode first (standard Solana format)
                secret_key = base58.b58decode(settings.treasury_solana_private_key)
                self._keypair = Keypair.from_bytes(secret_key)
            except Exception:
                # Try as raw bytes array
                try:
                    import json
                    key_bytes = bytes(json.loads(settings.treasury_solana_private_key))
                    self._keypair = Keypair.from_bytes(key_bytes)
                except Exception as e:
                    logger.error("Failed to parse Solana treasury key", error=str(e))
                    return False

            self._initialized = True
            logger.info(
                "Solana withdrawal service initialized",
                treasury_address=str(self._keypair.pubkey()),
                chain="solana",
            )
            return True

        except Exception as e:
            logger.error("Failed to initialize Solana withdrawal service", error=str(e))
            return False

    @property
    def is_available(self) -> bool:
        """Check if Solana withdrawal service is available."""
        return self._initialized and self._keypair is not None

    @property
    def treasury_address(self) -> Optional[str]:
        """Get treasury wallet address."""
        return str(self._keypair.pubkey()) if self._keypair else None

    async def get_treasury_balance(self) -> Decimal:
        """Get USDC balance of Solana treasury wallet."""
        if not self.is_available:
            return Decimal("0")

        try:
            from solders.pubkey import Pubkey
            from spl.token.constants import TOKEN_PROGRAM_ID

            usdc_mint = Pubkey.from_string(settings.usdc_mint_solana)
            owner = self._keypair.pubkey()

            # Get associated token account
            from spl.token.async_client import AsyncToken

            token = AsyncToken(
                self._client,
                usdc_mint,
                TOKEN_PROGRAM_ID,
                self._keypair,
            )

            # Get token account balance
            try:
                ata = await token.get_accounts_by_owner(owner)
                if ata.value:
                    balance_raw = ata.value[0].account.data.parsed['info']['tokenAmount']['amount']
                    return Decimal(balance_raw) / Decimal(10 ** USDC_DECIMALS)
            except Exception:
                pass

            return Decimal("0")

        except Exception as e:
            logger.error("Failed to get Solana treasury balance", error=str(e))
            return Decimal("0")

    async def send_usdc(
        self,
        to_address: str,
        amount_usdc: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Send USDC from treasury to user's Solana wallet.

        Args:
            to_address: Recipient's Solana wallet address
            amount_usdc: Amount to send in USDC (as string)

        Returns:
            Tuple of (success, tx_hash, error_message)
        """
        if not self.is_available:
            return False, None, "Solana withdrawal service not available"

        try:
            from solders.pubkey import Pubkey
            from solders.transaction import Transaction
            from solders.system_program import TransferParams, transfer
            from spl.token.constants import TOKEN_PROGRAM_ID
            from spl.token.instructions import transfer_checked, TransferCheckedParams
            from spl.token.async_client import AsyncToken
            from solana.rpc.commitment import Confirmed

            # Validate address
            try:
                recipient = Pubkey.from_string(to_address)
            except Exception:
                return False, None, "Invalid Solana wallet address"

            amount = Decimal(amount_usdc)
            amount_raw = int(amount * Decimal(10 ** USDC_DECIMALS))

            usdc_mint = Pubkey.from_string(settings.usdc_mint_solana)

            # Get or create associated token accounts
            token = AsyncToken(
                self._client,
                usdc_mint,
                TOKEN_PROGRAM_ID,
                self._keypair,
            )

            # Get sender's token account
            sender_ata = await token.get_accounts_by_owner(self._keypair.pubkey())
            if not sender_ata.value:
                return False, None, "Treasury has no USDC token account"

            sender_token_account = sender_ata.value[0].pubkey

            # Get or create recipient's token account
            from spl.token.instructions import get_associated_token_address
            recipient_ata = get_associated_token_address(recipient, usdc_mint)

            # Check if recipient ATA exists, if not create it
            recipient_account = await self._client.get_account_info(recipient_ata)

            instructions = []

            if not recipient_account.value:
                # Create ATA for recipient
                from spl.token.instructions import create_associated_token_account
                create_ata_ix = create_associated_token_account(
                    payer=self._keypair.pubkey(),
                    owner=recipient,
                    mint=usdc_mint,
                )
                instructions.append(create_ata_ix)

            # Create transfer instruction
            transfer_ix = transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=sender_token_account,
                    mint=usdc_mint,
                    dest=recipient_ata,
                    owner=self._keypair.pubkey(),
                    amount=amount_raw,
                    decimals=USDC_DECIMALS,
                )
            )
            instructions.append(transfer_ix)

            # Build and send transaction
            recent_blockhash = await self._client.get_latest_blockhash()

            from solders.message import Message
            from solders.transaction import Transaction as SoldersTransaction

            message = Message.new_with_blockhash(
                instructions,
                self._keypair.pubkey(),
                recent_blockhash.value.blockhash,
            )
            tx = SoldersTransaction.new_unsigned(message)
            tx.sign([self._keypair], recent_blockhash.value.blockhash)

            result = await self._client.send_transaction(
                tx,
                opts={"skip_preflight": False, "preflight_commitment": Confirmed},
            )

            tx_hash = str(result.value)

            logger.info(
                "Solana USDC withdrawal sent",
                to=to_address,
                amount=amount_usdc,
                tx_hash=tx_hash,
                chain="solana",
            )

            return True, tx_hash, None

        except Exception as e:
            logger.error("Solana withdrawal failed", error=str(e))
            return False, None, str(e)

    def get_explorer_url(self, tx_hash: str) -> str:
        """Get Solscan URL for transaction."""
        return f"https://solscan.io/tx/{tx_hash}"


class WithdrawalManager:
    """Unified manager for withdrawals across all chains."""

    def __init__(self):
        self.evm = EVMWithdrawalService()
        self.solana = SolanaWithdrawalService()

    def initialize(self) -> None:
        """Initialize all withdrawal services."""
        self.evm.initialize()
        # Note: Solana service is async, will be initialized on first use

    async def initialize_async(self) -> None:
        """Initialize async services."""
        await self.solana.initialize()

    def is_available(self, chain_family: str) -> bool:
        """Check if withdrawal is available for a chain family."""
        if chain_family.lower() == "evm":
            return self.evm.is_available
        elif chain_family.lower() == "solana":
            return self.solana.is_available
        return False

    async def send_usdc(
        self,
        chain_family: str,
        to_address: str,
        amount_usdc: str,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """Send USDC on the specified chain."""
        if chain_family.lower() == "evm":
            return await self.evm.send_usdc(to_address, amount_usdc)
        elif chain_family.lower() == "solana":
            return await self.solana.send_usdc(to_address, amount_usdc)
        return False, None, f"Unknown chain family: {chain_family}"

    def get_explorer_url(self, chain_family: str, tx_hash: str) -> str:
        """Get explorer URL for a transaction."""
        if chain_family.lower() == "evm":
            return self.evm.get_explorer_url(tx_hash)
        elif chain_family.lower() == "solana":
            return self.solana.get_explorer_url(tx_hash)
        return ""


# Global instances
evm_withdrawal_service = EVMWithdrawalService()
solana_withdrawal_service = SolanaWithdrawalService()
withdrawal_manager = WithdrawalManager()

# Legacy alias for backwards compatibility
withdrawal_service = evm_withdrawal_service
