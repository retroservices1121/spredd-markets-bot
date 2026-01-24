"""
Marketing postback service for conversion tracking.
Sends HTTP GET requests to marketing partner's postback URLs on conversion events.

Supported events:
- Registration (conv_type=1): User starts the bot with a click_id
- Qualification (conv_type=4): User completes first trade over $5
"""

import asyncio
from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone

import httpx

from src.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Conversion types
CONV_TYPE_REGISTRATION = 1
CONV_TYPE_QUALIFICATION = 4


class PostbackService:
    """
    Service for sending marketing attribution postbacks.

    Postback URL format:
    https://cmaffs-postback.org/direct/?cm_cid={click_id}&adver_payout={payout}&conv_type={type}&adv_id={id}
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._enabled = False

    async def initialize(self) -> None:
        """Initialize the HTTP client."""
        self._http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        )

        # Check if postback is configured
        self._enabled = bool(
            settings.postback_url and
            settings.postback_adv_id
        )

        if self._enabled:
            logger.info(
                "Postback service initialized",
                base_url=settings.postback_url,
                adv_id=settings.postback_adv_id,
            )
        else:
            logger.info("Postback service disabled (not configured)")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()

    def is_enabled(self) -> bool:
        """Check if postback service is enabled."""
        return self._enabled

    async def send_registration_postback(
        self,
        click_id: str,
        payout: Decimal = Decimal("0"),
    ) -> bool:
        """
        Send registration postback (conv_type=1).
        Called when a new user starts the bot with a click_id.

        Args:
            click_id: The marketing click ID from the user's URL
            payout: Optional payout amount (usually 0 for registration)

        Returns:
            True if postback was sent successfully
        """
        return await self._send_postback(
            click_id=click_id,
            conv_type=CONV_TYPE_REGISTRATION,
            payout=payout,
        )

    async def send_qualification_postback(
        self,
        click_id: str,
        payout: Decimal,
    ) -> bool:
        """
        Send qualification postback (conv_type=4).
        Called when user completes their first qualifying trade (over $5).

        Args:
            click_id: The marketing click ID from the user's URL
            payout: The payout amount (fee revenue for RevShare)

        Returns:
            True if postback was sent successfully
        """
        return await self._send_postback(
            click_id=click_id,
            conv_type=CONV_TYPE_QUALIFICATION,
            payout=payout,
        )

    async def _send_postback(
        self,
        click_id: str,
        conv_type: int,
        payout: Decimal = Decimal("0"),
    ) -> bool:
        """
        Send a postback to the marketing partner.

        Args:
            click_id: Marketing click ID
            conv_type: Conversion type (1=registration, 4=qualification)
            payout: Payout amount in USD

        Returns:
            True if successful
        """
        if not self._enabled:
            logger.debug("Postback disabled, skipping", click_id=click_id, conv_type=conv_type)
            return False

        if not click_id:
            logger.warning("No click_id provided, skipping postback")
            return False

        if not self._http_client:
            await self.initialize()

        try:
            # Build the postback URL
            # Format: https://cmaffs-postback.org/direct/?cm_cid={click_id}&adver_payout={payout}&conv_type={type}&adv_id={id}
            params = {
                "cm_cid": click_id,
                "adver_payout": str(payout),
                "conv_type": str(conv_type),
                "adv_id": settings.postback_adv_id,
            }

            url = settings.postback_url

            logger.info(
                "Sending postback",
                url=url,
                click_id=click_id,
                conv_type=conv_type,
                payout=str(payout),
            )

            response = await self._http_client.get(url, params=params)

            if response.status_code == 200:
                logger.info(
                    "Postback sent successfully",
                    click_id=click_id,
                    conv_type=conv_type,
                    status=response.status_code,
                )
                return True
            else:
                logger.warning(
                    "Postback returned non-200 status",
                    click_id=click_id,
                    conv_type=conv_type,
                    status=response.status_code,
                    response=response.text[:200] if response.text else "",
                )
                return False

        except httpx.TimeoutException:
            logger.error("Postback request timed out", click_id=click_id, conv_type=conv_type)
            return False
        except Exception as e:
            logger.error(
                "Failed to send postback",
                click_id=click_id,
                conv_type=conv_type,
                error=str(e),
            )
            return False


# Singleton instance
postback_service = PostbackService()


# ===================
# Database helpers
# ===================

async def store_click_id(telegram_id: int, click_id: str) -> bool:
    """
    Store click_id for a user and send registration postback if new.

    Args:
        telegram_id: User's Telegram ID
        click_id: Marketing click ID

    Returns:
        True if this is a new click_id attribution
    """
    from src.db.database import async_session_factory
    from src.db.models import User
    from sqlalchemy import select

    if not click_id:
        return False

    async with async_session_factory() as session:
        try:
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.warning("User not found for click_id storage", telegram_id=telegram_id)
                return False

            # Check if user already has a click_id (don't overwrite)
            if user.cm_click_id:
                logger.debug(
                    "User already has click_id, not overwriting",
                    telegram_id=telegram_id,
                    existing=user.cm_click_id,
                    new=click_id,
                )
                return False

            # Store click_id
            user.cm_click_id = click_id
            await session.commit()

            logger.info(
                "Stored click_id for user",
                telegram_id=telegram_id,
                click_id=click_id,
            )

            # Send registration postback if not already sent
            if not user.cm_registration_sent:
                success = await postback_service.send_registration_postback(click_id)
                if success:
                    user.cm_registration_sent = True
                    await session.commit()

            return True

        except Exception as e:
            logger.error("Failed to store click_id", telegram_id=telegram_id, error=str(e))
            await session.rollback()
            return False


async def check_and_send_qualification_postback(
    telegram_id: int,
    trade_amount: Decimal,
    fee_amount: Decimal,
) -> bool:
    """
    Check if user qualifies for qualification postback and send if so.

    Qualification criteria:
    - User has a click_id
    - Trade amount is >= $5
    - Qualification postback not already sent

    Args:
        telegram_id: User's Telegram ID
        trade_amount: Trade amount in USD
        fee_amount: Fee amount in USD (sent as payout for RevShare)

    Returns:
        True if qualification postback was sent
    """
    from src.db.database import async_session_factory
    from src.db.models import User
    from sqlalchemy import select

    # Check minimum trade amount for qualification
    min_qualification_amount = Decimal(str(settings.postback_min_qualification_amount))
    if trade_amount < min_qualification_amount:
        return False

    async with async_session_factory() as session:
        try:
            # Get user
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                return False

            # Check if user has click_id and qualification not already sent
            if not user.cm_click_id:
                return False

            if user.cm_qualification_sent:
                logger.debug(
                    "Qualification postback already sent",
                    telegram_id=telegram_id,
                )
                return False

            # Send qualification postback
            success = await postback_service.send_qualification_postback(
                click_id=user.cm_click_id,
                payout=fee_amount,
            )

            if success:
                user.cm_qualification_sent = True
                user.cm_qualified_at = datetime.now(timezone.utc)
                await session.commit()

                logger.info(
                    "Qualification postback sent",
                    telegram_id=telegram_id,
                    trade_amount=str(trade_amount),
                    fee_amount=str(fee_amount),
                )
                return True

            return False

        except Exception as e:
            logger.error(
                "Failed to check/send qualification postback",
                telegram_id=telegram_id,
                error=str(e),
            )
            await session.rollback()
            return False
