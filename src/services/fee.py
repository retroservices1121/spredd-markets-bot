"""
Fee service for handling transaction fees and referral distributions.

Fee Structure:
- 1% transaction fee on all trades
- Referral commissions from the fee:
  - Tier 1 (direct referrer): 25% of fee
  - Tier 2: 5% of fee
  - Tier 3: 3% of fee

Chain-Specific Tracking:
- Kalshi (Solana): Fees tracked as Solana USDC
- Polymarket/Opinion (EVM): Fees tracked as EVM USDC
"""

from decimal import Decimal, ROUND_DOWN
from typing import Optional

from src.db.database import (
    get_referral_chain,
    add_referral_earnings,
    get_user_by_telegram_id,
    update_partner_volume,
    get_effective_revenue_share,
)
from src.db.models import ChainFamily, Platform
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Fee configuration
TRANSACTION_FEE_BPS = 100  # 1% = 100 basis points
TIER_COMMISSIONS = {
    1: Decimal("0.25"),  # 25% of fee
    2: Decimal("0.05"),  # 5% of fee
    3: Decimal("0.03"),  # 3% of fee
}
MIN_WITHDRAWAL_USDC = Decimal("5.00")


def get_chain_family_for_platform(platform: Platform) -> ChainFamily:
    """Get the chain family for a platform."""
    if platform == Platform.KALSHI:
        return ChainFamily.SOLANA
    else:
        # Polymarket and Opinion are on EVM chains
        return ChainFamily.EVM


def calculate_fee(amount_usdc: str) -> str:
    """
    Calculate the 1% transaction fee.

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
        Net amount after 1% fee
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

    total_distributed = Decimal("0")

    for tier, referrer in enumerate(referral_chain, start=1):
        if tier > 3:
            break

        commission_rate = TIER_COMMISSIONS.get(tier, Decimal("0"))
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
            }
            total_distributed += commission

            logger.info(
                "Distributed referral commission",
                tier=tier,
                referrer_id=referrer.id,
                amount=str(commission),
                chain=chain_family.value,
                trader_id=trader_user_id,
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
