"""
Privy server-wallet client using the official privy-client SDK.

Handles user creation, HD wallet provisioning, and remote signing
via Privy's TEE-backed infrastructure. Spredd never touches raw private keys.

Docs: https://docs.privy.io/basics/python/quickstart
"""

import os
from typing import Any, Optional

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# CAIP-2 chain identifiers for Privy RPC calls
_EVM_DEFAULT_CAIP2 = "eip155:1"
_SOLANA_MAINNET_CAIP2 = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

# Map numeric chain IDs to CAIP-2
_CHAIN_ID_TO_CAIP2 = {
    1: "eip155:1",         # Ethereum
    10: "eip155:10",       # Optimism
    56: "eip155:56",       # BSC
    137: "eip155:137",     # Polygon
    2741: "eip155:2741",   # Abstract
    8453: "eip155:8453",   # Base
    42161: "eip155:42161", # Arbitrum
    59144: "eip155:59144", # Linea
    10143: "eip155:10143", # Monad
}


def _chain_id_to_caip2(chain_id: Any) -> str:
    """Convert a numeric or hex chain ID to a CAIP-2 identifier."""
    if chain_id is None:
        return _EVM_DEFAULT_CAIP2
    if isinstance(chain_id, str):
        if chain_id.startswith("0x"):
            chain_id = int(chain_id, 16)
        else:
            chain_id = int(chain_id)
    return _CHAIN_ID_TO_CAIP2.get(int(chain_id), f"eip155:{int(chain_id)}")


class PrivyClient:
    """Async wrapper around the official Privy SDK (AsyncPrivyAPI).

    Maintains the same external method signatures as the previous custom
    implementation so that signer.py, wallet.py, and commands.py work
    without changes.
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        signing_key_pem: Optional[str] = None,
    ):
        # Read from args, then pydantic settings, then env vars directly
        # (env var fallback handles cases where pydantic-settings fails to parse)
        self._app_id = (
            app_id
            or settings.privy_app_id
            or os.environ.get("PRIVY_APP_ID")
        )
        self._app_secret = (
            app_secret
            or settings.privy_app_secret
            or os.environ.get("PRIVY_APP_SECRET")
        )
        self._signing_key_raw = (
            signing_key_pem
            or settings.privy_signing_key
            or os.environ.get("PRIVY_SIGNING_KEY")
        )

        if not self._app_id or not self._app_secret:
            logger.warning(
                "Privy app credentials missing — PRIVY_APP_ID and PRIVY_APP_SECRET required",
                has_app_id=bool(self._app_id),
                has_app_secret=bool(self._app_secret),
            )

        self._client = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _get_client(self):
        """Lazily initialize the AsyncPrivyAPI client."""
        if self._client is None:
            if not self._app_id or not self._app_secret:
                raise RuntimeError(
                    f"Privy not configured: app_id={'set' if self._app_id else 'MISSING'}, "
                    f"app_secret={'set' if self._app_secret else 'MISSING'}"
                )

            from privy import AsyncPrivyAPI

            self._client = AsyncPrivyAPI(
                app_id=self._app_id,
                app_secret=self._app_secret,
            )

            # Register the authorization signing key for wallet operations
            if self._signing_key_raw:
                self._client.update_authorization_key(self._signing_key_raw)
                logger.info("Privy authorization key configured")

            logger.info(
                "Privy SDK client initialized",
                app_id_prefix=self._app_id[:8] + "..." if self._app_id else None,
            )

        return self._client

    async def close(self) -> None:
        """Close the underlying SDK client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    async def create_user(self, telegram_id: int) -> str:
        """Create a Privy user linked to a Telegram account.

        Returns the Privy user ID (e.g. "did:privy:...").
        """
        client = self._get_client()
        user = await client.users.create(
            linked_accounts=[
                {
                    "type": "telegram",
                    "telegram_user_id": str(telegram_id),
                }
            ]
        )
        privy_user_id = user.id
        logger.info(
            "Created Privy user",
            telegram_id=telegram_id,
            privy_user_id=privy_user_id,
        )
        return privy_user_id

    async def get_user(self, privy_user_id: str) -> dict[str, Any]:
        """Get Privy user details."""
        client = self._get_client()
        user = await client.users.get(user_id=privy_user_id)
        # Return as dict for backward compatibility
        return user.model_dump() if hasattr(user, "model_dump") else vars(user)

    # ------------------------------------------------------------------
    # Wallet management
    # ------------------------------------------------------------------

    async def create_wallet(
        self,
        privy_user_id: str,
        chain_type: str = "ethereum",
    ) -> dict[str, Any]:
        """Create an HD wallet for a Privy user.

        Args:
            privy_user_id: The Privy user ID (did:privy:...).
            chain_type: "ethereum" or "solana".

        Returns:
            Dict with keys: id, address, chain_type.
        """
        client = self._get_client()
        wallet = await client.wallets.create(
            chain_type=chain_type,
            owner={"user_id": privy_user_id},
        )
        wallet_id = wallet.id
        address = wallet.address
        logger.info(
            "Created Privy wallet",
            privy_user_id=privy_user_id,
            chain_type=chain_type,
            wallet_id=wallet_id,
            address=address[:10] + "..." if address else None,
        )
        return {
            "id": wallet_id,
            "address": address,
            "chain_type": getattr(wallet, "chain_type", chain_type),
        }

    async def get_user_wallets(self, privy_user_id: str) -> list[dict[str, Any]]:
        """List all wallets for a Privy user."""
        client = self._get_client()
        result = await client.wallets.list(user_id=privy_user_id)
        wallets = result.data if hasattr(result, "data") else result
        return [
            {
                "id": w.id,
                "address": w.address,
                "chain_type": getattr(w, "chain_type", None),
            }
            for w in wallets
        ]

    # ------------------------------------------------------------------
    # Signing — EVM
    # ------------------------------------------------------------------

    async def sign_message(self, wallet_id: str, message: str) -> str:
        """Sign an arbitrary message (personal_sign).

        Args:
            wallet_id: Privy wallet ID.
            message: Hex-encoded message (0x-prefixed).

        Returns:
            Signature hex string (0x-prefixed).
        """
        client = self._get_client()
        result = await client.wallets.rpc(
            wallet_id=wallet_id,
            method="personal_sign",
            caip2=_EVM_DEFAULT_CAIP2,
            params={
                "message": message,
                "encoding": "utf-8",
            },
        )
        return result.data.signature

    async def sign_typed_data(
        self,
        wallet_id: str,
        domain: dict,
        types: dict,
        primary_type: str,
        message: dict,
    ) -> str:
        """Sign EIP-712 typed data.

        Returns:
            Signature hex string (0x-prefixed).
        """
        client = self._get_client()

        # Extract chain ID from domain for CAIP-2
        chain_id = domain.get("chainId")
        caip2 = _chain_id_to_caip2(chain_id)

        result = await client.wallets.rpc(
            wallet_id=wallet_id,
            method="eth_signTypedData_v4",
            caip2=caip2,
            params={
                "typed_data": {
                    "domain": domain,
                    "types": types,
                    "primaryType": primary_type,
                    "message": message,
                },
            },
        )
        return result.data.signature

    async def sign_transaction(
        self,
        wallet_id: str,
        transaction: dict,
    ) -> str:
        """Sign an EVM transaction.

        Args:
            wallet_id: Privy wallet ID.
            transaction: Transaction dict with to, value, data, chainId, etc.

        Returns:
            Signed transaction hex (ready for broadcast).
        """
        client = self._get_client()

        # Extract chain ID for CAIP-2
        chain_id = transaction.get("chainId") or transaction.get("chain_id")
        caip2 = _chain_id_to_caip2(chain_id)

        result = await client.wallets.rpc(
            wallet_id=wallet_id,
            method="eth_signTransaction",
            caip2=caip2,
            params={
                "transaction": transaction,
            },
        )
        return result.data.signed_transaction

    # ------------------------------------------------------------------
    # Signing — Solana
    # ------------------------------------------------------------------

    async def sign_solana_transaction(
        self,
        wallet_id: str,
        transaction_b64: str,
    ) -> str:
        """Sign a Solana transaction.

        Args:
            wallet_id: Privy wallet ID.
            transaction_b64: Base64-encoded serialized transaction.

        Returns:
            Base64-encoded signed transaction.
        """
        client = self._get_client()
        result = await client.wallets.rpc(
            wallet_id=wallet_id,
            method="signTransaction",
            caip2=_SOLANA_MAINNET_CAIP2,
            params={
                "transaction": transaction_b64,
                "encoding": "base64",
            },
        )
        return result.data.signed_transaction


# Singleton
privy_client = PrivyClient()
