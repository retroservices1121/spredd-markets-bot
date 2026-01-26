"""
Fee service for handling transaction fees and referral distributions.

Fee Structure:
- 2% transaction fee on all trades
- Referral commissions from the fee:
  - Tier 1 (direct referrer): 25% of fee
  - Tier 2: 5% of fee
  - Tier 3: 3% of fee

Chain-Specific Tracking:
- Kalshi (Solana): Fees tracked as Solana USDC
- Polymarket/Opinion/Limitless/Myriad (EVM): Fees tracked as EVM USDC
"""

from decimal import Decimal, ROUND_DOWN
from typing import Optional

from src.db.database import (
    get_referral_chain,
    add_referral_earnings,
    get_user_by_telegram_id,
    update_partner_volume,
    get_effective_revenue_share,
    get_config,
    set_config,
)
from src.db.models import ChainFamily, Platform
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Fee configuration
TRANSACTION_FEE_BPS = 200  # 2% = 200 basis points

# Default tier commissions (can be overridden via admin commands)
DEFAULT_TIER_COMMISSIONS = {
    1: Decimal("0.25"),  # 25% of fee
    2: Decimal("0.05"),  # 5% of fee
    3: Decimal("0.03"),  # 3% of fee
}

# Config keys for tier commissions
TIER_CONFIG_KEYS = {
    1: "referral_tier1_percent",
    2: "referral_tier2_percent",
    3: "referral_tier3_percent",
}

MIN_WITHDRAWAL_USDC = Decimal("5.00")


async def get_tier_commissions() -> dict[int, Decimal]:
    """
    Get current tier commission rates from database config.
    Falls back to defaults if not configured.
    """
    commissions = {}
    for tier, key in TIER_CONFIG_KEYS.items():
        value = await get_config(key)
        if value is not None:
            try:
                # Convert percentage (e.g., "25") to decimal (0.25)
                commissions[tier] = Decimal(value) / Decimal("100")
            except Exception:
                commissions[tier] = DEFAULT_TIER_COMMISSIONS[tier]
        else:
            commissions[tier] = DEFAULT_TIER_COMMISSIONS[tier]
    return commissions


async def set_tier_commission(tier: int, percent: Decimal) -> bool:
    """
    Set a tier commission rate.

    Args:
        tier: Tier number (1, 2, or 3)
        percent: Commission percentage (e.g., 25 for 25%)

    Returns:
        True if successful
    """
    if tier not in TIER_CONFIG_KEYS:
        return False

    key = TIER_CONFIG_KEYS[tier]
    description = f"Tier {tier} referral commission percentage"
    await set_config(key, str(percent), description)
    return True


async def reset_tier_commissions() -> None:
    """Reset all tier commissions to default values."""
    for tier, default in DEFAULT_TIER_COMMISSIONS.items():
        percent = default * Decimal("100")  # Convert 0.25 to 25
        await set_tier_commission(tier, percent)


# ===================
# Per-User Rate Overrides
# ===================

def _user_rate_key(user_id: str) -> str:
    """Get the config key for a user's custom rate."""
    return f"user_rate_{user_id}"


async def get_user_custom_rate(user_id: str) -> Optional[Decimal]:
    """
    Get a user's custom Tier 1 commission rate if set.

    Returns:
        Decimal rate (e.g., 0.50 for 50%) or None if not set
    """
    value = await get_config(_user_rate_key(user_id))
    if value is not None:
        try:
            return Decimal(value) / Decimal("100")
        except Exception:
            return None
    return None


async def set_user_custom_rate(user_id: str, percent: Decimal) -> bool:
    """
    Set a custom Tier 1 commission rate for a specific user.

    Args:
        user_id: The user's database ID
        percent: Commission percentage (e.g., 50 for 50%)

    Returns:
        True if successful
    """
    key = _user_rate_key(user_id)
    description = f"Custom Tier 1 rate for user {user_id}"
    await set_config(key, str(percent), description)
    return True


async def clear_user_custom_rate(user_id: str) -> bool:
    """
    Remove a user's custom rate (they'll use global rates).

    Returns:
        True if a rate was removed, False if none existed
    """
    from src.db.database import delete_config
    return await delete_config(_user_rate_key(user_id))


def get_chain_family_for_platform(platform: Platform) -> ChainFamily:
    """Get the chain family for a platform."""
    if platform == Platform.KALSHI:
        return ChainFamily.SOLANA
    else:
        # Polymarket and Opinion are on EVM chains
        return ChainFamily.EVM


def calculate_fee(amount_usdc: str) -> str:
    """
    Calculate the 2% transaction fee.

    Args:
        amount_usdc: Trade amount in USDC (as string for precision)

    Returns:
        Fee amount in USDC (as string)
    """
    amount = Decimal(amount_usdc)
    fee = (amount * TRANSACTION_FEE_BPS / 10000).quantize(
        Decimal("0.000001"), rounding=ROUND_DOWN
    )
    return str(fee)


def calculate_net_amount(amount_usdc: str) -> str:
    """
    Calculate the net amount after fee deduction.

    Args:
        amount_usdc: Trade amount in USDC

    Returns:
        Net amount after 2% fee
    """
    amount = Decimal(amount_usdc)
    fee = Decimal(calculate_fee(amount_usdc))
    return str(amount - fee)


async def distribute_referral_fees(
    trader_user_id: str,
    order_id: str,
    fee_usdc: str,
    chain_family: ChainFamily,
) -> dict:
    """
    Distribute referral commissions from a trade fee.

    Args:
        trader_user_id: The user ID who made the trade
        order_id: The order ID for tracking
        fee_usdc: The total fee collected in USDC
        chain_family: The chain family where the fee was earned (Solana or EVM)

    Returns:
        Dictionary with distribution results
    """
    fee_amount = Decimal(fee_usdc)
    distributions = {
        "tier1": None,
        "tier2": None,
        "tier3": None,
        "total_distributed": "0",
        "chain_family": chain_family.value,
    }

    if fee_amount <= 0:
        return distributions

    # Get the referral chain for this user
    referral_chain = await get_referral_chain(trader_user_id)

    # Get current tier commission rates (may be customized via admin)
    tier_commissions = await get_tier_commissions()

    total_distributed = Decimal("0")

    for tier, referrer in enumerate(referral_chain, start=1):
        if tier > 3:
            break

        # For Tier 1, check if referrer has a custom rate
        custom_rate = None
        if tier == 1:
            custom_rate = await get_user_custom_rate(referrer.id)
            if custom_rate is not None:
                commission_rate = custom_rate
            else:
                commission_rate = tier_commissions.get(tier, Decimal("0"))
        else:
            commission_rate = tier_commissions.get(tier, Decimal("0"))

        commission = (fee_amount * commission_rate).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )

        if commission > 0:
            await add_referral_earnings(
                user_id=referrer.id,
                amount_usdc=str(commission),
                source_user_id=trader_user_id,
                order_id=order_id,
                tier=tier,
                chain_family=chain_family,
            )

            distributions[f"tier{tier}"] = {
                "user_id": referrer.id,
                "username": referrer.username,
                "amount": str(commission),
                "custom_rate": custom_rate is not None,
            }
            total_distributed += commission

            logger.info(
                "Distributed referral commission",
                tier=tier,
                referrer_id=referrer.id,
                amount=str(commission),
                chain=chain_family.value,
                trader_id=trader_user_id,
                custom_rate=float(custom_rate * 100) if custom_rate is not None else None,
            )

    distributions["total_distributed"] = str(total_distributed)
    return distributions


async def process_trade_fee(
    trader_telegram_id: int,
    order_id: str,
    trade_amount_usdc: str,
    platform: Platform,
) -> dict:
    """
    Process the complete fee for a trade including referral distributions.

    Args:
        trader_telegram_id: Telegram ID of the trader
        order_id: The order ID
        trade_amount_usdc: The trade amount in USDC
        platform: The trading platform (determines chain for fee tracking)

    Returns:
        Dictionary with fee details and distributions
    """
    # Get user
    user = await get_user_by_telegram_id(trader_telegram_id)
    if not user:
        logger.warning("User not found for fee processing", telegram_id=trader_telegram_id)
        return {
            "fee": "0",
            "net_amount": trade_amount_usdc,
            "distributions": {},
        }

    # Calculate fee
    fee = calculate_fee(trade_amount_usdc)
    net_amount = calculate_net_amount(trade_amount_usdc)

    # Determine chain family from platform
    chain_family = get_chain_family_for_platform(platform)

    # Distribute to referrers
    distributions = await distribute_referral_fees(
        trader_user_id=user.id,
        order_id=order_id,
        fee_usdc=fee,
        chain_family=chain_family,
    )

    # Track partner revenue if user is attributed to a partner
    partner_id = None
    partner_share_bps = None
    partner_group_id = None

    # Get effective revenue share (checks group-specific first, then partner default)
    share_bps, p_id, group_id = await get_effective_revenue_share(user.id)
    if share_bps is not None and p_id is not None:
        try:
            await update_partner_volume(
                partner_id=p_id,
                volume_usdc=Decimal(trade_amount_usdc),
                fee_usdc=Decimal(fee),
            )
            partner_id = p_id
            partner_share_bps = share_bps
            partner_group_id = group_id
            logger.info(
                "Partner revenue tracked",
                partner_id=p_id,
                group_id=group_id,
                share_bps=share_bps,
                volume=trade_amount_usdc,
                fee=fee,
            )
        except Exception as e:
            logger.error("Failed to track partner revenue", error=str(e), partner_id=p_id)

    logger.info(
        "Processed trade fee",
        trader_id=user.id,
        trade_amount=trade_amount_usdc,
        fee=fee,
        net_amount=net_amount,
        platform=platform.value,
        chain=chain_family.value,
        referral_distributed=distributions["total_distributed"],
        partner_id=partner_id,
    )

    return {
        "fee": fee,
        "net_amount": net_amount,
        "distributions": distributions,
        "partner_id": partner_id,
        "partner_share_bps": partner_share_bps,
        "partner_group_id": partner_group_id,
    }


def can_withdraw(claimable_usdc: str) -> bool:
    """Check if user can withdraw (minimum $5 USDC)."""
    return Decimal(claimable_usdc) >= MIN_WITHDRAWAL_USDC


def format_usdc(amount: str, decimals: int = 4) -> str:
    """Format USDC amount for display."""
    try:
        decimal_amount = Decimal(amount)
        if decimal_amount == 0:
            return "$0.00"
        return f"${decimal_amount:.{decimals}f}"
    except Exception:
        return "$0.00"
