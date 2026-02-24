"""
Privy server-wallet REST API client.

Handles user creation, HD wallet provisioning, and remote signing
via Privy's TEE-backed infrastructure. Spredd never touches raw private keys.

Docs: https://docs.privy.io/guide/server-wallets
"""

import hashlib
import json
import time
from typing import Any, Optional

import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Privy API version header
PRIVY_API_VERSION = "2025-01-01"


def _load_p256_private_key(pem_or_hex: str) -> ec.EllipticCurvePrivateKey:
    """Load a P-256 private key from PEM string or hex-encoded raw key."""
    pem_or_hex = pem_or_hex.strip()

    if pem_or_hex.startswith("-----BEGIN"):
        return serialization.load_pem_private_key(
            pem_or_hex.encode(), password=None
        )

    # Assume raw hex (32 bytes = 64 hex chars)
    raw_bytes = bytes.fromhex(pem_or_hex)
    return ec.derive_private_key(
        int.from_bytes(raw_bytes, "big"),
        ec.SECP256R1(),
    )


def _build_authorization_signature(
    signing_key: ec.EllipticCurvePrivateKey,
    url: str,
    body: Optional[dict],
) -> dict[str, str]:
    """Build Privy authorization headers with P-256 ECDSA signature.

    Returns dict with privy-authorization-signature and related headers.
    Follows: https://docs.privy.io/guide/server-wallets/authorization/signatures
    """
    timestamp = int(time.time())

    # Build the payload to sign: SHA-256(timestamp.url.body_json)
    body_json = json.dumps(body, separators=(",", ":"), sort_keys=True) if body else ""
    payload = f"{timestamp}.{url}.{body_json}"
    payload_hash = hashlib.sha256(payload.encode()).digest()

    # Sign with P-256
    der_sig = signing_key.sign(payload_hash, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_sig)

    # Encode as r:s hex
    sig_hex = f"{r:064x}:{s:064x}"

    return {
        "privy-authorization-signature": f"v1:{timestamp}:{sig_hex}",
    }


class PrivyClient:
    """Async HTTP client for Privy server-wallet API."""

    BASE_URL = "https://api.privy.io/v1"

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        signing_key_pem: Optional[str] = None,
    ):
        self._app_id = app_id or settings.privy_app_id
        self._app_secret = app_secret or settings.privy_app_secret
        self._signing_key: Optional[ec.EllipticCurvePrivateKey] = None

        raw_key = signing_key_pem or settings.privy_signing_key
        if raw_key:
            self._signing_key = _load_p256_private_key(raw_key)

        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.BASE_URL,
                timeout=30.0,
                auth=(self._app_id, self._app_secret),
                headers={
                    "privy-app-id": self._app_id,
                    "Content-Type": "application/json",
                },
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to Privy API."""
        client = await self._get_client()
        url = f"{self.BASE_URL}{path}"

        headers: dict[str, str] = {}

        # Add authorization signature if signing key is configured
        if self._signing_key:
            headers.update(
                _build_authorization_signature(self._signing_key, url, body)
            )

        response = await client.request(
            method,
            path,
            json=body,
            headers=headers,
        )

        if response.status_code >= 400:
            logger.error(
                "Privy API error",
                status=response.status_code,
                path=path,
                body=response.text[:500],
            )
            response.raise_for_status()

        return response.json()

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------

    async def create_user(self, telegram_id: int) -> str:
        """Create a Privy user linked to a Telegram account.

        Returns the Privy user ID (e.g. "did:privy:...").
        """
        data = await self._request("POST", "/users", body={
            "create_linked_accounts": [
                {
                    "type": "telegram",
                    "telegram_user_id": str(telegram_id),
                }
            ]
        })
        privy_user_id = data.get("id") or data.get("user_id")
        logger.info(
            "Created Privy user",
            telegram_id=telegram_id,
            privy_user_id=privy_user_id,
        )
        return privy_user_id

    async def get_user(self, privy_user_id: str) -> dict[str, Any]:
        """Get Privy user details."""
        return await self._request("GET", f"/users/{privy_user_id}")

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
        data = await self._request("POST", "/wallets", body={
            "user_id": privy_user_id,
            "chain_type": chain_type,
        })
        wallet_id = data.get("id")
        address = data.get("address")
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
            "chain_type": data.get("chain_type", chain_type),
        }

    async def get_user_wallets(self, privy_user_id: str) -> list[dict[str, Any]]:
        """List all wallets for a Privy user."""
        data = await self._request("GET", f"/users/{privy_user_id}/wallets")
        return data.get("wallets", data if isinstance(data, list) else [])

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
        data = await self._request("POST", f"/wallets/{wallet_id}/rpc", body={
            "method": "personal_sign",
            "params": {
                "message": message,
            },
        })
        return data.get("data", {}).get("signature", data.get("signature", ""))

    async def sign_typed_data(
        self,
        wallet_id: str,
        domain: dict,
        types: dict,
        primary_type: str,
        message: dict,
    ) -> str:
        """Sign EIP-712 typed data.

        Args:
            wallet_id: Privy wallet ID.
            domain: EIP-712 domain separator.
            types: Type definitions.
            primary_type: The primary type name.
            message: The structured data to sign.

        Returns:
            Signature hex string (0x-prefixed).
        """
        data = await self._request("POST", f"/wallets/{wallet_id}/rpc", body={
            "method": "eth_signTypedData_v4",
            "params": {
                "typed_data": {
                    "domain": domain,
                    "types": types,
                    "primaryType": primary_type,
                    "message": message,
                },
            },
        })
        return data.get("data", {}).get("signature", data.get("signature", ""))

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
        data = await self._request("POST", f"/wallets/{wallet_id}/rpc", body={
            "method": "eth_signTransaction",
            "params": {
                "transaction": transaction,
            },
        })
        return data.get("data", {}).get("signed_transaction", data.get("signed_transaction", ""))

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
        data = await self._request("POST", f"/wallets/{wallet_id}/rpc", body={
            "method": "solana_signTransaction",
            "params": {
                "transaction": transaction_b64,
            },
        })
        return data.get("data", {}).get("signed_transaction", data.get("signed_transaction", ""))


# Singleton
privy_client = PrivyClient()
