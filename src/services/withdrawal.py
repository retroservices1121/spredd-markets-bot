"""
Withdrawal service for processing referral earnings payouts.

Sends USDC from treasury wallet to user's wallet on Polygon.
"""

from decimal import Decimal
from typing import Optional, Tuple
from web3 import Web3
from eth_account import Account

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# USDC has 6 decimals
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


class WithdrawalService:
    """Service for processing USDC withdrawals on Polygon."""

    def __init__(self):
        self._web3: Optional[Web3] = None
        self._account: Optional[Account] = None
        self._usdc_contract = None
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the withdrawal service."""
        if not settings.treasury_private_key:
            logger.warning("Treasury private key not configured - withdrawals disabled")
            return False

        try:
            self._web3 = Web3(Web3.HTTPProvider(settings.treasury_rpc_url))

            if not self._web3.is_connected():
                logger.error("Failed to connect to Polygon RPC")
                return False

            # Load treasury account
            private_key = settings.treasury_private_key
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
                "Withdrawal service initialized",
                treasury_address=self._account.address,
                chain="polygon",
            )
            return True

        except Exception as e:
            logger.error("Failed to initialize withdrawal service", error=str(e))
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
                "USDC withdrawal sent",
                to=to_address,
                amount=amount_usdc,
                tx_hash=tx_hash_hex,
            )

            # Wait for confirmation (optional, can timeout)
            try:
                receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
                if receipt.status == 1:
                    logger.info("Withdrawal confirmed", tx_hash=tx_hash_hex)
                    return True, tx_hash_hex, None
                else:
                    logger.error("Withdrawal failed on-chain", tx_hash=tx_hash_hex)
                    return False, tx_hash_hex, "Transaction failed on-chain"
            except Exception as wait_error:
                # Transaction sent but confirmation timed out
                logger.warning("Withdrawal sent but confirmation timed out", tx_hash=tx_hash_hex)
                return True, tx_hash_hex, None

        except Exception as e:
            logger.error("Withdrawal failed", error=str(e))
            return False, None, str(e)


# Global instance
withdrawal_service = WithdrawalService()
