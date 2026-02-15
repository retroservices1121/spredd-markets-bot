"""
DFlow Proof KYC verification utilities.

Proof is DFlow's identity verification layer required for Kalshi trading.
API docs: https://proof.dflow.net
"""

import time
from urllib.parse import urlencode

import base58
import httpx
from solders.keypair import Keypair as SolanaKeypair

from src.utils.logging import get_logger

logger = get_logger(__name__)

PROOF_API_BASE = "https://proof.dflow.net"
PROOF_DEEP_LINK_BASE = "https://dflow.net/proof"


async def check_proof_verified(solana_address: str) -> bool:
    """Check if a Solana wallet is DFlow Proof KYC verified.

    Args:
        solana_address: Solana public key (base58)

    Returns:
        True if verified, False otherwise (including on errors)
    """
    url = f"{PROOF_API_BASE}/verify/{solana_address}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            verified = data.get("verified", False)
            logger.info("Proof KYC check", address=solana_address[:8], verified=verified)
            return verified
    except Exception as e:
        logger.error("Proof KYC check failed", address=solana_address[:8], error=str(e))
        return False


def generate_proof_deep_link(keypair: SolanaKeypair, bot_username: str) -> str:
    """Generate DFlow Proof KYC deep link with pre-signed wallet ownership proof.

    Args:
        keypair: Solana keypair for signing ownership proof
        bot_username: Telegram bot username for redirect after KYC

    Returns:
        Deep link URL for Proof KYC verification
    """
    pubkey = str(keypair.pubkey())
    timestamp = int(time.time() * 1000)
    message = f"Proof KYC verification: {timestamp}"
    signature = keypair.sign_message(message.encode())
    sig_b58 = base58.b58encode(bytes(signature)).decode()
    redirect_uri = f"https://t.me/{bot_username}"

    params = urlencode({
        "wallet": pubkey,
        "signature": sig_b58,
        "timestamp": str(timestamp),
        "redirect_uri": redirect_uri,
    })
    return f"{PROOF_DEEP_LINK_BASE}?{params}"
