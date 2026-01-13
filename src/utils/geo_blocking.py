"""
Geo-blocking utilities for platform compliance.
Uses IP-based detection for accurate country verification.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from src.db.models import Platform

# Countries blocked from Kalshi (ISO 3166-1 alpha-2 codes)
# Per agreement with Kalshi
KALSHI_BLOCKED_COUNTRIES = {
    "AF",  # Afghanistan
    "DZ",  # Algeria
    "AO",  # Angola
    "AU",  # Australia
    "BY",  # Belarus
    "BE",  # Belgium
    "BO",  # Bolivia
    "BG",  # Bulgaria
    "BF",  # Burkina Faso
    "CM",  # Cameroon
    "CA",  # Canada
    "CF",  # Central African Republic
    "CI",  # Cote d'Ivoire
    "CU",  # Cuba
    "CD",  # Democratic Republic of the Congo
    "ET",  # Ethiopia
    "FR",  # France
    "HT",  # Haiti
    "IR",  # Iran
    "IQ",  # Iraq
    "IT",  # Italy
    "KE",  # Kenya
    "LA",  # Laos
    "LB",  # Lebanon
    "LY",  # Libya
    "ML",  # Mali
    "MC",  # Monaco
    "MZ",  # Mozambique
    "MM",  # Myanmar (Burma)
    "NA",  # Namibia
    "NI",  # Nicaragua
    "NE",  # Niger
    "KP",  # North Korea
    "CN",  # People's Republic of China
    "PL",  # Poland
    "RU",  # Russia
    "SG",  # Singapore
    "SO",  # Somalia
    "SS",  # South Sudan
    "SD",  # Sudan
    "CH",  # Switzerland
    "SY",  # Syria
    "TW",  # Taiwan
    "TH",  # Thailand
    "UA",  # Ukraine
    "AE",  # United Arab Emirates
    "GB",  # United Kingdom
    "US",  # United States
    "VE",  # Venezuela
    "YE",  # Yemen
    "ZW",  # Zimbabwe
}

# Map of country codes to display names
COUNTRY_NAMES = {
    "AF": "Afghanistan",
    "DZ": "Algeria",
    "AO": "Angola",
    "AU": "Australia",
    "BY": "Belarus",
    "BE": "Belgium",
    "BO": "Bolivia",
    "BG": "Bulgaria",
    "BF": "Burkina Faso",
    "CM": "Cameroon",
    "CA": "Canada",
    "CF": "Central African Republic",
    "CI": "Cote d'Ivoire",
    "CU": "Cuba",
    "CD": "Democratic Republic of the Congo",
    "ET": "Ethiopia",
    "FR": "France",
    "HT": "Haiti",
    "IR": "Iran",
    "IQ": "Iraq",
    "IT": "Italy",
    "KE": "Kenya",
    "LA": "Laos",
    "LB": "Lebanon",
    "LY": "Libya",
    "ML": "Mali",
    "MC": "Monaco",
    "MZ": "Mozambique",
    "MM": "Myanmar",
    "NA": "Namibia",
    "NI": "Nicaragua",
    "NE": "Niger",
    "KP": "North Korea",
    "CN": "China",
    "PL": "Poland",
    "RU": "Russia",
    "SG": "Singapore",
    "SO": "Somalia",
    "SS": "South Sudan",
    "SD": "Sudan",
    "CH": "Switzerland",
    "SY": "Syria",
    "TW": "Taiwan",
    "TH": "Thailand",
    "UA": "Ukraine",
    "AE": "United Arab Emirates",
    "GB": "United Kingdom",
    "US": "United States",
    "VE": "Venezuela",
    "YE": "Yemen",
    "ZW": "Zimbabwe",
}

# Platform-specific blocked countries
PLATFORM_BLOCKED_COUNTRIES = {
    Platform.KALSHI: KALSHI_BLOCKED_COUNTRIES,
    # Other platforms have no geo-restrictions currently
    Platform.POLYMARKET: set(),
    Platform.OPINION: set(),
    Platform.LIMITLESS: set(),
}


def is_country_blocked(platform: Platform, country_code: str) -> bool:
    """Check if a country is blocked for a specific platform.

    Args:
        platform: The platform to check
        country_code: ISO 3166-1 alpha-2 country code (e.g., "US")

    Returns:
        True if the country is blocked, False otherwise
    """
    if not country_code:
        return False

    blocked_countries = PLATFORM_BLOCKED_COUNTRIES.get(platform, set())
    return country_code.upper() in blocked_countries


def get_country_name(country_code: str) -> str:
    """Get the display name for a country code."""
    return COUNTRY_NAMES.get(country_code.upper(), country_code)


def get_blocked_message(platform: Platform, country_code: str) -> str:
    """Get a user-friendly message explaining why access is blocked."""
    country_name = get_country_name(country_code)
    platform_name = platform.value.title()

    return (
        f"Access to {platform_name} is not available in {country_name} "
        f"due to regulatory restrictions.\n\n"
        f"Please select a different platform."
    )


# ===================
# IP Geolocation
# ===================

# How long a country verification is valid (30 days)
VERIFICATION_VALIDITY_DAYS = 30


def generate_verify_token() -> str:
    """Generate a secure random verification token."""
    return secrets.token_urlsafe(32)


async def get_country_from_ip(ip_address: str) -> Optional[str]:
    """Get country code from IP address using ip-api.com.

    Args:
        ip_address: The IP address to lookup

    Returns:
        ISO 3166-1 alpha-2 country code (e.g., "US") or None if lookup fails
    """
    # Skip private/local IPs
    if ip_address in ("127.0.0.1", "::1", "localhost") or ip_address.startswith(("10.", "172.16.", "192.168.")):
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # ip-api.com is free for non-commercial use, no API key needed
            # Returns JSON with countryCode field
            response = await client.get(
                f"http://ip-api.com/json/{ip_address}",
                params={"fields": "status,countryCode,message"}
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                return data.get("countryCode")

            return None
    except Exception:
        return None


def is_verification_valid(verified_at: Optional[datetime]) -> bool:
    """Check if a country verification is still valid.

    Args:
        verified_at: When the country was verified

    Returns:
        True if verification is valid, False if expired or never verified
    """
    if not verified_at:
        return False

    # Make sure verified_at is timezone-aware
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=timezone.utc)

    expiry = verified_at + timedelta(days=VERIFICATION_VALIDITY_DAYS)
    return datetime.now(timezone.utc) < expiry


def needs_reverification(verified_at: Optional[datetime]) -> bool:
    """Check if user needs to re-verify their country.

    Args:
        verified_at: When the country was last verified

    Returns:
        True if reverification is needed
    """
    return not is_verification_valid(verified_at)
