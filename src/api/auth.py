"""
Authentication utilities for Spredd API.
Supports Telegram Mini App initData and EVM wallet signature auth.
"""

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

from eth_account.messages import encode_defunct
from web3 import Web3
from pydantic import BaseModel


class TelegramUser(BaseModel):
    """Telegram user data from Mini App."""
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    language_code: Optional[str] = None


class AuthData(BaseModel):
    """Authenticated request data."""
    user: TelegramUser
    auth_date: int
    hash: str


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> Optional[AuthData]:
    """
    Validate Telegram Mini App initData.

    Args:
        init_data: The initData string from Telegram WebApp
        bot_token: The bot token for validation
        max_age_seconds: Maximum age of auth data (default 24 hours)

    Returns:
        AuthData if valid, None otherwise
    """
    try:
        # Parse the init data
        parsed = parse_qs(init_data)

        # Extract hash
        received_hash = parsed.get("hash", [None])[0]
        if not received_hash:
            return None

        # Build data check string (sorted alphabetically, excluding hash)
        data_check_parts = []
        for key in sorted(parsed.keys()):
            if key != "hash":
                value = parsed[key][0]
                data_check_parts.append(f"{key}={value}")

        data_check_string = "\n".join(data_check_parts)

        # Calculate secret key
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()

        # Calculate hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        # Verify hash
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # Check auth_date
        auth_date_str = parsed.get("auth_date", [None])[0]
        if not auth_date_str:
            return None

        auth_date = int(auth_date_str)
        if time.time() - auth_date > max_age_seconds:
            return None

        # Parse user data
        user_str = parsed.get("user", [None])[0]
        if not user_str:
            return None

        user_data = json.loads(unquote(user_str))
        user = TelegramUser(**user_data)

        return AuthData(
            user=user,
            auth_date=auth_date,
            hash=received_hash
        )

    except Exception as e:
        print(f"Error validating init data: {e}")
        return None


def validate_telegram_login(data: dict, bot_token: str, max_age_seconds: int = 86400) -> Optional[TelegramUser]:
    """
    Validate Telegram Login Widget callback data.

    Different from Mini App initData — Login Widget uses SHA256(bot_token) as HMAC key
    instead of HMAC("WebAppData", bot_token).

    Args:
        data: The callback data dict from Telegram Login Widget
        bot_token: The bot token for validation
        max_age_seconds: Maximum age of auth data (default 24 hours)

    Returns:
        TelegramUser if valid, None otherwise
    """
    try:
        # Work on a copy so we don't mutate the caller's dict
        data = dict(data)
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None

        # Build check string: sorted key=value pairs joined by \n
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))

        # Login Widget uses SHA256(bot_token) as secret key
        secret_key = hashlib.sha256(bot_token.encode()).digest()
        calculated_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # Check auth_date freshness
        auth_date = int(data.get("auth_date", 0))
        if time.time() - auth_date > max_age_seconds:
            return None

        return TelegramUser(
            id=int(data["id"]),
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name"),
            username=data.get("username"),
            photo_url=data.get("photo_url"),
        )

    except Exception as e:
        print(f"Error validating Telegram login: {e}")
        return None


def get_user_from_init_data(init_data: str, bot_token: str) -> Optional[TelegramUser]:
    """
    Extract and validate user from initData.

    Args:
        init_data: The initData string from Telegram WebApp
        bot_token: The bot token for validation

    Returns:
        TelegramUser if valid, None otherwise
    """
    auth_data = validate_init_data(init_data, bot_token)
    if auth_data:
        return auth_data.user
    return None


# ===================
# Wallet Signature Auth (for Chrome Extension)
# ===================

# Auth message format: "spredd-auth:{address}:{timestamp}"
WALLET_AUTH_MAX_AGE = 300  # 5 minutes


def validate_wallet_signature(
    address: str,
    signature: str,
    timestamp: str,
) -> Optional[str]:
    """
    Validate an EIP-191 personal_sign wallet signature for stateless auth.

    The extension signs a message: "spredd-auth:{address}:{timestamp}"
    We verify the signature recovers to the claimed address and the
    timestamp is fresh (within 5 minutes).

    Args:
        address: Claimed EVM wallet address (checksummed or lowercase)
        signature: Hex-encoded EIP-191 signature (0x-prefixed)
        timestamp: Unix timestamp string when the message was signed

    Returns:
        Checksummed address if valid, None otherwise
    """
    try:
        # Validate timestamp freshness
        ts = int(timestamp)
        if abs(time.time() - ts) > WALLET_AUTH_MAX_AGE:
            return None

        # Reconstruct the message that was signed
        address_lower = address.lower()
        message_text = f"spredd-auth:{address_lower}:{timestamp}"

        # Recover the signer address from the signature
        message = encode_defunct(text=message_text)
        w3 = Web3()
        recovered = w3.eth.account.recover_message(message, signature=signature)

        # Compare addresses (case-insensitive)
        if recovered.lower() != address_lower:
            return None

        return Web3.to_checksum_address(recovered)

    except Exception as e:
        print(f"Error validating wallet signature: {e}")
        return None
