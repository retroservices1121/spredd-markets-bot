"""
Telegram Mini App authentication utilities.
Validates initData from Telegram WebApp.
"""

import hashlib
import hmac
import json
import time
from typing import Optional
from urllib.parse import parse_qs, unquote

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
