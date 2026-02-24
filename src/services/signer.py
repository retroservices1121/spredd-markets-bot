"""
Signer abstraction layer for Spredd.

Provides a unified signing interface that works with both:
- Legacy wallets (local private keys via eth_account / solders)
- Privy wallets (remote signing via Privy API)

All platform code should use these signers instead of raw private keys.
"""

import base64
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Abstract Signers
# =============================================================================


class EVMSigner(ABC):
    """Abstract EVM signer — signs transactions and typed data."""

    @property
    @abstractmethod
    def address(self) -> str:
        """Checksummed EVM address."""
        ...

    @abstractmethod
    async def sign_message(self, message: bytes) -> str:
        """Sign an arbitrary message (personal_sign).

        Args:
            message: Raw message bytes.

        Returns:
            Signature hex string (0x-prefixed).
        """
        ...

    @abstractmethod
    async def sign_typed_data(
        self,
        domain: dict,
        types: dict,
        primary_type: str,
        message: dict,
    ) -> str:
        """Sign EIP-712 typed data.

        Returns:
            Signature hex string (0x-prefixed).
        """
        ...

    @abstractmethod
    async def sign_transaction(self, tx: dict) -> bytes:
        """Sign an EVM transaction.

        Args:
            tx: Transaction dict (to, value, data, gas, gasPrice, nonce, chainId).

        Returns:
            Signed raw transaction bytes (ready for send_raw_transaction).
        """
        ...

    @abstractmethod
    async def sign_and_send_transaction(self, tx: dict, web3: Any) -> str:
        """Sign a transaction and broadcast it.

        Args:
            tx: Transaction dict.
            web3: Web3 instance for broadcasting.

        Returns:
            Transaction hash hex string.
        """
        ...


class SolanaSigner(ABC):
    """Abstract Solana signer — signs transactions."""

    @property
    @abstractmethod
    def public_key(self) -> str:
        """Solana public key (base58)."""
        ...

    @abstractmethod
    async def sign_transaction(self, tx_bytes: bytes) -> bytes:
        """Sign a serialized Solana transaction.

        Args:
            tx_bytes: Serialized unsigned/partially-signed transaction.

        Returns:
            Serialized signed transaction bytes.
        """
        ...


# =============================================================================
# Legacy Signers (local private keys)
# =============================================================================


class LegacyEVMSigner(EVMSigner):
    """EVM signer backed by a local eth_account.LocalAccount."""

    def __init__(self, account: Any):
        """
        Args:
            account: eth_account.signers.local.LocalAccount instance.
        """
        self._account = account

    @property
    def address(self) -> str:
        return self._account.address

    @property
    def local_account(self) -> Any:
        """Access the underlying LocalAccount (needed for ClobClient compatibility)."""
        return self._account

    async def sign_message(self, message: bytes) -> str:
        from eth_account.messages import encode_defunct
        msg = encode_defunct(primitive=message)
        signed = self._account.sign_message(msg)
        return signed.signature.hex()

    async def sign_typed_data(
        self,
        domain: dict,
        types: dict,
        primary_type: str,
        message: dict,
    ) -> str:
        from eth_account import Account
        signed = Account.sign_typed_data(
            self._account.key,
            domain_data=domain,
            message_types=types,
            message_data=message,
        )
        return signed.signature.hex()

    async def sign_transaction(self, tx: dict) -> bytes:
        signed = self._account.sign_transaction(tx)
        return signed.raw_transaction

    async def sign_and_send_transaction(self, tx: dict, web3: Any) -> str:
        import asyncio
        signed = self._account.sign_transaction(tx)
        # Support both sync and async web3
        if hasattr(web3.eth, 'send_raw_transaction'):
            try:
                result = web3.eth.send_raw_transaction(signed.raw_transaction)
            except TypeError:
                # Async web3
                result = await web3.eth.send_raw_transaction(signed.raw_transaction)
        else:
            result = web3.eth.send_raw_transaction(signed.raw_transaction)
        return result.hex() if hasattr(result, 'hex') else str(result)


class LegacySolanaSigner(SolanaSigner):
    """Solana signer backed by a local solders.Keypair."""

    def __init__(self, keypair: Any):
        """
        Args:
            keypair: solders.keypair.Keypair instance.
        """
        self._keypair = keypair

    @property
    def public_key(self) -> str:
        return str(self._keypair.pubkey())

    @property
    def keypair(self) -> Any:
        """Access the underlying Keypair (needed for VersionedTransaction signing)."""
        return self._keypair

    async def sign_transaction(self, tx_bytes: bytes) -> bytes:
        from solders.transaction import VersionedTransaction
        from solders.signature import Signature
        from solders.presigner import Presigner

        tx = VersionedTransaction.from_bytes(tx_bytes)
        num_required = tx.message.header.num_required_signatures
        account_keys = tx.message.account_keys

        signers = [self._keypair]
        for i in range(num_required):
            pubkey = account_keys[i]
            if pubkey == self._keypair.pubkey():
                continue
            existing_sig = tx.signatures[i]
            if existing_sig != Signature.default():
                signers.append(Presigner(pubkey, existing_sig))

        signed_tx = VersionedTransaction(tx.message, signers)
        return bytes(signed_tx)


# =============================================================================
# Privy Signers (remote signing via Privy API)
# =============================================================================


class PrivyEVMSigner(EVMSigner):
    """EVM signer backed by Privy server-wallet API."""

    def __init__(self, wallet_id: str, wallet_address: str, privy_client: Any):
        """
        Args:
            wallet_id: Privy wallet ID.
            wallet_address: Checksummed EVM address.
            privy_client: PrivyClient instance.
        """
        self._wallet_id = wallet_id
        self._address = wallet_address
        self._privy = privy_client

    @property
    def address(self) -> str:
        return self._address

    @property
    def wallet_id(self) -> str:
        return self._wallet_id

    async def sign_message(self, message: bytes) -> str:
        msg_hex = "0x" + message.hex()
        return await self._privy.sign_message(self._wallet_id, msg_hex)

    async def sign_typed_data(
        self,
        domain: dict,
        types: dict,
        primary_type: str,
        message: dict,
    ) -> str:
        return await self._privy.sign_typed_data(
            self._wallet_id, domain, types, primary_type, message,
        )

    async def sign_transaction(self, tx: dict) -> bytes:
        # Privy returns hex-encoded signed transaction
        signed_hex = await self._privy.sign_transaction(self._wallet_id, tx)
        if signed_hex.startswith("0x"):
            signed_hex = signed_hex[2:]
        return bytes.fromhex(signed_hex)

    async def sign_and_send_transaction(self, tx: dict, web3: Any) -> str:
        signed_raw = await self.sign_transaction(tx)
        try:
            result = web3.eth.send_raw_transaction(signed_raw)
        except TypeError:
            result = await web3.eth.send_raw_transaction(signed_raw)
        return result.hex() if hasattr(result, 'hex') else str(result)


class PrivySolanaSigner(SolanaSigner):
    """Solana signer backed by Privy server-wallet API."""

    def __init__(self, wallet_id: str, wallet_address: str, privy_client: Any):
        """
        Args:
            wallet_id: Privy wallet ID.
            wallet_address: Solana public key (base58).
            privy_client: PrivyClient instance.
        """
        self._wallet_id = wallet_id
        self._address = wallet_address
        self._privy = privy_client

    @property
    def public_key(self) -> str:
        return self._address

    @property
    def wallet_id(self) -> str:
        return self._wallet_id

    async def sign_transaction(self, tx_bytes: bytes) -> bytes:
        tx_b64 = base64.b64encode(tx_bytes).decode()
        signed_b64 = await self._privy.sign_solana_transaction(
            self._wallet_id, tx_b64,
        )
        return base64.b64decode(signed_b64)
