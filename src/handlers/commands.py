"""
Telegram bot command handlers.
Handles all user interactions with platform selection and trading.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, WebAppInfo
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import Forbidden

from src.config import settings
from src.db.database import (
    get_or_create_user,
    get_user_by_telegram_id,
    update_user_platform,
    update_user_country,
    get_user_positions,
    get_user_orders,
    get_or_create_referral_code,
    get_user_by_referral_code,
    set_user_referrer,
    get_referral_stats,
    get_fee_balance,
    get_all_fee_balances,
    process_withdrawal,
    create_position,
    get_position_by_id,
    update_position,
    create_order,
    update_order,
    get_orders_for_pnl,
    get_positions_for_pnl,
    # Partner functions
    create_partner,
    get_partner_by_code,
    get_partner_by_id,
    get_all_partners,
    update_partner,
    get_partner_stats,
    create_partner_group,
    get_partner_group_by_chat_id,
    update_partner_group,
    attribute_user_to_partner,
    set_user_proof_verified,
    get_all_user_telegram_ids,
)
from src.utils.geo_blocking import (
    is_country_blocked,
    get_blocked_message,
    needs_reverification,
    get_country_name,
)
from src.utils.proof_kyc import check_proof_verified, generate_proof_deep_link
from src.db.models import Platform, ChainFamily, Chain, PositionStatus, OrderStatus
from src.platforms import (
    platform_registry,
    get_platform,
    get_platform_info,
    get_chain_family_for_platform,
    get_collateral_for_market,
    PLATFORM_INFO,
)
from src.services.wallet import wallet_service, WalletInfo
from src.services.fee import format_usdc, can_withdraw, MIN_WITHDRAWAL_USDC, process_trade_fee, calculate_fee
from src.services.pnl_card import generate_pnl_card
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ===================
# Helper Functions
# ===================

def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def friendly_error(error: str) -> str:
    """Convert technical error messages to user-friendly plain English.

    Returns HTML-escaped output safe for Telegram ParseMode.HTML.
    """
    error_lower = error.lower()

    # Common error patterns and their friendly versions
    if "insufficient" in error_lower and "conditional token" in error_lower:
        return "You don't have the tokens needed to sell. The position may not have been purchased successfully."
    if "insufficient" in error_lower and ("balance" in error_lower or "fund" in error_lower):
        return "You don't have enough funds in your wallet. Please deposit more and try again."
    if "allowance" in error_lower:
        return "Wallet approval is pending. Please wait a moment and try again."
    # Only show gas error for actual insufficient gas, not any error mentioning "gas"
    if ("insufficient" in error_lower and "gas" in error_lower) or "intrinsic gas too low" in error_lower:
        return "Not enough funds to cover network fees. Please add some ETH/MATIC/BNB to your wallet."
    if "nonce" in error_lower:
        return "Transaction conflict. Please wait a moment and try again."
    if "timeout" in error_lower or "timed out" in error_lower:
        return "The request took too long. Please try again."
    if "rate limit" in error_lower or "too many" in error_lower:
        return "Too many requests. Please wait a moment and try again."
    if "not found" in error_lower and "market" in error_lower:
        return "This market is no longer available."
    if "connection" in error_lower or "network" in error_lower:
        return "Connection issue. Please check your internet and try again."
    if "signature" in error_lower or "sign" in error_lower:
        return "Failed to sign the transaction. Please try again."
    if "rejected" in error_lower or "reverted" in error_lower:
        return "Transaction was rejected. The market price may have changed."
    if "slippage" in error_lower:
        return "Price moved too much. Please try again with the updated price."
    if "expired" in error_lower:
        return "This offer has expired. Please get a new quote."
    if "invalid" in error_lower and "address" in error_lower:
        return "Invalid wallet address. Please check and try again."
    if "decryption failed" in error_lower or "invalid pin" in error_lower:
        return "Incorrect PIN. Please try again."
    if "api" in error_lower and "error" in error_lower:
        return "The trading platform is having issues. Please try again later."
    if "minimum" in error_lower:
        return "Amount is below the minimum. Please increase your trade amount."
    if "maximum" in error_lower:
        return "Amount exceeds the maximum. Please reduce your trade amount."
    if "closed" in error_lower or "not active" in error_lower:
        return "This market is closed and no longer accepting trades."
    if "resolved" in error_lower:
        return "This market has already been resolved."

    # If no pattern matches, return a cleaned up version
    # Remove technical prefixes and make it more readable
    cleaned = error
    for prefix in ["PlatformError:", "API error:", "Error:", "HTTPError:", "Exception:"]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    # If it's still very technical, give a generic message
    if any(x in cleaned.lower() for x in ["traceback", "0x", "bytes", "uint", "abi", "keccak", "<bridgechain", "<platform"]):
        return "Something went wrong. Please try again or contact support if the issue persists."

    # Truncate and escape HTML to prevent Telegram parsing issues
    result = cleaned if len(cleaned) < 200 else cleaned[:200] + "..."
    return escape_html(result)


def format_price(price: Optional[Decimal]) -> str:
    """Format price as cents."""
    if price is None:
        return "N/A"
    cents = int(price * 100)
    return f"{cents}¢"


def format_probability(price: Optional[Decimal]) -> str:
    """Format price as probability."""
    if price is None:
        return "N/A"
    return f"{float(price * 100):.1f}%"


def format_usd(amount: Optional[Decimal]) -> str:
    """Format USD amount."""
    if amount is None:
        return "N/A"
    return f"${float(amount):,.2f}"


def format_expiration(close_time, show_time: bool = True) -> str:
    """Format expiration date/time in a user-friendly way."""
    if not close_time:
        return "N/A"

    try:
        from datetime import datetime, timezone

        dt = None

        # Handle Unix timestamp (integer or numeric string)
        if isinstance(close_time, (int, float)):
            # Check if timestamp is in milliseconds (Limitless uses ms)
            if close_time > 1e12:
                close_time = close_time / 1000
            dt = datetime.fromtimestamp(close_time, tz=timezone.utc)
        elif isinstance(close_time, str):
            # Check if it's a numeric string (Unix timestamp)
            if close_time.isdigit() or (close_time.replace('.', '', 1).isdigit()):
                ts = float(close_time)
                # Check if timestamp is in milliseconds
                if ts > 1e12:
                    ts = ts / 1000
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            # Parse ISO format date string
            elif close_time.endswith("Z"):
                dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            elif "T" in close_time:
                dt = datetime.fromisoformat(close_time)
            else:
                # Try parsing date-only format
                dt = datetime.fromisoformat(close_time + "T23:59:59+00:00")

        if dt is None:
            return "N/A"

        # Make timezone-aware if not already
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        diff = dt - now

        # If already expired
        if diff.total_seconds() < 0:
            return "Expired"

        # Format based on time remaining
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60

        if days > 30:
            return dt.strftime("%b %d, %Y")
        elif days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            # For hourly markets, show actual time
            if show_time and hours < 6:
                return f"{hours}h {minutes}m ({dt.strftime('%H:%M')} UTC)"
            return f"{hours}h {minutes}m"
        else:
            # Show actual time for very short expiration
            if show_time:
                return f"{minutes}m ({dt.strftime('%H:%M')} UTC)"
            return f"{minutes}m"
    except Exception:
        # Fallback: convert to string and truncate
        close_str = str(close_time)
        return close_str[:20] if len(close_str) > 20 else close_str


def platform_keyboard() -> InlineKeyboardMarkup:
    """Create platform selection keyboard."""
    buttons = []
    for platform_id in platform_registry.all_platforms:
        info = PLATFORM_INFO[platform_id]
        if info.get("hidden"):
            continue
        label = f"{info['emoji']} {info['name']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"platform:{platform_id.value}")])
    return InlineKeyboardMarkup(buttons)


def back_button(callback: str = "menu:main") -> InlineKeyboardMarkup:
    """Create back button."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data=callback)]
    ])


# ===================
# Command Handlers
# ===================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - welcome and platform selection."""
    if not update.effective_user or not update.message:
        return

    # Check for start parameter
    referral_code = None
    geo_verified = False
    cm_click_id = None

    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referral_code = arg[4:]  # Remove "ref_" prefix
        elif arg.startswith("cm_"):
            cm_click_id = arg[3:]  # Remove "cm_" prefix - marketing click ID
        elif arg == "geo_verified":
            geo_verified = True
        elif len(arg) > 8 and not arg.startswith("ref"):
            # Assume longer parameters are click IDs (for flexibility)
            # This allows direct click IDs without prefix
            cm_click_id = arg

    user = await get_or_create_user(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )

    # Process marketing click_id if provided
    if cm_click_id:
        from src.services.postback import store_click_id
        await store_click_id(update.effective_user.id, cm_click_id)

    # Process referral code if provided
    referral_message = ""
    if referral_code:
        referrer = await get_user_by_referral_code(referral_code)
        if referrer and referrer.id != user.id:
            # Set the referrer
            success = await set_user_referrer(user.id, referrer.id)
            if success:
                referrer_name = referrer.username or referrer.first_name or "Someone"
                referral_message = f"\n🎁 Referred by @{referrer_name}!\n"
                logger.info(
                    "Referral registered",
                    user_id=user.id,
                    referrer_id=referrer.id,
                    referral_code=referral_code,
                )

    # Handle returning from geo verification
    if geo_verified and user.country:
        country_name = get_country_name(user.country)
        is_blocked = is_country_blocked(Platform.KALSHI, user.country)

        if is_blocked:
            text = f"""
🚫 <b>Location Verified - Access Restricted</b>

Your location has been verified as: <b>{country_name}</b>

Unfortunately, Kalshi is not available in your region due to regulatory restrictions.

You can still trade on other platforms like Polymarket, Opinion, Limitless, and Myriad.
"""
        else:
            text = f"""
✅ <b>Location Verified Successfully!</b>

Your location has been verified as: <b>{country_name}</b>

You now have access to Kalshi markets!
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Select Platform", callback_data="menu:platform")],
        ])

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    welcome_text = f"""
🎯 <b>Welcome to Spredd Markets!</b>
{referral_message}
The easiest way to trade prediction markets directly from Telegram.

<b>What is Spredd?</b>
Spredd is a non-custodial trading bot that lets you buy and sell positions on prediction markets across multiple platforms — all without leaving Telegram.

<b>Supported Platforms:</b>
{platform_registry.format_platform_list()}

<b>Why Spredd?</b>
• Non-custodial — you control your keys
• Multi-platform — trade on Kalshi, Polymarket & more
• Fast & simple — no complex interfaces
• Shareable PnL cards — flex your wins

Join our community and follow us for updates!
"""

    # Build keyboard with optional Mini App button
    keyboard_rows = [
        [InlineKeyboardButton("🚀 Get Started", callback_data="landing:start")],
    ]

    # Mini App button - hidden for launch (will enable later for marketing)
    # if settings.miniapp_url:
    #     keyboard_rows.append([
    #         InlineKeyboardButton(
    #             "📱 Open Mini App",
    #             web_app=WebAppInfo(url=settings.miniapp_url)
    #         )
    #     ])

    keyboard_rows.append([
        InlineKeyboardButton("Follow on X", url="https://x.com/spreddterminal"),
        InlineKeyboardButton("Join Telegram", url="https://t.me/spreddmarketsgroup"),
    ])

    keyboard = InlineKeyboardMarkup(keyboard_rows)

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not update.message:
        return

    help_text = """
🎯 <b>Spredd Markets Bot Commands</b>

<b>Getting Started</b>
/start - Welcome & platform selection
/platform - Switch prediction market platform
/wallet - View/create your wallets

<b>Trading</b>
/markets - Browse trending markets
/search [query] - Search for markets
/buy - Start a buy order
/positions - View your open positions
/orders - View order history
/pnl - View profit & loss summary

<b>Account</b>
/balance - Check all balances
/referral - Referral Space & earn commissions
/export - Export private keys (use carefully!)
/settings - Trading preferences

<b>Help</b>
/faq - Frequently asked questions
/support - Contact support

<b>Platform Info</b>
• <b>Kalshi</b> (Solana)
• <b>Polymarket</b> (Polygon)
• <b>Opinion</b> (BNB Chain)

Need help? @spreddterminal
"""

    # Mini App button - hidden for launch (will enable later for marketing)
    # if settings.miniapp_url:
    #     keyboard = InlineKeyboardMarkup([
    #         [InlineKeyboardButton(
    #             "📱 Open Mini App",
    #             web_app=WebAppInfo(url=settings.miniapp_url)
    #         )],
    #     ])
    #     await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    # else:
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def groupinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /groupinfo command - send a pinnable welcome message in groups.
    Only works in groups/supergroups.
    """
    if not update.message or not update.effective_chat:
        return

    # Only allow in groups
    if update.effective_chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "This command only works in groups. Use /start in private chat.",
        )
        return

    # Get bot username for the button link
    bot = await context.bot.get_me()
    bot_username = bot.username
    start_link = f"https://t.me/{bot_username}?start=group"

    welcome_text = """
🎯 <b>Welcome to Spredd Markets!</b>

The easiest way to trade prediction markets directly from Telegram.

<b>Supported Platforms:</b>
• Kalshi (Solana)
• Polymarket (Polygon)
• Opinion (BNB Chain)

<b>Features:</b>
• Non-custodial trading
• Real-time market prices
• Shareable PnL cards
• Multi-platform support

Tap the button below to start trading!
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Trading", url=start_link)],
        [
            InlineKeyboardButton("Follow on X", url="https://x.com/spreddterminal"),
            InlineKeyboardButton("Join Community", url="https://t.me/spreddmarketsgroup"),
        ],
    ])

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def app_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /app command - open Mini App."""
    if not update.message:
        return

    # Mini App hidden for launch - will enable later for marketing
    await update.message.reply_text(
        "📱 <b>Spredd Mini App</b>\n\n"
        "🚧 Coming Soon!\n\n"
        "We're building a beautiful trading interface for you.\n"
        "Stay tuned for updates!\n\n"
        "For now, use the bot commands to trade.",
        parse_mode=ParseMode.HTML,
    )
    return

    # Original code - uncomment to enable Mini App
    # if not settings.miniapp_url:
    #     await update.message.reply_text(
    #         "📱 Mini App is not configured yet.\n\n"
    #         "Use the bot commands to trade!",
    #         parse_mode=ParseMode.HTML,
    #     )
    #     return
    #
    # keyboard = InlineKeyboardMarkup([
    #     [InlineKeyboardButton(
    #         "📱 Open Spredd Mini App",
    #         web_app=WebAppInfo(url=settings.miniapp_url)
    #     )],
    # ])
    #
    # await update.message.reply_text(
    #     "📱 <b>Spredd Mini App</b>\n\n"
    #     "Trade prediction markets with a beautiful interface!\n\n"
    #     "• Browse & search markets\n"
    #     "• View wallet balances\n"
    #     "• Track positions & P&L\n"
    #     "• Execute trades\n\n"
    #     "Tap the button below to open:",
    #     parse_mode=ParseMode.HTML,
    #     reply_markup=keyboard,
    # )


async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /faq command - show FAQ menu."""
    if not update.message:
        return

    text = """
❓ <b>Frequently Asked Questions</b>

Select a topic to learn more:
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Is this non-custodial?", callback_data="faq:noncustodial")],
        [InlineKeyboardButton("🔑 Why do I need a PIN?", callback_data="faq:pin")],
        [InlineKeyboardButton("💰 What are the fees?", callback_data="faq:fees")],
        [InlineKeyboardButton("📥 How do I deposit?", callback_data="faq:deposit")],
        [InlineKeyboardButton("🔄 USDC Auto-Swap", callback_data="faq:autoswap")],
        [InlineKeyboardButton("🌉 Cross-Chain Bridging", callback_data="faq:bridge")],
        [InlineKeyboardButton("⚠️ Security warnings", callback_data="faq:security")],
        [InlineKeyboardButton("« Back", callback_data="menu:main")],
    ])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /support command - show customer support options."""
    if not update.message:
        return

    text = """
📞 <b>Customer Support</b>

Need help? Reach out to us:
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("DM on X @spreddterminal", url="https://x.com/spreddterminal")],
        [InlineKeyboardButton("Join Telegram Group", url="https://t.me/spreddmarketsgroup")],
    ])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def platform_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /platform command - switch platforms."""
    if not update.effective_user or not update.message:
        return
    
    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return
    
    current_info = PLATFORM_INFO[user.active_platform]
    
    text = f"""
🔄 <b>Switch Platform</b>

Current: {current_info['emoji']} <b>{current_info['name']}</b>

Select a new platform:
"""
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=platform_keyboard(),
    )


async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet command - show wallet info and balances."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    # Check if user has existing wallets
    from src.db.database import get_user_wallets
    existing_wallets = await get_user_wallets(user.id)

    if not existing_wallets:
        # No wallets - prompt for PIN setup
        context.user_data["pending_new_wallet"] = True

        text = """
🔐 <b>Set Up Your Wallet</b>

Welcome! Let's create your secure wallets.

<b>Enter a 4-6 digit PIN to protect key exports:</b>
<i>(PIN is only needed when exporting keys, not for trading)</i>

Type /cancel to cancel.
"""
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
        )
        return

    # Existing code for when wallets already exist - kept for reference but unreachable now
    if False:  # Dead code - keeping structure for potential future use
        try:
            wallets = await wallet_service.get_or_create_wallets(
                user_id=user.id,
                telegram_id=update.effective_user.id,
            )

            solana_wallet = wallets.get(ChainFamily.SOLANA)
            evm_wallet = wallets.get(ChainFamily.EVM)

            text = """
✅ <b>Wallets Created!</b>

<b>🟣 Solana</b> (Kalshi)
<code>{}</code>

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless + Myriad)
<code>{}</code>

<i>Tap address to copy. Send funds to deposit.</i>
""".format(
                solana_wallet.public_key if solana_wallet else "Error",
                evm_wallet.public_key if evm_wallet else "Error",
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Browse Markets", callback_data="markets:refresh")],
                [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
            ])

            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return

        except Exception as e:
            logger.error("Wallet creation failed", error=str(e))
            await update.message.reply_text(
                f"❌ Failed to create wallets: {friendly_error(str(e))}",
                parse_mode=ParseMode.HTML,
            )
            return

    # Has wallets - show them
    wallets_dict = {w.chain_family: WalletInfo(chain_family=w.chain_family, public_key=w.public_key) for w in existing_wallets}

    # Get balances
    balances = await wallet_service.get_all_balances(user.id)

    # Format wallet info
    solana_wallet = wallets_dict.get(ChainFamily.SOLANA)
    evm_wallet = wallets_dict.get(ChainFamily.EVM)

    text = "💰 <b>Your Wallets</b>\n\n"

    # Solana wallet (for Kalshi)
    if solana_wallet:
        text += f"<b>🟣 Solana</b> (Kalshi)\n"
        text += f"<code>{solana_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.SOLANA, []):
            text += f"  • {bal.formatted}\n"
        text += "\n"

    # EVM wallet (for Polymarket, Opinion, Limitless & Myriad)
    if evm_wallet:
        text += f"<b>🔷 EVM</b> (Polymarket + Opinion + Limitless + Myriad)\n"
        text += f"<code>{evm_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.EVM, []):
            text += f"  • {bal.formatted} ({bal.chain.value})\n"

    text += "\n<i>Tap address to copy. Send funds to deposit.</i>"

    # Buttons
    buttons = [
        [InlineKeyboardButton("🔄 Refresh Balances", callback_data="wallet:refresh")],
        [InlineKeyboardButton("🌉 Bridge USDC", callback_data="wallet:bridge")],
        [InlineKeyboardButton("📤 Export Keys", callback_data="wallet:export")],
        [InlineKeyboardButton("« Back", callback_data="menu:main")],
    ]

    keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /balance command - detailed balance view."""
    # Same as wallet for now
    await wallet_command(update, context)


async def resetwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resetwallet command - delete existing wallets and create new PIN-protected ones."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    # Show warning and prompt for PIN setup
    text = """
⚠️ <b>Reset Wallets</b>

This will:
• <b>Delete your existing wallets</b>
• <b>Generate new wallet addresses</b>
• <b>Set up a PIN for key export protection</b>

<b>IMPORTANT:</b>
• Export your current keys first if needed
• Transfer any funds to a safe location
• Your old addresses will no longer work

<b>Enter a 4-6 digit PIN to protect key exports:</b>
<i>(PIN is only needed when exporting keys, not for trading)</i>

Type /cancel to cancel.
"""
    # Store pending reset state
    context.user_data["pending_wallet_reset"] = True

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def markets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /markets command - show trending markets with pagination."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    platform_info = PLATFORM_INFO[user.active_platform]
    platform = get_platform(user.active_platform)

    await update.message.reply_text(
        f"🔍 Loading {platform_info['emoji']} {platform_info['name']} markets...",
        parse_mode=ParseMode.HTML,
    )

    per_page = 10

    try:
        # Fetch more to account for deduplication of multi-outcome events
        markets = await platform.get_markets(limit=(per_page * 3) + 1, offset=0, active_only=True)

        # Deduplicate multi-outcome events by event_id or title
        seen_events = set()
        unique_markets = []
        for market in markets:
            # Use event_id for multi-outcome, fallback to title for dedup
            if market.is_multi_outcome:
                # Use event_id if available, otherwise use title as dedup key
                dedup_key = market.event_id if market.event_id else market.title
            else:
                dedup_key = market.market_id

            if dedup_key not in seen_events:
                seen_events.add(dedup_key)
                unique_markets.append(market)

        markets = unique_markets
        has_next = len(markets) > per_page
        markets = markets[:per_page]

        if not markets:
            await update.message.reply_text(
                f"No markets found on {platform_info['name']}. Try /search [query]",
                parse_mode=ParseMode.HTML,
            )
            return

        text = f"{platform_info['emoji']} <b>Trending on {platform_info['name']}</b>\n"
        text += f"<i>Page 1</i>\n\n"

        buttons = []
        for i, market in enumerate(markets, 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            exp = format_expiration(market.close_time)

            # Indicator for multi-outcome markets
            multi_indicator = f" [{market.related_market_count} options]" if market.is_multi_outcome else ""

            text += f"<b>{i}.</b> {title}{multi_indicator}\n"
            if market.is_multi_outcome and market.outcome_name:
                text += f"   {escape_html(market.outcome_name)}: {yes_prob} • Vol: {format_usd(market.volume_24h)} • Exp: {exp}\n\n"
            else:
                text += f"   YES: {yes_prob} • Vol: {format_usd(market.volume_24h)} • Exp: {exp}\n\n"

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:{user.active_platform.value}:{market.market_id[:40]}"
                )
            ])

        # Pagination buttons (page 0, only show Next if available)
        if has_next:
            buttons.append([InlineKeyboardButton("Next »", callback_data="markets:page:1")])

        buttons.append([
            InlineKeyboardButton("📂 Categories", callback_data="categories"),
            InlineKeyboardButton("🔄 Refresh", callback_data="markets:refresh"),
        ])

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to get markets", error=str(e))
        await update.message.reply_text(
            f"❌ Failed to load markets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command - search markets."""
    if not update.effective_user or not update.message:
        return
    
    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return
    
    # Get search query from args
    query = " ".join(context.args) if context.args else None
    
    if not query:
        await update.message.reply_text(
            "🔍 <b>Search Markets</b>\n\n"
            "Usage: /search [query]\n\n"
            "Examples:\n"
            "• /search bitcoin\n"
            "• /search fed rate\n"
            "• /search super bowl",
            parse_mode=ParseMode.HTML,
        )
        return
    
    platform_info = PLATFORM_INFO[user.active_platform]
    platform = get_platform(user.active_platform)
    
    await update.message.reply_text(
        f"🔍 Searching {platform_info['name']} for \"{escape_html(query)}\"...",
        parse_mode=ParseMode.HTML,
    )
    
    try:
        markets = await platform.search_markets(query, limit=10)
        
        if not markets:
            await update.message.reply_text(
                f"No results for \"{escape_html(query)}\" on {platform_info['name']}",
                parse_mode=ParseMode.HTML,
            )
            return
        
        text = f"🔍 <b>Results for \"{escape_html(query)}\"</b>\n\n"

        buttons = []
        for i, market in enumerate(markets, 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            exp = format_expiration(market.close_time)

            # Indicator for multi-outcome markets
            multi_indicator = f" [{market.related_market_count} options]" if market.is_multi_outcome else ""

            text += f"<b>{i}.</b> {title}{multi_indicator}\n"
            if market.is_multi_outcome and market.outcome_name:
                text += f"   {escape_html(market.outcome_name)}: {yes_prob} • Exp: {exp}\n\n"
            else:
                text += f"   YES: {yes_prob} • Exp: {exp}\n\n"

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:{user.active_platform.value}:{market.market_id[:40]}"
                )
            ])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        
    except Exception as e:
        logger.error("Search failed", error=str(e), query=query)
        await update.message.reply_text(
            f"❌ Search failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /positions command - show user positions."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    await show_positions(update.message, update.effective_user.id, page=0, is_callback=False)


async def show_positions(target, telegram_id: int, page: int = 0, is_callback: bool = False) -> None:
    """Show user positions with pagination."""
    POSITIONS_PER_PAGE = 5

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        return

    all_positions = await get_user_positions(
        user_id=user.id,
        platform=user.active_platform,
        status=PositionStatus.OPEN,
    )

    platform_info = PLATFORM_INFO[user.active_platform]
    platform = get_platform(user.active_platform)

    # Filter out expired/resolved positions and auto-close them
    active_positions = []
    for pos in all_positions:
        try:
            # First check if we can find the market at all
            # Use include_closed=True to find recently closed markets (not yet resolved)
            lookup_id = pos.event_id if pos.event_id else pos.market_id
            market = await platform.get_market(lookup_id, search_title=pos.market_title, include_closed=True)
            if not market and pos.event_id:
                market = await platform.get_market(pos.market_id, search_title=pos.market_title, include_closed=True)

            if not market:
                # Market not found - likely expired/delisted
                # Auto-close these positions to clean up database and speed up future queries
                await update_position(pos.id, status=PositionStatus.EXPIRED, token_amount="0")
                logger.info(f"Auto-closed position {pos.id} - market {pos.market_id} not found (likely expired)")
                continue

            # Check market resolution status
            # IMPORTANT: Always use market_id (specific outcome) for resolution, not event_id (group)
            # For multi-outcome markets, event_id is the group slug but each outcome has its own resolution
            resolution = await platform.get_market_resolution(pos.market_id)

            if resolution.is_resolved:
                # Auto-close resolved positions
                outcome_str = pos.outcome.upper() if isinstance(pos.outcome, str) else pos.outcome.value.upper()
                winning_str = resolution.winning_outcome.upper() if resolution.winning_outcome else None

                logger.debug(
                    f"Checking resolution for position {pos.id}: "
                    f"market={pos.market_id}, user_outcome={outcome_str}, winning={winning_str}"
                )

                if winning_str and winning_str == outcome_str:
                    # Won - check if platform auto-settles
                    if pos.platform == Platform.KALSHI:
                        # Kalshi auto-settles - funds already in wallet, mark as redeemed
                        await update_position(pos.id, status=PositionStatus.REDEEMED, token_amount="0")
                        logger.info(f"Auto-marked Kalshi position {pos.id} as redeemed (auto-settled)")
                    else:
                        # Other platforms require manual redemption
                        logger.info(f"Position {pos.id} won! market={pos.market_id}")
                        active_positions.append(pos)
                elif winning_str and winning_str != outcome_str:
                    # Lost - auto-close the position (only if we KNOW they lost)
                    await update_position(pos.id, status=PositionStatus.CLOSED, token_amount="0")
                    logger.info(f"Auto-closed losing position {pos.id} for resolved market {pos.market_id} (won={winning_str}, user={outcome_str})")
                else:
                    # Could not determine winner - keep position open for manual handling
                    logger.warning(f"Position {pos.id} resolved but winner unknown - keeping open for manual review")
                    active_positions.append(pos)
            else:
                # Market still active
                active_positions.append(pos)
        except Exception as e:
            # If we can't check, KEEP the position rather than hiding it
            # This is more conservative - users can still see and manage their positions
            logger.warning(f"Could not verify position {pos.id} (keeping it visible): {e}")
            active_positions.append(pos)

    all_positions = active_positions

    if not all_positions:
        text = (
            f"📊 <b>No Open Positions</b>\n\n"
            f"You don't have any open positions on {platform_info['name']}.\n\n"
            f"Use /markets or /search to find markets and trade!"
        )
        if is_callback:
            await target.edit_message_text(text, parse_mode=ParseMode.HTML)
        else:
            await target.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # Calculate pagination
    total_positions = len(all_positions)
    total_pages = (total_positions + POSITIONS_PER_PAGE - 1) // POSITIONS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start_idx = page * POSITIONS_PER_PAGE
    end_idx = start_idx + POSITIONS_PER_PAGE
    positions = all_positions[start_idx:end_idx]

    # Build header with page info
    if total_pages > 1:
        text = f"📊 <b>Your {platform_info['name']} Positions</b> (Page {page + 1}/{total_pages})\n\n"
    else:
        text = f"📊 <b>Your {platform_info['name']} Positions</b>\n\n"

    # Helper to check if outcome name is custom (not just Yes/No)
    def get_display_outcome(outcome_str: str, market) -> str:
        """Get display name for outcome, using custom name if available."""
        if not market:
            return outcome_str

        # Get the outcome name from market
        if outcome_str == "YES" and market.yes_outcome_name:
            name = market.yes_outcome_name.strip()
            # Only use custom name if it's not just "Yes"/"No"
            if name.lower() not in ("yes", "no", "y", "n"):
                return name[:15] + "..." if len(name) > 15 else name
        elif outcome_str == "NO" and market.no_outcome_name:
            name = market.no_outcome_name.strip()
            if name.lower() not in ("yes", "no", "y", "n"):
                return name[:15] + "..." if len(name) > 15 else name

        return outcome_str

    for i, pos in enumerate(positions, start=start_idx + 1):
        title = escape_html(pos.market_title[:40] + "..." if len(pos.market_title) > 40 else pos.market_title)
        outcome_str = pos.outcome.upper() if isinstance(pos.outcome, str) else pos.outcome.value.upper()
        entry = format_price(pos.entry_price)

        # Calculate amount spent (token_amount * entry_price)
        # token_amount is stored with 6 decimals (like USDC)
        try:
            token_amount = Decimal(pos.token_amount) / Decimal(10**6)
            amount_spent = token_amount * pos.entry_price if pos.entry_price else Decimal(0)
            spent_str = f"${amount_spent:.2f}"
        except Exception:
            spent_str = "N/A"

        # Fetch current price from platform
        current_price = None
        market = None
        try:
            # Try event_id (slug) first for Limitless, then fall back to market_id with title search
            # Use include_closed=True to get prices for resolved/closed markets
            lookup_id = pos.event_id if pos.event_id else pos.market_id
            market = await platform.get_market(lookup_id, search_title=pos.market_title, include_closed=True)
            if not market and pos.event_id:
                # Fallback to numeric ID with title search if slug lookup failed
                market = await platform.get_market(pos.market_id, search_title=pos.market_title, include_closed=True)
            if market:
                # Get the price for the outcome the user holds
                if outcome_str == "YES":
                    current_price = market.yes_price
                else:
                    current_price = market.no_price
        except Exception:
            pass

        # Get display name for outcome (use custom name if available)
        display_outcome = get_display_outcome(outcome_str, market)

        current = format_price(current_price) if current_price else "N/A"

        # Calculate P&L
        if current_price and pos.entry_price:
            pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100
            pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        else:
            pnl_str = "N/A"
            pnl_emoji = "⚪"

        text += f"<b>{i}. {title}</b>\n"
        text += f"  {display_outcome} ({spent_str}) • Entry: {entry} • Now: {current}\n"
        text += f"  {pnl_emoji} P&L: {pnl_str}\n\n"

    # Build buttons - sell/redeem button for each position + pagination
    buttons = []

    # Add sell or redeem buttons for each position on current page
    for pos in positions:
        short_title = pos.market_title[:20] + "..." if len(pos.market_title) > 20 else pos.market_title
        outcome_str = pos.outcome.upper() if isinstance(pos.outcome, str) else pos.outcome.value.upper()

        # Fetch fresh market price for resolution check
        fresh_price = None
        market = None
        try:
            lookup_id = pos.event_id if pos.event_id else pos.market_id
            market = await platform.get_market(lookup_id, search_title=pos.market_title, include_closed=True)
            if not market and pos.event_id:
                market = await platform.get_market(pos.market_id, search_title=pos.market_title, include_closed=True)
            if market:
                fresh_price = market.yes_price if outcome_str == "YES" else market.no_price
        except Exception:
            pass

        # Get display name for outcome (use custom name if available)
        btn_outcome = get_display_outcome(outcome_str, market)

        # Check if market is resolved for redemption
        # IMPORTANT: Use market_id (specific outcome) not event_id (group) for multi-outcome markets
        try:
            resolution = await platform.get_market_resolution(pos.market_id)
            logger.info(
                "Position resolution check",
                position_id=pos.id,
                market_id=pos.market_id[:20] if pos.market_id else "N/A",
                platform=pos.platform.value if hasattr(pos.platform, 'value') else str(pos.platform),
                is_resolved=resolution.is_resolved,
                winning_outcome=resolution.winning_outcome,
                position_outcome=outcome_str,
                fresh_price=str(fresh_price) if fresh_price else "N/A",
            )

            # Fallback: If price is ~$1 (100¢), market is effectively resolved
            # This catches cases where API resolution check fails
            from src.platforms.base import MarketResolution
            is_resolved = resolution.is_resolved
            if not is_resolved and fresh_price:
                # Price of 0.99+ or 0.01- indicates resolution
                if fresh_price >= Decimal("0.99"):
                    logger.info("Detected resolved market via price (winner)", position_id=pos.id, price=str(fresh_price))
                    is_resolved = True
                    resolution = MarketResolution(is_resolved=True, winning_outcome=outcome_str.lower(), resolution_time=None)
                elif fresh_price <= Decimal("0.01"):
                    logger.info("Detected resolved market via price (loser)", position_id=pos.id, price=str(fresh_price))
                    is_resolved = True
                    resolution = MarketResolution(is_resolved=True, winning_outcome="no" if outcome_str == "YES" else "yes", resolution_time=None)

            if is_resolved:
                # Show Redeem button for resolved markets
                if resolution.winning_outcome and resolution.winning_outcome.upper() == outcome_str:
                    buttons.append([
                        InlineKeyboardButton(
                            f"🏆 Redeem {btn_outcome}: {short_title}",
                            callback_data=f"redeem:{pos.id}"
                        ),
                        InlineKeyboardButton(
                            f"📤 Share Win",
                            callback_data=f"wincard:{pos.id}"
                        )
                    ])
                else:
                    # Lost position - show as expired
                    buttons.append([
                        InlineKeyboardButton(
                            f"❌ Lost: {short_title}",
                            callback_data=f"noop"
                        )
                    ])
            else:
                # Show Sell button for active markets
                buttons.append([
                    InlineKeyboardButton(
                        f"💰 Sell {btn_outcome}: {short_title}",
                        callback_data=f"sell:{pos.id}"
                    )
                ])
        except Exception as e:
            logger.warning("Resolution check failed, defaulting to Sell", error=str(e), position_id=pos.id)
            # Default to Sell if we can't check resolution
            buttons.append([
                InlineKeyboardButton(
                    f"💰 Sell {btn_outcome}: {short_title}",
                    callback_data=f"sell:{pos.id}"
                )
            ])

    # Add pagination buttons
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("« Prev", callback_data=f"positions:{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=f"positions:{page + 1}"))
        buttons.append(nav_buttons)

    if is_callback:
        if buttons:
            await target.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await target.edit_message_text(text, parse_mode=ParseMode.HTML)
    else:
        if buttons:
            await target.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await target.reply_text(text, parse_mode=ParseMode.HTML)


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /orders command - show order history."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    await show_orders(update.message, update.effective_user.id, page=0, is_callback=False)


async def show_orders(target, telegram_id: int, page: int = 0, is_callback: bool = False) -> None:
    """Show user orders with pagination."""
    ORDERS_PER_PAGE = 5

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        return

    # Fetch up to 100 orders for pagination
    all_orders = await get_user_orders(
        user_id=user.id,
        platform=user.active_platform,
        limit=100,
    )

    platform_info = PLATFORM_INFO[user.active_platform]

    if not all_orders:
        text = (
            f"📋 <b>No Order History</b>\n\n"
            f"You haven't placed any orders on {platform_info['name']} yet."
        )
        if is_callback:
            await target.edit_message_text(text, parse_mode=ParseMode.HTML)
        else:
            await target.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # Calculate pagination
    total_orders = len(all_orders)
    total_pages = (total_orders + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start_idx = page * ORDERS_PER_PAGE
    end_idx = start_idx + ORDERS_PER_PAGE
    orders = all_orders[start_idx:end_idx]

    # Build header with page info
    if total_pages > 1:
        text = f"📋 <b>Orders on {platform_info['name']}</b> (Page {page + 1}/{total_pages})\n\n"
    else:
        text = f"📋 <b>Recent Orders on {platform_info['name']}</b>\n\n"

    status_emoji = {
        "confirmed": "✅",
        "pending": "⏳",
        "submitted": "📤",
        "failed": "❌",
        "cancelled": "🚫",
    }

    for i, order in enumerate(orders, start=start_idx + 1):
        side = order.side.value.upper()
        outcome = order.outcome.value.upper()
        status = status_emoji.get(order.status.value, "❓")
        amount = format_usd(Decimal(order.input_amount) / Decimal(10**6))

        # Truncate market title if too long
        market_title = order.market_title or "Unknown Market"
        if len(market_title) > 40:
            market_title = market_title[:37] + "..."

        # Format price
        price_str = ""
        if order.price:
            price_str = f" @ {order.price:.2f}"

        text += f"{i}. {status} {side} {outcome}{price_str} • {amount}\n"
        text += f"   <i>{market_title}</i>\n"
        if order.tx_hash:
            # Polymarket uses CLOB - tx_hash is order ID, not blockchain tx
            if order.platform == Platform.POLYMARKET:
                text += f"   Order: <code>{order.tx_hash[:16]}...</code>\n"
            else:
                text += f"   <a href='{get_platform(order.platform).get_explorer_url(order.tx_hash)}'>View TX</a>\n"
        text += "\n"

    # Build pagination buttons
    buttons = []
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("« Prev", callback_data=f"orders:{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=f"orders:{page + 1}"))
        buttons.append(nav_buttons)

    if is_callback:
        if buttons:
            await target.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)
        else:
            await target.edit_message_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        if buttons:
            await target.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)
        else:
            await target.reply_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pnl command - show profit and loss summary."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    platform_info = PLATFORM_INFO[user.active_platform]
    platform = get_platform(user.active_platform)

    # Get time boundaries
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Get all orders for PnL calculation
    all_orders = await get_orders_for_pnl(user.id, platform=user.active_platform)
    day_orders = await get_orders_for_pnl(user.id, platform=user.active_platform, since=day_start)
    month_orders = await get_orders_for_pnl(user.id, platform=user.active_platform, since=month_start)

    # Get positions for unrealized PnL
    positions = await get_positions_for_pnl(user.id, platform=user.active_platform, include_open=True, include_closed=False)

    # Calculate realized PnL from orders
    # BUY orders = cost (negative), SELL orders = proceeds (positive)
    def calculate_realized_pnl(orders):
        total_cost = Decimal("0")
        total_proceeds = Decimal("0")
        for order in orders:
            try:
                amount = Decimal(order.input_amount) / Decimal(10**6)
                if order.side.value == "buy":
                    total_cost += amount
                else:  # sell
                    total_proceeds += amount
            except Exception:
                pass
        return total_proceeds - total_cost

    realized_day = calculate_realized_pnl(day_orders)
    realized_month = calculate_realized_pnl(month_orders)
    realized_all = calculate_realized_pnl(all_orders)

    # Calculate unrealized PnL from open positions
    unrealized_pnl = Decimal("0")
    total_invested = Decimal("0")
    positions_count = 0

    for pos in positions:
        try:
            token_amount = Decimal(pos.token_amount) / Decimal(10**6)
            entry_price = pos.entry_price if pos.entry_price else Decimal("0")
            cost_basis = token_amount * entry_price
            total_invested += cost_basis
            positions_count += 1

            # Fetch current price from platform - try event_id (slug) first for Limitless
            # Use include_closed=True to get prices for closed/resolved markets
            current_price = None
            try:
                lookup_id = pos.event_id if pos.event_id else pos.market_id
                market = await platform.get_market(lookup_id, search_title=pos.market_title, include_closed=True)
                if not market and pos.event_id:
                    market = await platform.get_market(pos.market_id, search_title=pos.market_title, include_closed=True)
                if market:
                    outcome_str = pos.outcome.upper() if isinstance(pos.outcome, str) else pos.outcome.value.upper()
                    if outcome_str == "YES":
                        current_price = market.yes_price
                    else:
                        current_price = market.no_price
            except Exception:
                pass

            if current_price:
                current_value = token_amount * current_price
                unrealized_pnl += current_value - cost_basis
        except Exception:
            pass

    # Format PnL values
    def format_pnl(value: Decimal) -> str:
        if value >= 0:
            return f"🟢 +${float(value):,.2f}"
        else:
            return f"🔴 -${float(abs(value)):,.2f}"

    def format_pnl_pct(value: Decimal, basis: Decimal) -> str:
        if basis == 0:
            return ""
        pct = (value / basis) * 100
        if pct >= 0:
            return f" (+{float(pct):.1f}%)"
        else:
            return f" ({float(pct):.1f}%)"

    text = f"📊 <b>P&L Summary - {platform_info['name']}</b>\n\n"

    # Today's PnL
    text += f"<b>📅 Today</b>\n"
    text += f"  Realized: {format_pnl(realized_day)}\n"
    text += f"  Trades: {len(day_orders)}\n\n"

    # This Month's PnL
    text += f"<b>📆 This Month</b>\n"
    text += f"  Realized: {format_pnl(realized_month)}\n"
    text += f"  Trades: {len(month_orders)}\n\n"

    # All-Time PnL
    text += f"<b>📈 All-Time</b>\n"
    text += f"  Realized: {format_pnl(realized_all)}\n"
    text += f"  Trades: {len(all_orders)}\n\n"

    # Unrealized PnL
    text += f"<b>💼 Open Positions</b>\n"
    text += f"  Positions: {positions_count}\n"
    text += f"  Invested: ${float(total_invested):,.2f}\n"
    text += f"  Unrealized: {format_pnl(unrealized_pnl)}{format_pnl_pct(unrealized_pnl, total_invested)}\n\n"

    # Total (Realized All-Time + Unrealized)
    total_pnl = realized_all + unrealized_pnl
    text += f"<b>💰 Total P&L</b>\n"
    text += f"  {format_pnl(total_pnl)}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def pnlcard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pnlcard command - generate shareable PnL card image."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    text = """📊 <b>Generate PnL Card</b>

Create a shareable image of your trading stats!

<b>Select a platform:</b>"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 Kalshi", callback_data="pnlcard:kalshi")],
        [InlineKeyboardButton("🔮 Polymarket", callback_data="pnlcard:polymarket")],
        [InlineKeyboardButton("🤖 Opinion", callback_data="pnlcard:opinion")],
        [InlineKeyboardButton("♾️ Limitless", callback_data="pnlcard:limitless")],
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def handle_pnlcard_generate(query: CallbackQuery, platform_value: str, telegram_id: int) -> None:
    """Handle PnL card generation for a specific platform."""
    try:
        platform = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform selection.")
        return

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    platform_info = PLATFORM_INFO[platform]

    # Show generating message
    await query.edit_message_text("⏳ Generating your PnL card...")

    # Get all orders for realized PnL calculation
    all_orders = await get_orders_for_pnl(user.id, platform=platform)

    # Calculate realized PnL and total invested
    total_cost = Decimal("0")
    total_proceeds = Decimal("0")

    for order in all_orders:
        try:
            amount = Decimal(order.input_amount) / Decimal(10**6)
            if order.side.value == "buy":
                total_cost += amount
            else:  # sell
                total_proceeds += amount
        except Exception:
            pass

    realized_pnl = total_proceeds - total_cost
    trade_count = len(all_orders)

    # Generate the PnL card image
    try:
        image_buffer = generate_pnl_card(
            platform=platform,
            platform_name=platform_info["name"],
            platform_emoji=platform_info["emoji"],
            total_pnl=realized_pnl,
            trade_count=trade_count,
            total_invested=total_cost,
        )

        # Send the image
        await query.message.reply_photo(
            photo=image_buffer,
            caption=f"📊 {platform_info['emoji']} {platform_info['name']} PnL Card\n\nGenerated by @SpreddMarketsBot",
        )

        # Update the original message
        await query.edit_message_text(
            f"✅ PnL card generated for {platform_info['name']}!\n\nUse /pnlcard to generate another.",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to generate PnL card", error=str(e), platform=platform_value)
        await query.edit_message_text(
            f"❌ Failed to generate PnL card: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_wincard_generate(query: CallbackQuery, position_id: str, telegram_id: int) -> None:
    """Handle win card generation for a specific winning position."""
    from src.services.pnl_card import generate_position_win_card

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get the position
    try:
        pos_id = int(position_id)
    except ValueError:
        await query.edit_message_text("Invalid position.")
        return

    position = await get_position_by_id(pos_id)
    if not position or position.user_id != user.id:
        await query.edit_message_text("Position not found.")
        return

    platform_enum = position.platform
    platform_info = PLATFORM_INFO[platform_enum]

    # Show generating message
    await query.edit_message_text("⏳ Generating your win card...")

    try:
        # Calculate profit
        entry_price = position.entry_price or Decimal("0.5")
        exit_price = Decimal("1.0")  # Winners resolve to $1

        # Token amount in USDC (6 decimals)
        token_amount = Decimal(position.token_amount) / Decimal(10**6)

        # Calculate profit: (exit - entry) * tokens
        profit_amount = (exit_price - entry_price) * token_amount

        # Calculate profit percentage
        if entry_price > 0:
            profit_percent = float(((exit_price - entry_price) / entry_price) * 100)
        else:
            profit_percent = 0.0

        # Determine outcome
        outcome = position.outcome.upper() if isinstance(position.outcome, str) else position.outcome.value.upper()

        # Generate the win card image
        image_buffer = generate_position_win_card(
            platform=platform_enum,
            platform_name=platform_info["name"],
            market_title=position.market_title,
            outcome=outcome,
            profit_amount=profit_amount,
            profit_percent=profit_percent,
            entry_price=entry_price,
            exit_price=exit_price,
        )

        # Send the image
        await query.message.reply_photo(
            photo=image_buffer,
            caption=f"🏆 <b>WINNER!</b>\n\n{escape_html(position.market_title)}\n\n+{profit_percent:.1f}% (+${float(profit_amount):.2f})\n\nGenerated by @SpreddMarketsBot",
            parse_mode=ParseMode.HTML,
        )

        # Update the original message
        await query.edit_message_text(
            f"✅ Win card generated!\n\nShare your victory on social media! 🎉",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to generate win card", error=str(e), position_id=position_id)
        await query.edit_message_text(
            f"❌ Failed to generate win card: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_sellwin_card(query: CallbackQuery, callback_data: str, telegram_id: int) -> None:
    """Handle win card generation for a profitable sell order.

    Args:
        callback_data: Format is "position_id:exit_price_x1000"
    """
    from src.services.pnl_card import generate_position_win_card

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Parse callback data: position_id:exit_price_x1000
    try:
        parts = callback_data.split(":")
        position_id = parts[0]
        exit_price_x1000 = int(parts[1])
        exit_price = Decimal(exit_price_x1000) / Decimal(1000)
    except (IndexError, ValueError):
        await query.edit_message_text("Invalid callback data.")
        return

    # Get the position (may be closed now)
    position = await get_position_by_id(position_id)
    if not position or position.user_id != user.id:
        await query.edit_message_text("Position not found.")
        return

    platform_enum = position.platform
    platform_info = PLATFORM_INFO[platform_enum]

    # Show generating message
    await query.edit_message_text("⏳ Generating your win card...")

    try:
        # Get entry price
        entry_price = position.entry_price or Decimal("0.5")

        # Token amount (use original full amount for percentage calculation)
        # Since we might have partial sold, use entry cost based approach
        token_amount = Decimal(position.token_amount) / Decimal(10**6) if position.token_amount != "0" else Decimal("1")

        # Calculate profit percentage (based on price movement)
        if entry_price > 0:
            profit_percent = float(((exit_price - entry_price) / entry_price) * 100)
        else:
            profit_percent = 0.0

        # For the card, show a representative profit amount
        # Use a reasonable estimate based on typical position size
        profit_per_token = exit_price - entry_price
        profit_amount = profit_per_token * token_amount if token_amount > 0 else profit_per_token

        # Determine outcome
        outcome = position.outcome.upper() if isinstance(position.outcome, str) else position.outcome.value.upper()

        # Generate the win card image
        image_buffer = generate_position_win_card(
            platform=platform_enum,
            platform_name=platform_info["name"],
            market_title=position.market_title,
            outcome=outcome,
            profit_amount=profit_amount,
            profit_percent=profit_percent,
            entry_price=entry_price,
            exit_price=exit_price,
        )

        # Send the image
        await query.message.reply_photo(
            photo=image_buffer,
            caption=f"🎉 <b>Profitable Trade!</b>\n\n{escape_html(position.market_title)}\n\n+{profit_percent:.1f}%\n\nGenerated by @SpreddMarketsBot",
            parse_mode=ParseMode.HTML,
        )

        # Update the original message
        await query.edit_message_text(
            f"✅ Win card generated!\n\nShare your profit on social media! 🎉",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to generate sell win card", error=str(e), position_id=position_id)
        await query.edit_message_text(
            f"❌ Failed to generate win card: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /referral command - show referral space."""
    if not update.effective_user or not update.message:
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    # Get or create referral code
    referral_code = await get_or_create_referral_code(user.id)

    # Get referral stats
    stats = await get_referral_stats(user.id)

    # Get fee balances for all chains
    fee_balances = await get_all_fee_balances(user.id)

    # Organize by chain
    solana_balance = None
    evm_balance = None
    for balance in fee_balances:
        if balance.chain_family == ChainFamily.SOLANA:
            solana_balance = balance
        elif balance.chain_family == ChainFamily.EVM:
            evm_balance = balance

    # Format amounts
    solana_claimable = format_usdc(solana_balance.claimable_usdc) if solana_balance else "$0.00"
    solana_earned = format_usdc(solana_balance.total_earned_usdc) if solana_balance else "$0.00"
    evm_claimable = format_usdc(evm_balance.claimable_usdc) if evm_balance else "$0.00"
    evm_earned = format_usdc(evm_balance.total_earned_usdc) if evm_balance else "$0.00"

    # Calculate totals
    total_claimable = Decimal(solana_balance.claimable_usdc if solana_balance else "0") + \
                      Decimal(evm_balance.claimable_usdc if evm_balance else "0")
    total_earned = Decimal(solana_balance.total_earned_usdc if solana_balance else "0") + \
                   Decimal(evm_balance.total_earned_usdc if evm_balance else "0")

    # Build invite link
    bot_username = (await context.bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start=ref_{referral_code}"

    # Calculate total reach
    total_reach = stats["tier1"] + stats["tier2"] + stats["tier3"]

    text = f"""
🫂 <b>Referral Space</b>
Earn commissions when your referrals trade!

🪪 <b>Your Code:</b> <code>{referral_code}</code>
🔗 <b>Invite Link:</b>
<code>{invite_link}</code>

━━━━━━━━━━━━━━━━
🛰 <b>Network Metrics</b>
├ Tier 1 (Direct): <b>{stats["tier1"]}</b> users (25%)
├ Tier 2: <b>{stats["tier2"]}</b> users (5%)
├ Tier 3: <b>{stats["tier3"]}</b> users (3%)
└ Total Reach: <b>{total_reach}</b> users

━━━━━━━━━━━━━━━━
💰 <b>Earnings Dashboard</b>

<b>🟣 Solana (Kalshi)</b>
├ Claimable: <b>{solana_claimable}</b> USDC
└ Total Earned: <b>{solana_earned}</b> USDC

<b>🔷 EVM (Polymarket/Opinion/Limitless/Myriad)</b>
├ Claimable: <b>{evm_claimable}</b> USDC
└ Total Earned: <b>{evm_earned}</b> USDC

📊 <b>Combined:</b> {format_usdc(str(total_claimable))} claimable / {format_usdc(str(total_earned))} earned

⚠️ <i>Minimum withdrawal: ${MIN_WITHDRAWAL_USDC} USDC per chain</i>
"""

    # Build keyboard
    buttons = [
        [InlineKeyboardButton("📋 Copy Invite Link", callback_data="referral:copy")],
    ]

    # Add withdraw buttons for each chain that meets minimum
    withdraw_buttons = []
    if solana_balance and can_withdraw(solana_balance.claimable_usdc):
        withdraw_buttons.append(
            InlineKeyboardButton("💸 Withdraw Solana", callback_data="referral:withdraw:solana")
        )
    if evm_balance and can_withdraw(evm_balance.claimable_usdc):
        withdraw_buttons.append(
            InlineKeyboardButton("💸 Withdraw EVM", callback_data="referral:withdraw:evm")
        )
    if withdraw_buttons:
        buttons.append(withdraw_buttons)

    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="referral:refresh")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ===================
# DFlow Proof KYC Gate
# ===================

async def check_and_gate_proof_kyc(query, user, telegram_id: int) -> bool:
    """Check DFlow Proof KYC verification and gate Kalshi trading if not verified.

    Returns True if verified (or not applicable), False if blocked.
    """
    from src.db.database import get_wallet

    # Check if user has a Solana wallet (Kalshi users)
    wallet = await get_wallet(user.id, ChainFamily.SOLANA)
    if not wallet:
        return True  # No Solana wallet — not a Kalshi user, skip

    # Already verified (permanent, cached in DB)
    if user.proof_verified_at:
        return True

    # Check Proof API
    verified = await check_proof_verified(wallet.public_key)
    if verified:
        await set_user_proof_verified(user.id)
        return True

    # Not verified — show KYC prompt
    try:
        keypair = await wallet_service.get_solana_keypair(user.id, telegram_id)
        if keypair:
            deep_link = generate_proof_deep_link(keypair, settings.telegram_bot_username)
        else:
            deep_link = "https://dflow.net/proof"
    except Exception:
        deep_link = "https://dflow.net/proof"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 Start Verification", url=deep_link)],
        [InlineKeyboardButton("✅ I've Completed KYC", callback_data="proof_retry")],
        [InlineKeyboardButton("🔄 Select Different Platform", callback_data="menu:platform")],
    ])

    await query.edit_message_text(
        "🔐 <b>Identity Verification Required</b>\n\n"
        "DFlow now requires identity verification (KYC) before "
        "trading on Kalshi prediction markets.\n\n"
        "Tap below to complete verification (~2 min):\n"
        "• Email authentication\n"
        "• Government ID upload\n"
        "• Quick selfie check\n\n"
        "Your wallet will be automatically linked.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    return False


async def handle_proof_retry(query, telegram_id: int) -> None:
    """Handle 'I've Completed KYC' button — re-check Proof API."""
    from src.db.database import get_wallet

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    wallet = await get_wallet(user.id, ChainFamily.SOLANA)
    if not wallet:
        await query.edit_message_text("No Solana wallet found. Please /start first!")
        return

    await query.edit_message_text("⏳ Checking verification status...")

    verified = await check_proof_verified(wallet.public_key)

    if verified:
        await set_user_proof_verified(user.id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Continue Trading", callback_data="menu:platform")],
        ])
        await query.edit_message_text(
            "✅ <b>Identity Verified!</b>\n\n"
            "Your wallet has been verified. You can now trade on Kalshi.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        # Not yet verified — show link again
        try:
            keypair = await wallet_service.get_solana_keypair(user.id, telegram_id)
            if keypair:
                deep_link = generate_proof_deep_link(keypair, settings.telegram_bot_username)
            else:
                deep_link = "https://dflow.net/proof"
        except Exception:
            deep_link = "https://dflow.net/proof"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Start Verification", url=deep_link)],
            [InlineKeyboardButton("✅ I've Completed KYC", callback_data="proof_retry")],
            [InlineKeyboardButton("🔄 Select Different Platform", callback_data="menu:platform")],
        ])
        await query.edit_message_text(
            "⏳ <b>Not Verified Yet</b>\n\n"
            "Your wallet hasn't been verified yet. Please complete "
            "the verification process and try again.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


# ===================
# Callback Handlers
# ===================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle all callback queries from inline buttons."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    action = parts[0]
    
    try:
        if action == "landing":
            # User clicked "Get Started" on landing page - show platform selection
            if parts[1] == "start":
                text = """
🎯 <b>Choose Your Platform</b>

Select which prediction market you want to trade on:
"""
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=platform_keyboard(),
                )

        elif action == "platform":
            await handle_platform_select(query, parts[1], update.effective_user.id)
        
        elif action == "market":
            await handle_market_view(query, parts[1], parts[2], update.effective_user.id)
        
        elif action == "buy":
            await handle_buy_start(query, parts[1], parts[2], parts[3], update.effective_user.id, context)

        elif action == "buy_start":
            # Retry button handler - same as buy
            await handle_buy_start(query, parts[1], parts[2], parts[3], update.effective_user.id, context)

        elif action == "confirm_buy":
            # Read from user_data (stored when quote was shown)
            pending = context.user_data.get("pending_confirm")
            if pending:
                context.user_data.pop("pending_confirm", None)
                await handle_buy_confirm(
                    query,
                    pending["platform"],
                    pending["market_id"],
                    pending["outcome"],
                    pending["amount"],
                    update.effective_user.id
                )
            else:
                await query.edit_message_text("❌ Order expired. Please try again.")

        elif action == "cancel_buy":
            context.user_data.pop("pending_confirm", None)
            await query.edit_message_text("❌ Order cancelled.")

        elif action == "polychain":
            await handle_polymarket_chain_select(query, parts[1], update.effective_user.id)

        elif action == "wallet":
            if parts[1] == "refresh":
                await handle_wallet_refresh(query, update.effective_user.id)
            elif parts[1] == "export":
                await handle_wallet_export(query, update.effective_user.id)
            elif parts[1] == "create_new":
                await handle_wallet_create_new(query, update.effective_user.id, context)
            elif parts[1] == "confirm_create":
                await handle_wallet_confirm_create(query, update.effective_user.id, context)
            elif parts[1] == "bridge":
                await handle_bridge_menu(query, update.effective_user.id, context)
            elif parts[1] == "setup":
                await handle_wallet_setup(query, update.effective_user.id, context)

        elif action == "bridge":
            # New format: bridge:dest:chain, bridge:source:source:dest, bridge:amount:source:dest:percent
            # Legacy format: bridge:start:source, bridge:amount:source:percent, bridge:custom:source
            logger.info("Bridge callback received", callback_data=data, parts=parts)
            if parts[1] == "action":
                # bridge:action:usdc/swap/gas - simplified action menu
                if parts[2] == "usdc":
                    await handle_bridge_usdc_menu(query, update.effective_user.id, context)
                elif parts[2] == "swap":
                    await handle_swap_menu(query, update.effective_user.id, context)
                elif parts[2] == "gas":
                    await handle_gas_bridge_menu(query, update.effective_user.id, context)
            elif parts[1] == "dest":
                # bridge:dest:chain - user selected destination chain
                await handle_bridge_dest(query, parts[2], update.effective_user.id, context)
            elif parts[1] == "source":
                # bridge:source:source_chain:dest_chain - user selected source chain
                await handle_bridge_start(query, parts[2], update.effective_user.id, context, dest_chain=parts[3])
            elif parts[1] == "amount":
                # New: bridge:amount:source:dest:percent or Legacy: bridge:amount:source:percent
                if len(parts) == 5:
                    # New format with destination
                    await handle_bridge_amount(query, parts[2], parts[3], int(parts[4]), update.effective_user.id, context)
                else:
                    # Legacy format - assume polygon destination
                    await handle_bridge_amount(query, parts[2], "polygon", int(parts[3]), update.effective_user.id, context)
            elif parts[1] == "custom":
                # New: bridge:custom:source:dest or Legacy: bridge:custom:source
                if len(parts) == 4:
                    await handle_bridge_custom(query, parts[2], parts[3], update.effective_user.id, context)
                else:
                    await handle_bridge_custom(query, parts[2], "polygon", update.effective_user.id, context)
            elif parts[1] == "speed":
                # bridge:speed:source:dest:mode or legacy bridge:speed:source:mode
                if len(parts) == 5:
                    await handle_bridge_speed(query, parts[2], parts[3], parts[4], update.effective_user.id, context)
                else:
                    await handle_bridge_speed(query, parts[2], "polygon", parts[3], update.effective_user.id, context)
            elif parts[1] == "start":
                # Legacy: bridge:start:source_chain - assume polygon destination
                await handle_bridge_start(query, parts[2], update.effective_user.id, context, dest_chain="polygon")
            elif parts[1] == "swap" and parts[2] == "bsc_usdt":
                # Swap BSC USDC → USDT for Opinion Labs
                await handle_bsc_usdc_swap(query, update.effective_user.id, context)
            elif parts[1] == "swap_exec":
                # Execute BSC USDC → USDT swap
                await handle_bsc_swap_execute(query, int(parts[2]), update.effective_user.id, context)
            else:
                # bridge:source_chain - legacy format
                logger.info("Using legacy bridge format", chain=parts[1])
                await handle_bridge_start(query, parts[1], update.effective_user.id, context, dest_chain="polygon")

        elif action == "swap":
            # Token → USDC swaps
            # Format: swap:native:{chain}, swap:erc20:{token_key}, swap:amount:{chain}:{percent}, swap:confirm
            if parts[1] == "native":
                # swap:native:polygon - user wants to swap native token on chain
                await handle_native_swap(query, parts[2], update.effective_user.id, context)
            elif parts[1] == "erc20":
                # swap:erc20:virtual - user wants to swap an ERC-20 token
                await handle_erc20_swap(query, parts[2], update.effective_user.id, context)
            elif parts[1] == "amount":
                # swap:amount:{chain}:{percent} - user selected swap amount
                await handle_native_swap_amount(query, parts[2], int(parts[3]), update.effective_user.id, context)
            elif parts[1] == "confirm":
                # swap:confirm - user confirmed the swap (quote stored in user_data)
                await handle_native_swap_confirm(query, update.effective_user.id, context)

        elif action == "gas_bridge":
            # Native token bridging (ETH/POL between chains)
            # Format: gas_bridge:source:{chain}, gas_bridge:dest:{source}:{dest},
            #         gas_bridge:amount:{source}:{dest}:{percent}, gas_bridge:confirm
            if parts[1] == "source":
                # gas_bridge:source:base - user wants to bridge from this chain
                await handle_gas_bridge_source(query, parts[2], update.effective_user.id, context)
            elif parts[1] == "dest":
                # gas_bridge:dest:{source}:{dest} - user selected destination
                await handle_gas_bridge_dest(query, parts[2], parts[3], update.effective_user.id, context)
            elif parts[1] == "amount":
                # gas_bridge:amount:{source}:{dest}:{percent}
                await handle_gas_bridge_amount(query, parts[2], parts[3], int(parts[4]), update.effective_user.id, context)
            elif parts[1] == "confirm":
                # gas_bridge:confirm - execute the bridge
                await handle_gas_bridge_confirm(query, update.effective_user.id, context)

        elif action == "export":
            await handle_export_key(query, parts[1], update.effective_user.id, context)

        elif action == "markets":
            if parts[1] == "refresh":
                await handle_markets_refresh(query, update.effective_user.id, page=0)
            elif parts[1] == "page":
                page = int(parts[2]) if len(parts) > 2 else 0
                await handle_markets_refresh(query, update.effective_user.id, page=page)
            elif parts[1] == "15m":
                await handle_15m_markets(query, update.effective_user.id, page=0)
            elif parts[1] == "hourly":
                await handle_hourly_markets(query, update.effective_user.id, page=0)
            elif parts[1] == "5m":
                await handle_5m_markets(query, update.effective_user.id, page=0)

        elif action == "markets15m":
            # 15-minute markets pagination: markets15m:page:X
            page = int(parts[2]) if len(parts) > 2 else 0
            await handle_15m_markets(query, update.effective_user.id, page=page)

        elif action == "marketshourly":
            # Hourly markets pagination: marketshourly:page:X
            page = int(parts[2]) if len(parts) > 2 else 0
            await handle_hourly_markets(query, update.effective_user.id, page=page)

        elif action == "markets5m":
            # 5-minute markets pagination: markets5m:page:X
            page = int(parts[2]) if len(parts) > 2 else 0
            await handle_5m_markets(query, update.effective_user.id, page=page)

        elif action == "categories":
            await handle_categories_menu(query, update.effective_user.id)

        elif action == "category":
            # Format: category:category_id or category:category_id:page
            page = int(parts[2]) if len(parts) > 2 else 0
            await handle_category_view(query, parts[1], update.effective_user.id, page=page)

        elif action == "positions":
            # Format: positions:page or positions:view or positions:refresh
            page = 0
            if len(parts) > 1 and parts[1] not in ("view", "refresh"):
                try:
                    page = int(parts[1])
                except ValueError:
                    page = 0
            await show_positions(query, update.effective_user.id, page=page, is_callback=True)

        elif action == "orders":
            # Format: orders:page
            page = int(parts[1]) if len(parts) > 1 else 0
            await show_orders(query, update.effective_user.id, page=page, is_callback=True)

        elif action == "sell":
            # Format: sell:position_id
            await handle_sell_start(query, parts[1], update.effective_user.id)

        elif action == "sell_start":
            # Retry button handler - same as sell
            await handle_sell_start(query, parts[1], update.effective_user.id)

        elif action == "sell_confirm":
            # Format: sell_confirm:position_id:percent
            await handle_sell_confirm(query, parts[1], parts[2], update.effective_user.id)

        elif action == "redeem":
            # Format: redeem:position_id
            await handle_redeem(query, parts[1], update.effective_user.id)

        elif action == "wincard":
            # Format: wincard:position_id
            await handle_wincard_generate(query, parts[1], update.effective_user.id)

        elif action == "sellwin":
            # Format: sellwin:position_id:exit_price_x1000 - generate win card from sell
            # Combine parts after action to preserve the position_id:price format
            callback_data = ":".join(parts[1:])
            await handle_sellwin_card(query, callback_data, update.effective_user.id)

        elif action == "menu":
            if parts[1] == "main":
                await handle_main_menu(query, update.effective_user.id)
            elif parts[1] == "platform":
                await handle_platform_menu(query, update.effective_user.id)

        elif action == "faq":
            await handle_faq_topic(query, parts[1])

        elif action == "referral":
            # parts[1] is the action, parts[2] might be chain_family for withdraw
            chain_param = parts[2] if len(parts) > 2 else None
            await handle_referral_action(query, parts[1], update.effective_user.id, context, chain_param)

        elif action == "pnlcard":
            # Format: pnlcard:platform
            await handle_pnlcard_generate(query, parts[1], update.effective_user.id)

        elif action == "geo":
            # IP-based geo verification
            # Formats: geo:verify, geo:verify:platform
            if parts[1] == "verify":
                pending_platform = parts[2] if len(parts) > 2 else None
                await show_geo_verification(query, update.effective_user.id, pending_platform)

        elif action == "proof_retry":
            # User clicked "I've Completed KYC" — re-check Proof API
            await handle_proof_retry(query, update.effective_user.id)

        elif action == "more":
            # View more options for multi-outcome market
            # Format: more:platform:market_id:offset (shortened from market_more for 64-byte limit)
            offset = int(parts[3]) if len(parts) > 3 else 0
            await handle_market_more_options(query, parts[1], parts[2], offset, update.effective_user.id)

        elif action == "ai_research":
            # AI Research for market
            # Format: ai_research:platform:market_id
            await handle_ai_research(query, parts[1], parts[2], update.effective_user.id)

        elif action == "analytics":
            # Admin analytics dashboard
            # Formats: analytics:period, analytics:platforms, analytics:plat:period, analytics:traders, analytics:top:period, analytics:referrers, analytics:ref:period
            if parts[1] == "platforms":
                await handle_analytics_platforms(query, update.effective_user.id)
            elif parts[1] == "plat":
                # Platform breakdown with time period
                period = parts[2] if len(parts) > 2 else "all"
                await handle_analytics_platforms(query, update.effective_user.id, period)
            elif parts[1] == "traders":
                await handle_analytics_traders(query, update.effective_user.id)
            elif parts[1] == "top":
                # Top traders with time period
                period = parts[2] if len(parts) > 2 else "all"
                await handle_analytics_traders(query, update.effective_user.id, period)
            elif parts[1] == "referrers":
                await handle_analytics_referrers(query, update.effective_user.id)
            elif parts[1] == "ref":
                # Top referrers with time period
                period = parts[2] if len(parts) > 2 else "all"
                await handle_analytics_referrers(query, update.effective_user.id, period)
            else:
                # Time period selection (daily, weekly, monthly, all)
                await handle_analytics_callback(query, parts[1], update.effective_user.id)

        elif action == "arbitrage":
            await handle_arbitrage_callback(query, parts[1], update.effective_user.id)

        elif action == "alerts":
            await handle_alerts_callback(query, parts[1], update.effective_user.id)

        elif action == "arb_trade":
            # Format: arb_trade:platform:market_id:outcome:side
            await handle_arb_trade(query, parts[1], parts[2], parts[3], parts[4], update.effective_user.id, context)

        elif action == "arb_amount":
            # Format: arb_amount:platform:market_id:outcome:side:amount
            await handle_arb_amount(query, parts[1], parts[2], parts[3], parts[4], parts[5], update.effective_user.id, context)

        elif action == "cancel_arb":
            context.user_data.pop("pending_arb_trade", None)
            await query.edit_message_text("❌ Trade cancelled.")

        elif action == "view_market":
            # Format: view_market:platform:market_id
            await handle_view_market_from_arb(query, parts[1], parts[2], update.effective_user.id)

    except Exception as e:
        error_str = str(e)
        # Silently ignore "message not modified" errors (happens on refresh with no changes)
        if "message is not modified" in error_str.lower():
            return
        logger.error("Callback handler error", error=error_str, data=data)
        try:
            await query.edit_message_text(
                f"❌ Error: {friendly_error(error_str)}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass  # Ignore errors when showing error message


async def handle_platform_select(query, platform_value: str, telegram_id: int) -> None:
    """Handle platform selection."""
    try:
        platform = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform selection.")
        return

    # Get user first to check country for geo-blocking
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Check DFlow Proof KYC for Kalshi (replaces geo-blocking — Proof handles compliance)
    if platform == Platform.KALSHI:
        if not await check_and_gate_proof_kyc(query, user, telegram_id):
            return

    # Polymarket: show chain picker instead of immediately selecting
    if platform == Platform.POLYMARKET:
        text = """
🔮 <b>Polymarket</b>

Choose your settlement chain:
"""
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⬡ Polygon", callback_data="polychain:polygon"),
                InlineKeyboardButton("◎ Solana", callback_data="polychain:solana"),
            ],
            [InlineKeyboardButton("🔄 Switch Platform", callback_data="menu:platform")],
        ])
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    await update_user_platform(telegram_id, platform)

    info = PLATFORM_INFO[platform]
    chain_family = get_chain_family_for_platform(platform)

    # Check if user has wallets
    from src.db.database import get_user_wallets
    existing_wallets = await get_user_wallets(user.id)

    if not existing_wallets:
        # No wallets - redirect to wallet setup with PIN
        text = f"""
{info['emoji']} <b>{info['name']} Selected!</b>

Before you can trade, you need to set up your wallet.

<b>Use /wallet to create your secure wallets with PIN protection.</b>
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Set Up Wallet", callback_data="wallet:setup")],
            [InlineKeyboardButton("🔄 Switch Platform", callback_data="menu:platform")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    # User has wallets - show normal platform selected screen
    wallet = None
    for w in existing_wallets:
        if w.chain_family == chain_family:
            wallet = w
            break
    wallet_addr = wallet.public_key if wallet else "Not created"

    text = f"""
{info['emoji']} <b>{info['name']} Selected!</b>

Chain: {info['chain']}
Collateral: {info['collateral']}

Your {info['chain']} Wallet:
<code>{wallet_addr}</code>

<b>What would you like to do?</b>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Browse Markets", callback_data="markets:refresh")],
        [InlineKeyboardButton("🔍 Search Markets", callback_data="menu:search")],
        [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        [InlineKeyboardButton("🔄 Switch Platform", callback_data="menu:platform")],
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def show_geo_verification(query, telegram_id: int, pending_platform: str = None) -> None:
    """Prompt user to open the Mini App for automatic IP-based geo verification."""
    miniapp_url = settings.miniapp_url

    if not miniapp_url:
        text = """
⚠️ <b>Configuration Required</b>

Geo verification is not configured. Please contact support.
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Select Different Platform", callback_data="menu:platform")],
        ])
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    text = """
🌍 <b>Location Verification Required</b>

To comply with regulatory requirements, we need to verify your location before you can access Kalshi markets.

<b>Tap the button below to verify your location:</b>

⚠️ <i>Make sure you're not using a VPN for accurate verification.</i>

This verification is valid for 30 days.
"""

    # Open geo check page which detects IP and shows result
    verify_url = f"{miniapp_url.rstrip('/')}/api/v1/geo/check"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌍 Verify My Location", web_app=WebAppInfo(url=verify_url))],
        [InlineKeyboardButton("🔄 Select Different Platform", callback_data="menu:platform")],
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_platform_menu(query, telegram_id: int) -> None:
    """Show platform selection menu."""
    user = await get_user_by_telegram_id(telegram_id)

    current_text = ""
    if user:
        current_info = PLATFORM_INFO[user.active_platform]
        current_text = f"Current: {current_info['emoji']} <b>{current_info['name']}</b>\n\n"

    text = f"""
🔄 <b>Switch Platform</b>

{current_text}Select a platform:
"""

    buttons = []
    for platform_id in platform_registry.all_platforms:
        info = PLATFORM_INFO[platform_id]
        if info.get("hidden"):
            continue
        label = f"{info['emoji']} {info['name']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"platform:{platform_id.value}")])

    buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_market_view(query, platform_value: str, market_id: str, telegram_id: int) -> None:
    """Handle viewing a specific market."""
    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform.")
        return

    platform = get_platform(platform_enum)
    market = await platform.get_market(market_id)

    # Truncate market_id for callback_data (Telegram 64-byte limit)
    # Polymarket condition IDs can be 66+ chars, which exceeds the limit
    short_market_id = market_id[:40]

    if not market:
        await query.edit_message_text("Market not found.")
        return

    info = PLATFORM_INFO[platform_enum]
    expiration_text = format_expiration(market.close_time)

    # Check if this is a multi-outcome event
    related_markets = []
    if market.is_multi_outcome and market.event_id:
        related_markets = await platform.get_related_markets(market.event_id)

    if related_markets and len(related_markets) > 1:
        # Multi-outcome event - show all options
        # Check if this looks like a player props market (has Over/Under pattern)
        def check_player_prop(rm):
            """Check if a market is a player prop by looking for over/under keywords."""
            import re
            def has_ou_keywords(text):
                """Check for over/under patterns as whole words (not substrings like 'thunder')."""
                if not text:
                    return False
                t = text.lower()
                # Use word boundaries to avoid matching "thunder" -> "under"
                if re.search(r'\bover\b', t) or re.search(r'\bunder\b', t):
                    return True
                # Also check abbreviations
                return "o/u" in t or " ou " in t

            # Check title
            if rm.title and has_ou_keywords(rm.title):
                return True
            # Check outcome_name
            if rm.outcome_name and has_ou_keywords(rm.outcome_name):
                return True
            # Check raw_data for question or groupItemTitle (Polymarket structure)
            if rm.raw_data and isinstance(rm.raw_data, dict):
                # Polymarket: nested under "market" key
                market_raw = rm.raw_data.get("market", {})
                if isinstance(market_raw, dict):
                    question = market_raw.get("question") or market_raw.get("groupItemTitle") or ""
                    if has_ou_keywords(question):
                        return True
                # Kalshi: direct fields at top level
                kalshi_title = rm.raw_data.get("title") or rm.raw_data.get("question") or ""
                kalshi_subtitle = rm.raw_data.get("yesSubtitle") or rm.raw_data.get("subtitle") or ""
                if has_ou_keywords(kalshi_title) or has_ou_keywords(kalshi_subtitle):
                    return True
            return False

        is_player_props = any(check_player_prop(rm) for rm in related_markets[:5])

        # Limit display items
        max_buttons = 8 if is_player_props else 15
        displayed_markets = related_markets[:max_buttons]

        # Fetch orderbook prices for all displayed markets in parallel
        from src.db.models import Outcome as OutcomeEnum
        import asyncio

        orderbook_prices = {}  # market_id -> {yes_ask, no_ask}

        async def fetch_orderbook_prices(rm):
            """Fetch orderbook prices for a single market."""
            try:
                yes_price = rm.yes_price  # fallback
                no_price = rm.no_price    # fallback

                # Get slug for orderbook lookup (needed for Limitless with numeric IDs)
                slug = None
                if rm.raw_data and isinstance(rm.raw_data, dict):
                    slug = rm.raw_data.get("slug")

                # Fetch YES orderbook
                try:
                    yes_ob = await platform.get_orderbook(rm.market_id, OutcomeEnum.YES, slug=slug)
                    if yes_ob and yes_ob.best_ask:
                        yes_price = yes_ob.best_ask
                except:
                    pass

                # Fetch NO orderbook
                try:
                    no_ob = await platform.get_orderbook(rm.market_id, OutcomeEnum.NO, slug=slug)
                    if no_ob and no_ob.best_ask:
                        no_price = no_ob.best_ask
                except:
                    pass

                return rm.market_id, {"yes_ask": yes_price, "no_ask": no_price}
            except Exception as e:
                return rm.market_id, {"yes_ask": rm.yes_price, "no_ask": rm.no_price}

        # Fetch all orderbooks in parallel
        try:
            results = await asyncio.gather(*[fetch_orderbook_prices(rm) for rm in displayed_markets])
            for market_id, prices in results:
                orderbook_prices[market_id] = prices
        except Exception as e:
            logger.warning("Failed to fetch orderbook prices for multi-outcome", error=str(e))

        text = f"""
{info['emoji']} <b>{escape_html(market.title)}</b>

📊 <b>Buy Prices</b> (from orderbook)
"""
        # Add each outcome with orderbook prices
        for i, rm in enumerate(displayed_markets, 1):
            name = rm.outcome_name or rm.title
            # Truncate long names
            if len(name) > 35:
                name = name[:32] + "..."

            # Get orderbook prices (or fallback to mid-price)
            prices = orderbook_prices.get(rm.market_id, {"yes_ask": rm.yes_price, "no_ask": rm.no_price})
            yes_price_str = format_probability(prices["yes_ask"]) if prices["yes_ask"] else "N/A"
            no_price_str = format_probability(prices["no_ask"]) if prices["no_ask"] else "N/A"

            if is_player_props:
                # For player props: show Over/Under format
                text += f"{i}. {escape_html(name)}\n   ⬆️ Over: {yes_price_str} | ⬇️ Under: {no_price_str}\n"
            else:
                # For other multi-outcome (like elections): show YES price
                text += f"{i}. {escape_html(name)}: {yes_price_str}\n"

        text += f"""
📈 <b>Stats</b>
Volume (24h): {format_usd(market.volume_24h)}
Liquidity: {format_usd(market.liquidity)}
Status: {"🟢 Active" if market.is_active else "🔴 Closed"}
Expires: {expiration_text}
"""
        # Show resolution criteria if available
        if market.resolution_criteria:
            criteria_text = market.resolution_criteria[:300]
            if len(market.resolution_criteria) > 300:
                criteria_text += "..."
            text += f"\n📋 <b>Resolution Rules</b>\n{escape_html(criteria_text)}\n"

        # Create buy buttons for each outcome with orderbook prices
        buttons = []
        for rm in displayed_markets:
            name = rm.outcome_name or rm.title
            # Truncate market_id to fit callback_data limit (64 bytes)
            short_id = rm.market_id[:40]

            # Get orderbook prices
            prices = orderbook_prices.get(rm.market_id, {"yes_ask": rm.yes_price, "no_ask": rm.no_price})

            if is_player_props:
                # For player props: show prop name button + Over/Under buttons below
                if len(name) > 30:
                    display_name = name[:27] + "..."
                else:
                    display_name = name
                yes_price_str = format_probability(prices["yes_ask"]) if prices["yes_ask"] else "?"
                no_price_str = format_probability(prices["no_ask"]) if prices["no_ask"] else "?"
                # Row 1: Prop name (clicking opens market details)
                buttons.append([
                    InlineKeyboardButton(
                        f"📊 {escape_html(display_name)}",
                        callback_data=f"market:{platform_value}:{short_id}"
                    )
                ])
                # Row 2: Over and Under buttons
                buttons.append([
                    InlineKeyboardButton(
                        f"⬆️ Over ({yes_price_str})",
                        callback_data=f"buy:{platform_value}:{short_id}:yes"
                    ),
                    InlineKeyboardButton(
                        f"⬇️ Under ({no_price_str})",
                        callback_data=f"buy:{platform_value}:{short_id}:no"
                    )
                ])
            else:
                # For other multi-outcome: single button per option
                if len(name) > 20:
                    name = name[:17] + "..."
                prob = format_probability(prices["yes_ask"])
                buttons.append([
                    InlineKeyboardButton(
                        f"{escape_html(name)} ({prob})",
                        callback_data=f"buy:{platform_value}:{short_id}:yes"
                    )
                ])

        # Show "more options" if there are more than max_buttons
        if len(related_markets) > max_buttons:
            remaining = len(related_markets) - max_buttons
            buttons.append([
                InlineKeyboardButton(
                    f"📋 View {remaining} more options...",
                    callback_data=f"more:{platform_value}:{short_market_id}:{max_buttons}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🤖 AI Research",
                callback_data=f"ai_research:{platform_value}:{short_market_id}"
            ),
        ])
        buttons.append([InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")])
        keyboard = InlineKeyboardMarkup(buttons)
    else:
        # Binary market - show YES/NO with orderbook prices
        # Fetch actual orderbook prices (what you'd pay to buy)
        from src.db.models import Outcome as OutcomeEnum
        yes_ask_price = market.yes_price  # fallback to mid-price
        no_ask_price = market.no_price    # fallback to mid-price

        # Check if this is an AMM market (Limitless has both CLOB and AMM)
        is_amm_market = False
        if market.raw_data and isinstance(market.raw_data, dict):
            trade_type = market.raw_data.get("tradeType", "").lower()
            is_amm_market = trade_type == "amm"

        # Get slug for orderbook lookup (needed for Limitless with numeric IDs)
        slug = None
        if market.raw_data and isinstance(market.raw_data, dict):
            slug = market.raw_data.get("slug")

        # Skip orderbook fetch for AMM markets (they don't have orderbooks)
        if not is_amm_market:
            try:
                # Get orderbook for YES - best_ask is what you pay to buy YES
                yes_orderbook = await platform.get_orderbook(market_id, OutcomeEnum.YES, slug=slug)
                if yes_orderbook and yes_orderbook.best_ask:
                    yes_ask_price = yes_orderbook.best_ask

                # Get orderbook for NO - best_ask is what you pay to buy NO
                no_orderbook = await platform.get_orderbook(market_id, OutcomeEnum.NO, slug=slug)
                if no_orderbook and no_orderbook.best_ask:
                    no_ask_price = no_orderbook.best_ask
            except Exception as e:
                logger.warning("Failed to fetch orderbook prices", market_id=market_id, error=str(e))

        # Check if this is a player prop market (contains over/under in title, outcome_name, or question)
        import re
        def has_ou_keywords(text):
            """Check for over/under patterns as whole words (not substrings like 'thunder')."""
            if not text:
                return False
            t = text.lower()
            if re.search(r'\bover\b', t) or re.search(r'\bunder\b', t):
                return True
            return "o/u" in t or " ou " in t

        # Check all relevant fields
        question_text = ""
        if market.raw_data and isinstance(market.raw_data, dict):
            market_raw = market.raw_data.get("market", {})
            if isinstance(market_raw, dict):
                question_text = market_raw.get("question") or market_raw.get("groupItemTitle") or ""

        is_player_prop = (
            has_ou_keywords(market.title) or
            has_ou_keywords(market.outcome_name) or
            has_ou_keywords(question_text)
        )

        # Check if market has custom outcome names (not just "Yes"/"No")
        def is_custom_outcome_name(name: str) -> bool:
            """Check if outcome name is different from default Yes/No."""
            if not name:
                return False
            normalized = name.strip().lower()
            return normalized not in ("yes", "no", "y", "n")

        has_custom_outcomes = (
            market.yes_outcome_name and market.no_outcome_name and
            (is_custom_outcome_name(market.yes_outcome_name) or is_custom_outcome_name(market.no_outcome_name))
        )

        if is_player_prop:
            # Player prop - show Over/Under labels
            yes_label = "⬆️ Over"
            no_label = "⬇️ Under"
            yes_btn_label = f"⬆️ Buy OVER ({format_probability(yes_ask_price)})"
            no_btn_label = f"⬇️ Buy UNDER ({format_probability(no_ask_price)})"
        elif has_custom_outcomes:
            # Matchup market with named outcomes (e.g., "Magic vs Cavaliers")
            yes_name = market.yes_outcome_name
            no_name = market.no_outcome_name
            # Truncate long names
            if len(yes_name) > 20:
                yes_name = yes_name[:17] + "..."
            if len(no_name) > 20:
                no_name = no_name[:17] + "..."
            yes_label = f"🏆 {yes_name}"
            no_label = f"🏆 {no_name}"
            yes_btn_label = f"🏆 Buy {yes_name} ({format_probability(yes_ask_price)})"
            no_btn_label = f"🏆 Buy {no_name} ({format_probability(no_ask_price)})"
        else:
            # Regular binary market - show YES/NO labels
            yes_label = "🟢 YES"
            no_label = "🔴 NO"
            yes_btn_label = f"🟢 Buy YES ({format_probability(yes_ask_price)})"
            no_btn_label = f"🔴 Buy NO ({format_probability(no_ask_price)})"

        # Build the text and keyboard based on market type
        if is_amm_market:
            # AMM market - show info but no trading buttons
            text = f"""
{info['emoji']} <b>{escape_html(market.title)}</b>

⚠️ <b>AMM Market</b>
This market uses liquidity pool trading (AMM) which is not yet supported.
Trading is only available for orderbook (CLOB) markets.

📊 <b>Estimated Prices</b>
{yes_label}: {format_probability(yes_ask_price)} ({format_price(yes_ask_price)})
{no_label}: {format_probability(no_ask_price)} ({format_price(no_ask_price)})

📈 <b>Stats</b>
Volume (24h): {format_usd(market.volume_24h)}
Liquidity: {format_usd(market.liquidity)}
Status: {"🟢 Active" if market.is_active else "🔴 Closed"}
Expires: {expiration_text}
"""
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🤖 AI Research",
                        callback_data=f"ai_research:{platform_value}:{short_market_id}"
                    ),
                ],
                [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
            ])
        else:
            text = f"""
{info['emoji']} <b>{escape_html(market.title)}</b>

📊 <b>Buy Prices</b> (from orderbook)
{yes_label}: {format_probability(yes_ask_price)} ({format_price(yes_ask_price)})
{no_label}: {format_probability(no_ask_price)} ({format_price(no_ask_price)})

📈 <b>Stats</b>
Volume (24h): {format_usd(market.volume_24h)}
Liquidity: {format_usd(market.liquidity)}
Status: {"🟢 Active" if market.is_active else "🔴 Closed"}
Expires: {expiration_text}
"""
            # Show resolution criteria if available
            if market.resolution_criteria:
                criteria_text = market.resolution_criteria[:400]
                if len(market.resolution_criteria) > 400:
                    criteria_text += "..."
                text += f"\n📋 <b>Resolution Rules</b>\n{escape_html(criteria_text)}\n"

            # Buy buttons for binary market with orderbook prices
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        yes_btn_label,
                        callback_data=f"buy:{platform_value}:{short_market_id}:yes"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        no_btn_label,
                        callback_data=f"buy:{platform_value}:{short_market_id}:no"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🤖 AI Research",
                        callback_data=f"ai_research:{platform_value}:{short_market_id}"
                    ),
                ],
                [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
            ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_market_more_options(query, platform_value: str, market_id: str, offset: int, telegram_id: int) -> None:
    """Handle viewing more options for multi-outcome markets."""
    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform.")
        return

    platform = get_platform(platform_enum)
    market = await platform.get_market(market_id)

    # Truncate for callback_data limit
    short_market_id = market_id[:40]

    if not market:
        await query.edit_message_text("Market not found.")
        return

    # Get related markets for multi-outcome event
    related_markets = []
    if market.is_multi_outcome and market.event_id:
        related_markets = await platform.get_related_markets(market.event_id)

    if not related_markets or len(related_markets) <= offset:
        await query.answer("No more options available")
        return

    await query.answer()

    info = PLATFORM_INFO[platform_enum]

    # Get the remaining options starting from offset
    remaining_markets = related_markets[offset:]

    # Check if this is a player props market
    import re
    def check_player_prop(rm):
        """Check if a market is a player prop by looking for over/under keywords."""
        def has_ou_keywords(text):
            if not text:
                return False
            t = text.lower()
            if re.search(r'\bover\b', t) or re.search(r'\bunder\b', t):
                return True
            return "o/u" in t or " ou " in t

        # Check title
        if rm.title and has_ou_keywords(rm.title):
            return True
        # Check outcome_name
        if rm.outcome_name and has_ou_keywords(rm.outcome_name):
            return True
        # Check raw_data for question or groupItemTitle (Polymarket structure)
        if rm.raw_data and isinstance(rm.raw_data, dict):
            # Polymarket: nested under "market" key
            market_raw = rm.raw_data.get("market", {})
            if isinstance(market_raw, dict):
                question = market_raw.get("question") or market_raw.get("groupItemTitle") or ""
                if has_ou_keywords(question):
                    return True
            # Kalshi: direct fields at top level
            kalshi_title = rm.raw_data.get("title") or rm.raw_data.get("question") or ""
            kalshi_subtitle = rm.raw_data.get("yesSubtitle") or rm.raw_data.get("subtitle") or ""
            if has_ou_keywords(kalshi_title) or has_ou_keywords(kalshi_subtitle):
                return True
        return False

    is_player_props = any(check_player_prop(rm) for rm in related_markets[:5])

    max_buttons = 8 if is_player_props else 15
    displayed_markets = remaining_markets[:max_buttons]

    # Fetch orderbook prices for all displayed markets in parallel
    from src.db.models import Outcome as OutcomeEnum
    import asyncio

    orderbook_prices = {}  # market_id -> {yes_ask, no_ask}

    async def fetch_orderbook_prices(rm):
        """Fetch orderbook prices for a single market."""
        try:
            yes_price = rm.yes_price  # fallback
            no_price = rm.no_price    # fallback

            # Get slug for orderbook lookup (needed for Limitless with numeric IDs)
            slug = None
            if rm.raw_data and isinstance(rm.raw_data, dict):
                slug = rm.raw_data.get("slug")

            try:
                yes_ob = await platform.get_orderbook(rm.market_id, OutcomeEnum.YES, slug=slug)
                if yes_ob and yes_ob.best_ask:
                    yes_price = yes_ob.best_ask
            except:
                pass

            try:
                no_ob = await platform.get_orderbook(rm.market_id, OutcomeEnum.NO, slug=slug)
                if no_ob and no_ob.best_ask:
                    no_price = no_ob.best_ask
            except:
                pass

            return rm.market_id, {"yes_ask": yes_price, "no_ask": no_price}
        except Exception:
            return rm.market_id, {"yes_ask": rm.yes_price, "no_ask": rm.no_price}

    # Fetch all orderbooks in parallel
    try:
        results = await asyncio.gather(*[fetch_orderbook_prices(rm) for rm in displayed_markets])
        for market_id, prices in results:
            orderbook_prices[market_id] = prices
    except Exception as e:
        logger.warning("Failed to fetch orderbook prices for more options", error=str(e))

    text = f"""
{info['emoji']} <b>{escape_html(market.title)}</b>

📊 <b>More Options</b> (showing {offset + 1}-{min(offset + max_buttons, len(related_markets))} of {len(related_markets)})
"""
    # List remaining options with orderbook prices
    for i, rm in enumerate(displayed_markets, offset + 1):
        name = rm.outcome_name or rm.title
        if len(name) > 35:
            name = name[:32] + "..."

        prices = orderbook_prices.get(rm.market_id, {"yes_ask": rm.yes_price, "no_ask": rm.no_price})
        yes_price_str = format_probability(prices["yes_ask"]) if prices["yes_ask"] else "N/A"
        no_price_str = format_probability(prices["no_ask"]) if prices["no_ask"] else "N/A"

        if is_player_props:
            text += f"{i}. {escape_html(name)}\n   ⬆️ Over: {yes_price_str} | ⬇️ Under: {no_price_str}\n"
        else:
            text += f"{i}. {escape_html(name)}: {yes_price_str}\n"

    # Create buttons for remaining options with orderbook prices
    buttons = []
    for rm in displayed_markets:
        name = rm.outcome_name or rm.title
        short_id = rm.market_id[:40]

        prices = orderbook_prices.get(rm.market_id, {"yes_ask": rm.yes_price, "no_ask": rm.no_price})

        if is_player_props:
            # Show prop name on one row, Over/Under buttons below
            if len(name) > 30:
                display_name = name[:27] + "..."
            else:
                display_name = name
            yes_price_str = format_probability(prices["yes_ask"]) if prices["yes_ask"] else "?"
            no_price_str = format_probability(prices["no_ask"]) if prices["no_ask"] else "?"
            # Row 1: Prop name
            buttons.append([
                InlineKeyboardButton(
                    f"📊 {escape_html(display_name)}",
                    callback_data=f"market:{platform_value}:{short_id}"
                )
            ])
            # Row 2: Over and Under buttons
            buttons.append([
                InlineKeyboardButton(
                    f"⬆️ Over ({yes_price_str})",
                    callback_data=f"buy:{platform_value}:{short_id}:yes"
                ),
                InlineKeyboardButton(
                    f"⬇️ Under ({no_price_str})",
                    callback_data=f"buy:{platform_value}:{short_id}:no"
                )
            ])
        else:
            if len(name) > 20:
                name = name[:17] + "..."
            prob = format_probability(prices["yes_ask"])
            buttons.append([
                InlineKeyboardButton(
                    f"{escape_html(name)} ({prob})",
                    callback_data=f"buy:{platform_value}:{short_id}:yes"
                )
            ])

    # Show more if still more options
    new_offset = offset + max_buttons
    if len(related_markets) > new_offset:
        remaining = len(related_markets) - new_offset
        buttons.append([
            InlineKeyboardButton(
                f"📋 View {remaining} more options...",
                callback_data=f"more:{platform_value}:{short_market_id}:{new_offset}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("« Back to Market", callback_data=f"market:{platform_value}:{short_market_id}"),
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_ai_research(query, platform_value: str, market_id: str, telegram_id: int) -> None:
    """Handle AI research request for a market."""
    from src.services.factsai import factsai_service
    from src.db.database import get_user_trading_volume, get_wallet

    # Truncate for callback_data limit
    short_market_id = market_id[:40]

    await query.answer()

    # Check if FactsAI is configured
    if not factsai_service.is_configured:
        await query.edit_message_text(
            "❌ AI Research is not available at this time.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Get user and check access
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get user's trading volume
    trading_volume = await get_user_trading_volume(user.id)

    # Get user's EVM wallet for token balance check
    wallet = await get_wallet(user.id, ChainFamily.EVM)
    wallet_address = wallet.public_key if wallet else None

    # Check access
    has_access, access_message = await factsai_service.check_access(
        wallet_address=wallet_address,
        trading_volume=trading_volume,
    )

    if not has_access:
        await query.edit_message_text(
            f"🔒 <b>Premium Feature</b>\n\n{access_message}\n\n"
            f"<i>Get $SPRDD tokens or increase your trading volume to unlock AI Research!</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Buy $SPRDD", url="https://app.virtuals.io/virtuals/23167")],
                [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{short_market_id}")],
            ]),
        )
        return

    # Show loading message
    await query.edit_message_text(
        "🤖 <b>AI Research</b>\n\n"
        "⏳ Analyzing market and gathering insights...\n\n"
        "<i>This may take a few seconds...</i>",
        parse_mode=ParseMode.HTML,
    )

    # Get market info
    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform.")
        return

    platform = get_platform(platform_enum)
    market = await platform.get_market(market_id)

    if not market:
        await query.edit_message_text("Market not found.")
        return

    # Call FactsAI
    result = await factsai_service.research_market(
        market_title=market.title,
        market_description=market.resolution_criteria or "",
    )

    if result.get("error"):
        await query.edit_message_text(
            f"❌ <b>Research Failed</b>\n\n{result['error']}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Retry", callback_data=f"ai_research:{platform_value}:{short_market_id}")],
                [InlineKeyboardButton("« Back to Market", callback_data=f"market:{platform_value}:{short_market_id}")],
            ]),
        )
        return

    # Format the response
    answer = result.get("answer", "No analysis available.")
    citations = result.get("citations", [])

    # Truncate answer if too long for Telegram
    if len(answer) > 3500:
        answer = answer[:3500] + "..."

    text = f"""🤖 <b>AI Research: {escape_html(market.title[:50])}...</b>

📊 <b>Analysis</b>
{escape_html(answer)}
"""

    # Add citations if available
    if citations:
        text += "\n\n📚 <b>Sources</b>\n"
        for i, cite in enumerate(citations[:5], 1):
            title = cite.get("title", "Source")[:40]
            url = cite.get("url", "")
            if url:
                text += f"{i}. <a href=\"{url}\">{escape_html(title)}</a>\n"
            else:
                text += f"{i}. {escape_html(title)}\n"

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Analysis", callback_data=f"ai_research:{platform_value}:{short_market_id}")],
            [InlineKeyboardButton("« Back to Market", callback_data=f"market:{platform_value}:{short_market_id}")],
        ]),
    )


async def handle_buy_start(query, platform_value: str, market_id: str, outcome: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle starting a buy order."""
    # Truncate for callback_data limit
    short_market_id = market_id[:40]

    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform.")
        return

    info = PLATFORM_INFO[platform_enum]
    chain_family = get_chain_family_for_platform(platform_enum)

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # For Polymarket, check USDC balance and auto-swap if needed
    if platform_enum == Platform.POLYMARKET:
        await query.edit_message_text(
            "🔄 Checking USDC balance...",
            parse_mode=ParseMode.HTML,
        )

        try:
            from src.platforms.polymarket import polymarket_platform, MIN_USDC_BALANCE

            # Get private key directly (no PIN required for trading)
            private_key = await wallet_service.get_private_key(user.id, telegram_id, chain_family)
            if not private_key:
                await query.edit_message_text(
                    "❌ No wallet found. Please /start to create one.",
                    parse_mode=ParseMode.HTML,
                )
                return

            # Show initial status
            await query.edit_message_text(
                "🔄 <b>Checking USDC balance...</b>",
                parse_mode=ParseMode.HTML,
            )

            # Create progress callback for bridge updates
            last_update_time = [0]  # Use list to allow modification in closure
            main_loop = asyncio.get_running_loop()  # Capture main event loop

            async def update_progress(msg: str, elapsed: int, total: int):
                import time
                # Throttle updates to once per 5 seconds to avoid rate limits
                now = time.time()
                if now - last_update_time[0] < 5:
                    return
                last_update_time[0] = now

                try:
                    progress_pct = min(100, int((elapsed / max(1, total)) * 100))
                    progress_bar = "█" * (progress_pct // 10) + "░" * (10 - progress_pct // 10)
                    await query.edit_message_text(
                        f"🌉 <b>Bridging USDC</b>\n\n"
                        f"{escape_html(msg)}\n\n"
                        f"[{progress_bar}] {progress_pct}%",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass  # Ignore update errors

            # Wrap async callback for sync bridge service (called from thread)
            def sync_progress_callback(msg: str, elapsed: int, total: int):
                try:
                    # Schedule coroutine on main event loop from thread
                    future = asyncio.run_coroutine_threadsafe(
                        update_progress(msg, elapsed, total),
                        main_loop
                    )
                    # Don't wait for result, just fire and forget
                except Exception:
                    pass

            # Check and auto-swap/bridge USDC if needed
            ready, message, swap_tx = await polymarket_platform.ensure_usdc_balance(
                private_key, MIN_USDC_BALANCE, progress_callback=sync_progress_callback
            )

            if not ready:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{short_market_id}")],
                ])
                await query.edit_message_text(
                    f"❌ <b>Cannot Trade</b>\n\n{escape_html(message)}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
                return

            # If swap/bridge happened, show notification
            swap_note = ""
            if swap_tx:
                if "Bridged" in message:
                    swap_note = f"\n\n✅ <i>{escape_html(message)}</i>"
                else:
                    swap_note = f"\n\n✅ <i>Auto-swapped USDC to USDC.e</i>"

        except Exception as e:
            logger.error("Balance check failed", error=str(e))
            # Continue anyway - let the trade fail with a proper error if needed

    swap_note = locals().get("swap_note", "")

    # Fetch market to check if it's a player prop
    platform = get_platform(platform_enum)
    market = await platform.get_market(market_id)

    # Check if this is a player prop market
    import re
    def has_ou_keywords(text):
        if not text:
            return False
        t = text.lower()
        if re.search(r'\bover\b', t) or re.search(r'\bunder\b', t):
            return True
        return "o/u" in t or " ou " in t

    is_player_prop = False
    if market:
        question_text = ""
        if market.raw_data and isinstance(market.raw_data, dict):
            market_raw = market.raw_data.get("market", {})
            if isinstance(market_raw, dict):
                question_text = market_raw.get("question") or market_raw.get("groupItemTitle") or ""
        is_player_prop = (
            has_ou_keywords(market.title) or
            has_ou_keywords(market.outcome_name) or
            has_ou_keywords(question_text)
        )

    # Use appropriate label
    if is_player_prop:
        position_label = "OVER" if outcome == "yes" else "UNDER"
    else:
        position_label = outcome.upper()

    # Get correct collateral symbol for this market's network
    collateral_symbol = get_collateral_for_market(platform_enum, market)

    # Store buy context for message handler
    context.user_data["pending_buy"] = {
        "platform": platform_value,
        "market_id": market_id,
        "outcome": outcome,
        "collateral_symbol": collateral_symbol,
    }

    text = f"""
💰 <b>Buy {position_label} Position</b>

Platform: {info['name']}
Collateral: {collateral_symbol}{swap_note}

Enter the amount in {collateral_symbol} you want to spend:

<i>Example: 10 (for 10 {collateral_symbol})</i>

Type /cancel to cancel.
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{short_market_id}")],
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_wallet_refresh(query, telegram_id: int) -> None:
    """Refresh wallet balances."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Check if user has wallets
    from src.db.database import get_user_wallets
    existing_wallets = await get_user_wallets(user.id)

    if not existing_wallets:
        # No wallets - redirect to setup
        text = """
🔐 <b>Set Up Your Wallet</b>

You haven't created your wallets yet.

<b>Use /wallet to create your secure wallets with PIN protection.</b>
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Set Up Wallet", callback_data="wallet:setup")],
            [InlineKeyboardButton("« Back", callback_data="menu:main")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    await query.edit_message_text("🔄 Refreshing balances...")

    balances = await wallet_service.get_all_balances(user.id)

    # Convert existing_wallets list to dict by chain_family
    wallets = {w.chain_family: w for w in existing_wallets}

    solana_wallet = wallets.get(ChainFamily.SOLANA)
    evm_wallet = wallets.get(ChainFamily.EVM)

    # Get native token balances for gas display
    native_balances = {}
    if evm_wallet:
        try:
            from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS
            if not bridge_service._initialized:
                bridge_service.initialize()

            # Check native balances on key chains
            for chain in [BridgeChain.ETHEREUM, BridgeChain.POLYGON, BridgeChain.BASE, BridgeChain.ABSTRACT, BridgeChain.BSC, BridgeChain.ARBITRUM, BridgeChain.OPTIMISM]:
                try:
                    native_bal = bridge_service.get_native_balance(chain, evm_wallet.public_key)
                    if native_bal >= Decimal("0"):
                        native_balances[chain] = native_bal
                except Exception:
                    pass
        except Exception:
            pass

    text = "💰 <b>Your Wallets</b>\n\n"

    if solana_wallet:
        text += f"<b>🟣 Solana</b> (Kalshi)\n"
        text += f"<code>{solana_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.SOLANA, []):
            text += f"  • {bal.formatted}\n"
        text += "\n"

    if evm_wallet:
        text += f"<b>🔷 EVM</b> (Polymarket + Opinion + Limitless + Myriad)\n"
        text += f"<code>{evm_wallet.public_key}</code>\n"

        # Show USDC balances
        text += "<b>USDC:</b>\n"
        for bal in balances.get(ChainFamily.EVM, []):
            text += f"  • {bal.formatted} ({bal.chain.value})\n"

        # Show native token balances (for gas)
        if native_balances:
            text += "\n<b>Gas Tokens:</b>\n"
            chain_emoji = {
                BridgeChain.ETHEREUM: "⚪",
                BridgeChain.POLYGON: "🟣",
                BridgeChain.BASE: "🔵",
                BridgeChain.ABSTRACT: "🌀",
                BridgeChain.BSC: "🟡",
                BridgeChain.ARBITRUM: "🔷",
                BridgeChain.OPTIMISM: "🔴",
            }
            for chain, bal in native_balances.items():
                symbol = NATIVE_TOKEN_SYMBOLS.get(chain, "ETH")
                emoji = chain_emoji.get(chain, "🔹")
                text += f"  {emoji} {float(bal):.6f} {symbol} ({chain.value})\n"

    text += "\n<i>Tap address to copy. Send funds to deposit.</i>"

    # Build buttons
    buttons = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="wallet:refresh")],
        [InlineKeyboardButton("🌉 Bridge USDC", callback_data="wallet:bridge")],
        [InlineKeyboardButton("📤 Export Keys", callback_data="wallet:export")],
        [InlineKeyboardButton("« Back", callback_data="menu:main")],
    ]

    keyboard = InlineKeyboardMarkup(buttons)

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_bridge_menu(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show simplified bridge & swap menu with action-first flow."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_user_wallets

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Get user's wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text(
                "❌ No EVM wallet found. Please /start to create one.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Get total USDC balance across all chains
        balances = bridge_service.get_all_usdc_balances(evm_wallet.public_key)
        total_usdc = sum(balances.values())

        # Get BSC USDT balance
        bsc_usdt_balance = bridge_service.get_bsc_usdt_balance(evm_wallet.public_key)

        text = "🌉 <b>Bridge & Swap</b>\n\n"
        text += f"💰 <b>Total USDC:</b> ${float(total_usdc):.2f}\n"
        if bsc_usdt_balance > 0:
            text += f"💰 <b>BSC USDT:</b> ${float(bsc_usdt_balance):.2f}\n"
        text += "\n<i>What would you like to do?</i>"

        buttons = [
            [
                InlineKeyboardButton("🌉 Bridge USDC", callback_data="bridge:action:usdc"),
                InlineKeyboardButton("💱 Swap", callback_data="bridge:action:swap"),
            ],
            [InlineKeyboardButton("⛽ Get Gas Tokens", callback_data="bridge:action:gas")],
            [InlineKeyboardButton("« Back to Wallet", callback_data="wallet:refresh")],
        ]

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        error_str = str(e)
        if "Message is not modified" in error_str:
            logger.debug("Bridge menu unchanged, ignoring")
            return
        logger.error("Failed to load bridge menu", error=error_str)
        try:
            await query.edit_message_text(
                f"❌ Failed to load bridge info: {friendly_error(error_str)}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back to Wallet", callback_data="wallet:refresh")],
                ]),
            )
        except Exception:
            pass


async def handle_bridge_usdc_menu(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show destination selection for USDC bridging."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_user_wallets

        if not bridge_service._initialized:
            bridge_service.initialize()

        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)
        solana_wallet = next((w for w in wallets if w.chain_family == ChainFamily.SOLANA), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        balances = bridge_service.get_all_usdc_balances(evm_wallet.public_key)

        chain_emoji = {
            BridgeChain.POLYGON: "🟣",
            BridgeChain.BASE: "🔵",
            BridgeChain.BSC: "🟡",
            BridgeChain.ABSTRACT: "🌀",
            BridgeChain.SOLANA: "🟠",
        }

        # Platform destinations
        dest_options = [
            (BridgeChain.POLYGON, "Polymarket"),
            (BridgeChain.BASE, "Limitless"),
            (BridgeChain.BSC, "Opinion Labs"),
            (BridgeChain.ABSTRACT, "Myriad"),
            (BridgeChain.SOLANA, "Kalshi"),
        ]

        text = "🌉 <b>Bridge USDC</b>\n\n"
        text += "<i>Select destination:</i>\n"

        buttons = []
        available_routes = False

        for dest_chain, platform in dest_options:
            if dest_chain == BridgeChain.SOLANA and not solana_wallet:
                continue

            valid_sources = bridge_service.get_valid_source_chains(dest_chain)
            sources_with_balance = [
                src for src in valid_sources
                if balances.get(src, Decimal(0)) > Decimal("0.01")
            ]

            if sources_with_balance:
                available_routes = True
                emoji = chain_emoji.get(dest_chain, "🔹")
                # Show current balance on dest chain
                dest_bal = balances.get(dest_chain, Decimal(0))
                bal_text = f" (${float(dest_bal):.2f})" if dest_bal > 0 else ""
                buttons.append([
                    InlineKeyboardButton(
                        f"{emoji} {platform}{bal_text}",
                        callback_data=f"bridge:dest:{dest_chain.value}"
                    )
                ])

        if not available_routes:
            text += "\n⚠️ <i>No USDC available to bridge.</i>\n"
            text += "<i>Deposit USDC to any supported chain first.</i>"

        if not solana_wallet:
            text += "\n\n<i>💡 Create a Solana wallet to bridge to Kalshi</i>"

        buttons.append([InlineKeyboardButton("« Back", callback_data="wallet:bridge")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to load bridge USDC menu", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_swap_menu(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show swap options menu."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS, SWAP_SUPPORTED_CHAINS, ERC20_SWAP_TOKENS
        from src.db.database import get_user_wallets

        if not bridge_service._initialized:
            bridge_service.initialize()

        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        chain_emoji = {
            BridgeChain.BASE: "🔵",
            BridgeChain.POLYGON: "🟣",
            BridgeChain.BSC: "🟡",
            BridgeChain.ABSTRACT: "🌀",
            BridgeChain.ARBITRUM: "🔷",
            BridgeChain.OPTIMISM: "🔴",
            BridgeChain.LINEA: "🔷",
        }

        text = "💱 <b>Swap</b>\n\n"
        text += "<i>Convert tokens to USDC:</i>\n"

        buttons = []
        has_swaps = False

        # Native token swaps
        for chain in SWAP_SUPPORTED_CHAINS:
            try:
                native_bal = bridge_service.get_native_balance(chain, evm_wallet.public_key)
                if native_bal > Decimal("0.001"):
                    has_swaps = True
                    symbol = NATIVE_TOKEN_SYMBOLS.get(chain, "TOKEN")
                    emoji = chain_emoji.get(chain, "🔹")
                    out_token = "USDT" if chain == BridgeChain.BSC else "USDC"
                    buttons.append([
                        InlineKeyboardButton(
                            f"{emoji} {symbol} → {out_token} ({float(native_bal):.4f})",
                            callback_data=f"swap:native:{chain.value}"
                        )
                    ])
            except Exception:
                pass

        # ERC-20 token swaps (e.g., VIRTUAL → USDC)
        for token_key, token_info in ERC20_SWAP_TOKENS.items():
            try:
                token_bal = bridge_service.get_erc20_balance(
                    token_info["chain"], evm_wallet.public_key,
                    token_info["address"], token_info["decimals"]
                )
                if token_bal > Decimal("0.1"):
                    has_swaps = True
                    emoji = chain_emoji.get(token_info["chain"], "🔹")
                    buttons.append([
                        InlineKeyboardButton(
                            f"{emoji} {token_info['symbol']} → USDC ({float(token_bal):.2f})",
                            callback_data=f"swap:erc20:{token_key}"
                        )
                    ])
            except Exception:
                pass

        # BSC USDC → USDT swap
        bsc_usdc = bridge_service.get_usdc_balance(BridgeChain.BSC, evm_wallet.public_key)
        if bsc_usdc > Decimal("0.01"):
            has_swaps = True
            buttons.append([
                InlineKeyboardButton(
                    f"🟡 USDC → USDT (${float(bsc_usdc):.2f})",
                    callback_data="bridge:swap:bsc_usdt"
                )
            ])

        if not has_swaps:
            text += "\n⚠️ <i>No tokens available to swap.</i>"

        buttons.append([InlineKeyboardButton("« Back", callback_data="wallet:bridge")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to load swap menu", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_gas_bridge_menu(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show gas token bridging options."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS, SWAP_SUPPORTED_CHAINS
        from src.db.database import get_user_wallets

        if not bridge_service._initialized:
            bridge_service.initialize()

        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        chain_emoji = {
            BridgeChain.ETHEREUM: "⚪",
            BridgeChain.BASE: "🔵",
            BridgeChain.POLYGON: "🟣",
            BridgeChain.OPTIMISM: "🔴",
            BridgeChain.ARBITRUM: "🔷",
            BridgeChain.ABSTRACT: "🌀",
            BridgeChain.LINEA: "🔷",
        }

        text = "⛽ <b>Bridge Gas Tokens</b>\n\n"
        text += "<i>Bridge ETH between chains for gas:</i>\n"

        buttons = []
        has_gas = False

        # Check chains that can bridge gas
        native_check_chains = set(SWAP_SUPPORTED_CHAINS) | {
            BridgeChain.ETHEREUM,
            BridgeChain.OPTIMISM,
        }

        for source_chain in native_check_chains:
            try:
                native_bal = bridge_service.get_native_balance(source_chain, evm_wallet.public_key)
                if native_bal < Decimal("0.001"):
                    continue

                valid_dests = bridge_service.get_valid_native_dest_chains(source_chain)
                if valid_dests:
                    has_gas = True
                    symbol = NATIVE_TOKEN_SYMBOLS.get(source_chain, "TOKEN")
                    emoji = chain_emoji.get(source_chain, "🔹")
                    buttons.append([
                        InlineKeyboardButton(
                            f"{emoji} {source_chain.value.title()} ({float(native_bal):.4f} {symbol})",
                            callback_data=f"gas_bridge:source:{source_chain.value}"
                        )
                    ])
            except Exception:
                pass

        if not has_gas:
            text += "\n⚠️ <i>No gas tokens available to bridge.</i>\n"
            text += "<i>Deposit ETH to Ethereum, Base, or Polygon first.</i>"

        buttons.append([InlineKeyboardButton("« Back", callback_data="wallet:bridge")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to load gas bridge menu", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_bsc_usdc_swap(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle BSC USDC → USDT swap for Opinion Labs."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_user_wallets
        from src.services.wallet import wallet_service

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Get user's EVM wallet
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get BSC USDC balance
        bsc_usdc = bridge_service.get_usdc_balance(BridgeChain.BSC, evm_wallet.public_key)

        if bsc_usdc < Decimal("0.01"):
            await query.edit_message_text(
                "❌ No BSC USDC to swap.\n\nBridge USDC to BSC first, then swap to USDT.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Check BNB balance for gas
        bnb_balance = bridge_service.get_native_balance(BridgeChain.BSC, evm_wallet.public_key)
        has_bnb = bnb_balance >= Decimal("0.001")

        text = f"💱 <b>Swap BSC USDC → USDT</b>\n\n"
        text += f"Balance: <b>${float(bsc_usdc):.2f} USDC</b>\n\n"

        if not has_bnb:
            text += "⚠️ <b>You need BNB for gas fees!</b>\n"
            text += f"Send ~$0.50 worth of BNB to:\n"
            text += f"<code>{evm_wallet.public_key}</code>\n\n"
        else:
            text += "Opinion Labs uses USDT for trading.\n"

        text += "Select how much to swap:\n"

        buttons = []

        # Add percentage buttons
        for percent in [25, 50, 75, 100]:
            amount = bsc_usdc * Decimal(percent) / Decimal(100)
            if amount >= Decimal("0.01"):
                buttons.append(
                    InlineKeyboardButton(
                        f"{percent}% (${float(amount):.2f})",
                        callback_data=f"bridge:swap_exec:{percent}"
                    )
                )

        # Arrange buttons in rows of 2
        button_rows = []
        for i in range(0, len(buttons), 2):
            button_rows.append(buttons[i:i+2])

        button_rows.append([InlineKeyboardButton("« Back", callback_data="wallet:bridge")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(button_rows),
        )

    except Exception as e:
        logger.error("Failed to show BSC swap menu", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_bsc_swap_execute(query, percent: int, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute BSC USDC → USDT swap."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_user_wallets
        from src.services.wallet import wallet_service

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Get user's EVM wallet
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get BSC USDC balance
        bsc_usdc = bridge_service.get_usdc_balance(BridgeChain.BSC, evm_wallet.public_key)
        swap_amount = bsc_usdc * Decimal(percent) / Decimal(100)

        if swap_amount < Decimal("0.01"):
            await query.edit_message_text("❌ Amount too small to swap.")
            return

        # Get private key
        private_key = await wallet_service.get_evm_account(user.id, telegram_id)
        if not private_key:
            await query.edit_message_text("❌ Failed to load wallet.")
            return

        # Show progress
        progress_msg = await query.edit_message_text(
            f"💱 <b>Swapping BSC USDC → USDT</b>\n\n"
            f"Amount: ${float(swap_amount):.2f}\n\n"
            f"⏳ Getting swap quote...",
            parse_mode=ParseMode.HTML,
        )

        async def update_progress(status: str, current: int, total: int):
            try:
                await progress_msg.edit_text(
                    f"💱 <b>Swapping BSC USDC → USDT</b>\n\n"
                    f"Amount: ${float(swap_amount):.2f}\n\n"
                    f"{status}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        # Execute swap
        import asyncio
        loop = asyncio.get_running_loop()
        result = await asyncio.to_thread(
            bridge_service.swap_bsc_usdc_to_usdt,
            private_key,
            swap_amount,
            lambda s, c, t: asyncio.run_coroutine_threadsafe(update_progress(s, c, t), loop),
        )

        if result.success:
            text = f"✅ <b>Swap Successful!</b>\n\n"
            text += f"Swapped: ${float(swap_amount):.2f} USDC\n"
            text += f"Received: ~${float(result.received_amount or swap_amount):.2f} USDT\n\n"
            if result.explorer_url:
                text += f"<a href='{result.explorer_url}'>View on BscScan</a>"
        else:
            error_msg = result.error_message or 'Unknown error'
            text = f"❌ <b>Swap Failed</b>\n\n"

            # Check if it's a gas-related error
            if "bnb" in error_msg.lower() or "gas" in error_msg.lower():
                text += f"⛽ <b>Insufficient BNB for gas fees</b>\n\n"
                text += f"You need a small amount of BNB (~$0.50) to pay for transaction fees on BSC.\n\n"
                text += f"<b>Your BSC wallet address:</b>\n"
                text += f"<code>{evm_wallet.public_key}</code>\n\n"
                text += f"💡 Send a small amount of BNB to this address from an exchange (Binance, Coinbase, etc.) and try again."
            else:
                text += f"Error: {error_msg}"

        await progress_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Bridge", callback_data="wallet:bridge")],
            ]),
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error("BSC swap failed", error=str(e))
        await query.edit_message_text(
            f"❌ Swap failed: {str(e)[:100]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_native_swap(query, chain_str: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle native token → USDC swap - show amount selection."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Parse chain
        try:
            chain = BridgeChain(chain_str.lower())
        except ValueError:
            await query.edit_message_text(f"❌ Invalid chain: {chain_str}")
            return

        if not bridge_service.supports_swap(chain):
            await query.edit_message_text(f"❌ Swaps not supported on {chain.value.title()}")
            return

        # Get user's EVM wallet
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get native balance
        native_balance = bridge_service.get_native_balance(chain, evm_wallet.public_key)
        native_symbol = NATIVE_TOKEN_SYMBOLS.get(chain, "TOKEN")
        out_token = "USDT" if chain == BridgeChain.BSC else "USDC"

        if native_balance < Decimal("0.0001"):
            await query.edit_message_text(
                f"❌ Insufficient {native_symbol} balance on {chain.value.title()}.\n\n"
                f"Balance: {float(native_balance):.6f} {native_symbol}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        text = f"💱 <b>Swap {native_symbol} → {out_token}</b>\n\n"
        text += f"Chain: {chain.value.title()}\n"
        text += f"Balance: {float(native_balance):.6f} {native_symbol}\n\n"
        text += f"Select amount to swap:"

        # Amount buttons
        buttons = [
            [
                InlineKeyboardButton("25%", callback_data=f"swap:amount:{chain.value}:25"),
                InlineKeyboardButton("50%", callback_data=f"swap:amount:{chain.value}:50"),
            ],
            [
                InlineKeyboardButton("75%", callback_data=f"swap:amount:{chain.value}:75"),
                InlineKeyboardButton("100%", callback_data=f"swap:amount:{chain.value}:100"),
            ],
            [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
        ]

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to show native swap menu", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_erc20_swap(query, token_key: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ERC-20 token → USDC swap - show amount selection."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, ERC20_SWAP_TOKENS

        if not bridge_service._initialized:
            bridge_service.initialize()

        token_info = ERC20_SWAP_TOKENS.get(token_key)
        if not token_info:
            await query.edit_message_text(f"❌ Unknown token: {token_key}")
            return

        chain = token_info["chain"]
        symbol = token_info["symbol"]

        # Get user's EVM wallet
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get token balance
        token_balance = bridge_service.get_erc20_balance(
            chain, evm_wallet.public_key, token_info["address"], token_info["decimals"]
        )

        if token_balance < Decimal("0.01"):
            await query.edit_message_text(
                f"❌ Insufficient {symbol} balance on {chain.value.title()}.\n\n"
                f"Balance: {float(token_balance):.4f} {symbol}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Store ERC-20 token info in user_data for the amount handler
        context.user_data["pending_erc20_swap"] = {
            "token_key": token_key,
            "from_token": token_info["address"],
            "from_decimals": token_info["decimals"],
            "symbol": symbol,
        }

        text = f"💱 <b>Swap {symbol} → USDC</b>\n\n"
        text += f"Chain: {chain.value.title()}\n"
        text += f"Balance: {float(token_balance):.4f} {symbol}\n\n"
        text += f"Select amount to swap:"

        # Amount buttons - reuse same callback format but chain is the ERC-20's chain
        buttons = [
            [
                InlineKeyboardButton("25%", callback_data=f"swap:amount:{chain.value}:25"),
                InlineKeyboardButton("50%", callback_data=f"swap:amount:{chain.value}:50"),
            ],
            [
                InlineKeyboardButton("75%", callback_data=f"swap:amount:{chain.value}:75"),
                InlineKeyboardButton("100%", callback_data=f"swap:amount:{chain.value}:100"),
            ],
            [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
        ]

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to show ERC-20 swap menu", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_native_swap_amount(query, chain_str: str, percent: int, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle swap amount selection - get quote and show confirmation. Works for both native and ERC-20 swaps."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS, NATIVE_TOKEN

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Parse chain
        try:
            chain = BridgeChain(chain_str.lower())
        except ValueError:
            await query.edit_message_text(f"❌ Invalid chain: {chain_str}")
            return

        # Get user's EVM wallet
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Check if this is an ERC-20 swap (set by handle_erc20_swap)
        erc20_info = context.user_data.pop("pending_erc20_swap", None)
        out_token = "USDT" if chain == BridgeChain.BSC else "USDC"

        if erc20_info:
            # ERC-20 token swap
            from_token = erc20_info["from_token"]
            from_decimals = erc20_info["from_decimals"]
            input_symbol = erc20_info["symbol"]
            token_balance = bridge_service.get_erc20_balance(
                chain, evm_wallet.public_key, from_token, from_decimals
            )
            # No gas reserve needed for ERC-20 swaps (100% of token is fine)
            swap_amount = token_balance * Decimal(percent) / Decimal(100)
        else:
            # Native token swap
            from_token = NATIVE_TOKEN
            from_decimals = 18
            input_symbol = NATIVE_TOKEN_SYMBOLS.get(chain, "TOKEN")
            token_balance = bridge_service.get_native_balance(chain, evm_wallet.public_key)
            # For 100%, leave some for gas (0.001 of native token)
            if percent == 100:
                swap_amount = token_balance - Decimal("0.001")
            else:
                swap_amount = token_balance * Decimal(percent) / Decimal(100)

        if swap_amount <= Decimal(0):
            await query.edit_message_text(
                f"❌ Amount too small." + (f" Leave some {input_symbol} for gas fees." if from_token == NATIVE_TOKEN else ""),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Show loading
        await query.edit_message_text(
            f"💱 <b>Getting swap quote...</b>\n\n"
            f"Swapping: {float(swap_amount):.6f} {input_symbol} → {out_token}",
            parse_mode=ParseMode.HTML,
        )

        # Get quote
        import asyncio
        quote = await asyncio.to_thread(
            bridge_service.get_swap_quote,
            chain,
            swap_amount,
            evm_wallet.public_key,
            from_token,
            from_decimals,
        )

        if quote.error:
            await query.edit_message_text(
                f"❌ Quote failed: {friendly_error(quote.error)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Store quote data in user_data for confirmation
        context.user_data["pending_swap"] = {
            "chain": chain.value,
            "amount": str(swap_amount),
            "quote": quote,
            "from_token": from_token,
            "from_decimals": from_decimals,
            "input_symbol": input_symbol,
        }

        text = f"💱 <b>Swap Quote</b>\n\n"
        text += f"<b>You send:</b> {float(swap_amount):.6f} {input_symbol}\n"
        text += f"<b>You receive:</b> ~{float(quote.output_amount):.2f} {out_token}\n"
        text += f"<b>DEX:</b> {quote.tool_name}\n"
        text += f"<b>Fees:</b> ~${float(quote.fee_amount):.2f}\n"
        text += f"<b>Time:</b> ~{quote.estimated_time_seconds}s\n\n"
        text += f"⚠️ Output may vary due to slippage."

        buttons = [
            [InlineKeyboardButton("✅ Confirm Swap", callback_data="swap:confirm")],
            [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
        ]

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to get swap quote", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_native_swap_confirm(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute the token → USDC swap (works for both native and ERC-20)."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get pending swap from user_data
    pending = context.user_data.get("pending_swap")
    if not pending:
        await query.edit_message_text(
            "❌ Swap expired. Please try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS, NATIVE_TOKEN

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        chain = BridgeChain(pending["chain"])
        swap_amount = Decimal(pending["amount"])
        from_token = pending.get("from_token", NATIVE_TOKEN)
        from_decimals = pending.get("from_decimals", 18)
        input_symbol = pending.get("input_symbol", NATIVE_TOKEN_SYMBOLS.get(chain, "TOKEN"))
        out_token = "USDT" if chain == BridgeChain.BSC else "USDC"

        # Get user's EVM wallet and private key
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        private_key = await wallet_service.get_evm_account(user.id, telegram_id)
        if not private_key:
            await query.edit_message_text("❌ Failed to load wallet.")
            return

        # Clear pending swap
        context.user_data.pop("pending_swap", None)

        # Show progress
        progress_msg = await query.edit_message_text(
            f"💱 <b>Swapping {input_symbol} → {out_token}</b>\n\n"
            f"Amount: {float(swap_amount):.6f} {input_symbol}\n\n"
            f"⏳ Executing swap...",
            parse_mode=ParseMode.HTML,
        )

        async def update_progress(status: str, current: int, total: int):
            try:
                await progress_msg.edit_text(
                    f"💱 <b>Swapping {input_symbol} → {out_token}</b>\n\n"
                    f"Amount: {float(swap_amount):.6f} {input_symbol}\n\n"
                    f"{status}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        # Execute swap
        import asyncio
        loop = asyncio.get_running_loop()
        result = await asyncio.to_thread(
            bridge_service.execute_swap,
            private_key,
            chain,
            swap_amount,
            lambda s, c, t: asyncio.run_coroutine_threadsafe(update_progress(s, c, t), loop),
            from_token,
            from_decimals,
        )

        if result.success:
            text = f"✅ <b>Swap Successful!</b>\n\n"
            text += f"Swapped: {float(swap_amount):.6f} {input_symbol}\n"
            text += f"Received: ~{float(result.received_amount or 0):.2f} {out_token}\n"
            text += f"Chain: {chain.value.title()}\n\n"
            if result.explorer_url:
                text += f"<a href='{result.explorer_url}'>View on Explorer</a>"
        else:
            error_msg = result.error_message or 'Unknown error'
            text = f"❌ <b>Swap Failed</b>\n\n"

            # Check if it's a gas-related error
            if "gas" in error_msg.lower() or "eth" in error_msg.lower():
                text += f"⛽ <b>Insufficient ETH for gas fees</b>\n\n"
                text += f"You need some ETH to pay for transaction fees.\n\n"
                text += f"<b>Your wallet address:</b>\n"
                text += f"<code>{evm_wallet.public_key}</code>"
            else:
                text += f"Error: {friendly_error(error_msg)}"

        await progress_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Bridge", callback_data="wallet:bridge")],
            ]),
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error("Swap failed", error=str(e))
        await query.edit_message_text(
            f"❌ Swap failed: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_gas_bridge_source(query, source_chain_str: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle gas bridge source selection - show valid destination chains."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Parse source chain
        try:
            source_chain = BridgeChain(source_chain_str.lower())
        except ValueError:
            await query.edit_message_text(f"❌ Invalid chain: {source_chain_str}")
            return

        # Get user's EVM wallet
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get native balance
        native_balance = bridge_service.get_native_balance(source_chain, evm_wallet.public_key)
        native_symbol = NATIVE_TOKEN_SYMBOLS.get(source_chain, "TOKEN")

        # Get valid destinations
        valid_dests = bridge_service.get_valid_native_dest_chains(source_chain)

        if not valid_dests:
            await query.edit_message_text(
                f"❌ No valid bridge destinations from {source_chain.value.title()}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        chain_emoji = {
            BridgeChain.POLYGON: "🟣",
            BridgeChain.BASE: "🔵",
            BridgeChain.ABSTRACT: "🌀",
            BridgeChain.BSC: "🟡",
            BridgeChain.ARBITRUM: "🔷",
            BridgeChain.ETHEREUM: "⚪",
            BridgeChain.OPTIMISM: "🔴",
            BridgeChain.LINEA: "🔷",
        }

        text = f"⛽ <b>Bridge {native_symbol} from {source_chain.value.title()}</b>\n\n"
        text += f"Balance: {float(native_balance):.6f} {native_symbol}\n\n"
        text += "Select destination chain:"

        buttons = []
        for dest in valid_dests:
            dest_symbol = NATIVE_TOKEN_SYMBOLS.get(dest, "TOKEN")
            emoji = chain_emoji.get(dest, "🔹")
            buttons.append([
                InlineKeyboardButton(
                    f"{emoji} → {dest.value.title()} (receive {dest_symbol})",
                    callback_data=f"gas_bridge:dest:{source_chain.value}:{dest.value}"
                )
            ])

        buttons.append([InlineKeyboardButton("« Back", callback_data="wallet:bridge")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to show gas bridge destinations", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_gas_bridge_dest(query, source_chain_str: str, dest_chain_str: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle gas bridge destination selection - show amount options."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Parse chains
        try:
            source_chain = BridgeChain(source_chain_str.lower())
            dest_chain = BridgeChain(dest_chain_str.lower())
        except ValueError:
            await query.edit_message_text(f"❌ Invalid chain")
            return

        # Get user's EVM wallet
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get native balance
        native_balance = bridge_service.get_native_balance(source_chain, evm_wallet.public_key)
        source_symbol = NATIVE_TOKEN_SYMBOLS.get(source_chain, "TOKEN")
        dest_symbol = NATIVE_TOKEN_SYMBOLS.get(dest_chain, "TOKEN")

        text = f"⛽ <b>Bridge {source_symbol} → {dest_chain.value.title()}</b>\n\n"
        text += f"From: {source_chain.value.title()}\n"
        text += f"To: {dest_chain.value.title()}\n"
        text += f"Balance: {float(native_balance):.6f} {source_symbol}\n\n"
        text += "Select amount to bridge:"

        # Amount buttons
        buttons = [
            [
                InlineKeyboardButton("25%", callback_data=f"gas_bridge:amount:{source_chain.value}:{dest_chain.value}:25"),
                InlineKeyboardButton("50%", callback_data=f"gas_bridge:amount:{source_chain.value}:{dest_chain.value}:50"),
            ],
            [
                InlineKeyboardButton("75%", callback_data=f"gas_bridge:amount:{source_chain.value}:{dest_chain.value}:75"),
                InlineKeyboardButton("90%", callback_data=f"gas_bridge:amount:{source_chain.value}:{dest_chain.value}:90"),
            ],
            [InlineKeyboardButton("« Back", callback_data=f"gas_bridge:source:{source_chain.value}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to show gas bridge amount options", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_gas_bridge_amount(query, source_chain_str: str, dest_chain_str: str, percent: int, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle gas bridge amount selection - get quote and show confirmation."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Parse chains
        try:
            source_chain = BridgeChain(source_chain_str.lower())
            dest_chain = BridgeChain(dest_chain_str.lower())
        except ValueError:
            await query.edit_message_text(f"❌ Invalid chain")
            return

        # Get user's EVM wallet
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get native balance and calculate bridge amount
        native_balance = bridge_service.get_native_balance(source_chain, evm_wallet.public_key)
        source_symbol = NATIVE_TOKEN_SYMBOLS.get(source_chain, "TOKEN")
        dest_symbol = NATIVE_TOKEN_SYMBOLS.get(dest_chain, "TOKEN")

        # Leave some for gas on source chain
        max_bridge = native_balance - Decimal("0.002")  # Keep 0.002 for gas
        if max_bridge <= Decimal(0):
            await query.edit_message_text(
                f"❌ Insufficient balance. Need to keep some {source_symbol} for gas fees.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        bridge_amount = max_bridge * Decimal(percent) / Decimal(100)

        if bridge_amount < Decimal("0.0001"):
            await query.edit_message_text(
                f"❌ Amount too small to bridge.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Show loading
        await query.edit_message_text(
            f"⛽ <b>Getting bridge quote...</b>\n\n"
            f"Bridging: {float(bridge_amount):.6f} {source_symbol}\n"
            f"Route: {source_chain.value.title()} → {dest_chain.value.title()}",
            parse_mode=ParseMode.HTML,
        )

        # Get quote
        import asyncio
        quote = await asyncio.to_thread(
            bridge_service.get_native_bridge_quote,
            source_chain,
            dest_chain,
            bridge_amount,
            evm_wallet.public_key,
        )

        if quote.error:
            await query.edit_message_text(
                f"❌ Quote failed: {friendly_error(quote.error)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Store quote data in user_data for confirmation
        context.user_data["pending_gas_bridge"] = {
            "source_chain": source_chain.value,
            "dest_chain": dest_chain.value,
            "amount": str(bridge_amount),
            "quote": quote,
        }

        text = f"⛽ <b>Gas Bridge Quote</b>\n\n"
        text += f"<b>You send:</b> {float(bridge_amount):.6f} {source_symbol}\n"
        text += f"<b>You receive:</b> ~{float(quote.output_amount):.6f} {dest_symbol}\n"
        text += f"<b>Route:</b> {source_chain.value.title()} → {dest_chain.value.title()}\n"
        text += f"<b>Bridge:</b> {quote.tool_name}\n"
        text += f"<b>Fees:</b> ~${float(quote.fee_amount):.2f}\n"
        text += f"<b>Time:</b> ~{quote.estimated_time_seconds}s\n\n"
        text += f"⚠️ Output may vary slightly."

        buttons = [
            [InlineKeyboardButton("✅ Confirm Bridge", callback_data="gas_bridge:confirm")],
            [InlineKeyboardButton("« Back", callback_data=f"gas_bridge:dest:{source_chain.value}:{dest_chain.value}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to get gas bridge quote", error=str(e))
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_gas_bridge_confirm(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute the gas bridge."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get pending bridge from user_data
    pending = context.user_data.get("pending_gas_bridge")
    if not pending:
        await query.edit_message_text(
            "❌ Bridge expired. Please try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain, NATIVE_TOKEN_SYMBOLS

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        source_chain = BridgeChain(pending["source_chain"])
        dest_chain = BridgeChain(pending["dest_chain"])
        bridge_amount = Decimal(pending["amount"])
        source_symbol = NATIVE_TOKEN_SYMBOLS.get(source_chain, "TOKEN")
        dest_symbol = NATIVE_TOKEN_SYMBOLS.get(dest_chain, "TOKEN")

        # Get user's EVM wallet and private key
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        private_key = await wallet_service.get_evm_account(user.id, telegram_id)
        if not private_key:
            await query.edit_message_text("❌ Failed to load wallet.")
            return

        # Clear pending bridge
        context.user_data.pop("pending_gas_bridge", None)

        # Show progress
        progress_msg = await query.edit_message_text(
            f"⛽ <b>Bridging {source_symbol} → {dest_chain.value.title()}</b>\n\n"
            f"Amount: {float(bridge_amount):.6f} {source_symbol}\n\n"
            f"⏳ Executing bridge...",
            parse_mode=ParseMode.HTML,
        )

        async def update_progress(status: str, current: int, total: int):
            try:
                await progress_msg.edit_text(
                    f"⛽ <b>Bridging {source_symbol} → {dest_chain.value.title()}</b>\n\n"
                    f"Amount: {float(bridge_amount):.6f} {source_symbol}\n\n"
                    f"{status}",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        # Execute bridge
        import asyncio
        loop = asyncio.get_running_loop()
        result = await asyncio.to_thread(
            bridge_service.execute_native_bridge,
            private_key,
            source_chain,
            dest_chain,
            bridge_amount,
            lambda s, c, t: asyncio.run_coroutine_threadsafe(update_progress(s, c, t), loop),
        )

        if result.success:
            text = f"✅ <b>Bridge Initiated!</b>\n\n"
            text += f"Sent: {float(bridge_amount):.6f} {source_symbol}\n"
            text += f"Expected: ~{float(result.received_amount or bridge_amount):.6f} {dest_symbol}\n"
            text += f"Route: {source_chain.value.title()} → {dest_chain.value.title()}\n\n"
            text += f"⏳ Funds will arrive on {dest_chain.value.title()} in 1-5 minutes.\n\n"
            if result.explorer_url:
                text += f"<a href='{result.explorer_url}'>View on Explorer</a>"
        else:
            error_msg = result.error_message or 'Unknown error'
            text = f"❌ <b>Bridge Failed</b>\n\n"

            # Check if it's a gas-related error
            if "gas" in error_msg.lower() or "insufficient" in error_msg.lower():
                text += f"⛽ <b>Insufficient {source_symbol} for gas fees</b>\n\n"
                text += f"You need some {source_symbol} to pay for the bridge transaction.\n\n"
                text += f"<b>Your wallet address:</b>\n"
                text += f"<code>{evm_wallet.public_key}</code>"
            else:
                text += f"Error: {friendly_error(error_msg)}"

        await progress_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Bridge", callback_data="wallet:bridge")],
            ]),
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error("Gas bridge failed", error=str(e))
        await query.edit_message_text(
            f"❌ Bridge failed: {friendly_error(str(e))}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_bridge_dest(query, dest_chain: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle destination chain selection - show source chains with balance."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_user_wallets

        # Initialize bridge service if needed
        if not bridge_service._initialized:
            bridge_service.initialize()

        # Get user's EVM wallet
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)
        solana_wallet = next((w for w in wallets if w.chain_family == ChainFamily.SOLANA), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Parse destination chain
        dest_chain_lower = dest_chain.lower()
        try:
            dest = BridgeChain(dest_chain_lower)
        except ValueError:
            await query.edit_message_text(f"Invalid destination chain: {dest_chain}")
            return

        # For Solana destination, ensure we have Solana wallet
        if dest == BridgeChain.SOLANA and not solana_wallet:
            await query.edit_message_text(
                "❌ No Solana wallet found. Please /start to create one.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Get balances on all chains
        balances = bridge_service.get_all_usdc_balances(evm_wallet.public_key)

        dest_emoji = {
            BridgeChain.POLYGON: "🟣",
            BridgeChain.SOLANA: "🟠",
            BridgeChain.BASE: "🔵",
            BridgeChain.BSC: "🟡",
            BridgeChain.ABSTRACT: "🌀",
            BridgeChain.LINEA: "🔷",
        }.get(dest, "🔹")

        text = f"🌉 <b>Bridge to {dest.value.title()}</b> {dest_emoji}\n\n"
        text += "Select source chain:\n\n"

        buttons = []
        for chain, balance in balances.items():
            # Skip the destination chain
            if chain == dest:
                continue

            # Skip if route is not valid
            if not bridge_service.is_valid_bridge_route(chain, dest):
                continue

            chain_emoji = {
                BridgeChain.BASE: "🔵",
                BridgeChain.ARBITRUM: "🔷",
                BridgeChain.OPTIMISM: "🔴",
                BridgeChain.ETHEREUM: "⚪",
                BridgeChain.POLYGON: "🟣",
                BridgeChain.MONAD: "🟢",
                BridgeChain.ABSTRACT: "🌀",
                BridgeChain.LINEA: "🔷",
            }.get(chain, "🔹")

            text += f"{chain_emoji} {chain.value.title()}: ${float(balance):.2f}\n"

            # Only show bridge button for chains with balance
            if balance > 0:
                buttons.append([
                    InlineKeyboardButton(
                        f"{chain_emoji} From {chain.value.title()} (${float(balance):.2f})",
                        callback_data=f"bridge:source:{chain.value}:{dest_chain_lower}"
                    )
                ])

        if not buttons:
            text += "\n⚠️ <i>No valid source chains with balance for this destination.</i>"

        buttons.append([InlineKeyboardButton("« Back", callback_data="wallet:bridge")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        error_str = str(e)
        if "Message is not modified" in error_str:
            return
        logger.error("Bridge dest selection failed", error=error_str)
        try:
            await query.edit_message_text(
                f"❌ Error: {friendly_error(error_str)}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
        except Exception:
            pass


async def handle_bridge_start(query, source_chain: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, dest_chain: str = "polygon") -> None:
    """Start manual bridge - show amount selection."""
    logger.info("Bridge start called", source_chain=source_chain, dest_chain=dest_chain, telegram_id=telegram_id)

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_user_wallets

        # Get chain enums
        try:
            source = BridgeChain(source_chain.lower())
            dest = BridgeChain(dest_chain.lower())
        except ValueError as e:
            await query.edit_message_text(f"Invalid chain: {e}")
            return

        # Get user's wallet
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)
        solana_wallet = next((w for w in wallets if w.chain_family == ChainFamily.SOLANA), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # For Solana destination, ensure we have Solana wallet
        if dest == BridgeChain.SOLANA and not solana_wallet:
            await query.edit_message_text(
                "❌ No Solana wallet found. Please /start to create one.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Get balance on source chain
        if not bridge_service._initialized:
            bridge_service.initialize()

        balance = bridge_service.get_usdc_balance(source, evm_wallet.public_key)

        if balance <= 0:
            await query.edit_message_text(
                f"❌ No USDC balance on {source.value.title()}.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Store pending bridge info for amount selection
        context.user_data["pending_bridge"] = {
            "source_chain": source_chain,
            "dest_chain": dest_chain,
            "max_balance": str(balance),
            "awaiting_amount": True,
        }

        # Calculate preset amounts
        amounts = {
            "25%": balance * Decimal("0.25"),
            "50%": balance * Decimal("0.50"),
            "75%": balance * Decimal("0.75"),
            "100%": balance,
        }

        dest_emoji = {
            BridgeChain.POLYGON: "🟣",
            BridgeChain.SOLANA: "🟠",
            BridgeChain.BASE: "🔵",
            BridgeChain.BSC: "🟡",
            BridgeChain.ABSTRACT: "🌀",
            BridgeChain.LINEA: "🔷",
        }.get(dest, "🔹")

        # Determine bridge method
        bridge_method = bridge_service.get_best_bridge_method(source, dest)
        if bridge_method == "lifi":
            speed_note = "via LI.FI (~1-3 min)"
        else:
            speed_note = "fast (~30s) or standard (~15min)"

        text = f"""
🌉 <b>Bridge USDC to {dest.value.title()}</b> {dest_emoji}

Source: {source.value.title()}
Destination: {dest.value.title()}
Available: <b>${float(balance):.2f} USDC</b>

<i>Bridge: {speed_note}</i>

Select amount to bridge:
"""

        buttons = [
            [
                InlineKeyboardButton(f"25% (${float(amounts['25%']):.2f})", callback_data=f"bridge:amount:{source_chain}:{dest_chain}:25"),
                InlineKeyboardButton(f"50% (${float(amounts['50%']):.2f})", callback_data=f"bridge:amount:{source_chain}:{dest_chain}:50"),
            ],
            [
                InlineKeyboardButton(f"75% (${float(amounts['75%']):.2f})", callback_data=f"bridge:amount:{source_chain}:{dest_chain}:75"),
                InlineKeyboardButton(f"100% (${float(amounts['100%']):.2f})", callback_data=f"bridge:amount:{source_chain}:{dest_chain}:100"),
            ],
            [InlineKeyboardButton("✏️ Custom Amount", callback_data=f"bridge:custom:{source_chain}:{dest_chain}")],
            [InlineKeyboardButton("« Back", callback_data=f"bridge:dest:{dest_chain}")],
        ]

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        error_str = str(e)
        if "Message is not modified" in error_str:
            logger.debug("Bridge start screen unchanged, ignoring")
            return
        logger.error("Bridge start failed", error=error_str)
        try:
            await query.edit_message_text(
                f"❌ Bridge error: {friendly_error(error_str)}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
        except Exception:
            pass


async def handle_bridge_amount(query, source_chain: str, dest_chain: str, percentage: int, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bridge amount selection - show speed options or execute for LI.FI."""
    pending = context.user_data.get("pending_bridge")
    if not pending:
        await query.edit_message_text("No pending bridge. Please start again.")
        return

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    max_balance = Decimal(pending["max_balance"])
    amount = max_balance * Decimal(percentage) / Decimal(100)

    # Update pending bridge with amount
    context.user_data["pending_bridge"]["amount"] = str(amount)
    context.user_data["pending_bridge"]["dest_chain"] = dest_chain
    context.user_data["pending_bridge"]["awaiting_amount"] = False

    from src.services.bridge import BridgeChain, bridge_service
    from src.db.database import get_wallet
    source = BridgeChain(source_chain.lower())
    dest = BridgeChain(dest_chain.lower())

    # Determine bridge method
    bridge_method = bridge_service.get_best_bridge_method(source, dest)

    # For LI.FI (Solana/BSC routes), skip speed selection and show confirmation
    if bridge_method == "lifi":
        evm_wallet = await get_wallet(user.id, ChainFamily.EVM)

        if not evm_wallet:
            await query.edit_message_text("❌ EVM wallet not found. Please /start first.")
            return

        # Determine destination address based on chain
        if dest == BridgeChain.SOLANA:
            solana_wallet = await get_wallet(user.id, ChainFamily.SOLANA)
            if not solana_wallet:
                await query.edit_message_text("❌ Solana wallet not found. Please /start first.")
                return
            to_address = solana_wallet.public_key
            dest_label = "Solana (for Kalshi)"
        else:
            # BSC or other EVM chains - use same EVM wallet
            to_address = evm_wallet.public_key
            platform_name = {"bsc": "Opinion Labs", "base": "Limitless"}.get(dest_chain, "")
            dest_label = f"{dest.value.title()}" + (f" (for {platform_name})" if platform_name else "")

        # Get LI.FI quote
        lifi_quote = bridge_service.get_lifi_quote(
            source, dest, amount, evm_wallet.public_key, to_address
        )

        if lifi_quote.error:
            await query.edit_message_text(
                f"❌ Failed to get bridge quote: {lifi_quote.error}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        fee_display = f"${float(lifi_quote.fee_amount):.2f}" if lifi_quote.fee_amount > Decimal("0.01") else f"{lifi_quote.fee_percent:.1f}%"
        est_time = lifi_quote.estimated_time_seconds

        dest_emoji_display = {"polygon": "🟣", "solana": "🟠", "base": "🔵", "bsc": "🟡", "abstract": "🌀"}.get(dest_chain, "🔹")

        text = f"""
🌉 <b>Bridge USDC to {dest.value.title()}</b> {dest_emoji_display}

From: {source.value.title()}
To: {dest_label}
Amount: <b>${float(amount):.2f} USDC</b>

<b>Bridge Details (LI.FI via {lifi_quote.tool_name}):</b>
• You receive: ~${float(lifi_quote.output_amount):.2f} USDC
• Fee: {fee_display}
• Time: ~{est_time // 60}m {est_time % 60}s

<b>Confirm bridge?</b>
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Bridge", callback_data=f"bridge:speed:{source_chain}:{dest_chain}:lifi")],
            [InlineKeyboardButton("« Back", callback_data=f"bridge:source:{source_chain}:{dest_chain}")],
        ])

        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # For EVM-to-EVM bridges, show speed selection
    evm_wallet = await get_wallet(user.id, ChainFamily.EVM)
    fast_quote = None
    if evm_wallet:
        fast_quote = bridge_service.get_fast_bridge_quote(
            source, dest, amount, evm_wallet.public_key
        )

    # Show speed selection
    fee_text = ""
    if fast_quote and not fast_quote.error:
        fee_display = f"${float(fast_quote.fee_amount):.2f}" if fast_quote.fee_amount > 0 else f"{fast_quote.fee_percent:.1f}%"
        receive_amount = f"${float(fast_quote.output_amount):.2f}"
        fee_text = f"\n<b>🚀 Fast:</b> ~30 seconds, {fee_display} fee → receive {receive_amount}"
    else:
        fee_text = "\n<b>🚀 Fast:</b> ~30 seconds (small fee)"

    dest_emoji = {"polygon": "🟣", "base": "🔵", "arbitrum": "🔷", "abstract": "🌀"}.get(dest_chain, "🔹")

    text = f"""
🌉 <b>Bridge USDC - Select Speed</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: <b>${float(amount):.2f} USDC</b>

<b>Choose bridge speed:</b>
{fee_text}
<b>🐢 Standard:</b> ~10-15 min, FREE (Circle CCTP)
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Fast (~30s)", callback_data=f"bridge:speed:{source_chain}:{dest_chain}:fast")],
        [InlineKeyboardButton("🐢 Standard (Free)", callback_data=f"bridge:speed:{source_chain}:{dest_chain}:standard")],
        [InlineKeyboardButton("« Back", callback_data=f"bridge:source:{source_chain}:{dest_chain}")],
    ])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def handle_bridge_custom(query, source_chain: str, dest_chain: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to enter custom bridge amount."""
    pending = context.user_data.get("pending_bridge")
    if not pending:
        await query.edit_message_text("No pending bridge. Please start again.")
        return

    max_balance = Decimal(pending["max_balance"])

    from src.services.bridge import BridgeChain
    source = BridgeChain(source_chain.lower())
    dest = BridgeChain(dest_chain.lower())

    context.user_data["pending_bridge"]["awaiting_custom_amount"] = True
    context.user_data["pending_bridge"]["dest_chain"] = dest_chain

    dest_emoji = {"polygon": "🟣", "solana": "🟠", "base": "🔵", "bsc": "🟡", "abstract": "🌀"}.get(dest_chain, "🔹")

    text = f"""
🌉 <b>Bridge USDC - Custom Amount</b>

Source: {source.value.title()}
Destination: {dest.value.title()} {dest_emoji}
Available: <b>${float(max_balance):.2f} USDC</b>

<b>Enter the amount in USDC to bridge:</b>
<i>(e.g., 10, 25.50, 100)</i>
"""
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def handle_bridge_custom_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE, amount_str: str) -> None:
    """Handle custom bridge amount input from user - show speed selection or LI.FI confirmation."""
    pending = context.user_data.get("pending_bridge")
    if not pending:
        await update.message.reply_text("No pending bridge. Please start again.")
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    # Parse amount
    try:
        amount = Decimal(amount_str.replace(",", ".").replace("$", "").strip())
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0.")
            return
    except:
        await update.message.reply_text("❌ Invalid amount. Please enter a number (e.g., 10, 25.50).")
        return

    max_balance = Decimal(pending["max_balance"])
    if amount > max_balance:
        await update.message.reply_text(
            f"❌ Amount exceeds available balance (${float(max_balance):.2f}).\n"
            f"Please enter a smaller amount.",
            parse_mode=ParseMode.HTML,
        )
        return

    source_chain = pending["source_chain"]
    dest_chain = pending.get("dest_chain", "polygon")

    # Update pending bridge with amount
    context.user_data["pending_bridge"]["amount"] = str(amount)
    context.user_data["pending_bridge"]["awaiting_custom_amount"] = False

    from src.services.bridge import BridgeChain, bridge_service
    from src.db.database import get_wallet
    source = BridgeChain(source_chain.lower())
    dest = BridgeChain(dest_chain.lower())

    # Determine bridge method
    bridge_method = bridge_service.get_best_bridge_method(source, dest)

    # For LI.FI (Solana/BSC routes), show confirmation
    if bridge_method == "lifi":
        evm_wallet = await get_wallet(user.id, ChainFamily.EVM)

        if not evm_wallet:
            await update.message.reply_text("❌ EVM wallet not found. Please /start first.")
            return

        # Determine destination address based on chain
        if dest == BridgeChain.SOLANA:
            solana_wallet = await get_wallet(user.id, ChainFamily.SOLANA)
            if not solana_wallet:
                await update.message.reply_text("❌ Solana wallet not found. Please /start first.")
                return
            to_address = solana_wallet.public_key
            dest_label = "Solana (for Kalshi)"
        else:
            # BSC or other EVM chains - use same EVM wallet
            to_address = evm_wallet.public_key
            platform_name = {"bsc": "Opinion Labs", "base": "Limitless"}.get(dest_chain, "")
            dest_label = f"{dest.value.title()}" + (f" (for {platform_name})" if platform_name else "")

        # Get LI.FI quote
        lifi_quote = bridge_service.get_lifi_quote(
            source, dest, amount, evm_wallet.public_key, to_address
        )

        if lifi_quote.error:
            await update.message.reply_text(
                f"❌ Failed to get bridge quote: {lifi_quote.error}",
                parse_mode=ParseMode.HTML,
            )
            return

        fee_display = f"${float(lifi_quote.fee_amount):.2f}" if lifi_quote.fee_amount > Decimal("0.01") else f"{lifi_quote.fee_percent:.1f}%"
        est_time = lifi_quote.estimated_time_seconds

        dest_emoji_display = {"polygon": "🟣", "solana": "🟠", "base": "🔵", "bsc": "🟡", "abstract": "🌀"}.get(dest_chain, "🔹")

        text = f"""
🌉 <b>Bridge USDC to {dest.value.title()}</b> {dest_emoji_display}

From: {source.value.title()}
To: {dest_label}
Amount: <b>${float(amount):.2f} USDC</b>

<b>Bridge Details (LI.FI via {lifi_quote.tool_name}):</b>
• You receive: ~${float(lifi_quote.output_amount):.2f} USDC
• Fee: {fee_display}
• Time: ~{est_time // 60}m {est_time % 60}s

<b>Confirm bridge?</b>
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Bridge", callback_data=f"bridge:speed:{source_chain}:{dest_chain}:lifi")],
            [InlineKeyboardButton("« Back", callback_data=f"bridge:source:{source_chain}:{dest_chain}")],
        ])

        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # For EVM-to-EVM bridges, show speed selection
    evm_wallet = await get_wallet(user.id, ChainFamily.EVM)
    fast_quote = None
    if evm_wallet:
        fast_quote = bridge_service.get_fast_bridge_quote(
            source, dest, amount, evm_wallet.public_key
        )

    # Show speed selection
    fee_text = ""
    if fast_quote and not fast_quote.error:
        fee_display = f"${float(fast_quote.fee_amount):.2f}" if fast_quote.fee_amount > 0 else f"{fast_quote.fee_percent:.1f}%"
        receive_amount = f"${float(fast_quote.output_amount):.2f}"
        fee_text = f"\n<b>🚀 Fast:</b> ~30 seconds, {fee_display} fee → receive {receive_amount}"
    else:
        fee_text = "\n<b>🚀 Fast:</b> ~30 seconds (small fee)"

    dest_emoji = {"polygon": "🟣", "base": "🔵", "solana": "🟠", "abstract": "🌀"}.get(dest_chain, "🔹")

    text = f"""
🌉 <b>Bridge USDC - Select Speed</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: <b>${float(amount):.2f} USDC</b>

<b>Choose bridge speed:</b>
{fee_text}
<b>🐢 Standard:</b> ~10-15 min, FREE (Circle CCTP)
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Fast (~30s)", callback_data=f"bridge:speed:{source_chain}:{dest_chain}:fast")],
        [InlineKeyboardButton("🐢 Standard (Free)", callback_data=f"bridge:speed:{source_chain}:{dest_chain}:standard")],
        [InlineKeyboardButton("« Back", callback_data=f"bridge:source:{source_chain}:{dest_chain}")],
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def handle_bridge_speed(query, source_chain: str, dest_chain: str, speed: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bridge speed selection (fast, standard, or lifi)."""
    pending = context.user_data.get("pending_bridge")
    if not pending:
        await query.edit_message_text("No pending bridge. Please start again.")
        return

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    amount = Decimal(pending["amount"])

    # Store the speed choice and destination
    context.user_data["pending_bridge"]["speed"] = speed
    context.user_data["pending_bridge"]["dest_chain"] = dest_chain

    # Execute bridge directly (no PIN required)
    await execute_bridge(query, user.id, telegram_id, source_chain, dest_chain, amount, context)


async def execute_bridge(query, user_id: str, telegram_id: int, source_chain: str, dest_chain: str, amount: Decimal, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute the bridge operation (fast, standard, or lifi based on pending_bridge settings)."""
    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_wallet
        import asyncio

        source = BridgeChain(source_chain.lower())
        dest = BridgeChain(dest_chain.lower())
        chain_family = ChainFamily.EVM

        # Get speed from pending bridge (default to standard)
        pending = context.user_data.get("pending_bridge", {})
        speed = pending.get("speed", "standard")
        use_lifi = speed == "lifi" or bridge_service.requires_lifi(source, dest)
        use_fast_bridge = speed == "fast" and not use_lifi

        # Get private key directly (no PIN required)
        private_key = await wallet_service.get_private_key(user_id, telegram_id, chain_family)
        if not private_key:
            await query.edit_message_text(
                "❌ Failed to get wallet key.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # For Solana destination, get Solana wallet address
        # For EVM destinations (including BSC), use EVM wallet
        to_address = None
        if dest == BridgeChain.SOLANA:
            solana_wallet = await get_wallet(user_id, ChainFamily.SOLANA)
            if not solana_wallet:
                await query.edit_message_text(
                    "❌ No Solana wallet found. Please /start first.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                    ]),
                )
                return
            to_address = solana_wallet.public_key
        elif use_lifi:
            # For BSC and other LI.FI routes, destination is EVM wallet
            evm_wallet_obj = await get_wallet(user_id, ChainFamily.EVM)
            to_address = evm_wallet_obj.public_key if evm_wallet_obj else private_key.address

        # Show progress message
        if use_lifi:
            speed_label = "🔗 LI.FI"
        elif use_fast_bridge:
            speed_label = "🚀 Fast"
        else:
            speed_label = "🐢 Standard"

        dest_emoji = {"polygon": "🟣", "solana": "🟠", "base": "🔵", "bsc": "🟡", "abstract": "🌀"}.get(dest_chain, "🔹")

        await query.edit_message_text(
            f"🌉 <b>Bridging USDC ({speed_label})</b>\n\n"
            f"From: {source.value.title()}\n"
            f"To: {dest.value.title()} {dest_emoji}\n"
            f"Amount: ${float(amount):.2f}\n\n"
            f"⏳ Initiating transfer...",
            parse_mode=ParseMode.HTML,
        )

        # Create progress callback
        main_loop = asyncio.get_running_loop()
        last_update_time = [0]

        async def update_progress(msg: str, elapsed: int, total: int):
            import time
            now = time.time()
            if now - last_update_time[0] < 3:  # Update more frequently for fast bridge
                return
            last_update_time[0] = now

            try:
                progress_pct = min(100, int((elapsed / max(1, total)) * 100))
                progress_bar = "█" * (progress_pct // 10) + "░" * (10 - progress_pct // 10)
                await query.edit_message_text(
                    f"🌉 <b>Bridging USDC ({speed_label})</b>\n\n"
                    f"{escape_html(msg)}\n\n"
                    f"[{progress_bar}] {progress_pct}%",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        def sync_progress_callback(msg: str, elapsed: int, total: int):
            try:
                asyncio.run_coroutine_threadsafe(
                    update_progress(msg, elapsed, total),
                    main_loop
                )
            except Exception:
                pass

        # Execute bridge in thread (lifi, fast, or standard)
        if use_lifi:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc_lifi,
                private_key,
                source,
                dest,
                amount,
                to_address,
                sync_progress_callback,
            )
        elif use_fast_bridge:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc_fast,
                private_key,
                source,
                dest,
                amount,
                sync_progress_callback,
            )
        else:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc,
                private_key,
                source,
                dest,
                amount,
                sync_progress_callback,
            )

        if result.success:
            if use_lifi:
                text = f"""
✅ <b>LI.FI Bridge Complete!</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: ~${float(result.amount):.2f} USDC (after fees)

TX: <code>{result.burn_tx_hash[:16] if result.burn_tx_hash else 'pending'}...</code>

🔗 Funds are being delivered to your {dest.value.title()} wallet!
<i>Usually arrives in 1-3 minutes.</i>
"""
            elif use_fast_bridge:
                text = f"""
✅ <b>Fast Bridge Complete!</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: ${float(result.amount):.2f} USDC (after fees)

TX: <code>{result.burn_tx_hash[:16] if result.burn_tx_hash else 'pending'}...</code>

🚀 Funds are arriving on {dest.value.title()} now!
"""
            else:
                text = f"""
✅ <b>Bridge Initiated!</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: ${float(amount):.2f} USDC

Burn TX: <code>{result.burn_tx_hash[:16]}...</code>
"""
                if result.mint_tx_hash:
                    text += f"Mint TX: <code>{result.mint_tx_hash[:16]}...</code>\n"
                    text += f"\n✅ Bridge complete! Funds are now on {dest.value.title()}."
                else:
                    text += f"\n⏳ Waiting for Circle attestation. Funds will arrive on {dest.value.title()} in ~10-15 minutes."

        else:
            text = f"❌ <b>Bridge Failed</b>\n\n{friendly_error(result.error_message or 'Unknown error')}"

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh Wallet", callback_data="wallet:refresh")],
                [InlineKeyboardButton("« Back to Wallet", callback_data="wallet:refresh")],
            ]),
        )

        # Clear pending bridge
        if "pending_bridge" in context.user_data:
            del context.user_data["pending_bridge"]

    except Exception as e:
        if "Decryption failed" in str(e):
            await query.edit_message_text(
                "❌ <b>Invalid PIN</b>\n\nPlease try again.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Try Again", callback_data="wallet:bridge")],
                ]),
            )
        else:
            logger.error("Bridge execution failed", error=str(e))
            await query.edit_message_text(
                f"❌ Bridge failed: {friendly_error(str(e))}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )


async def handle_bridge_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Handle PIN entry for bridge operation (fast, standard, or lifi)."""
    pending = context.user_data.get("pending_bridge")
    if not pending:
        await update.message.reply_text("No pending bridge operation.")
        return

    # Validate PIN format
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        await update.message.reply_text(
            "❌ Invalid PIN. Please enter a 4-6 digit PIN.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except Exception:
        pass

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("User not found.")
        return

    # Get bridge info from pending (before deleting)
    source_chain = pending["source_chain"]
    dest_chain = pending.get("dest_chain", "polygon")
    amount = Decimal(pending["amount"])
    speed = pending.get("speed", "standard")

    from src.services.bridge import bridge_service, BridgeChain
    from src.db.database import get_wallet
    import asyncio

    source = BridgeChain(source_chain.lower())
    dest = BridgeChain(dest_chain.lower())

    use_lifi = speed == "lifi" or bridge_service.requires_lifi(source, dest)
    use_fast_bridge = speed == "fast" and not use_lifi

    if use_lifi:
        speed_label = "🔗 LI.FI"
    elif use_fast_bridge:
        speed_label = "🚀 Fast"
    else:
        speed_label = "🐢 Standard"

    dest_emoji = {"polygon": "🟣", "solana": "🟠", "base": "🔵", "bsc": "🟡", "abstract": "🌀"}.get(dest_chain, "🔹")

    # Send initial status
    status_msg = await update.message.reply_text(
        f"🌉 <b>Starting Bridge ({speed_label})</b>\n\n⏳ Verifying PIN and initiating transfer...",
        parse_mode=ParseMode.HTML,
    )

    # Clear pending bridge before executing
    del context.user_data["pending_bridge"]

    # Execute the bridge using the status message as query
    try:
        chain_family = ChainFamily.EVM

        # Get private key
        try:
            private_key = await wallet_service.get_private_key(user.id, update.effective_user.id, chain_family, pin)
        except Exception as e:
            if "Decryption failed" in str(e):
                await status_msg.edit_text(
                    "❌ <b>Invalid PIN</b>\n\nPlease try again.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again", callback_data="wallet:bridge")],
                    ]),
                )
                return
            raise

        if not private_key:
            await status_msg.edit_text("❌ Failed to get wallet key.")
            return

        # For Solana destination, get Solana wallet address
        # For EVM destinations (including BSC), use EVM wallet
        to_address = None
        if dest == BridgeChain.SOLANA:
            solana_wallet = await get_wallet(user.id, ChainFamily.SOLANA)
            if not solana_wallet:
                await status_msg.edit_text("❌ No Solana wallet found.")
                return
            to_address = solana_wallet.public_key
        elif use_lifi:
            # For BSC and other LI.FI routes, destination is EVM wallet
            evm_wallet_obj = await get_wallet(user.id, ChainFamily.EVM)
            to_address = evm_wallet_obj.public_key if evm_wallet_obj else private_key.address

        # Show progress message
        await status_msg.edit_text(
            f"🌉 <b>Bridging USDC ({speed_label})</b>\n\n"
            f"From: {source.value.title()}\n"
            f"To: {dest.value.title()} {dest_emoji}\n"
            f"Amount: ${float(amount):.2f}\n\n"
            f"⏳ Initiating transfer...",
            parse_mode=ParseMode.HTML,
        )

        # Create progress callback
        main_loop = asyncio.get_running_loop()
        last_update_time = [0]

        async def update_progress(msg: str, elapsed: int, total: int):
            import time
            now = time.time()
            if now - last_update_time[0] < 3:  # Update more frequently for fast bridge
                return
            last_update_time[0] = now

            try:
                progress_pct = min(100, int((elapsed / max(1, total)) * 100))
                progress_bar = "█" * (progress_pct // 10) + "░" * (10 - progress_pct // 10)
                await status_msg.edit_text(
                    f"🌉 <b>Bridging USDC ({speed_label})</b>\n\n"
                    f"{escape_html(msg)}\n\n"
                    f"[{progress_bar}] {progress_pct}%",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        def sync_progress_callback(msg: str, elapsed: int, total: int):
            try:
                asyncio.run_coroutine_threadsafe(
                    update_progress(msg, elapsed, total),
                    main_loop
                )
            except Exception:
                pass

        # Execute bridge in thread (lifi, fast, or standard)
        if use_lifi:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc_lifi,
                private_key,
                source,
                dest,
                amount,
                to_address,
                sync_progress_callback,
            )
        elif use_fast_bridge:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc_fast,
                private_key,
                source,
                dest,
                amount,
                sync_progress_callback,
            )
        else:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc,
                private_key,
                source,
                dest,
                amount,
                sync_progress_callback,
            )

        if result.success:
            if use_lifi:
                text = f"""
✅ <b>LI.FI Bridge Complete!</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: ~${float(result.amount):.2f} USDC (after fees)

TX: <code>{result.burn_tx_hash[:16] if result.burn_tx_hash else 'pending'}...</code>

🔗 Funds are being delivered to your {dest.value.title()} wallet!
<i>Usually arrives in 1-3 minutes.</i>
"""
            elif use_fast_bridge:
                text = f"""
✅ <b>Fast Bridge Complete!</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: ${float(result.amount):.2f} USDC (after fees)

TX: <code>{result.burn_tx_hash[:16] if result.burn_tx_hash else 'pending'}...</code>

🚀 Funds are arriving on {dest.value.title()} now!
"""
            else:
                text = f"""
✅ <b>Bridge Initiated!</b>

From: {source.value.title()}
To: {dest.value.title()} {dest_emoji}
Amount: ${float(amount):.2f} USDC

Burn TX: <code>{result.burn_tx_hash[:16]}...</code>
"""
                if result.mint_tx_hash:
                    text += f"Mint TX: <code>{result.mint_tx_hash[:16]}...</code>\n"
                    text += f"\n✅ Bridge complete! Funds are now on {dest.value.title()}."
                else:
                    text += f"\n⏳ Waiting for Circle attestation. Funds will arrive on {dest.value.title()} in ~10-15 minutes."

        else:
            text = f"❌ <b>Bridge Failed</b>\n\n{friendly_error(result.error_message or 'Unknown error')}"

        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh Wallet", callback_data="wallet:refresh")],
                [InlineKeyboardButton("« Back to Wallet", callback_data="wallet:refresh")],
            ]),
        )

    except Exception as e:
        logger.error("Bridge with PIN failed", error=str(e))
        await status_msg.edit_text(
            f"❌ Bridge failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
            ]),
        )


async def handle_wallet_export(query, telegram_id: int) -> None:
    """Handle private key export."""
    text = """
⚠️ <b>Export Private Keys</b>

This will show your private keys. Anyone with these keys can access your funds!

<b>Only export if you need to:</b>
• Backup your wallet
• Import to another wallet app
• Migrate funds

Keys will be auto-deleted after 60 seconds.
"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Export Solana Key", callback_data="export:solana")],
        [InlineKeyboardButton("🔑 Export EVM Key", callback_data="export:evm")],
        [InlineKeyboardButton("« Back", callback_data="wallet:refresh")],
    ])
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_wallet_create_new(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle creating a new wallet with PIN protection."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Check if user has existing wallets with funds
    from src.db.database import get_user_wallets
    existing_wallets = await get_user_wallets(user.id)

    if existing_wallets:
        # Show warning about replacing wallets
        text = """
⚠️ <b>Create New Wallet</b>

You already have wallets. Creating new ones will:

• <b>Generate NEW wallet addresses</b>
• <b>Replace your existing wallets</b>
• Your old addresses will no longer work

<b>IMPORTANT:</b>
Before proceeding, make sure to:
1. Export your current private keys (if needed)
2. Transfer any funds to a safe location

<b>Are you sure you want to continue?</b>
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, Create New Wallet", callback_data="wallet:confirm_create")],
            [InlineKeyboardButton("📤 Export Keys First", callback_data="wallet:export")],
            [InlineKeyboardButton("❌ Cancel", callback_data="wallet:refresh")],
        ])
    else:
        # No existing wallets, go straight to PIN setup
        text = """
🔐 <b>Create Secure Wallet</b>

You'll create PIN-protected wallets for:
• <b>Solana</b> (for Kalshi trading)
• <b>EVM</b> (for Polymarket, Opinion, Limitless & Myriad)

Your PIN ensures only YOU can sign transactions.

<b>Ready to set up your secure wallets?</b>
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Set Up PIN", callback_data="wallet:confirm_create")],
            [InlineKeyboardButton("❌ Cancel", callback_data="wallet:refresh")],
        ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_wallet_confirm_create(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm wallet creation - delete old wallets and start PIN setup."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Delete existing wallets if any
    from src.db.database import delete_user_wallets
    await delete_user_wallets(user.id)

    # Start PIN setup
    context.user_data["pending_wallet_pin"] = {"confirm": False}

    text = """
🔐 <b>Set Your Wallet PIN</b>

Choose a 4-6 digit PIN to protect your wallets.

<b>Important:</b>
• Your PIN is NEVER stored anywhere
• It's used to encrypt your private keys
• Only you can access your funds with this PIN
• <b>If you forget it, your funds are LOST forever</b>

<b>Enter your PIN (4-6 digits):</b>
"""

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def handle_export_key(query, chain_type: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle exporting a private key - prompts for PIN."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Determine chain family
    if chain_type == "solana":
        chain_family = ChainFamily.SOLANA
        chain_name = "Solana"
    elif chain_type == "evm":
        chain_family = ChainFamily.EVM
        chain_name = "EVM"
    else:
        await query.edit_message_text("Invalid chain type.")
        return

    # Check if wallet has export PIN set
    has_pin = await wallet_service.has_export_pin(user.id, chain_family)

    if has_pin:
        # Has export PIN - prompt for verification
        context.user_data["pending_export"] = {
            "chain_family": chain_type,
        }

        text = f"""
🔑 <b>Export {chain_name} Private Key</b>

⚠️ <b>Warning:</b> Your private key gives full access to your funds!

🔐 <b>Enter your PIN to export:</b>
<i>(Your PIN is never stored)</i>

Type /cancel to cancel.
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="wallet:export")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        # No export PIN - allow direct export for legacy wallets
        # New wallets created via /resetwallet will have export PIN
        try:
            private_key = await wallet_service.export_private_key(user.id, telegram_id, chain_family, "")
            if private_key:
                text = f"""
🔑 <b>{chain_name} Private Key</b>

<code>{private_key}</code>

⚠️ <b>WARNING:</b>
• Anyone with this key can access your funds
• Never share this with anyone
• Store it securely offline

💡 <b>Tip:</b> Use /resetwallet to create a new wallet with PIN protection for exports.

<i>This message should be deleted after copying.</i>
"""
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑 Delete", callback_data="wallet:refresh")],
                ])

                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            else:
                await query.edit_message_text("❌ Wallet not found.")
        except Exception as e:
            logger.error("Export key failed", error=str(e))
            await query.edit_message_text(f"❌ Export failed: {friendly_error(str(e))}")


async def handle_markets_refresh(query, telegram_id: int, page: int = 0) -> None:
    """Refresh markets list with pagination."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    platform_info = PLATFORM_INFO[user.active_platform]
    platform = get_platform(user.active_platform)

    await query.edit_message_text(
        f"🔄 Loading {platform_info['name']} markets...",
        parse_mode=ParseMode.HTML,
    )

    # Pagination settings
    per_page = 10
    offset = page * per_page

    try:
        # Fetch more to account for deduplication of multi-outcome events
        markets = await platform.get_markets(limit=(per_page * 3) + 1, offset=offset, active_only=True)

        # Deduplicate multi-outcome events by event_id or title
        seen_events = set()
        unique_markets = []
        for market in markets:
            # Use event_id for multi-outcome, fallback to title for dedup
            if market.is_multi_outcome:
                # Use event_id if available, otherwise use title as dedup key
                dedup_key = market.event_id if market.event_id else market.title
            else:
                dedup_key = market.market_id

            if dedup_key not in seen_events:
                seen_events.add(dedup_key)
                unique_markets.append(market)

        markets = unique_markets
        has_next = len(markets) > per_page
        markets = markets[:per_page]  # Trim to actual page size

        if not markets:
            await query.edit_message_text(
                f"No markets found on {platform_info['name']}.",
                parse_mode=ParseMode.HTML,
            )
            return

        page_display = page + 1
        text = f"{platform_info['emoji']} <b>Trending on {platform_info['name']}</b>\n"
        text += f"<i>Page {page_display}</i>\n\n"

        buttons = []
        for i, market in enumerate(markets, 1):
            display_num = offset + i
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            exp = format_expiration(market.close_time)

            # Indicator for multi-outcome markets
            multi_indicator = f" [{market.related_market_count} options]" if market.is_multi_outcome else ""

            text += f"<b>{display_num}.</b> {title}{multi_indicator}\n"
            if market.is_multi_outcome and market.outcome_name:
                text += f"   {escape_html(market.outcome_name)}: {yes_prob} • Vol: {format_usd(market.volume_24h)} • Exp: {exp}\n\n"
            else:
                text += f"   YES: {yes_prob} • Vol: {format_usd(market.volume_24h)} • Exp: {exp}\n\n"

            buttons.append([
                InlineKeyboardButton(
                    f"{display_num}. {market.title[:30]}...",
                    callback_data=f"market:{user.active_platform.value}:{market.market_id[:40]}"
                )
            ])

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("« Previous", callback_data=f"markets:page:{page - 1}"))
        if has_next:
            nav_buttons.append(InlineKeyboardButton("Next »", callback_data=f"markets:page:{page + 1}"))
        if nav_buttons:
            buttons.append(nav_buttons)

        buttons.append([
            InlineKeyboardButton("📂 Categories", callback_data="categories"),
            InlineKeyboardButton("🔄 Refresh", callback_data="markets:refresh"),
        ])
        buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to refresh markets", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load markets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_categories_menu(query, telegram_id: int) -> None:
    """Show categories menu."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Only Polymarket, Limitless, Kalshi, Opinion, and Myriad support categories currently
    if user.active_platform not in (Platform.POLYMARKET, Platform.LIMITLESS, Platform.KALSHI, Platform.OPINION, Platform.MYRIAD):
        await query.edit_message_text(
            "📂 <b>Categories</b>\n\n"
            "Categories are currently only available for Polymarket, Limitless, Kalshi, Opinion, and Myriad.\n\n"
            "Switch to one of these platforms to browse by category.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="markets:refresh")],
            ]),
        )
        return

    platform = get_platform(user.active_platform)
    categories = platform.get_available_categories()

    text = "📂 <b>Browse by Category</b>\n\n"
    text += "Select a category to see related markets:\n"

    buttons = []
    # Create 2-column layout for categories
    for i in range(0, len(categories), 2):
        row = []
        for j in range(2):
            if i + j < len(categories):
                cat = categories[i + j]
                row.append(InlineKeyboardButton(
                    f"{cat['emoji']} {cat['label']}",
                    callback_data=f"category:{cat['id']}"
                ))
        buttons.append(row)

    # Add fast crypto markets buttons
    if user.active_platform == Platform.KALSHI:
        buttons.append([
            InlineKeyboardButton("⏱️ 15m Markets", callback_data="markets:15m"),
            InlineKeyboardButton("🕐 Hourly Markets", callback_data="markets:hourly"),
        ])
    if user.active_platform == Platform.MYRIAD:
        buttons.append([
            InlineKeyboardButton("🕐 5m Candles", callback_data="markets:5m"),
        ])
    buttons.append([InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_category_view(query, category_id: str, telegram_id: int, page: int = 0) -> None:
    """Show markets in a category with pagination."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    platform = get_platform(user.active_platform)
    categories = platform.get_available_categories()

    # Find category info
    category_info = next((c for c in categories if c["id"] == category_id), None)
    category_label = category_info["label"] if category_info else category_id.title()
    category_emoji = category_info["emoji"] if category_info else "📂"

    MARKETS_PER_PAGE = 10

    try:
        # Fetch markets (Limitless API has max limit of 25)
        all_markets = await platform.get_markets_by_category(category_id, limit=25)

        if not all_markets:
            await query.edit_message_text(
                f"{category_emoji} <b>{category_label}</b>\n\n"
                "No active markets found in this category.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back to Categories", callback_data="categories")],
                ]),
            )
            return

        # Calculate pagination
        total_markets = len(all_markets)
        total_pages = (total_markets + MARKETS_PER_PAGE - 1) // MARKETS_PER_PAGE
        page = max(0, min(page, total_pages - 1))  # Clamp page to valid range

        start_idx = page * MARKETS_PER_PAGE
        end_idx = min(start_idx + MARKETS_PER_PAGE, total_markets)
        markets = all_markets[start_idx:end_idx]

        text = f"{category_emoji} <b>{category_label} Markets</b>"
        if total_pages > 1:
            text += f" (Page {page + 1}/{total_pages})"
        text += "\n\n"

        buttons = []
        for i, market in enumerate(markets, start_idx + 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            exp = format_expiration(market.close_time)

            # Indicator for multi-outcome markets
            multi_indicator = f" [{market.related_market_count} options]" if market.is_multi_outcome else ""

            text += f"<b>{i}.</b> {title}{multi_indicator}\n"
            if market.is_multi_outcome and market.outcome_name:
                text += f"   {escape_html(market.outcome_name)}: {yes_prob} • Vol: {format_usd(market.volume_24h)} • Exp: {exp}\n\n"
            else:
                text += f"   YES: {yes_prob} • Vol: {format_usd(market.volume_24h)} • Exp: {exp}\n\n"

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:{user.active_platform.value}:{market.market_id[:40]}"
                )
            ])

        # Add pagination buttons if needed
        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("« Prev", callback_data=f"category:{category_id}:{page - 1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Next »", callback_data=f"category:{category_id}:{page + 1}"))
            buttons.append(nav_buttons)

        buttons.append([InlineKeyboardButton("« Back to Categories", callback_data="categories")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to load category markets", category=category_id, error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load {category_label} markets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Categories", callback_data="categories")],
            ]),
        )


async def handle_15m_markets(query, telegram_id: int, page: int = 0) -> None:
    """Show 15-minute Kalshi markets with pagination."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # 15-minute markets are only available on Kalshi
    from src.platforms.kalshi import KalshiPlatform
    kalshi = get_platform(Platform.KALSHI)

    if not isinstance(kalshi, KalshiPlatform):
        await query.edit_message_text(
            "❌ 15-minute markets are only available on Kalshi.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="markets:refresh")],
            ]),
        )
        return

    await query.edit_message_text(
        "⏱️ Loading 15-minute markets...",
        parse_mode=ParseMode.HTML,
    )

    MARKETS_PER_PAGE = 10

    try:
        # Fetch 15-minute markets
        all_markets = await kalshi.get_15m_markets(limit=50)

        if not all_markets:
            await query.edit_message_text(
                "⏱️ <b>15-Minute Markets</b>\n\n"
                "No active 15-minute markets found.\n\n"
                "<i>These are fast-expiring crypto price markets (BTC, ETH, SOL) "
                "that settle every 15 minutes.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="markets:15m")],
                    [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
                ]),
            )
            return

        # Calculate pagination
        total_markets = len(all_markets)
        total_pages = (total_markets + MARKETS_PER_PAGE - 1) // MARKETS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * MARKETS_PER_PAGE
        end_idx = min(start_idx + MARKETS_PER_PAGE, total_markets)
        markets = all_markets[start_idx:end_idx]

        text = "⏱️ <b>15-Minute Kalshi Markets</b>"
        if total_pages > 1:
            text += f" (Page {page + 1}/{total_pages})"
        text += "\n<i>Fast-expiring crypto price predictions</i>\n\n"

        buttons = []
        for i, market in enumerate(markets, start_idx + 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            exp = format_expiration(market.close_time)

            text += f"<b>{i}.</b> {title}\n"
            text += f"   YES: {yes_prob} • Exp: {exp}\n\n"

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:kalshi:{market.market_id[:40]}"
                )
            ])

        # Add pagination buttons if needed
        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("« Prev", callback_data=f"markets15m:page:{page - 1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Next »", callback_data=f"markets15m:page:{page + 1}"))
            buttons.append(nav_buttons)

        buttons.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="markets:15m"),
        ])
        buttons.append([InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to load 15m markets", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load 15-minute markets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
            ]),
        )


async def handle_hourly_markets(query, telegram_id: int, page: int = 0) -> None:
    """Show hourly Kalshi crypto markets with pagination."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    from src.platforms.kalshi import KalshiPlatform
    kalshi = get_platform(Platform.KALSHI)

    if not isinstance(kalshi, KalshiPlatform):
        await query.edit_message_text(
            "❌ Hourly markets are only available on Kalshi.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="markets:refresh")],
            ]),
        )
        return

    await query.edit_message_text(
        "🕐 Loading hourly markets...",
        parse_mode=ParseMode.HTML,
    )

    MARKETS_PER_PAGE = 10

    try:
        all_markets = await kalshi.get_hourly_markets(limit=50)

        if not all_markets:
            await query.edit_message_text(
                "🕐 <b>Hourly Markets</b>\n\n"
                "No active hourly markets found.\n\n"
                "<i>These are crypto price above/below markets (BTC, ETH, SOL, XRP, DOGE) "
                "that settle every hour.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="markets:hourly")],
                    [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
                ]),
            )
            return

        total_markets = len(all_markets)
        total_pages = (total_markets + MARKETS_PER_PAGE - 1) // MARKETS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * MARKETS_PER_PAGE
        end_idx = min(start_idx + MARKETS_PER_PAGE, total_markets)
        markets = all_markets[start_idx:end_idx]

        text = "🕐 <b>Hourly Kalshi Markets</b>"
        if total_pages > 1:
            text += f" (Page {page + 1}/{total_pages})"
        text += "\n<i>Crypto price above/below predictions</i>\n\n"

        buttons = []
        for i, market in enumerate(markets, start_idx + 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            exp = format_expiration(market.close_time)

            text += f"<b>{i}.</b> {title}\n"
            text += f"   YES: {yes_prob} • Exp: {exp}\n\n"

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:kalshi:{market.market_id[:40]}"
                )
            ])

        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("« Prev", callback_data=f"marketshourly:page:{page - 1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Next »", callback_data=f"marketshourly:page:{page + 1}"))
            buttons.append(nav_buttons)

        buttons.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="markets:hourly"),
        ])
        buttons.append([InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to load hourly markets", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load hourly markets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
            ]),
        )


async def handle_5m_markets(query, telegram_id: int, page: int = 0) -> None:
    """Show 5-minute crypto candle markets from Myriad (BNB Chain)."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    from src.platforms.myriad import MyriadPlatform
    myriad = get_platform(Platform.MYRIAD)

    if not isinstance(myriad, MyriadPlatform):
        await query.edit_message_text(
            "❌ 5-minute candle markets require Myriad platform.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back", callback_data="markets:refresh")],
            ]),
        )
        return

    await query.edit_message_text(
        "🕐 Loading 5-minute candle markets...",
        parse_mode=ParseMode.HTML,
    )

    MARKETS_PER_PAGE = 10

    try:
        all_markets = await myriad.get_5m_markets(limit=50)

        if not all_markets:
            await query.edit_message_text(
                "🕐 <b>5-Minute Candle Markets</b>\n\n"
                "No active 5-minute candle markets found.\n\n"
                "<i>These are fast-expiring crypto candle predictions (BTC, ETH, BNB) "
                "on BNB Chain that settle every 5 minutes.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="markets:5m")],
                    [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
                ]),
            )
            return

        total_markets = len(all_markets)
        total_pages = (total_markets + MARKETS_PER_PAGE - 1) // MARKETS_PER_PAGE
        page = max(0, min(page, total_pages - 1))

        start_idx = page * MARKETS_PER_PAGE
        end_idx = min(start_idx + MARKETS_PER_PAGE, total_markets)
        markets = all_markets[start_idx:end_idx]

        text = "🕐 <b>5-Minute Candle Markets</b>"
        if total_pages > 1:
            text += f" (Page {page + 1}/{total_pages})"
        text += "\n<i>Predict if the next candle will be green or red</i>\n\n"

        buttons = []
        for i, market in enumerate(markets, start_idx + 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            exp = format_expiration(market.close_time)

            text += f"<b>{i}.</b> {title}\n"
            text += f"   Green: {yes_prob} • Exp: {exp}\n\n"

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:myriad:{market.market_id[:40]}"
                )
            ])

        if total_pages > 1:
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("« Prev", callback_data=f"markets5m:page:{page - 1}"))
            nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Next »", callback_data=f"markets5m:page:{page + 1}"))
            buttons.append(nav_buttons)

        buttons.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="markets:5m"),
        ])
        buttons.append([InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to load 5m markets", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load 5-minute markets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
            ]),
        )


async def handle_main_menu(query, telegram_id: int) -> None:
    """Show main menu."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    info = PLATFORM_INFO[user.active_platform]

    text = f"""
🎯 <b>Spredd Markets</b>

Current Platform: {info['emoji']} {info['name']}

<b>What would you like to do?</b>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Browse Markets", callback_data="markets:refresh")],
        [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        [InlineKeyboardButton("📊 My Positions", callback_data="positions:view")],
        [InlineKeyboardButton("🔄 Switch Platform", callback_data="menu:platform")],
        [InlineKeyboardButton("❓ FAQ", callback_data="faq:menu")],
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_faq_topic(query, topic: str) -> None:
    """Handle FAQ topic display."""

    faq_content = {
        "menu": {
            "title": "❓ Frequently Asked Questions",
            "text": "Select a topic to learn more:",
            "buttons": [
                ("🔐 Is this non-custodial?", "faq:noncustodial"),
                ("🔑 Why do I need a PIN?", "faq:pin"),
                ("💰 What are the fees?", "faq:fees"),
                ("📥 How do I deposit?", "faq:deposit"),
                ("🔄 USDC Auto-Swap", "faq:autoswap"),
                ("🌉 Cross-Chain Bridging", "faq:bridge"),
                ("⚠️ Security warnings", "faq:security"),
            ],
        },
        "noncustodial": {
            "title": "🔐 Is this non-custodial?",
            "text": """<b>Yes, Spredd is non-custodial.</b>

Your private keys are encrypted and stored securely. Only YOU can export your keys using your PIN.

<b>What this means:</b>
• We cannot access your private keys
• We cannot export your wallet
• Your keys stay encrypted at rest
• Trading is seamless - no PIN needed for trades

<b>How it works:</b>
• Private keys are encrypted using our secure encryption
• Your PIN is hashed separately for export verification
• Trading doesn't require PIN entry (for convenience)
• Exporting keys requires your PIN (for security)

<b>You are fully in control of your funds.</b>""",
        },
        "pin": {
            "title": "🔑 Why do I need a PIN?",
            "text": """<b>Your PIN protects your private key export.</b>

The PIN ensures only YOU can export your wallet's private keys. This prevents unauthorized access to your keys.

<b>PIN requirements:</b>
• 4-6 digits
• Set when creating your wallet
• Required ONLY for exporting private keys
• The PIN hash is stored (not the PIN itself)

<b>How it's used:</b>
• <b>Trading:</b> No PIN needed - trade instantly
• <b>Exporting keys:</b> PIN required for security

<b>Important:</b>
• Choose a PIN you'll remember
• Don't share it with anyone
• If you forget it, you cannot export your keys
• Your funds remain accessible for trading

<b>This design balances security with convenience - trade fast, export securely.</b>""",
        },
        "fees": {
            "title": "💰 What are the fees?",
            "text": """<b>Fee Structure:</b>

<b>Spredd Bot Fees:</b>
• <b>2% transaction fee</b> on all trades
• No deposit/withdrawal fees
• Fee supports referral program rewards

<b>Referral Rewards (from our 2% fee):</b>
• Tier 1 referrers earn 25% of fee
• Tier 2 referrers earn 5% of fee
• Tier 3 referrers earn 3% of fee

<b>Platform Fees (charged by markets):</b>
• <b>Kalshi:</b> ~2% on winnings
• <b>Polymarket:</b> ~2% trading fee
• <b>Limitless:</b> ~3% trading fee
• <b>Opinion Labs:</b> Varies by market

<b>Network Fees (blockchain gas):</b>
• <b>Solana:</b> ~$0.001 per transaction
• <b>Polygon:</b> ~$0.01 per transaction
• <b>Base:</b> ~$0.01 per transaction
• <b>BSC:</b> ~$0.10 per transaction

<b>Note:</b> You need native tokens (SOL, MATIC, ETH, BNB) in your wallet to pay gas fees.""",
        },
        "deposit": {
            "title": "📥 How do I deposit?",
            "text": """<b>Depositing Funds:</b>

1️⃣ Go to /wallet to see your addresses

2️⃣ Send funds to the correct address:

<b>For Kalshi (Solana):</b>
• Send USDC (SPL) to your Solana address
• Also send small amount of SOL for gas (~0.01 SOL)

<b>For Polymarket (Polygon):</b>
• Send USDC to your EVM address
• Also send MATIC for gas (~0.1 MATIC)

<b>For Opinion Labs (BSC):</b>
• Send USDT to your EVM address
• Also send BNB for gas (~0.005 BNB)

<b>For Monad:</b>
• Send USDC to your EVM address
• Also send MON for gas (~0.01 MON)

<b>Important:</b>
• Double-check the network before sending
• Your EVM address works on Polygon, BSC, and Monad
• Start with small amounts to test""",
        },
        "autoswap": {
            "title": "🔄 USDC Auto-Swap (Polymarket)",
            "text": """<b>Automatic USDC Conversion for Polymarket</b>

Polymarket requires <b>USDC.e</b> (bridged USDC), not native USDC. The bot automatically handles this for you!

<b>How it works:</b>
When you start a trade on Polymarket, the bot checks your balances:

✅ <b>If USDC.e is $5 or more:</b>
Trade proceeds normally

🔄 <b>If USDC.e is under $5 but native USDC is $5+:</b>
Bot automatically swaps your native USDC to USDC.e via Uniswap, then proceeds with trade

❌ <b>If both are under $5:</b>
You'll be asked to deposit more USDC

<b>Why this matters:</b>
• On Polygon, there are TWO types of USDC
• <b>Native USDC</b> (0x3c49...) - Circle's official USDC
• <b>USDC.e</b> (0x2791...) - Bridged from Ethereum
• Polymarket only accepts USDC.e

<b>Swap details:</b>
• Uses Uniswap V3 (0.05% fee tier)
• About 1% slippage tolerance
• Nearly 1:1 exchange rate
• Requires MATIC for gas

<b>The swap happens BEFORE you enter your trade amount, so prices won't change during the swap.</b>""",
        },
        "bridge": {
            "title": "🌉 Cross-Chain Bridging",
            "text": """<b>Trade on Polymarket with USDC from Other Chains</b>

Have USDC on Base, Arbitrum, Monad or other chains? The bot can bridge it to Polygon for you!

<b>Supported Source Chains:</b>
• Base
• Arbitrum One
• Optimism
• Ethereum Mainnet
• Monad

<b>Two Bridge Options:</b>

🚀 <b>FAST BRIDGE (~30 seconds)</b>
• Powered by Relay.link
• Near-instant transfers
• Small fee (typically 0.1-0.5%)
• Best for: Quick trades, time-sensitive markets

🐢 <b>STANDARD BRIDGE (~15 min, FREE)</b>
• Uses Circle's CCTP protocol
• No fees (only gas costs)
• Burns on source → Mints on destination
• Best for: Large amounts, no rush

<b>How it works:</b>
1️⃣ Select source chain and amount
2️⃣ Choose speed (Fast or Standard)
3️⃣ Confirm the bridge transaction
4️⃣ USDC arrives on Polygon automatically

<b>What is CCTP?</b>
Circle's Cross-Chain Transfer Protocol - the official way to move native USDC. It's secure but requires ~15 min for Circle to verify the burn.

<b>What is Relay.link?</b>
A fast bridge protocol that provides instant liquidity. You pay a small fee but get your USDC in ~30 seconds.

<b>Important Notes:</b>
• You need gas tokens on BOTH chains
• Market prices won't change during bridging
• If bridge fails, funds stay on source chain

<b>Choose Fast for convenience, Standard for savings!</b>""",
        },
        "security": {
            "title": "⚠️ Security Warnings",
            "text": """<b>Keep Your Funds Safe:</b>

🔴 <b>NEVER share your PIN</b>
Anyone with your PIN can export your private keys

🔴 <b>NEVER share your private keys</b>
Use /export only for backup purposes

🔴 <b>Remember your PIN</b>
Lost PIN = Cannot export keys (trading still works)

🔴 <b>Verify addresses</b>
Always double-check before depositing

🔴 <b>Start small</b>
Test with small amounts first

🔴 <b>Beware of scams</b>
We will NEVER DM you first
We will NEVER ask for your PIN
We will NEVER ask for private keys

<b>If something seems suspicious, stop and verify.</b>

Official support: @spreddterminal""",
        },
    }

    content = faq_content.get(topic)
    if not content:
        await query.edit_message_text("FAQ topic not found.")
        return

    text = f"<b>{content['title']}</b>\n\n{content['text']}"

    if "buttons" in content:
        # Menu with multiple buttons
        buttons = [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in content["buttons"]]
        buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])
        keyboard = InlineKeyboardMarkup(buttons)
    else:
        # Single FAQ page with back button
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back to FAQ", callback_data="faq:menu")],
            [InlineKeyboardButton("« Main Menu", callback_data="menu:main")],
        ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_referral_action(query, action: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, chain_param: str = None) -> None:
    """Handle referral-related callback actions."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    if action == "refresh":
        await handle_referral_hub(query, telegram_id, context)

    elif action == "copy":
        # Show the invite link prominently for easy copying
        referral_code = await get_or_create_referral_code(user.id)
        bot_username = (await context.bot.get_me()).username
        invite_link = f"https://t.me/{bot_username}?start=ref_{referral_code}"

        text = f"""
📋 <b>Your Referral Link</b>

Share this link with friends:

<code>{invite_link}</code>

<i>Tap to copy, then share!</i>

You earn:
• 25% of fees from direct referrals (Tier 1)
• 5% of fees from their referrals (Tier 2)
• 3% of fees from Tier 2's referrals (Tier 3)
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back to Referrals", callback_data="referral:refresh")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    elif action == "withdraw":
        # chain_param will be "solana" or "evm"
        chain_family = ChainFamily.SOLANA if chain_param == "solana" else ChainFamily.EVM
        await handle_referral_withdraw(query, telegram_id, context, chain_family)


async def handle_referral_hub(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the referral space (refresh)."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get or create referral code
    referral_code = await get_or_create_referral_code(user.id)

    # Get referral stats
    stats = await get_referral_stats(user.id)

    # Get fee balances for all chains
    fee_balances = await get_all_fee_balances(user.id)

    # Organize by chain
    solana_balance = None
    evm_balance = None
    for balance in fee_balances:
        if balance.chain_family == ChainFamily.SOLANA:
            solana_balance = balance
        elif balance.chain_family == ChainFamily.EVM:
            evm_balance = balance

    # Format amounts
    solana_claimable = format_usdc(solana_balance.claimable_usdc) if solana_balance else "$0.00"
    solana_earned = format_usdc(solana_balance.total_earned_usdc) if solana_balance else "$0.00"
    evm_claimable = format_usdc(evm_balance.claimable_usdc) if evm_balance else "$0.00"
    evm_earned = format_usdc(evm_balance.total_earned_usdc) if evm_balance else "$0.00"

    # Calculate totals
    total_claimable = Decimal(solana_balance.claimable_usdc if solana_balance else "0") + \
                      Decimal(evm_balance.claimable_usdc if evm_balance else "0")
    total_earned = Decimal(solana_balance.total_earned_usdc if solana_balance else "0") + \
                   Decimal(evm_balance.total_earned_usdc if evm_balance else "0")

    # Build invite link
    bot_username = (await context.bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start=ref_{referral_code}"

    # Calculate total reach
    total_reach = stats["tier1"] + stats["tier2"] + stats["tier3"]

    text = f"""
🫂 <b>Referral Space</b>
Earn commissions when your referrals trade!

🪪 <b>Your Code:</b> <code>{referral_code}</code>
🔗 <b>Invite Link:</b>
<code>{invite_link}</code>

━━━━━━━━━━━━━━━━
🛰 <b>Network Metrics</b>
├ Tier 1 (Direct): <b>{stats["tier1"]}</b> users (25%)
├ Tier 2: <b>{stats["tier2"]}</b> users (5%)
├ Tier 3: <b>{stats["tier3"]}</b> users (3%)
└ Total Reach: <b>{total_reach}</b> users

━━━━━━━━━━━━━━━━
💰 <b>Earnings Dashboard</b>

<b>🟣 Solana (Kalshi)</b>
├ Claimable: <b>{solana_claimable}</b> USDC
└ Total Earned: <b>{solana_earned}</b> USDC

<b>🔷 EVM (Polymarket/Opinion/Limitless/Myriad)</b>
├ Claimable: <b>{evm_claimable}</b> USDC
└ Total Earned: <b>{evm_earned}</b> USDC

📊 <b>Combined:</b> {format_usdc(str(total_claimable))} claimable / {format_usdc(str(total_earned))} earned

⚠️ <i>Minimum withdrawal: ${MIN_WITHDRAWAL_USDC} USDC per chain</i>
"""

    # Build keyboard
    buttons = [
        [InlineKeyboardButton("📋 Copy Invite Link", callback_data="referral:copy")],
    ]

    # Add withdraw buttons for each chain that meets minimum
    withdraw_buttons = []
    if solana_balance and can_withdraw(solana_balance.claimable_usdc):
        withdraw_buttons.append(
            InlineKeyboardButton("💸 Withdraw Solana", callback_data="referral:withdraw:solana")
        )
    if evm_balance and can_withdraw(evm_balance.claimable_usdc):
        withdraw_buttons.append(
            InlineKeyboardButton("💸 Withdraw EVM", callback_data="referral:withdraw:evm")
        )
    if withdraw_buttons:
        buttons.append(withdraw_buttons)

    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="referral:refresh")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_referral_withdraw(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, chain_family: ChainFamily) -> None:
    """Handle withdrawal of referral earnings for a specific chain."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get fee balance for the specific chain
    fee_balance = await get_fee_balance(user.id, chain_family)
    if not fee_balance or not can_withdraw(fee_balance.claimable_usdc):
        await query.edit_message_text(
            f"❌ <b>Cannot Withdraw</b>\n\n"
            f"Minimum withdrawal is ${MIN_WITHDRAWAL_USDC} USDC.\n"
            f"Your {chain_family.value.upper()} balance: {format_usdc(fee_balance.claimable_usdc) if fee_balance else '$0.00'}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Referrals", callback_data="referral:refresh")],
            ]),
        )
        return

    # Show withdrawal confirmation
    claimable = format_usdc(fee_balance.claimable_usdc)

    # Determine chain-specific info
    if chain_family == ChainFamily.SOLANA:
        chain_display = "🟣 Solana"
        wallet_info = "your Solana wallet"
    else:
        chain_display = "🔷 EVM (Polygon)"
        wallet_info = "your EVM wallet (Polygon USDC)"

    # Store pending withdrawal state
    context.user_data["pending_withdrawal"] = {
        "amount": fee_balance.claimable_usdc,
        "chain_family": chain_family.value,
    }

    text = f"""
💸 <b>Withdraw {chain_display} Referral Earnings</b>

Amount: <b>{claimable}</b> USDC

Withdrawals are sent to {wallet_info}.

<b>Enter your PIN to confirm withdrawal:</b>
<i>(Your PIN is never stored)</i>

Type /cancel to cancel.
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="referral:refresh")],
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ===================
# Buy Order Processing
# ===================

async def handle_buy_confirm(query, platform_value: str, market_id: str, outcome: str, amount_str: str, telegram_id: int) -> None:
    """Execute the confirmed buy order."""
    # Truncate for callback_data limit
    short_market_id = market_id[:40]

    try:
        amount = Decimal(amount_str)
        platform_enum = Platform(platform_value)
    except (InvalidOperation, ValueError):
        await query.edit_message_text("Invalid order data.")
        return

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # DFlow Proof KYC gate for Kalshi
    if platform_enum == Platform.KALSHI:
        if not await check_and_gate_proof_kyc(query, user, telegram_id):
            return

    platform = get_platform(platform_enum)
    platform_info = PLATFORM_INFO[platform_enum]
    chain_family = get_chain_family_for_platform(platform_enum)

    # Get correct collateral symbol for this market's network
    market = await platform.get_market(market_id)
    collateral_sym = get_collateral_for_market(platform_enum, market)

    await query.edit_message_text(
        f"⏳ Executing order...\n\nBuying {outcome.upper()} with {amount} {collateral_sym}",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get fresh quote
        from src.db.models import Outcome as OutcomeEnum
        outcome_enum = OutcomeEnum.YES if outcome == "yes" else OutcomeEnum.NO

        quote = await platform.get_quote(
            market_id=market_id,
            outcome=outcome_enum,
            side="buy",
            amount=amount,
        )

        # Get private key directly (no PIN required for trading)
        private_key = await wallet_service.get_private_key(user.id, telegram_id, chain_family)
        if not private_key:
            await query.edit_message_text("❌ Wallet not found. Please try again.")
            return

        # For Polymarket, check if we need to swap native USDC to USDC.e before trading
        if platform_enum == Platform.POLYMARKET:
            from src.platforms.polymarket import polymarket_platform
            native_balance, bridged_balance = polymarket_platform.get_usdc_balances(private_key.address)
            total_polygon = native_balance + bridged_balance

            # If not enough USDC.e but combined balance is enough, swap native USDC
            if bridged_balance < amount and total_polygon >= amount and native_balance > Decimal("0.01"):
                await query.edit_message_text(
                    f"💱 Swapping USDC → USDC.e for trading...\n\n"
                    f"Amount: {native_balance:.2f} USDC",
                    parse_mode=ParseMode.HTML,
                )

                success, swap_tx, swap_error = polymarket_platform.swap_native_to_bridged_usdc(
                    private_key, native_balance
                )

                if not success:
                    await query.edit_message_text(
                        f"❌ <b>Swap Failed</b>\n\n{escape_html(swap_error or 'Unknown error')}",
                        parse_mode=ParseMode.HTML,
                    )
                    return

                await query.edit_message_text(
                    f"✅ Swapped USDC → USDC.e\n\n⏳ Executing order...",
                    parse_mode=ParseMode.HTML,
                )

        # Get market title from quote data or fetch market
        # Prefer outcome_name or question for player props
        market_title = None
        market = await platform.get_market(market_id)
        if market:
            # For multi-outcome/player props, use outcome_name if available
            if market.outcome_name:
                market_title = market.outcome_name
            elif market.raw_data and isinstance(market.raw_data, dict):
                market_raw = market.raw_data.get("market", {})
                if isinstance(market_raw, dict):
                    market_title = (
                        market_raw.get("question") or
                        market_raw.get("groupItemTitle") or
                        market.title
                    )
                else:
                    market_title = market.title
            else:
                market_title = market.title
        elif quote.quote_data and "market" in quote.quote_data:
            market_data = quote.quote_data["market"]
            market_title = market_data.get("question") or market_data.get("title") or market_data.get("market_title")

        # Create order record before executing
        order = await create_order(
            user_id=user.id,
            platform=platform_enum,
            chain=quote.chain,
            market_id=market_id,
            outcome=outcome,
            side="buy",
            input_token=quote.input_token,
            input_amount=str(int(amount * Decimal(10**6))),
            output_token=quote.output_token,
            expected_output=str(int(quote.expected_output * Decimal(10**6))) if quote.expected_output else "0",
            price=float(quote.price_per_token) if quote.price_per_token else None,
            market_title=market_title,
        )

        # Execute trade
        result = await platform.execute_trade(quote, private_key)

        if result.success:
            # Update order as confirmed
            await update_order(
                order.id,
                status=OrderStatus.CONFIRMED,
                tx_hash=result.tx_hash,
                executed_at=datetime.now(timezone.utc),
            )

            # Check if order was actually filled (not just placed in orderbook)
            is_orderbook_order = result.error_message and "orderbook" in result.error_message.lower()
            actual_output = result.output_amount if result.output_amount else Decimal("0")

            # Only process fees and create position if order was filled
            if actual_output > 0 and not is_orderbook_order:
                # Process trading fee and distribute to referrers
                fee_result = await process_trade_fee(
                    trader_telegram_id=telegram_id,
                    order_id=order.id,
                    trade_amount_usdc=str(amount),
                    platform=platform_enum,
                )

                # Create position record (market_title already set above)
                try:
                    # For Limitless, the exchange fee (3%) is deducted from output tokens
                    # Adjust stored amount to reflect actual received tokens
                    adjusted_output = actual_output
                    if platform_enum == Platform.LIMITLESS:
                        # fee_rate_bps=300 means 3% fee deducted from output
                        adjusted_output = actual_output * Decimal("0.97")
                        logger.info(
                            "Adjusted token amount for Limitless fee",
                            raw_output=str(actual_output),
                            adjusted_output=str(adjusted_output),
                        )

                    token_amount = str(int(adjusted_output * Decimal(10**6)))

                    await create_position(
                        user_id=user.id,
                        platform=platform_enum,
                        chain=quote.chain,
                        market_id=market_id,
                        market_title=market_title,
                        outcome=outcome,
                        token_id=quote.output_token,
                        token_amount=token_amount,
                        entry_price=float(quote.price_per_token) if quote.price_per_token else 0.0,
                        event_id=market.event_id if market else None,  # Store slug for Limitless lookups
                    )
                except Exception as pos_error:
                    logger.warning("Failed to create position record", error=str(pos_error))

                fee_amount = fee_result.get("fee", "0")
                fee_display = format_usdc(fee_amount) if Decimal(fee_amount) > 0 else ""
                fee_line = f"\n💸 Fee: {fee_display}" if fee_display else ""

                # Check for marketing qualification postback (first trade over $5)
                try:
                    from src.services.postback import check_and_send_trade_postback
                    await check_and_send_trade_postback(
                        telegram_id=telegram_id,
                        trade_amount=amount,
                        fee_amount=Decimal(fee_amount) if fee_amount else Decimal("0"),
                    )
                except Exception as pb_error:
                    logger.debug("Postback check failed", error=str(pb_error))

                text = f"""
✅ <b>Order Executed!</b>

Bought {outcome.upper()} position
Amount: {amount} {collateral_sym}{fee_line}
Received: ~{actual_output:.2f} tokens

<a href="{result.explorer_url}">View Transaction</a>
"""
            else:
                # Order was placed in orderbook but not filled
                text = f"""
⏳ <b>Limit Order Placed</b>

Your {outcome.upper()} order has been placed in the orderbook.
Amount: {amount} {collateral_sym}
Price: {quote.price_per_token:.4f}

The order will fill when a matching seller is found.
Check your orders on the exchange to monitor status.

Note: No position created until order fills.
"""
        else:
            # Update order as failed
            await update_order(
                order.id,
                status=OrderStatus.FAILED,
                error_message=result.error_message,
            )

            text = f"""
❌ <b>Order Failed</b>

{friendly_error(result.error_message or 'Unknown error')}

Please check your wallet balance and try again.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Back to Markets", callback_data="markets:refresh")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
            [InlineKeyboardButton("📊 View Positions", callback_data="positions:refresh")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error("Trade execution failed", error=str(e))
        # Add retry button to go back to market with fresh prices
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Retry", callback_data=f"buy:{platform_value}:{short_market_id}:{outcome}")],
            [InlineKeyboardButton("« Back to Markets", callback_data=f"markets:{platform_value}:1")],
        ])
        await query.edit_message_text(
            f"❌ Trade failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=retry_keyboard,
        )


async def handle_sell_start(query, position_id: str, telegram_id: int) -> None:
    """Show sell options for a position."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    position = await get_position_by_id(position_id)
    if not position:
        await query.edit_message_text("❌ Position not found.")
        return

    if position.user_id != user.id:
        await query.edit_message_text("❌ This position doesn't belong to you.")
        return

    if position.status != PositionStatus.OPEN:
        await query.edit_message_text("❌ This position is already closed.")
        return

    platform = get_platform(position.platform)
    platform_info = PLATFORM_INFO[position.platform]

    # Get current price - try event_id (slug) first for Limitless
    current_price = None
    try:
        lookup_id = position.event_id if position.event_id else position.market_id
        market = await platform.get_market(lookup_id, search_title=position.market_title)
        if not market and position.event_id:
            market = await platform.get_market(position.market_id, search_title=position.market_title)
        if market:
            outcome_str = position.outcome.upper() if isinstance(position.outcome, str) else position.outcome.value.upper()
            if outcome_str == "YES":
                current_price = market.yes_price
            else:
                current_price = market.no_price
    except Exception:
        pass

    # Calculate position value
    token_amount = Decimal(position.token_amount) / Decimal(10**6)
    entry_price = Decimal(str(position.entry_price)) if position.entry_price else Decimal("0")
    current_price_dec = Decimal(str(current_price)) if current_price else entry_price

    # Position value = tokens * current price (what you'd get if you sold)
    position_value = token_amount * current_price_dec
    cost_basis = token_amount * entry_price

    # P&L
    if current_price and entry_price:
        pnl = position_value - cost_basis
        pnl_pct = ((current_price_dec - entry_price) / entry_price) * 100 if entry_price > 0 else Decimal(0)
        pnl_str = f"+${pnl:.2f} (+{pnl_pct:.1f}%)" if pnl >= 0 else f"-${abs(pnl):.2f} ({pnl_pct:.1f}%)"
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    else:
        pnl_str = "N/A"
        pnl_emoji = "⚪"

    outcome_str = position.outcome.upper() if isinstance(position.outcome, str) else position.outcome.value.upper()
    title = escape_html(position.market_title[:50] + "..." if len(position.market_title) > 50 else position.market_title)

    text = f"""
💰 <b>Sell Position</b>

<b>{title}</b>

Outcome: {outcome_str}
Tokens: {token_amount:.4f}
Entry Price: {format_price(entry_price)}
Current Price: {format_price(current_price_dec)}

💵 <b>Position Value: ~${position_value:.2f}</b>
{pnl_emoji} P&L: {pnl_str}

Select amount to sell:
"""

    # Sell amount buttons
    buttons = [
        [
            InlineKeyboardButton("25%", callback_data=f"sell_confirm:{position_id}:25"),
            InlineKeyboardButton("50%", callback_data=f"sell_confirm:{position_id}:50"),
        ],
        [
            InlineKeyboardButton("75%", callback_data=f"sell_confirm:{position_id}:75"),
            InlineKeyboardButton("100% (All)", callback_data=f"sell_confirm:{position_id}:100"),
        ],
        [InlineKeyboardButton("« Back to Positions", callback_data="positions:0")],
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_sell_confirm(query, position_id: str, percent_str: str, telegram_id: int) -> None:
    """Execute the sell order."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    position = await get_position_by_id(position_id)
    if not position:
        await query.edit_message_text("❌ Position not found.")
        return

    if position.user_id != user.id:
        await query.edit_message_text("❌ This position doesn't belong to you.")
        return

    if position.status != PositionStatus.OPEN:
        await query.edit_message_text("❌ This position is already closed.")
        return

    # DFlow Proof KYC gate for Kalshi
    if position.platform == Platform.KALSHI:
        if not await check_and_gate_proof_kyc(query, user, telegram_id):
            return

    try:
        percent = int(percent_str)
    except ValueError:
        await query.edit_message_text("❌ Invalid percentage.")
        return

    platform = get_platform(position.platform)
    platform_info = PLATFORM_INFO[position.platform]
    chain_family = get_chain_family_for_platform(position.platform)

    # Get correct collateral symbol for this market's network
    sell_market_info = await platform.get_market(position.market_id)
    collateral_sym = get_collateral_for_market(position.platform, sell_market_info)

    outcome_str = position.outcome.upper() if isinstance(position.outcome, str) else position.outcome.value.upper()

    await query.edit_message_text(
        f"⏳ Checking balance...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get private key directly (no PIN required for trading)
        private_key = await wallet_service.get_private_key(user.id, telegram_id, chain_family)
        if not private_key:
            await query.edit_message_text("❌ Wallet not found. Please try again.")
            return

        from src.db.models import Outcome as OutcomeEnum
        outcome_enum = OutcomeEnum.YES if outcome_str == "YES" else OutcomeEnum.NO

        # Get actual on-chain token balance before selling
        actual_balance = None
        if position.platform == Platform.KALSHI:
            # Get the market to find the token mint
            market = await platform.get_market(position.market_id)
            if market:
                token_mint = market.yes_token if outcome_str == "YES" else market.no_token
                if token_mint and hasattr(platform, 'get_token_balance'):
                    wallet_pubkey = str(private_key.pubkey())
                    actual_balance = await platform.get_token_balance(wallet_pubkey, token_mint)
                    logger.info(
                        "Checked actual token balance (Kalshi)",
                        stored=str(Decimal(position.token_amount) / Decimal(10**6)),
                        actual=str(actual_balance),
                        market_id=position.market_id,
                    )
        elif position.platform == Platform.LIMITLESS:
            # Check on-chain CTF token balance for Limitless
            # private_key is an EVM LocalAccount with .address attribute
            if hasattr(private_key, 'address') and hasattr(platform, 'get_token_balance'):
                wallet_address = private_key.address
                # Use event_id (slug) for market lookup, fall back to market_id
                lookup_id = position.event_id if position.event_id else position.market_id
                actual_balance = await platform.get_token_balance(wallet_address, lookup_id, outcome_enum)
                logger.info(
                    "Checked actual token balance (Limitless)",
                    stored=str(Decimal(position.token_amount) / Decimal(10**6)),
                    actual=str(actual_balance) if actual_balance else "None",
                    market_id=position.market_id,
                    lookup_id=lookup_id,
                )

        # Use actual balance if available, otherwise fall back to stored
        stored_amount = Decimal(position.token_amount) / Decimal(10**6)
        if actual_balance is not None and actual_balance > 0:
            token_amount = actual_balance
            if actual_balance < stored_amount:
                logger.warning(
                    "Actual balance less than stored",
                    stored=str(stored_amount),
                    actual=str(actual_balance),
                )
        else:
            token_amount = stored_amount

        if token_amount <= 0:
            await query.edit_message_text(
                "❌ No tokens found in wallet for this position.\n\n"
                "The position may have already been sold or redeemed.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Calculate sell amount based on actual balance
        sell_amount = (token_amount * Decimal(percent)) / Decimal(100)

        await query.edit_message_text(
            f"⏳ Executing sell...\n\nSelling {percent}% of {outcome_str} position (~{sell_amount:.4f} tokens)",
            parse_mode=ParseMode.HTML,
        )

        # Use event_id (slug) for Limitless, otherwise market_id
        quote_market_id = position.event_id if position.event_id else position.market_id

        quote = await platform.get_quote(
            market_id=quote_market_id,
            outcome=outcome_enum,
            side="sell",
            amount=sell_amount,
            token_id=position.token_id,  # Use stored token_id from position
        )

        # Create order record
        order = await create_order(
            user_id=user.id,
            platform=position.platform,
            chain=quote.chain,
            market_id=position.market_id,
            outcome=outcome_str.lower(),
            side="sell",
            input_token=quote.input_token,
            input_amount=str(int(sell_amount * Decimal(10**6))),
            output_token=quote.output_token,
            expected_output=str(int(quote.expected_output * Decimal(10**6))) if quote.expected_output else "0",
            price=float(quote.price_per_token) if quote.price_per_token else None,
            market_title=position.market_title,
        )

        # Execute trade
        result = await platform.execute_trade(quote, private_key)

        if result.success:
            # Update order as confirmed
            await update_order(
                order.id,
                status=OrderStatus.CONFIRMED,
                tx_hash=result.tx_hash,
                executed_at=datetime.now(timezone.utc),
            )

            # Process trading fee
            fee_result = await process_trade_fee(
                trader_telegram_id=telegram_id,
                order_id=order.id,
                trade_amount_usdc=str(quote.expected_output) if quote.expected_output else "0",
                platform=position.platform,
            )

            # Update position - use actual balance for remaining calculation
            actual_remaining = token_amount - sell_amount
            remaining_raw = int(actual_remaining * Decimal(10**6))
            if remaining_raw <= 0 or percent == 100:
                # Position fully closed
                await update_position(
                    position_id,
                    status=PositionStatus.CLOSED,
                    token_amount="0",
                )
            else:
                # Partial sell - update remaining tokens based on actual balance
                await update_position(
                    position_id,
                    token_amount=str(remaining_raw),
                )

            fee_amount = fee_result.get("fee", "0")
            fee_display = format_usdc(fee_amount) if Decimal(fee_amount) > 0 else ""
            fee_line = f"\n💸 Fee: {fee_display}" if fee_display else ""

            # Calculate profit/loss
            entry_cost = Decimal(str(position.entry_price)) * sell_amount
            sale_revenue = quote.expected_output if quote.expected_output else Decimal("0")
            profit = sale_revenue - entry_cost
            profit_percent = ((sale_revenue / entry_cost) - 1) * 100 if entry_cost > 0 else Decimal("0")
            is_profitable = profit > 0

            if is_profitable:
                profit_line = f"\n🎉 Profit: +${profit:.2f} (+{profit_percent:.1f}%)"
            else:
                profit_line = f"\n📉 Loss: -${abs(profit):.2f} ({profit_percent:.1f}%)"

            text = f"""
✅ <b>Sold Successfully!</b>

Sold {percent}% of {outcome_str} position
Tokens Sold: ~{sell_amount:.4f}
Received: ~${quote.expected_output:.2f} {collateral_sym}{fee_line}{profit_line}

<a href="{result.explorer_url}">View Transaction</a>
"""
            # Store data for win card generation (position_id:exit_price_x1000)
            if is_profitable and quote.price_per_token:
                exit_price_int = int(float(quote.price_per_token) * 1000)
                win_callback_data = f"{position_id}:{exit_price_int}"
            else:
                win_callback_data = None
        else:
            # Update order as failed
            await update_order(
                order.id,
                status=OrderStatus.FAILED,
                error_message=result.error_message,
            )

            text = f"""
❌ <b>Sell Failed</b>

{friendly_error(result.error_message or 'Unknown error')}

Please try again.
"""
            win_callback_data = None

        # Build keyboard with optional Share Win button
        buttons = []
        if win_callback_data:
            buttons.append([InlineKeyboardButton("📤 Share Win", callback_data=f"sellwin:{win_callback_data}")])
        buttons.append([InlineKeyboardButton("📊 View Positions", callback_data="positions:0")])
        buttons.append([InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")])
        keyboard = InlineKeyboardMarkup(buttons)

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error("Sell execution failed", error=str(e))
        # Add retry button to go back to sell options
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Retry", callback_data=f"sell_start:{position_id}")],
            [InlineKeyboardButton("« Back to Positions", callback_data="positions")],
        ])
        await query.edit_message_text(
            f"❌ Sell failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=retry_keyboard,
        )


async def handle_redeem(query, position_id: str, telegram_id: int) -> None:
    """Redeem winning tokens from a resolved market."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    position = await get_position_by_id(position_id)
    if not position:
        await query.edit_message_text("❌ Position not found.")
        return

    if position.user_id != user.id:
        await query.edit_message_text("❌ This position doesn't belong to you.")
        return

    platform = get_platform(position.platform)
    platform_info = PLATFORM_INFO[position.platform]
    chain_family = get_chain_family_for_platform(position.platform)

    # Get position details
    token_amount = Decimal(position.token_amount) / Decimal(10**6)
    outcome_str = position.outcome.upper() if isinstance(position.outcome, str) else position.outcome.value.upper()

    await query.edit_message_text(
        f"⏳ Redeeming {outcome_str} position...\n\n"
        f"Tokens: {token_amount:.4f}\n"
        f"Expected: ~${token_amount:.2f} USDC",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get private key directly (no PIN required for trading)
        private_key = await wallet_service.get_private_key(user.id, telegram_id, chain_family)
        if not private_key:
            await query.edit_message_text("❌ Wallet not found. Please try again.")
            return

        # Get outcome enum
        from src.db.models import Outcome as OutcomeEnum
        outcome_enum = OutcomeEnum.YES if outcome_str == "YES" else OutcomeEnum.NO

        # Execute redemption - use event_id (slug) for Limitless
        redeem_market_id = position.event_id if position.event_id else position.market_id
        result = await platform.redeem_position(
            market_id=redeem_market_id,
            outcome=outcome_enum,
            token_amount=token_amount,
            private_key=private_key,
        )

        if result.success:
            # Update position as redeemed
            await update_position(
                position_id,
                status=PositionStatus.REDEEMED,
                token_amount="0",
            )

            text = f"""
🏆 <b>Redemption Successful!</b>

Redeemed {outcome_str} position
Amount: ~${result.amount_redeemed:.2f} USDC

<a href="{result.explorer_url}">View Transaction</a>
"""
        else:
            text = f"""
❌ <b>Redemption Failed</b>

{friendly_error(result.error_message or 'Unknown error')}

Please try again or redeem manually.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 View Positions", callback_data="positions:0")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error("Redemption failed", error=str(e))
        await query.edit_message_text(
            f"❌ Redemption failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_polymarket_chain_select(query, chain: str, telegram_id: int) -> None:
    """Handle chain selection for Polymarket: Polygon stays Polymarket, Solana switches to Jupiter."""
    if chain == "solana":
        platform = Platform.JUPITER
        # Check Jupiter API key is configured
        if not settings.is_platform_configured("jupiter"):
            await query.edit_message_text(
                "⚠️ <b>Solana settlement is not available yet.</b>\n\n"
                "Jupiter API key is not configured. Please use Polygon for now.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬡ Use Polygon", callback_data="polychain:polygon")],
                    [InlineKeyboardButton("🔄 Switch Platform", callback_data="menu:platform")],
                ]),
            )
            return
    else:
        platform = Platform.POLYMARKET

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    await update_user_platform(telegram_id, platform)

    info = PLATFORM_INFO[platform]
    chain_family = get_chain_family_for_platform(platform)

    from src.db.database import get_user_wallets
    existing_wallets = await get_user_wallets(user.id)

    if not existing_wallets:
        text = f"""
{info['emoji']} <b>{info['name']} Selected!</b>

Before you can trade, you need to set up your wallet.

<b>Use /wallet to create your secure wallets with PIN protection.</b>
"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔐 Set Up Wallet", callback_data="wallet:setup")],
            [InlineKeyboardButton("🔄 Switch Platform", callback_data="menu:platform")],
        ])
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        return

    wallet = None
    for w in existing_wallets:
        if w.chain_family == chain_family:
            wallet = w
            break
    wallet_addr = wallet.public_key if wallet else "Not created"

    text = f"""
{info['emoji']} <b>{info['name']} Selected!</b>

Chain: {info['chain']}
Collateral: {info['collateral']}

Your {info['chain']} Wallet:
<code>{wallet_addr}</code>

<b>What would you like to do?</b>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Browse Markets", callback_data="markets:refresh")],
        [InlineKeyboardButton("🔍 Search Markets", callback_data="menu:search")],
        [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        [InlineKeyboardButton("🔄 Switch Platform", callback_data="menu:platform")],
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_buy_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, amount_text: str) -> None:
    """Process buy order amount from user."""
    if not update.effective_user or not update.message:
        return

    pending = context.user_data.get("pending_buy")
    if not pending:
        return

    # Parse amount
    try:
        amount = Decimal(amount_text)
        if amount <= 0:
            raise ValueError("Amount must be positive")
    except (InvalidOperation, ValueError):
        await update.message.reply_text(
            "❌ Invalid amount. Please enter a number like: 10 or 5.5\n\n"
            "Type /cancel to cancel the order.",
            parse_mode=ParseMode.HTML,
        )
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return

    platform_value = pending["platform"]
    market_id = pending["market_id"]
    outcome = pending["outcome"]

    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await update.message.reply_text("Invalid platform.")
        context.user_data.pop("pending_buy", None)
        return

    platform = get_platform(platform_enum)
    platform_info = PLATFORM_INFO[platform_enum]

    # Use stored collateral symbol from buy prompt, or fallback
    collateral_sym = pending.get("collateral_symbol") or platform_info['collateral']

    await update.message.reply_text(
        f"⏳ Getting quote for {amount} {collateral_sym}...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get market info
        market = await platform.get_market(market_id)
        if not market:
            context.user_data.pop("pending_buy", None)
            await update.message.reply_text("❌ Market not found.")
            return

        # Update collateral symbol with actual market network info
        collateral_sym = get_collateral_for_market(platform_enum, market)

        # Get quote
        from src.db.models import Outcome as OutcomeEnum
        outcome_enum = OutcomeEnum.YES if outcome == "yes" else OutcomeEnum.NO

        quote = await platform.get_quote(
            market_id=market_id,
            outcome=outcome_enum,
            side="buy",
            amount=amount,
        )

        # Show quote confirmation
        expected_tokens = quote.expected_output
        price = quote.price_per_token

        # Calculate fee for display
        fee = calculate_fee(str(amount))
        fee_display = format_usdc(fee)

        # Clear pending_buy and store confirmation data
        context.user_data.pop("pending_buy", None)
        context.user_data["pending_confirm"] = {
            "platform": platform_value,
            "market_id": market_id,
            "outcome": outcome,
            "amount": str(amount),
        }

        # Get market's displayed price (mid-price) for comparison
        displayed_price = market.yes_price if outcome == "yes" else market.no_price
        price_warning = ""
        if displayed_price and price:
            diff = abs(float(price) - float(displayed_price))
            if diff > 0.05:  # More than 5% difference
                price_warning = f"\n⚠️ <b>Note:</b> Execution price ({format_probability(price)}) differs from displayed mid-price ({format_probability(displayed_price)}) due to orderbook depth.\n"

        # Check for liquidity warning from Limitless
        liquidity_warning = ""
        if quote.quote_data:
            warning_msg = quote.quote_data.get("liquidity_warning")
            if warning_msg:
                liquidity_warning = f"\n⚠️ <b>Warning:</b> {warning_msg}\n"

        # Check if this is a player prop market (contains over/under in title, outcome_name, or question)
        import re
        def has_ou_keywords(text):
            """Check for over/under patterns as whole words (not substrings like 'thunder')."""
            if not text:
                return False
            t = text.lower()
            if re.search(r'\bover\b', t) or re.search(r'\bunder\b', t):
                return True
            return "o/u" in t or " ou " in t

        # Check all relevant fields
        question_text = ""
        if market.raw_data and isinstance(market.raw_data, dict):
            market_raw = market.raw_data.get("market", {})
            if isinstance(market_raw, dict):
                question_text = market_raw.get("question") or market_raw.get("groupItemTitle") or ""

        is_player_prop = (
            has_ou_keywords(market.title) or
            has_ou_keywords(market.outcome_name) or
            has_ou_keywords(question_text)
        )

        if is_player_prop:
            # Player prop - use Over/Under labels
            side_label = "OVER" if outcome == "yes" else "UNDER"
            token_label = "OVER" if outcome == "yes" else "UNDER"
        else:
            # Regular market - use YES/NO labels
            side_label = outcome.upper()
            token_label = outcome.upper()

        text = f"""
📋 <b>Order Quote</b>

Market: {escape_html(market.title[:50])}...
Side: BUY {side_label}

💰 <b>You Pay:</b> {amount} {collateral_sym}
💸 <b>Fee (2%):</b> {fee_display}
📦 <b>You Receive:</b> ~{expected_tokens:.2f} {token_label} tokens
📊 <b>Execution Price:</b> {format_probability(price)} per token
{price_warning}{liquidity_warning}"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_buy")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_buy")],
        ])

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Quote failed", error=str(e))
        context.user_data.pop("pending_buy", None)
        await update.message.reply_text(
            f"❌ Failed to get quote: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_balance_check_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Handle PIN entry for balance check before Polymarket trade."""
    if not update.effective_user or not update.message:
        return

    pending = context.user_data.get("pending_balance_check")
    if not pending:
        await update.message.reply_text("No pending balance check.")
        return

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        del context.user_data["pending_balance_check"]
        await update.message.reply_text("Please /start first!")
        return

    platform_value = pending["platform"]
    market_id = pending["market_id"]
    outcome = pending["outcome"]
    chain_family = ChainFamily.EVM
    # Truncate for callback_data limit
    short_market_id = market_id[:40]

    status_msg = await update.message.reply_text(
        "🔄 Verifying PIN and checking USDC balance...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get private key with PIN
        private_key = await wallet_service.get_private_key(user.id, update.effective_user.id, chain_family, pin)

        from src.platforms.polymarket import polymarket_platform, MIN_USDC_BALANCE

        # Create progress callback for bridge updates
        last_update_time = [0]  # Use list to allow modification in closure
        main_loop = asyncio.get_running_loop()  # Capture main event loop

        async def update_progress(msg: str, elapsed: int, total: int):
            import time
            # Throttle updates to once per 5 seconds to avoid rate limits
            now = time.time()
            if now - last_update_time[0] < 5:
                return
            last_update_time[0] = now

            try:
                progress_pct = min(100, int((elapsed / max(1, total)) * 100))
                progress_bar = "█" * (progress_pct // 10) + "░" * (10 - progress_pct // 10)
                await status_msg.edit_text(
                    f"🌉 <b>Bridging USDC</b>\n\n"
                    f"{escape_html(msg)}\n\n"
                    f"[{progress_bar}] {progress_pct}%",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass  # Ignore update errors

        # Wrap async callback for sync bridge service (called from thread)
        def sync_progress_callback(msg: str, elapsed: int, total: int):
            try:
                # Schedule coroutine on main event loop from thread
                future = asyncio.run_coroutine_threadsafe(
                    update_progress(msg, elapsed, total),
                    main_loop
                )
                # Don't wait for result, just fire and forget
            except Exception:
                pass

        # Check and auto-swap/bridge USDC if needed
        ready, message, swap_tx = await polymarket_platform.ensure_usdc_balance(
            private_key, MIN_USDC_BALANCE, progress_callback=sync_progress_callback
        )

        del context.user_data["pending_balance_check"]

        if not ready:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
            ])
            await status_msg.edit_text(
                f"❌ <b>Cannot Trade</b>\n\n{escape_html(message)}",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return

        # Balance OK - proceed to buy flow
        swap_note = ""
        if swap_tx:
            if "Bridged" in message:
                swap_note = f"\n\n✅ <i>{escape_html(message)}</i>"
            else:
                swap_note = "\n\n✅ <i>Auto-swapped USDC to USDC.e</i>"

        # Fetch market to check if it's a player prop
        platform = get_platform(Platform(platform_value))
        market = await platform.get_market(market_id)
        collateral_symbol = get_collateral_for_market(Platform(platform_value), market)

        context.user_data["pending_buy"] = {
            "platform": platform_value,
            "market_id": market_id,
            "outcome": outcome,
            "pin_protected": True,
            "verified_pin": pin,  # Store PIN for trade execution
            "collateral_symbol": collateral_symbol,
        }

        info = PLATFORM_INFO[Platform(platform_value)]

        # Check if this is a player prop market
        import re
        def has_ou_keywords(text):
            if not text:
                return False
            t = text.lower()
            if re.search(r'\bover\b', t) or re.search(r'\bunder\b', t):
                return True
            return "o/u" in t or " ou " in t

        is_player_prop = False
        if market:
            question_text = ""
            if market.raw_data and isinstance(market.raw_data, dict):
                market_raw = market.raw_data.get("market", {})
                if isinstance(market_raw, dict):
                    question_text = market_raw.get("question") or market_raw.get("groupItemTitle") or ""
            is_player_prop = (
                has_ou_keywords(market.title) or
                has_ou_keywords(market.outcome_name) or
                has_ou_keywords(question_text)
            )

        # Use appropriate label
        if is_player_prop:
            position_label = "OVER" if outcome == "yes" else "UNDER"
        else:
            position_label = outcome.upper()

        text = f"""
💰 <b>Buy {position_label} Position</b>

Platform: {info['name']}
Collateral: {collateral_symbol}{swap_note}

Enter the amount in {collateral_symbol} you want to spend:

<i>Example: 10 (for 10 {collateral_symbol})</i>

Type /cancel to cancel.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{short_market_id}")],
        ])

        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        del context.user_data["pending_balance_check"]
        error_msg = str(e)
        if "Decryption failed" in error_msg or "Invalid" in error_msg:
            await status_msg.edit_text(
                "❌ <b>Invalid PIN</b>\n\nThe PIN you entered is incorrect.",
                parse_mode=ParseMode.HTML,
            )
        else:
            logger.error("Balance check with PIN failed", error=error_msg)
            await status_msg.edit_text(
                f"❌ Error: {friendly_error(error_msg)}",
                parse_mode=ParseMode.HTML,
            )


async def handle_buy_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Process buy order with user's PIN."""
    if not update.effective_user or not update.message:
        return

    pending = context.user_data.get("pending_buy")
    if not pending or not pending.get("awaiting_pin"):
        return

    # Validate PIN format (4-6 digits recommended)
    if not pin.isdigit() or len(pin) < 4:
        await update.message.reply_text(
            "❌ Invalid PIN format. Please enter your 4-6 digit PIN.\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.HTML,
        )
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        context.user_data.pop("pending_buy", None)
        return

    platform_value = pending["platform"]
    market_id = pending["market_id"]
    outcome = pending["outcome"]
    amount_str = pending["amount"]
    # Truncate for callback_data limit
    short_market_id = market_id[:40]

    # Clear pending state
    context.user_data.pop("pending_buy", None)

    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await update.message.reply_text("Invalid platform.")
        return

    platform = get_platform(platform_enum)
    platform_info = PLATFORM_INFO[platform_enum]
    chain_family = get_chain_family_for_platform(platform_enum)

    # Get correct collateral symbol (stored during buy prompt, or fetch market)
    collateral_sym = pending.get("collateral_symbol") or platform_info['collateral']

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Send executing message (use chat.send_message since original may be deleted)
    executing_msg = await update.effective_chat.send_message(
        f"⏳ Executing order...\n\nBuying {outcome.upper()} with {amount_str} {collateral_sym}",
        parse_mode=ParseMode.HTML,
    )

    try:
        amount = Decimal(amount_str)

        # Get fresh quote
        from src.db.models import Outcome as OutcomeEnum
        outcome_enum = OutcomeEnum.YES if outcome == "yes" else OutcomeEnum.NO

        quote = await platform.get_quote(
            market_id=market_id,
            outcome=outcome_enum,
            side="buy",
            amount=amount,
        )

        # Get private key with PIN
        try:
            private_key = await wallet_service.get_private_key(user.id, update.effective_user.id, chain_family, pin)
        except Exception as decrypt_error:
            if "Decryption failed" in str(decrypt_error):
                await executing_msg.edit_text(
                    "❌ <b>Invalid PIN</b>\n\nThe PIN you entered is incorrect.",
                    parse_mode=ParseMode.HTML,
                )
                return
            raise

        if not private_key:
            await executing_msg.edit_text("❌ Wallet not found.")
            return

        # For Polymarket, check if we need to swap native USDC to USDC.e before trading
        if platform_enum == Platform.POLYMARKET:
            from src.platforms.polymarket import polymarket_platform
            native_balance, bridged_balance = polymarket_platform.get_usdc_balances(private_key.address)
            total_polygon = native_balance + bridged_balance

            # If not enough USDC.e but combined balance is enough, swap native USDC
            if bridged_balance < amount and total_polygon >= amount and native_balance > Decimal("0.01"):
                await executing_msg.edit_text(
                    f"💱 Swapping USDC → USDC.e for trading...\n\n"
                    f"Amount: {native_balance:.2f} USDC",
                    parse_mode=ParseMode.HTML,
                )

                success, swap_tx, swap_error = polymarket_platform.swap_native_to_bridged_usdc(
                    private_key, native_balance
                )

                if not success:
                    await executing_msg.edit_text(
                        f"❌ <b>Swap Failed</b>\n\n{escape_html(swap_error or 'Unknown error')}",
                        parse_mode=ParseMode.HTML,
                    )
                    return

                await executing_msg.edit_text(
                    f"✅ Swapped USDC → USDC.e\n\n⏳ Executing order...",
                    parse_mode=ParseMode.HTML,
                )

        # Get market title from quote data or fetch market
        # Prefer outcome_name or question for player props
        market_title = None
        market = await platform.get_market(market_id)
        if market:
            # For multi-outcome/player props, use outcome_name if available
            if market.outcome_name:
                market_title = market.outcome_name
            elif market.raw_data and isinstance(market.raw_data, dict):
                market_raw = market.raw_data.get("market", {})
                if isinstance(market_raw, dict):
                    market_title = (
                        market_raw.get("question") or
                        market_raw.get("groupItemTitle") or
                        market.title
                    )
                else:
                    market_title = market.title
            else:
                market_title = market.title
        elif quote.quote_data and "market" in quote.quote_data:
            market_data = quote.quote_data["market"]
            market_title = market_data.get("question") or market_data.get("title") or market_data.get("market_title")

        # Create order record before executing
        order = await create_order(
            user_id=user.id,
            platform=platform_enum,
            chain=quote.chain,
            market_id=market_id,
            outcome=outcome,
            side="buy",
            input_token=quote.input_token,
            input_amount=str(int(amount * Decimal(10**6))),
            output_token=quote.output_token,
            expected_output=str(int(quote.expected_output * Decimal(10**6))) if quote.expected_output else "0",
            price=float(quote.price_per_token) if quote.price_per_token else None,
            market_title=market_title,
        )

        # Execute trade
        result = await platform.execute_trade(quote, private_key)

        if result.success:
            # Update order as confirmed
            await update_order(
                order.id,
                status=OrderStatus.CONFIRMED,
                tx_hash=result.tx_hash,
                executed_at=datetime.now(timezone.utc),
            )

            # Check if order was actually filled (not just placed in orderbook)
            is_orderbook_order = result.error_message and "orderbook" in result.error_message.lower()
            actual_output = result.output_amount if result.output_amount else Decimal("0")

            # Only process fees and create position if order was filled
            if actual_output > 0 and not is_orderbook_order:
                # Process trading fee and distribute to referrers
                fee_result = await process_trade_fee(
                    trader_telegram_id=update.effective_user.id,
                    order_id=order.id,
                    trade_amount_usdc=str(amount),
                    platform=platform_enum,
                )

                # Create position record (market_title already set above)
                try:
                    # For Limitless, the exchange fee (3%) is deducted from output tokens
                    adjusted_output = actual_output
                    if platform_enum == Platform.LIMITLESS:
                        adjusted_output = actual_output * Decimal("0.97")
                        logger.info(
                            "Adjusted token amount for Limitless fee",
                            raw_output=str(actual_output),
                            adjusted_output=str(adjusted_output),
                        )

                    token_amount = str(int(adjusted_output * Decimal(10**6)))

                    await create_position(
                        user_id=user.id,
                        platform=platform_enum,
                        chain=quote.chain,
                        market_id=market_id,
                        market_title=market_title,
                        outcome=outcome,
                        token_id=quote.output_token,
                        token_amount=token_amount,
                        entry_price=float(quote.price_per_token) if quote.price_per_token else 0.0,
                        event_id=market.event_id if market else None,  # Store slug for Limitless lookups
                    )
                except Exception as pos_error:
                    logger.warning("Failed to create position record", error=str(pos_error))

                fee_amount = fee_result.get("fee", "0")
                fee_display = format_usdc(fee_amount) if Decimal(fee_amount) > 0 else ""
                fee_line = f"\n💸 Fee: {fee_display}" if fee_display else ""

                # Check for marketing qualification postback (first trade over $5)
                try:
                    from src.services.postback import check_and_send_trade_postback
                    await check_and_send_trade_postback(
                        telegram_id=update.effective_user.id,
                        trade_amount=amount,
                        fee_amount=Decimal(fee_amount) if fee_amount else Decimal("0"),
                    )
                except Exception as pb_error:
                    logger.debug("Postback check failed", error=str(pb_error))

                text = f"""
✅ <b>Order Executed!</b>

Bought {outcome.upper()} position
Amount: {amount} {collateral_sym}{fee_line}
Received: ~{actual_output:.2f} tokens

<a href="{result.explorer_url}">View Transaction</a>
"""
            else:
                # Order was placed in orderbook but not filled
                text = f"""
⏳ <b>Limit Order Placed</b>

Your {outcome.upper()} order has been placed in the orderbook.
Amount: {amount} {collateral_sym}
Price: {quote.price_per_token:.4f}

The order will fill when a matching seller is found.
Check your orders on the exchange to monitor status.

Note: No position created until order fills.
"""
        else:
            # Update order as failed
            await update_order(
                order.id,
                status=OrderStatus.FAILED,
                error_message=result.error_message,
            )

            text = f"""
❌ <b>Order Failed</b>

{friendly_error(result.error_message or 'Unknown error')}

Please check your wallet balance and try again.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Back to Markets", callback_data="markets:refresh")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
            [InlineKeyboardButton("📊 View Positions", callback_data="positions:refresh")],
        ])

        await executing_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error("Trade with PIN failed", error=str(e))
        # Add retry button to go back to market with fresh prices
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Retry", callback_data=f"buy:{platform_value}:{short_market_id}:{outcome}")],
            [InlineKeyboardButton("« Back to Markets", callback_data=f"markets:{platform_value}:1")],
        ])
        await executing_msg.edit_text(
            f"❌ Trade failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=retry_keyboard,
        )


async def handle_sell_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Process sell order with user's PIN."""
    if not update.effective_user or not update.message:
        return

    pending = context.user_data.get("pending_sell")
    if not pending or not pending.get("awaiting_pin"):
        return

    # Validate PIN format (4-6 digits)
    if not pin.isdigit() or len(pin) < 4:
        await update.message.reply_text(
            "❌ Invalid PIN format. Please enter your 4-6 digit PIN.\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.HTML,
        )
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        del context.user_data["pending_sell"]
        return

    position_id = pending["position_id"]
    percent = pending["percent"]

    # Clear pending state
    del context.user_data["pending_sell"]

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Get position
    position = await get_position_by_id(position_id)
    if not position:
        await update.effective_chat.send_message("❌ Position not found.")
        return

    if position.user_id != user.id:
        await update.effective_chat.send_message("❌ This position doesn't belong to you.")
        return

    if position.status != PositionStatus.OPEN:
        await update.effective_chat.send_message("❌ This position is already closed.")
        return

    platform = get_platform(position.platform)
    platform_info = PLATFORM_INFO[position.platform]
    chain_family = get_chain_family_for_platform(position.platform)

    # Get correct collateral symbol for this market's network
    sell_market = await platform.get_market(position.market_id)
    collateral_sym = get_collateral_for_market(position.platform, sell_market)

    # Calculate sell amount
    token_amount = Decimal(position.token_amount) / Decimal(10**6)
    sell_amount = (token_amount * Decimal(percent)) / Decimal(100)
    outcome_str = position.outcome.upper() if isinstance(position.outcome, str) else position.outcome.value.upper()

    # Send executing message
    executing_msg = await update.effective_chat.send_message(
        f"⏳ Executing sell...\n\nSelling {percent}% of {outcome_str} position (~{sell_amount:.4f} tokens)",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get private key with PIN
        try:
            private_key = await wallet_service.get_private_key(user.id, update.effective_user.id, chain_family, pin)
        except Exception as decrypt_error:
            if "Decryption failed" in str(decrypt_error):
                await executing_msg.edit_text(
                    "❌ <b>Invalid PIN</b>\n\nThe PIN you entered is incorrect.",
                    parse_mode=ParseMode.HTML,
                )
                return
            raise

        if not private_key:
            await executing_msg.edit_text("❌ Wallet not found.")
            return

        # Get quote for selling
        from src.db.models import Outcome as OutcomeEnum
        outcome_enum = OutcomeEnum.YES if outcome_str == "YES" else OutcomeEnum.NO

        quote = await platform.get_quote(
            market_id=position.market_id,
            outcome=outcome_enum,
            side="sell",
            amount=sell_amount,
            token_id=position.token_id,  # Use stored token_id from position
        )

        # Create order record
        order = await create_order(
            user_id=user.id,
            platform=position.platform,
            chain=quote.chain,
            market_id=position.market_id,
            outcome=outcome_str.lower(),
            side="sell",
            input_token=quote.input_token,
            input_amount=str(int(sell_amount * Decimal(10**6))),
            output_token=quote.output_token,
            expected_output=str(int(quote.expected_output * Decimal(10**6))) if quote.expected_output else "0",
            price=float(quote.price_per_token) if quote.price_per_token else None,
            market_title=position.market_title,
        )

        # Execute trade
        result = await platform.execute_trade(quote, private_key)

        if result.success:
            # Update order as confirmed
            await update_order(
                order.id,
                status=OrderStatus.CONFIRMED,
                tx_hash=result.tx_hash,
                executed_at=datetime.now(timezone.utc),
            )

            # Process trading fee
            fee_result = await process_trade_fee(
                trader_telegram_id=update.effective_user.id,
                order_id=order.id,
                trade_amount_usdc=str(quote.expected_output) if quote.expected_output else "0",
                platform=position.platform,
            )

            # Update position - use actual balance for remaining calculation
            actual_remaining = token_amount - sell_amount
            remaining_raw = int(actual_remaining * Decimal(10**6))
            if remaining_raw <= 0 or percent == 100:
                # Position fully closed
                await update_position(
                    position_id,
                    status=PositionStatus.CLOSED,
                    token_amount="0",
                )
            else:
                # Partial sell - update remaining tokens based on actual balance
                await update_position(
                    position_id,
                    token_amount=str(remaining_raw),
                )

            fee_amount = fee_result.get("fee", "0")
            fee_display = format_usdc(fee_amount) if Decimal(fee_amount) > 0 else ""
            fee_line = f"\n💸 Fee: {fee_display}" if fee_display else ""

            # Calculate profit/loss
            entry_cost = Decimal(str(position.entry_price)) * sell_amount
            sale_revenue = quote.expected_output if quote.expected_output else Decimal("0")
            profit = sale_revenue - entry_cost
            profit_percent = ((sale_revenue / entry_cost) - 1) * 100 if entry_cost > 0 else Decimal("0")
            is_profitable = profit > 0

            if is_profitable:
                profit_line = f"\n🎉 Profit: +${profit:.2f} (+{profit_percent:.1f}%)"
            else:
                profit_line = f"\n📉 Loss: -${abs(profit):.2f} ({profit_percent:.1f}%)"

            text = f"""
✅ <b>Sold Successfully!</b>

Sold {percent}% of {outcome_str} position
Tokens Sold: ~{sell_amount:.4f}
Received: ~{quote.expected_output:.2f} {collateral_sym}{fee_line}{profit_line}

<a href="{result.explorer_url}">View Transaction</a>
"""
            # Store data for win card generation (position_id:exit_price_x1000)
            if is_profitable and quote.price_per_token:
                exit_price_int = int(float(quote.price_per_token) * 1000)
                win_callback_data = f"{position_id}:{exit_price_int}"
            else:
                win_callback_data = None
        else:
            # Update order as failed
            await update_order(
                order.id,
                status=OrderStatus.FAILED,
                error_message=result.error_message,
            )

            text = f"""
❌ <b>Sell Failed</b>

{friendly_error(result.error_message or 'Unknown error')}

Please try again later.
"""
            win_callback_data = None

        # Build keyboard with optional Share Win button
        buttons = []
        if win_callback_data:
            buttons.append([InlineKeyboardButton("📤 Share Win", callback_data=f"sellwin:{win_callback_data}")])
        buttons.append([InlineKeyboardButton("📊 View Positions", callback_data="positions:0")])
        buttons.append([InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")])
        keyboard = InlineKeyboardMarkup(buttons)

        await executing_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error("Sell with PIN failed", error=str(e))
        # Add retry button to go back to sell options
        retry_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Retry", callback_data=f"sell_start:{position_id}")],
            [InlineKeyboardButton("« Back to Positions", callback_data="positions")],
        ])
        await executing_msg.edit_text(
            f"❌ Sell failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
            reply_markup=retry_keyboard,
        )


async def handle_wallet_pin_setup(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Handle PIN setup for new wallet."""
    if not update.effective_user or not update.message:
        return

    pending = context.user_data.get("pending_wallet_pin")
    if not pending:
        return

    # Validate PIN format
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        await update.message.reply_text(
            "❌ PIN must be 4-6 digits. Please try again.\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Check if confirming PIN
    if pending.get("confirm"):
        original_pin = pending["pin"]
        if pin != original_pin:
            del context.user_data["pending_wallet_pin"]
            await update.message.reply_text(
                "❌ PINs don't match. Please start over with /wallet",
                parse_mode=ParseMode.HTML,
            )
            return

        # PINs match - create wallets with PIN
        user = await get_user_by_telegram_id(update.effective_user.id)
        if not user:
            del context.user_data["pending_wallet_pin"]
            await update.message.reply_text("Please /start first!")
            return

        del context.user_data["pending_wallet_pin"]

        # Delete PIN message for security
        try:
            await update.message.delete()
        except:
            pass

        # Send status message (use chat.send_message since original message may be deleted)
        status_msg = await update.effective_chat.send_message(
            "🔐 Creating secure wallets...",
            parse_mode=ParseMode.HTML,
        )

        try:
            wallets = await wallet_service.get_or_create_wallets(
                user_id=user.id,
                telegram_id=update.effective_user.id,
                user_pin=pin,
            )

            solana_wallet = wallets.get(ChainFamily.SOLANA)
            evm_wallet = wallets.get(ChainFamily.EVM)

            text = """
✅ <b>Wallets Created!</b>

Your wallets are protected with your PIN.
<b>Only you can access your funds.</b>

<b>🟣 Solana</b> (Kalshi)
<code>{}</code>

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless + Myriad)
<code>{}</code>

⚠️ <b>Important:</b>
• Your PIN is never stored
• If you forget your PIN, your funds are lost
• Keep your PIN safe!
""".format(
                solana_wallet.public_key if solana_wallet else "Error",
                evm_wallet.public_key if evm_wallet else "Error",
            )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Browse Markets", callback_data="markets:refresh")],
                [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
            ])

            # Edit the status message with results
            await status_msg.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

        except Exception as e:
            logger.error("Wallet creation failed", error=str(e))
            await status_msg.edit_text(
                f"❌ Failed to create wallets: {friendly_error(str(e))}",
                parse_mode=ParseMode.HTML,
            )
    else:
        # First PIN entry - ask for confirmation
        context.user_data["pending_wallet_pin"] = {
            "pin": pin,
            "confirm": True,
        }

        # Delete PIN message for security
        try:
            await update.message.delete()
        except:
            pass

        # Send confirmation prompt (use chat.send_message since original may be deleted)
        await update.effective_chat.send_message(
            "🔐 <b>Confirm your PIN</b>\n\n"
            "Please enter your PIN again to confirm:",
            parse_mode=ParseMode.HTML,
        )


async def handle_export_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Export private key after verifying user's PIN."""
    if not update.effective_user or not update.message:
        return

    pending = context.user_data.get("pending_export")
    if not pending:
        return

    # Validate PIN format
    if not pin.isdigit() or len(pin) < 4:
        await update.message.reply_text(
            "❌ Invalid PIN format. Please enter your 4-6 digit PIN.\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.HTML,
        )
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        del context.user_data["pending_export"]
        return

    chain_type = pending["chain_family"]

    # Determine chain family
    if chain_type == "solana":
        chain_family = ChainFamily.SOLANA
        chain_name = "Solana"
    else:
        chain_family = ChainFamily.EVM
        chain_name = "EVM"

    # Clear pending state
    del context.user_data["pending_export"]

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Send processing message
    status_msg = await update.effective_chat.send_message(
        "🔐 Verifying PIN...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Verify PIN against stored hash
        stored_hash = await wallet_service.get_export_pin_hash(user.id, chain_family)
        if not stored_hash:
            await status_msg.edit_text(
                "❌ No export PIN set for this wallet.",
                parse_mode=ParseMode.HTML,
            )
            return

        if not wallet_service.verify_export_pin(pin, update.effective_user.id, stored_hash):
            await status_msg.edit_text(
                "❌ <b>Invalid PIN</b>\n\nThe PIN you entered is incorrect.",
                parse_mode=ParseMode.HTML,
            )
            return

        # PIN verified - export key (key not PIN-encrypted, so pass empty string)
        await status_msg.edit_text("🔐 Exporting private key...", parse_mode=ParseMode.HTML)
        private_key = await wallet_service.export_private_key(user.id, update.effective_user.id, chain_family, "")

        if private_key:
            text = f"""
🔑 <b>{chain_name} Private Key</b>

<code>{private_key}</code>

⚠️ <b>WARNING:</b>
• Anyone with this key can access your funds
• Never share this with anyone
• Store it securely offline
• Delete this message after copying!

<i>Click Delete below to remove this message.</i>
"""
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Delete This Message", callback_data="wallet:refresh")],
            ])

            await status_msg.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await status_msg.edit_text("❌ Wallet not found.")

    except Exception as e:
        logger.error("Export with PIN failed", error=str(e))
        await status_msg.edit_text(
            f"❌ Export failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_withdrawal_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Process withdrawal with user's PIN - sends USDC to user's wallet."""
    if not update.effective_user or not update.message:
        return

    pending = context.user_data.get("pending_withdrawal")
    if not pending:
        return

    # Validate PIN format
    if not pin.isdigit() or len(pin) < 4:
        await update.message.reply_text(
            "❌ Invalid PIN format. Please enter your 4-6 digit PIN.\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.HTML,
        )
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        del context.user_data["pending_withdrawal"]
        return

    amount = pending["amount"]
    chain_family_str = pending.get("chain_family", "evm")
    chain_family = ChainFamily.SOLANA if chain_family_str == "solana" else ChainFamily.EVM

    # Clear pending state
    del context.user_data["pending_withdrawal"]

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Chain-specific display info
    if chain_family == ChainFamily.SOLANA:
        chain_display = "🟣 Solana"
        explorer_name = "Solscan"
        explorer_base = "https://solscan.io/tx/"
    else:
        chain_display = "🔷 EVM"
        explorer_name = "PolygonScan"
        explorer_base = "https://polygonscan.com/tx/"

    # Send processing message
    status_msg = await update.effective_chat.send_message(
        f"⏳ Processing {chain_display} withdrawal...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Verify PIN by trying to get private key for the respective chain
        try:
            private_key = await wallet_service.get_private_key(user.id, update.effective_user.id, chain_family, pin)
        except Exception as decrypt_error:
            if "Decryption failed" in str(decrypt_error):
                await status_msg.edit_text(
                    "❌ <b>Invalid PIN</b>\n\nThe PIN you entered is incorrect.",
                    parse_mode=ParseMode.HTML,
                )
                return
            raise

        # Get user's wallet address for the correct chain
        from src.db.database import get_wallet
        user_wallet = await get_wallet(user.id, chain_family)
        if not user_wallet:
            await status_msg.edit_text(
                f"❌ <b>No Wallet Found</b>\n\nYou need a {chain_family.value.upper()} wallet to receive withdrawals.",
                parse_mode=ParseMode.HTML,
            )
            return

        user_address = user_wallet.public_key

        # Check if withdrawal service is available for this chain
        from src.services.withdrawal import withdrawal_manager
        if not withdrawal_manager.is_available(chain_family.value):
            await status_msg.edit_text(
                f"❌ <b>Withdrawals Unavailable</b>\n\n{chain_family.value.upper()} withdrawal service is not configured. Please contact support.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Update status
        await status_msg.edit_text(
            f"⏳ Sending USDC to your {chain_family.value.upper()} wallet...",
            parse_mode=ParseMode.HTML,
        )

        # Send USDC to user's wallet
        success, tx_hash, error = await withdrawal_manager.send_usdc(
            chain_family=chain_family.value,
            to_address=user_address,
            amount_usdc=amount,
        )

        if success and tx_hash:
            # Process the withdrawal in database
            await process_withdrawal(
                user_id=user.id,
                amount_usdc=amount,
                withdrawal_address=user_address,
                tx_hash=tx_hash,
                chain_family=chain_family,
            )

            claimable_formatted = format_usdc(amount)
            explorer_url = withdrawal_manager.get_explorer_url(chain_family.value, tx_hash)
            text = f"""
✅ <b>{chain_display} Withdrawal Complete!</b>

Amount: <b>{claimable_formatted}</b> USDC
To: <code>{user_address}</code>

<b>Transaction:</b>
<a href="{explorer_url}">View on {explorer_name}</a>

<i>USDC has been sent to your wallet!</i>
"""
        else:
            text = f"❌ <b>Withdrawal Failed</b>\n\n{friendly_error(error or 'Unknown error')}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back to Referrals", callback_data="referral:refresh")],
        ])

        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error("Withdrawal failed", error=str(e), chain=chain_family.value)
        await status_msg.edit_text(
            f"❌ Withdrawal failed: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_reset_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Handle wallet reset with PIN for export protection."""
    if not update.effective_user or not update.message:
        return

    # Validate PIN format
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        await update.message.reply_text(
            "❌ PIN must be 4-6 digits. Please try again.\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.HTML,
        )
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        del context.user_data["pending_wallet_reset"]
        await update.message.reply_text("Please /start first!")
        return

    # Clear pending state
    del context.user_data["pending_wallet_reset"]

    # Delete PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Send status message
    status_msg = await update.effective_chat.send_message(
        "🔐 Creating new wallets with export PIN protection...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Delete existing wallets
        from src.db.database import delete_user_wallets
        await delete_user_wallets(user.id)

        # Create new wallets with export PIN
        wallets = await wallet_service.get_or_create_wallets(
            user_id=user.id,
            telegram_id=update.effective_user.id,
            user_pin=pin,  # This will hash the PIN for export verification
        )

        solana_wallet = wallets.get(ChainFamily.SOLANA)
        evm_wallet = wallets.get(ChainFamily.EVM)

        text = """
✅ <b>New Wallets Created!</b>

<b>🟣 Solana</b> (Kalshi)
<code>{}</code>

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless + Myriad)
<code>{}</code>

🔐 <b>Export PIN set!</b>
Your PIN is required only when exporting private keys.
Trading works without PIN.

<i>Tap address to copy. Send funds to deposit.</i>
""".format(
            solana_wallet.public_key if solana_wallet else "Error",
            evm_wallet.public_key if evm_wallet else "Error",
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Browse Markets", callback_data="markets:refresh")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        ])

        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Wallet reset with PIN failed", error=str(e))
        await status_msg.edit_text(
            f"❌ Failed to reset wallets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_wallet_setup(query: CallbackQuery, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle wallet setup button - prompt for PIN for new users."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Set pending state
    context.user_data["pending_new_wallet"] = True

    await query.edit_message_text(
        "🔐 <b>Set Up Your Wallet PIN</b>\n\n"
        "Please enter a 4-6 digit PIN to protect your private keys.\n\n"
        "This PIN will be required <b>only when exporting</b> your private keys.\n"
        "Trading (buy/sell/bridge) works without PIN.\n\n"
        "Type /cancel to cancel.",
        parse_mode=ParseMode.HTML,
    )


async def handle_new_wallet_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Handle new wallet creation with PIN for new users."""
    if not update.effective_user or not update.message:
        return

    # Validate PIN format
    if not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        await update.message.reply_text(
            "❌ PIN must be 4-6 digits. Please try again.\n\n"
            "Type /cancel to cancel.",
            parse_mode=ParseMode.HTML,
        )
        return

    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        del context.user_data["pending_new_wallet"]
        await update.message.reply_text("Please /start first!")
        return

    # Clear pending state
    del context.user_data["pending_new_wallet"]

    # Delete PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Send status message
    status_msg = await update.effective_chat.send_message(
        "🔐 Creating your wallets with export PIN protection...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Create new wallets with export PIN
        wallets = await wallet_service.get_or_create_wallets(
            user_id=user.id,
            telegram_id=update.effective_user.id,
            user_pin=pin,  # This will hash the PIN for export verification
        )

        solana_wallet = wallets.get(ChainFamily.SOLANA)
        evm_wallet = wallets.get(ChainFamily.EVM)

        text = """
✅ <b>Wallets Created!</b>

<b>🟣 Solana</b> (Kalshi)
<code>{}</code>

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless + Myriad)
<code>{}</code>

🔐 <b>Export PIN set!</b>
Your PIN is required only when exporting private keys.
Trading works without PIN.

<i>Tap address to copy. Send funds to deposit.</i>
""".format(
            solana_wallet.public_key if solana_wallet else "Error",
            evm_wallet.public_key if evm_wallet else "Error",
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Browse Markets", callback_data="markets:refresh")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        ])

        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("New wallet with PIN failed", error=str(e))
        await status_msg.edit_text(
            f"❌ Failed to create wallets: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


# ===================
# Admin Partner Commands
# ===================

def is_admin(telegram_id: int) -> bool:
    """Check if user is an admin."""
    return telegram_id in settings.admin_ids


async def verify_position_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to verify on-chain token balance for a position.
    Usage:
        /verify_position <position_id> - Check if tokens exist on-chain
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "📊 <b>Verify Position</b>\n\n"
            "Checks if tokens actually exist on-chain for a position.\n\n"
            "Usage:\n"
            "<code>/verify_position &lt;position_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    position_id = args[0]
    position = await get_position_by_id(position_id)

    if not position:
        await update.message.reply_text(f"❌ Position {position_id} not found.")
        return

    # Only works for Limitless positions (they have CTF tokens)
    if position.platform != Platform.LIMITLESS:
        await update.message.reply_text(
            f"❌ Verify only works for Limitless positions.\n"
            f"This position is on {position.platform.value}."
        )
        return

    await update.message.reply_text("⏳ Checking on-chain token balance...")

    try:
        # Get the user's wallet address
        user = await get_user_by_telegram_id(telegram_id)
        if not user:
            # Try to get wallet from position owner
            from src.db.database import get_user_by_id
            user = await get_user_by_id(position.user_id)

        if not user:
            await update.message.reply_text("❌ Could not find user for this position.")
            return

        # Get wallet from database
        from src.db.database import get_wallet
        wallet = await get_wallet(user.id, ChainFamily.EVM)
        if not wallet:
            await update.message.reply_text("❌ No EVM wallet found for this user.")
            return

        wallet_address = wallet.public_key

        # Get platform and check balance
        platform = platform_registry.get(Platform.LIMITLESS)

        # Use the market ID (could be numeric or slug)
        market_id = position.market_id

        # Check balance for the outcome
        outcome = Outcome.YES if position.outcome.lower() == "yes" else Outcome.NO
        balance = await platform.get_token_balance(wallet_address, market_id, outcome)

        if balance is None:
            await update.message.reply_text(
                f"❌ <b>Could not check balance</b>\n\n"
                f"Position ID: <code>{position_id}</code>\n"
                f"Market: {escape_html(position.market_title or position.market_id)[:40]}\n"
                f"Wallet: <code>{wallet_address}</code>\n\n"
                f"Error: Failed to query on-chain balance",
                parse_mode=ParseMode.HTML,
            )
            return

        # Compare with recorded position
        recorded_amount = position.token_amount
        is_match = abs(balance - recorded_amount) < Decimal("0.001")
        is_phantom = balance == 0 and recorded_amount > 0

        if is_phantom:
            status = "🚨 PHANTOM POSITION"
            recommendation = "This position has no tokens on-chain. Consider deleting it with /delete_position"
        elif is_match:
            status = "✅ VERIFIED"
            recommendation = "On-chain balance matches recorded amount."
        else:
            status = "⚠️ MISMATCH"
            recommendation = f"On-chain has {balance:.6f}, database has {recorded_amount:.6f}"

        await update.message.reply_text(
            f"📊 <b>Position Verification</b>\n\n"
            f"Status: {status}\n\n"
            f"Position ID: <code>{position_id}</code>\n"
            f"Market: {escape_html(position.market_title or position.market_id)[:40]}\n"
            f"Outcome: {position.outcome.upper()}\n"
            f"Wallet: <code>{wallet_address}</code>\n\n"
            f"📈 <b>Amounts:</b>\n"
            f"• Database: {recorded_amount:.6f} tokens\n"
            f"• On-chain: {balance:.6f} tokens\n\n"
            f"💡 {recommendation}",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to verify position", error=str(e), position_id=position_id)
        await update.message.reply_text(f"❌ Error verifying position: {str(e)}")


async def delete_position_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to delete positions.
    Usage:
        /delete_position <position_id> - Delete a specific position
        /delete_position list <telegram_id> - List positions for a user
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "📊 <b>Delete Position</b>\n\n"
            "Usage:\n"
            "<code>/delete_position &lt;position_id&gt;</code> - Delete by ID\n"
            "<code>/delete_position list &lt;telegram_id&gt;</code> - List user's positions",
            parse_mode=ParseMode.HTML,
        )
        return

    action = args[0].lower()

    if action == "list" and len(args) >= 2:
        # List positions for a user
        try:
            target_telegram_id = int(args[1])
            target_user = await get_user_by_telegram_id(target_telegram_id)
            if not target_user:
                await update.message.reply_text(f"❌ User with Telegram ID {target_telegram_id} not found.")
                return

            positions = await get_user_positions(target_user.id)
            if not positions:
                await update.message.reply_text(f"No positions found for user {target_telegram_id}.")
                return

            text = f"📊 <b>Positions for {target_telegram_id}</b>\n\n"
            for pos in positions:
                text += f"ID: <code>{pos.id}</code>\n"
                text += f"   {pos.platform.value} - {pos.outcome.upper()}\n"
                text += f"   Market: {escape_html(pos.market_title or pos.market_id)[:40]}...\n"
                text += f"   Amount: {pos.token_amount} @ {pos.entry_price}\n\n"

            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        except ValueError:
            await update.message.reply_text("❌ Invalid Telegram ID. Must be a number.")
        return

    # Delete by position ID
    position_id = args[0]

    # First get the position to show what we're deleting
    position = await get_position_by_id(position_id)
    if not position:
        await update.message.reply_text(f"❌ Position {position_id} not found.")
        return

    # Import and call delete function
    from src.db.database import delete_position_by_id
    deleted = await delete_position_by_id(position_id)

    if deleted:
        await update.message.reply_text(
            f"✅ <b>Position Deleted</b>\n\n"
            f"ID: <code>{position_id}</code>\n"
            f"Platform: {position.platform.value}\n"
            f"Market: {escape_html(position.market_title or position.market_id)[:50]}\n"
            f"Outcome: {position.outcome.upper()}\n"
            f"Amount: {position.token_amount}",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(f"❌ Failed to delete position {position_id}.")


async def partner_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to manage partners.
    Usage:
        /partner - List all partners
        /partner create <name> <share%> - Create new partner
        /partner stats <code> - View partner statistics
        /partner link <code> - Get group invite link for partner
        /partner deactivate <code> - Deactivate partner
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    args = context.args or []

    # No args - list partners
    if not args:
        partners = await get_all_partners(active_only=False)
        if not partners:
            await update.message.reply_text(
                "📊 <b>No partners yet</b>\n\n"
                "Create one with:\n<code>/partner create Name 10</code>\n"
                "(Name, 10% revenue share)",
                parse_mode=ParseMode.HTML,
            )
            return

        text = "📊 <b>Partner List</b>\n\n"
        for p in partners:
            status = "✅" if p.is_active else "❌"
            share = p.revenue_share_bps / 100
            text += f"{status} <b>{escape_html(p.name)}</b>\n"
            text += f"   Code: <code>{p.code}</code>\n"
            text += f"   Share: {share:.1f}% | Users: {p.total_users}\n"
            text += f"   Volume: ${float(Decimal(p.total_volume_usdc)):.2f}\n\n"

        text += "<i>Use /partner stats CODE for details</i>"
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    action = args[0].lower()

    if action == "create":
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: <code>/partner create Name SharePercent</code>\n"
                "Example: <code>/partner create AlphaGroup 15</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        name = args[1]
        try:
            share_percent = float(args[2])
            share_bps = int(share_percent * 100)
        except ValueError:
            await update.message.reply_text("❌ Invalid share percentage.")
            return

        if share_bps < 0 or share_bps > 5000:  # Max 50%
            await update.message.reply_text("❌ Share must be between 0-50%.")
            return

        # Generate unique code
        import secrets
        code = secrets.token_hex(4)  # 8 character hex code

        # Check if code exists (unlikely but possible)
        existing = await get_partner_by_code(code)
        if existing:
            code = secrets.token_hex(4)

        try:
            partner = await create_partner(
                name=name,
                code=code,
                revenue_share_bps=share_bps,
            )

            # Get bot username for link
            bot = await context.bot.get_me()
            bot_username = bot.username
            group_link = f"https://t.me/{bot_username}?startgroup=partner_{code}"

            text = f"""
✅ <b>Partner Created!</b>

<b>Name:</b> {escape_html(name)}
<b>Code:</b> <code>{code}</code>
<b>Revenue Share:</b> {share_percent:.1f}%

<b>Group Invite Link:</b>
<code>{group_link}</code>

<i>Share this link with the partner.
When they add the bot to their group using this link,
users from that group will be attributed to them.</i>
"""
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.error("Partner creation failed", error=str(e))
            await update.message.reply_text(f"❌ Failed to create partner: {friendly_error(str(e))}")

    elif action == "stats":
        if len(args) < 2:
            await update.message.reply_text("Usage: <code>/partner stats CODE</code>", parse_mode=ParseMode.HTML)
            return

        code = args[1].lower()
        partner = await get_partner_by_code(code)
        if not partner:
            await update.message.reply_text(f"❌ Partner not found: {code}")
            return

        stats = await get_partner_stats(partner.id)
        if not stats:
            await update.message.reply_text("❌ Failed to get partner stats.")
            return

        groups_text = ""
        default_share_bps = partner.revenue_share_bps
        for g in stats["groups"][:5]:
            status = "✅" if g.is_active and not g.bot_removed else "❌"
            # Show group-specific share if different from default
            share_info = ""
            if g.revenue_share_bps is not None and g.revenue_share_bps != default_share_bps:
                share_info = f" [{g.revenue_share_bps / 100:.0f}%]"
            groups_text += f"   {status} {escape_html(g.chat_title or 'Unknown')} ({g.users_attributed} users){share_info}\n"
            groups_text += f"      ID: <code>{g.telegram_chat_id}</code>\n"

        if not groups_text:
            groups_text = "   <i>No groups yet</i>\n"

        share_pct = stats["revenue_share_bps"] / 100
        total_fees = float(Decimal(partner.total_fees_usdc))
        owed = total_fees * (share_pct / 100)
        paid = float(Decimal(partner.total_paid_usdc))

        text = f"""
📊 <b>Partner: {escape_html(partner.name)}</b>

<b>Code:</b> <code>{partner.code}</code>
<b>Status:</b> {"✅ Active" if partner.is_active else "❌ Inactive"}
<b>Revenue Share:</b> {share_pct:.1f}%

<b>Stats:</b>
   Users: {stats["total_users"]}
   Volume: ${float(stats["total_volume_usdc"]):.2f}
   Fees Generated: ${total_fees:.2f}
   Owed: ${owed:.2f}
   Paid: ${paid:.2f}

<b>Groups ({stats["total_groups"]}):</b>
{groups_text}
<b>Created:</b> {partner.created_at.strftime("%Y-%m-%d")}
"""
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    elif action == "link":
        if len(args) < 2:
            await update.message.reply_text("Usage: <code>/partner link CODE</code>", parse_mode=ParseMode.HTML)
            return

        code = args[1].lower()
        partner = await get_partner_by_code(code)
        if not partner:
            await update.message.reply_text(f"❌ Partner not found: {code}")
            return

        bot = await context.bot.get_me()
        bot_username = bot.username
        group_link = f"https://t.me/{bot_username}?startgroup=partner_{code}"

        text = f"""
🔗 <b>Partner Link: {escape_html(partner.name)}</b>

<b>Group Invite Link:</b>
<code>{group_link}</code>

<i>When partners add the bot to their group using this link,
new users from that group will be attributed to them.</i>
"""
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    elif action == "deactivate":
        if len(args) < 2:
            await update.message.reply_text("Usage: <code>/partner deactivate CODE</code>", parse_mode=ParseMode.HTML)
            return

        code = args[1].lower()
        partner = await get_partner_by_code(code)
        if not partner:
            await update.message.reply_text(f"❌ Partner not found: {code}")
            return

        updated = await update_partner(partner.id, is_active=False)
        if updated:
            await update.message.reply_text(f"✅ Partner <b>{escape_html(partner.name)}</b> deactivated.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Failed to deactivate partner.")

    elif action == "activate":
        if len(args) < 2:
            await update.message.reply_text("Usage: <code>/partner activate CODE</code>", parse_mode=ParseMode.HTML)
            return

        code = args[1].lower()
        partner = await get_partner_by_code(code)
        if not partner:
            await update.message.reply_text(f"❌ Partner not found: {code}")
            return

        updated = await update_partner(partner.id, is_active=True)
        if updated:
            await update.message.reply_text(f"✅ Partner <b>{escape_html(partner.name)}</b> activated.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Failed to activate partner.")

    elif action == "setshare":
        # Set group-specific revenue share: /partner setshare <group_id> <share%>
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: <code>/partner setshare GROUP_ID Share%</code>\n"
                "Example: <code>/partner setshare -1001234567890 20</code>\n\n"
                "<i>Use /partner stats CODE to see group IDs</i>",
                parse_mode=ParseMode.HTML,
            )
            return

        try:
            group_chat_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid group ID. Must be a number.")
            return

        try:
            share_percent = float(args[2])
            share_bps = int(share_percent * 100)
        except ValueError:
            await update.message.reply_text("❌ Invalid share percentage.")
            return

        if share_bps < 0 or share_bps > 5000:  # Max 50%
            await update.message.reply_text("❌ Share must be between 0-50%.")
            return

        # Get the group
        group = await get_partner_group_by_chat_id(group_chat_id)
        if not group:
            await update.message.reply_text(f"❌ Partner group not found: {group_chat_id}")
            return

        # Update the group's revenue share
        updated = await update_partner_group(group_chat_id, revenue_share_bps=share_bps)
        if updated:
            partner = await get_partner_by_id(group.partner_id)
            partner_name = partner.name if partner else "Unknown"
            await update.message.reply_text(
                f"✅ <b>Group share updated!</b>\n\n"
                f"Group: {escape_html(group.chat_title or str(group_chat_id))}\n"
                f"Partner: {escape_html(partner_name)}\n"
                f"New Share: <b>{share_percent:.1f}%</b>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text("❌ Failed to update group share.")

    elif action == "clearshare":
        # Clear group-specific share (revert to partner default): /partner clearshare <group_id>
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: <code>/partner clearshare GROUP_ID</code>\n"
                "<i>Reverts group to use partner's default share</i>",
                parse_mode=ParseMode.HTML,
            )
            return

        try:
            group_chat_id = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid group ID. Must be a number.")
            return

        group = await get_partner_group_by_chat_id(group_chat_id)
        if not group:
            await update.message.reply_text(f"❌ Partner group not found: {group_chat_id}")
            return

        # Set revenue_share_bps to None to use partner default
        from src.db.database import clear_partner_group_share
        await clear_partner_group_share(group_chat_id)

        partner = await get_partner_by_id(group.partner_id)
        default_share = partner.revenue_share_bps / 100 if partner else 10
        await update.message.reply_text(
            f"✅ Group share cleared!\n\n"
            f"Group: {escape_html(group.chat_title or str(group_chat_id))}\n"
            f"Now using partner default: <b>{default_share:.1f}%</b>",
            parse_mode=ParseMode.HTML,
        )

    else:
        await update.message.reply_text(
            "Unknown action. Available:\n"
            "• <code>/partner</code> - List partners\n"
            "• <code>/partner create Name Share%</code>\n"
            "• <code>/partner stats CODE</code>\n"
            "• <code>/partner link CODE</code>\n"
            "• <code>/partner deactivate CODE</code>\n"
            "• <code>/partner activate CODE</code>\n"
            "• <code>/partner setshare GROUP_ID Share%</code>\n"
            "• <code>/partner clearshare GROUP_ID</code>",
            parse_mode=ParseMode.HTML,
        )


async def handle_group_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle bot being added to a group.
    Called via my_chat_member handler when bot status changes.
    """
    if not update.my_chat_member:
        return

    chat = update.my_chat_member.chat
    new_status = update.my_chat_member.new_chat_member.status

    # Bot was added to group (as member or admin)
    if new_status in ("member", "administrator"):
        # Check if this was via partner link
        # The startgroup parameter is passed in context when adding via link
        partner_code = None

        # Extract partner code from deep link if present
        if context.args and len(context.args) > 0:
            param = context.args[0]
            if param.startswith("partner_"):
                partner_code = param.replace("partner_", "")

        if partner_code:
            partner = await get_partner_by_code(partner_code)
            if partner and partner.is_active:
                # Check if group already exists
                existing = await get_partner_group_by_chat_id(chat.id)
                if not existing:
                    # Create partner group mapping
                    await create_partner_group(
                        partner_id=partner.id,
                        telegram_chat_id=chat.id,
                        chat_title=chat.title,
                        chat_type=chat.type,
                    )
                    logger.info(
                        "Partner group created",
                        partner_code=partner_code,
                        chat_id=chat.id,
                        chat_title=chat.title,
                    )
                else:
                    # Update existing group if it was inactive
                    if not existing.is_active or existing.bot_removed:
                        await update_partner_group(
                            chat.id,
                            chat_title=chat.title,
                            is_active=True,
                            bot_removed=False,
                        )
                        logger.info(
                            "Partner group reactivated",
                            partner_code=partner_code,
                            chat_id=chat.id,
                        )

    # Bot was removed from group
    elif new_status in ("left", "kicked"):
        existing = await get_partner_group_by_chat_id(chat.id)
        if existing:
            await update_partner_group(chat.id, bot_removed=True, is_active=False)
            logger.info("Partner group - bot removed", chat_id=chat.id)


async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle messages in groups to attribute users to partners.
    This runs for any message in a partner group.
    """
    if not update.effective_user or not update.effective_chat:
        return

    # Only process group messages
    if update.effective_chat.type not in ("group", "supergroup"):
        return

    chat_id = update.effective_chat.id
    telegram_id = update.effective_user.id

    # Check if this is a partner group
    partner_group = await get_partner_group_by_chat_id(chat_id)
    if not partner_group or not partner_group.is_active:
        return

    # Get or create user
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        # User doesn't exist yet - they'll be attributed when they /start
        return

    # Attribute user to partner if not already attributed
    if user.partner_id is None:
        partner = await get_partner_by_id(partner_group.partner_id)
        if partner and partner.is_active:
            await attribute_user_to_partner(
                user_id=user.id,
                partner_id=partner.id,
                partner_group_id=chat_id,
            )
            logger.info(
                "User attributed to partner",
                user_id=user.id,
                partner_code=partner.code,
                group_id=chat_id,
            )


# ===================
# Message Handler
# ===================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages (for search and trading input)."""
    if not update.effective_user or not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Handle /cancel command
    if text.lower() == "/cancel":
        if "pending_buy" in context.user_data:
            context.user_data.pop("pending_buy", None)
            await update.message.reply_text("Order cancelled.")
        elif "pending_withdrawal" in context.user_data:
            del context.user_data["pending_withdrawal"]
            await update.message.reply_text("Withdrawal cancelled.")
        elif "pending_export" in context.user_data:
            del context.user_data["pending_export"]
            await update.message.reply_text("Export cancelled.")
        elif "pending_bridge" in context.user_data:
            del context.user_data["pending_bridge"]
            await update.message.reply_text("Bridge cancelled.")
        elif "pending_wallet_reset" in context.user_data:
            del context.user_data["pending_wallet_reset"]
            await update.message.reply_text("Wallet reset cancelled.")
        elif "pending_new_wallet" in context.user_data:
            del context.user_data["pending_new_wallet"]
            await update.message.reply_text("Wallet setup cancelled.")
        elif "awaiting_broadcast" in context.user_data:
            del context.user_data["awaiting_broadcast"]
            await update.message.reply_text("Broadcast cancelled.")
        else:
            await update.message.reply_text("Nothing to cancel.")
        return

    # Check if admin is awaiting broadcast text
    if context.user_data.get("awaiting_broadcast") and not text.startswith("/"):
        await handle_broadcast_message(update, context)
        return

    # Check if user has a pending wallet reset (PIN setup)
    if "pending_wallet_reset" in context.user_data and not text.startswith("/"):
        await handle_wallet_reset_with_pin(update, context, text)
        return

    # Check if user has a pending new wallet setup (PIN setup for new users)
    if "pending_new_wallet" in context.user_data and not text.startswith("/"):
        await handle_new_wallet_with_pin(update, context, text)
        return

    # Check if user has a pending export (PIN required for security)
    if "pending_export" in context.user_data and not text.startswith("/"):
        await handle_export_with_pin(update, context, text)
        return

    # Check if user has a pending withdrawal (PIN required for security)
    if "pending_withdrawal" in context.user_data and not text.startswith("/"):
        await handle_withdrawal_with_pin(update, context, text)
        return

    # Check if user has a pending bridge with custom amount input
    if "pending_bridge" in context.user_data and not text.startswith("/"):
        pending = context.user_data["pending_bridge"]
        if pending.get("awaiting_custom_amount"):
            await handle_bridge_custom_amount_input(update, context, text)
            return

    # Check if user has a pending buy order (amount input)
    if "pending_buy" in context.user_data and not text.startswith("/"):
        await handle_buy_amount(update, context, text)
        return

    # Check if it's a search query (doesn't start with /)
    if not text.startswith("/"):
        user = await get_user_by_telegram_id(update.effective_user.id)
        if not user:
            await update.message.reply_text("Please /start first!")
            return

        # Treat as search query
        platform_info = PLATFORM_INFO[user.active_platform]
        platform = get_platform(user.active_platform)
        
        await update.message.reply_text(
            f"🔍 Searching {platform_info['name']} for \"{escape_html(text)}\"...",
            parse_mode=ParseMode.HTML,
        )
        
        try:
            markets = await platform.search_markets(text, limit=5)
            
            if not markets:
                await update.message.reply_text(
                    f"No results for \"{escape_html(text)}\".\nTry different keywords!",
                    parse_mode=ParseMode.HTML,
                )
                return
            
            response = f"🔍 <b>Results for \"{escape_html(text)}\"</b>\n\n"

            buttons = []
            for i, market in enumerate(markets, 1):
                title = escape_html(market.title[:45] + "..." if len(market.title) > 45 else market.title)
                yes_prob = format_probability(market.yes_price)
                exp = format_expiration(market.close_time)

                response += f"<b>{i}.</b> {title}\n   YES: {yes_prob} • Exp: {exp}\n\n"

                buttons.append([
                    InlineKeyboardButton(
                        f"{i}. View Market",
                        callback_data=f"market:{user.active_platform.value}:{market.market_id[:40]}"
                    )
                ])
            
            await update.message.reply_text(
                response,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            
        except Exception as e:
            logger.error("Search failed", error=str(e))
            await update.message.reply_text(
                f"❌ Search failed: {friendly_error(str(e))}",
                parse_mode=ParseMode.HTML,
            )


# ===================
# Admin Analytics Dashboard
# ===================

from datetime import timedelta
from src.db.database import get_analytics_stats, get_analytics_by_platform, get_top_traders, get_top_referrers

PLATFORM_NAMES = {
    "kalshi": "Kalshi",
    "polymarket": "Polymarket",
    "opinion": "Opinion Labs",
    "limitless": "Limitless",
}


async def analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to view analytics dashboard.
    Usage: /analytics
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    # Show the analytics dashboard with time period selection
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Today", callback_data="analytics:daily"),
            InlineKeyboardButton("📆 This Week", callback_data="analytics:weekly"),
        ],
        [
            InlineKeyboardButton("📊 This Month", callback_data="analytics:monthly"),
            InlineKeyboardButton("📈 All Time", callback_data="analytics:all"),
        ],
        [
            InlineKeyboardButton("🔍 By Platform", callback_data="analytics:platforms"),
        ],
        [
            InlineKeyboardButton("🏆 Top Traders", callback_data="analytics:traders"),
            InlineKeyboardButton("👥 Top Referrers", callback_data="analytics:referrers"),
        ],
    ])

    await update.message.reply_text(
        "📊 <b>Admin Analytics Dashboard</b>\n\n"
        "Select a time period to view stats:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_analytics_callback(query, period: str, telegram_id: int) -> None:
    """Handle analytics time period selection."""
    from datetime import datetime, timezone

    if not is_admin(telegram_id):
        await query.answer("❌ Admin only", show_alert=True)
        return

    await query.answer()

    now = datetime.now(timezone.utc)
    since = None
    period_name = "All Time"

    if period == "daily":
        since = now - timedelta(days=1)
        period_name = "Last 24 Hours"
    elif period == "weekly":
        since = now - timedelta(weeks=1)
        period_name = "Last 7 Days"
    elif period == "monthly":
        since = now - timedelta(days=30)
        period_name = "Last 30 Days"
    elif period == "all":
        since = None
        period_name = "All Time"

    try:
        stats = await get_analytics_stats(since=since)

        # Get alerts stats
        from src.services.alerts import alerts_service
        arb_subscribers = len(alerts_service._arbitrage_subscribers)
        price_alerts = len([a for a in alerts_service._alerts.values() if not a.triggered])

        text = f"""📊 <b>Analytics - {period_name}</b>

👥 <b>Users</b>
├ Total Users: <code>{stats['total_users']:,}</code>
└ New Users: <code>{stats['new_users']:,}</code>

💰 <b>Trading</b>
├ Volume: <code>${stats['trade_volume']:,.2f}</code>
└ Trades: <code>{stats['trade_count']:,}</code>

💵 <b>Revenue</b>
├ Fees Collected: <code>${stats['fee_revenue']:,.2f}</code>
├ Referral Payouts: <code>${stats['referral_payouts']:,.2f}</code> ({stats['referral_count']} payouts)
└ Net Revenue: <code>${stats['net_revenue']:,.2f}</code>

🔔 <b>Alerts</b>
├ Arbitrage Subscribers: <code>{arb_subscribers}</code>
└ Active Price Alerts: <code>{price_alerts}</code>
"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📅 Today", callback_data="analytics:daily"),
                InlineKeyboardButton("📆 Week", callback_data="analytics:weekly"),
            ],
            [
                InlineKeyboardButton("📊 Month", callback_data="analytics:monthly"),
                InlineKeyboardButton("📈 All", callback_data="analytics:all"),
            ],
            [
                InlineKeyboardButton("🔍 By Platform", callback_data="analytics:platforms"),
            ],
            [
                InlineKeyboardButton("🏆 Top Traders", callback_data="analytics:traders"),
                InlineKeyboardButton("👥 Top Referrers", callback_data="analytics:referrers"),
            ],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Analytics query failed", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load analytics: {str(e)[:100]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_analytics_traders(query, telegram_id: int, period: str = "all") -> None:
    """Handle top traders view."""
    from datetime import datetime, timezone

    if not is_admin(telegram_id):
        await query.answer("❌ Admin only", show_alert=True)
        return

    await query.answer()

    now = datetime.now(timezone.utc)
    since = None
    period_name = "All Time"

    if period == "daily":
        since = now - timedelta(days=1)
        period_name = "Last 24 Hours"
    elif period == "weekly":
        since = now - timedelta(weeks=1)
        period_name = "Last 7 Days"
    elif period == "monthly":
        since = now - timedelta(days=30)
        period_name = "Last 30 Days"

    try:
        traders = await get_top_traders(since=since, limit=10)

        text = f"🏆 <b>Top Traders - {period_name}</b>\n\n"

        if not traders:
            text += "<i>No trades in this period</i>"
        else:
            for i, trader in enumerate(traders, 1):
                # Display name: username or first_name or telegram_id
                name = trader["username"] or trader["first_name"] or f"User {trader['telegram_id']}"
                if trader["username"]:
                    name = f"@{name}"

                medal = ""
                if i == 1:
                    medal = "🥇 "
                elif i == 2:
                    medal = "🥈 "
                elif i == 3:
                    medal = "🥉 "

                text += f"""{medal}<b>{i}. {name}</b>
├ Volume: <code>${trader['volume']:,.2f}</code>
├ Trades: <code>{trader['trade_count']:,}</code>
└ Fees: <code>${trader['fees_paid']:,.2f}</code>

"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📅 Today", callback_data="analytics:top:daily"),
                InlineKeyboardButton("📆 Week", callback_data="analytics:top:weekly"),
            ],
            [
                InlineKeyboardButton("📊 Month", callback_data="analytics:top:monthly"),
                InlineKeyboardButton("📈 All", callback_data="analytics:top:all"),
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="analytics:all"),
            ],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Analytics traders query failed", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load top traders: {str(e)[:100]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_analytics_referrers(query, telegram_id: int, period: str = "all") -> None:
    """Handle top referrers view."""
    from datetime import datetime, timezone

    if not is_admin(telegram_id):
        await query.answer("❌ Admin only", show_alert=True)
        return

    await query.answer()

    now = datetime.now(timezone.utc)
    since = None
    period_name = "All Time"

    if period == "daily":
        since = now - timedelta(days=1)
        period_name = "Last 24 Hours"
    elif period == "weekly":
        since = now - timedelta(weeks=1)
        period_name = "Last 7 Days"
    elif period == "monthly":
        since = now - timedelta(days=30)
        period_name = "Last 30 Days"

    try:
        referrers = await get_top_referrers(since=since, limit=10)

        text = f"👥 <b>Top Referrers - {period_name}</b>\n\n"

        if not referrers:
            text += "<i>No referral earnings in this period</i>"
        else:
            for i, ref in enumerate(referrers, 1):
                # Display name: username or first_name or telegram_id
                name = ref["username"] or ref["first_name"] or f"User {ref['telegram_id']}"
                if ref["username"]:
                    name = f"@{name}"

                medal = ""
                if i == 1:
                    medal = "🥇 "
                elif i == 2:
                    medal = "🥈 "
                elif i == 3:
                    medal = "🥉 "

                text += f"""{medal}<b>{i}. {name}</b>
├ Earned: <code>${ref['total_earned']:,.2f}</code>
├ Direct Referrals: <code>{ref['direct_referrals']:,}</code>
├ Tier 1: <code>${ref['tier1_earned']:,.2f}</code>
├ Tier 2: <code>${ref['tier2_earned']:,.2f}</code>
└ Tier 3: <code>${ref['tier3_earned']:,.2f}</code>

"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📅 Today", callback_data="analytics:ref:daily"),
                InlineKeyboardButton("📆 Week", callback_data="analytics:ref:weekly"),
            ],
            [
                InlineKeyboardButton("📊 Month", callback_data="analytics:ref:monthly"),
                InlineKeyboardButton("📈 All", callback_data="analytics:ref:all"),
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="analytics:all"),
            ],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Analytics referrers query failed", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load top referrers: {str(e)[:100]}",
            parse_mode=ParseMode.HTML,
        )


async def handle_analytics_platforms(query, telegram_id: int, period: str = "all") -> None:
    """Handle analytics platform breakdown."""
    from datetime import datetime, timezone

    if not is_admin(telegram_id):
        await query.answer("❌ Admin only", show_alert=True)
        return

    await query.answer()

    now = datetime.now(timezone.utc)
    since = None
    period_name = "All Time"

    if period == "daily":
        since = now - timedelta(days=1)
        period_name = "Last 24 Hours"
    elif period == "weekly":
        since = now - timedelta(weeks=1)
        period_name = "Last 7 Days"
    elif period == "monthly":
        since = now - timedelta(days=30)
        period_name = "Last 30 Days"

    try:
        platform_stats = await get_analytics_by_platform(since=since)

        text = f"📊 <b>Platform Breakdown - {period_name}</b>\n\n"

        total_volume = Decimal("0")
        total_trades = 0
        total_users = 0
        total_fees = Decimal("0")

        for plat_key, stats in platform_stats.items():
            plat_name = PLATFORM_NAMES.get(plat_key, plat_key.title())
            volume = stats["trade_volume"]
            trades = stats["trade_count"]
            users = stats["active_users"]
            fees = stats["fee_revenue"]

            total_volume += volume
            total_trades += trades
            total_users += users
            total_fees += fees

            if trades > 0 or users > 0:
                text += f"""<b>{plat_name}</b>
├ Volume: <code>${volume:,.2f}</code>
├ Trades: <code>{trades:,}</code>
├ Fees: <code>${fees:,.2f}</code>
└ Active Users: <code>{users:,}</code>

"""

        text += f"""<b>📈 Totals</b>
├ Volume: <code>${total_volume:,.2f}</code>
├ Trades: <code>{total_trades:,}</code>
├ Fees: <code>${total_fees:,.2f}</code>
└ Active Users: <code>{total_users:,}</code>
"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📅 Today", callback_data="analytics:plat:daily"),
                InlineKeyboardButton("📆 Week", callback_data="analytics:plat:weekly"),
            ],
            [
                InlineKeyboardButton("📊 Month", callback_data="analytics:plat:monthly"),
                InlineKeyboardButton("📈 All", callback_data="analytics:plat:all"),
            ],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="analytics:all"),
            ],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Analytics platform query failed", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load platform analytics: {str(e)[:100]}",
            parse_mode=ParseMode.HTML,
        )


# ===================
# ACP Analytics (Admin)
# ===================

async def acpstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to view ACP (Agent Commerce Protocol) analytics.
    Usage: /acpstats [days]
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("This command is admin-only.")
        return

    # Parse days argument
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
            days = max(1, min(365, days))  # Clamp to 1-365
        except ValueError:
            pass

    try:
        from src.db.database import get_acp_analytics, get_acp_top_agents

        stats = await get_acp_analytics(days=days)
        top_agents = await get_acp_top_agents(limit=5)

        # Format platform breakdown
        platform_lines = []
        for platform, data in stats["trade_volume"]["by_platform"].items():
            platform_lines.append(
                f"  {platform.capitalize()}: ${data['volume']:,.2f} ({data['count']} trades)"
            )

        platform_text = "\n".join(platform_lines) if platform_lines else "  No trades yet"

        # Format top agents
        agent_lines = []
        for i, agent in enumerate(top_agents, 1):
            agent_lines.append(
                f"  {i}. {agent['agent_id']}: ${agent['volume']:,.2f} ({agent['trades']} trades)"
            )

        agents_text = "\n".join(agent_lines) if agent_lines else "  No agents yet"

        # Format jobs breakdown
        job_lines = []
        for job_type, data in stats.get("jobs_by_type", {}).items():
            job_lines.append(
                f"  {job_type}: {data['total']} ({data['success_rate']}% success)"
            )

        jobs_text = "\n".join(job_lines) if job_lines else "  No jobs yet"

        text = f"""<b>ACP Analytics - Last {days} Days</b>

<b>Trade Volume</b>
{platform_text}
Total: <code>${stats['trade_volume']['total']:,.2f}</code>
Trades: <code>{stats['trade_volume']['count']:,}</code>

<b>Bridge Volume</b>
Total: <code>${stats['bridge_volume']['total']:,.2f}</code>
Transactions: <code>{stats['bridge_volume']['count']:,}</code>

<b>Agents</b>
Unique Agents: <code>{stats['unique_agents']:,}</code>

<b>Jobs by Type</b>
{jobs_text}

<b>Top Agents</b>
{agents_text}

<b>All-Time Stats</b>
Total Volume: <code>${stats['all_time']['trade_volume']:,.2f}</code>
Total Trades: <code>{stats['all_time']['trade_count']:,}</code>
Total Agents: <code>{stats['all_time']['unique_agents']:,}</code>
"""

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to get ACP stats", error=str(e))
        await update.message.reply_text(f"Failed to get ACP stats: {str(e)[:100]}")


async def acpwallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to view ACP wallet balances and liquidity status.
    Usage: /acpwallet
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("This command is admin-only.")
        return

    try:
        from src.services.acp.wallet_manager import acp_wallet_manager

        acp_wallet_manager.initialize()

        if not acp_wallet_manager.acp_wallet_address:
            await update.message.reply_text(
                "<b>ACP Wallet Not Configured</b>\n\n"
                "Set ACP_AGENT_WALLET_PRIVATE_KEY in .env",
                parse_mode=ParseMode.HTML,
            )
            return

        status = acp_wallet_manager.get_supported_chains_status()

        lines = [
            f"<b>ACP Wallet Status</b>\n",
        ]

        # Show EVM wallet
        if acp_wallet_manager.acp_wallet_address:
            lines.append(f"<b>EVM:</b> <code>{acp_wallet_manager.acp_wallet_address}</code>")
        else:
            lines.append("<b>EVM:</b> Not configured")

        # Show Solana wallet
        if acp_wallet_manager.acp_solana_address:
            lines.append(f"<b>Solana:</b> <code>{acp_wallet_manager.acp_solana_address}</code>")
        else:
            lines.append("<b>Solana:</b> Not configured")

        chain_names = {
            "base": ("Base (Limitless)", "ETH"),
            "polygon": ("Polygon (Polymarket)", "MATIC"),
            "bsc": ("BSC (Opinion)", "BNB"),
            "solana": ("Solana (Kalshi)", "SOL"),
        }

        for chain, data in status.items():
            name, gas_token = chain_names.get(chain, (chain, "ETH"))

            if not data.get("configured", False):
                lines.append(f"\n<b>⚪ {name}</b>")
                lines.append(f"  Not configured")
                continue

            ready_icon = "✅" if data["ready"] else "❌"

            if chain == "bsc":
                lines.append(f"\n<b>{ready_icon} {name}</b>")
                lines.append(f"  USDT: <code>${data['usdt']:,.2f}</code>")
            else:
                lines.append(f"\n<b>{ready_icon} {name}</b>")
                lines.append(f"  USDC: <code>${data['usdc']:,.2f}</code>")

            lines.append(f"  {gas_token}: <code>{data['gas']:.6f}</code>")

        lines.append("\n\n<b>Recommended Minimums:</b>")
        lines.append("  Base: 0.001 ETH + $100 USDC")
        lines.append("  Polygon: 1 MATIC + $100 USDC")
        lines.append("  BSC: 0.01 BNB + $100 USDT")
        lines.append("  Solana: 0.1 SOL + $100 USDC")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to get ACP wallet status", error=str(e))
        await update.message.reply_text(f"Error: {str(e)[:100]}")


# ===================
# Fee Configuration Commands (Admin)
# ===================

async def getfees_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to view current referral fee percentages.
    Usage: /getfees
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    from src.services.fee import get_tier_commissions, DEFAULT_TIER_COMMISSIONS

    try:
        current = await get_tier_commissions()

        text = """⚙️ <b>Referral Fee Configuration</b>

<b>Current Rates (% of 2% fee):</b>
├ Tier 1 (Direct): <code>{:.1f}%</code>{}
├ Tier 2: <code>{:.1f}%</code>{}
└ Tier 3: <code>{:.1f}%</code>{}

<b>Default Rates:</b>
├ Tier 1: 25%
├ Tier 2: 5%
└ Tier 3: 3%

<b>Commands:</b>
• <code>/setfee 1 50</code> - Set Tier 1 to 50%
• <code>/setfee 2 10</code> - Set Tier 2 to 10%
• <code>/resetfees</code> - Reset to defaults (25/5/3)""".format(
            float(current[1] * 100),
            " ✏️" if current[1] != DEFAULT_TIER_COMMISSIONS[1] else "",
            float(current[2] * 100),
            " ✏️" if current[2] != DEFAULT_TIER_COMMISSIONS[2] else "",
            float(current[3] * 100),
            " ✏️" if current[3] != DEFAULT_TIER_COMMISSIONS[3] else "",
        )

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error("Failed to get fee config", error=str(e))
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def setfee_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to set referral fee percentage for a tier.
    Usage: /setfee <tier> <percent>
    Example: /setfee 1 50  (sets Tier 1 to 50%)
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    from src.services.fee import set_tier_commission
    from decimal import Decimal

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/setfee &lt;tier&gt; &lt;percent&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/setfee 1 50</code> - Tier 1 = 50%\n"
            "• <code>/setfee 2 10</code> - Tier 2 = 10%\n"
            "• <code>/setfee 3 5</code> - Tier 3 = 5%",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        tier = int(args[0])
        percent = Decimal(args[1])

        if tier not in [1, 2, 3]:
            await update.message.reply_text("❌ Tier must be 1, 2, or 3")
            return

        if percent < 0 or percent > 100:
            await update.message.reply_text("❌ Percent must be between 0 and 100")
            return

        success = await set_tier_commission(tier, percent)

        if success:
            await update.message.reply_text(
                f"✅ <b>Tier {tier} commission set to {percent}%</b>\n\n"
                f"Use /getfees to see all current rates.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text("❌ Failed to update fee configuration")

    except ValueError:
        await update.message.reply_text("❌ Invalid tier or percent value. Both must be numbers.")
    except Exception as e:
        logger.error("Failed to set fee", error=str(e))
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def resetfees_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to reset referral fees to default values.
    Usage: /resetfees
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    from src.services.fee import reset_tier_commissions

    try:
        await reset_tier_commissions()

        await update.message.reply_text(
            "✅ <b>Referral fees reset to defaults:</b>\n\n"
            "├ Tier 1: 25%\n"
            "├ Tier 2: 5%\n"
            "└ Tier 3: 3%",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to reset fees", error=str(e))
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def checkuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to check a user's referral stats.
    Usage: /checkuser <telegram_id>
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    from src.db.database import get_user_by_telegram_id, get_referral_stats
    from src.services.fee import get_user_custom_rate, DEFAULT_TIER_COMMISSIONS

    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/checkuser &lt;telegram_id&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/checkuser 123456789</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_telegram_id = int(args[0])
        user = await get_user_by_telegram_id(target_telegram_id)

        if not user:
            await update.message.reply_text(f"❌ User with Telegram ID {target_telegram_id} not found.")
            return

        # Get referral stats
        stats = await get_referral_stats(user.id)

        # Check for custom rate
        custom_rate = await get_user_custom_rate(user.id)
        default_rate = DEFAULT_TIER_COMMISSIONS[1] * 100

        rate_text = f"{float(custom_rate * 100):.0f}% ⭐ (VIP)" if custom_rate else f"{float(default_rate):.0f}% (default)"

        text = f"""👤 <b>User Details</b>

<b>Telegram ID:</b> <code>{user.telegram_id}</code>
<b>Username:</b> @{user.username or 'N/A'}
<b>Name:</b> {user.first_name or 'N/A'}
<b>Database ID:</b> <code>{user.id}</code>

📊 <b>Referral Stats</b>
├ Direct Referrals: <code>{stats.get('direct_referrals', 0)}</code>
├ Tier 2 Referrals: <code>{stats.get('tier2_referrals', 0)}</code>
├ Tier 3 Referrals: <code>{stats.get('tier3_referrals', 0)}</code>
└ Total Earnings: <code>${float(stats.get('total_earnings', 0)):,.2f}</code>

💰 <b>Commission Rate</b>
└ Tier 1 Rate: <code>{rate_text}</code>

<b>Commands:</b>
• <code>/setuserrate {user.telegram_id} 50</code> - Set to 50%
• <code>/clearuserrate {user.telegram_id}</code> - Reset to default"""

        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID. Must be a number.")
    except Exception as e:
        logger.error("Failed to check user", error=str(e))
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def setuserrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to set a custom referral rate for a specific user.
    Usage: /setuserrate <telegram_id> <percent>
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    from src.db.database import get_user_by_telegram_id
    from src.services.fee import set_user_custom_rate
    from decimal import Decimal

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/setuserrate &lt;telegram_id&gt; &lt;percent&gt;</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/setuserrate 123456789 50</code> - Give user 50% commission",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_telegram_id = int(args[0])
        percent = Decimal(args[1])

        if percent < 0 or percent > 100:
            await update.message.reply_text("❌ Percent must be between 0 and 100")
            return

        user = await get_user_by_telegram_id(target_telegram_id)
        if not user:
            await update.message.reply_text(f"❌ User with Telegram ID {target_telegram_id} not found.")
            return

        await set_user_custom_rate(user.id, percent)

        await update.message.reply_text(
            f"✅ <b>Custom rate set!</b>\n\n"
            f"User: @{user.username or user.first_name or target_telegram_id}\n"
            f"Tier 1 Rate: <code>{percent}%</code> ⭐\n\n"
            f"This user will now earn {percent}% of trading fees from their direct referrals.",
            parse_mode=ParseMode.HTML,
        )

    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID or percent. Both must be numbers.")
    except Exception as e:
        logger.error("Failed to set user rate", error=str(e))
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def clearuserrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to remove a user's custom rate (back to default).
    Usage: /clearuserrate <telegram_id>
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    from src.db.database import get_user_by_telegram_id
    from src.services.fee import clear_user_custom_rate

    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/clearuserrate &lt;telegram_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_telegram_id = int(args[0])

        user = await get_user_by_telegram_id(target_telegram_id)
        if not user:
            await update.message.reply_text(f"❌ User with Telegram ID {target_telegram_id} not found.")
            return

        removed = await clear_user_custom_rate(user.id)

        if removed:
            await update.message.reply_text(
                f"✅ Custom rate removed for @{user.username or user.first_name or target_telegram_id}\n\n"
                f"They will now earn the default global rate.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                f"ℹ️ User @{user.username or user.first_name or target_telegram_id} had no custom rate set.",
                parse_mode=ParseMode.HTML,
            )

    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID. Must be a number.")
    except Exception as e:
        logger.error("Failed to clear user rate", error=str(e))
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


# ===================
# Price Alerts Commands
# ===================

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    View and manage price alerts.
    Usage: /alerts
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    from src.services.alerts import alerts_service

    user_alerts = await alerts_service.get_user_alerts(telegram_id)

    if not user_alerts:
        text = """
🔔 <b>Price Alerts</b>

You have no active price alerts.

<b>Create an alert:</b>
Use the "Set Alert" button on any market page, or:
<code>/setalert [platform] [market_id] [yes/no] [above/below] [price]</code>

Example:
<code>/setalert polymarket abc123 yes above 0.75</code>
"""
    else:
        text = f"🔔 <b>Your Price Alerts</b> ({len(user_alerts)})\n\n"

        for alert in user_alerts[:10]:  # Show max 10
            price_cents = int(alert.target_price * 100)
            current_cents = int(alert.current_price * 100) if alert.current_price else "?"
            text += f"• <b>{alert.market_title[:40]}...</b>\n"
            text += f"  {alert.outcome.upper()} {alert.condition} {price_cents}¢ (now: {current_cents}¢)\n"
            text += f"  <code>/deletealert {alert.id}</code>\n\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Clear All Alerts", callback_data="alerts:clear_all")],
    ]) if user_alerts else None

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def setalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Create a price alert.
    Usage: /setalert [platform] [market_id] [yes/no] [above/below] [price]
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    args = context.args

    if not args or len(args) < 5:
        await update.message.reply_text(
            "❌ <b>Usage:</b>\n"
            "<code>/setalert [platform] [market_id] [yes/no] [above/below] [price]</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/setalert polymarket abc123 yes above 0.75</code>\n\n"
            "<b>Platforms:</b> polymarket, kalshi, limitless, opinion, myriad",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        platform_str = args[0].lower()
        market_id = args[1]
        outcome = args[2].lower()
        condition = args[3].lower()
        target_price = Decimal(args[4])

        # Validate inputs
        if platform_str not in ["polymarket", "kalshi", "limitless", "opinion", "myriad"]:
            await update.message.reply_text("❌ Invalid platform. Use: polymarket, kalshi, limitless, opinion, myriad")
            return

        if outcome not in ["yes", "no"]:
            await update.message.reply_text("❌ Outcome must be 'yes' or 'no'")
            return

        if condition not in ["above", "below"]:
            await update.message.reply_text("❌ Condition must be 'above' or 'below'")
            return

        if target_price < 0 or target_price > 1:
            await update.message.reply_text("❌ Price must be between 0 and 1 (e.g., 0.75 for 75¢)")
            return

        # Get platform and market
        platform_enum = Platform(platform_str)
        platform = get_platform(platform_enum)
        market = await platform.get_market(market_id)

        if not market:
            await update.message.reply_text(f"❌ Market not found: {market_id}")
            return

        # Create alert
        from src.services.alerts import alerts_service

        alert = await alerts_service.create_alert(
            user_telegram_id=telegram_id,
            platform=platform_enum,
            market_id=market_id,
            market_title=market.title,
            outcome=outcome,
            condition=condition,
            target_price=target_price,
        )

        price_cents = int(target_price * 100)
        current_price = market.yes_price if outcome == "yes" else market.no_price
        current_cents = int(current_price * 100) if current_price else "?"

        await update.message.reply_text(
            f"✅ <b>Alert Created!</b>\n\n"
            f"<b>Market:</b> {market.title[:50]}...\n"
            f"<b>Condition:</b> {outcome.upper()} {condition} {price_cents}¢\n"
            f"<b>Current:</b> {current_cents}¢\n\n"
            f"Alert ID: <code>{alert.id}</code>\n"
            f"Delete with: <code>/deletealert {alert.id}</code>",
            parse_mode=ParseMode.HTML,
        )

    except Exception as e:
        logger.error("Failed to create alert", error=str(e))
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


async def deletealert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Delete a price alert.
    Usage: /deletealert [alert_id]
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "❌ <b>Usage:</b> <code>/deletealert [alert_id]</code>\n\n"
            "Use /alerts to see your alert IDs.",
            parse_mode=ParseMode.HTML,
        )
        return

    alert_id = args[0]

    from src.services.alerts import alerts_service

    deleted = await alerts_service.delete_alert(alert_id, telegram_id)

    if deleted:
        await update.message.reply_text(f"✅ Alert {alert_id} deleted.")
    else:
        await update.message.reply_text(f"❌ Alert not found or not yours: {alert_id}")


# ===================
# Arbitrage Commands
# ===================

async def arbitrage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Subscribe/unsubscribe to cross-platform arbitrage alerts.
    Usage: /arbitrage
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    from src.services.alerts import alerts_service

    is_subscribed = alerts_service.is_subscribed_arbitrage(telegram_id)

    text = """
⚡ <b>Cross-Platform Arbitrage Alerts</b>

Get notified when the same market has significantly different prices on Polymarket vs Kalshi (3%+ spread).

<b>How it works:</b>
• We monitor matching markets across platforms
• Alert you when prices diverge significantly
• You can profit by buying low on one platform, selling high on another

<b>Note:</b> Consider fees, slippage, and settlement times.
"""

    if is_subscribed:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔕 Unsubscribe", callback_data="arbitrage:unsubscribe")],
            [InlineKeyboardButton("🔍 Check Now", callback_data="arbitrage:check")],
        ])
        text += "\n✅ <b>You are subscribed to arbitrage alerts.</b>"
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 Subscribe", callback_data="arbitrage:subscribe")],
            [InlineKeyboardButton("🔍 Check Now", callback_data="arbitrage:check")],
        ])
        text += "\n❌ <b>You are not subscribed.</b>"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_arbitrage_callback(query, action: str, telegram_id: int) -> None:
    """Handle arbitrage-related callback queries."""
    from src.services.alerts import alerts_service

    if action == "subscribe":
        await alerts_service.subscribe_arbitrage(telegram_id)
        await query.edit_message_text(
            "✅ <b>Subscribed to Arbitrage Alerts!</b>\n\n"
            "You'll receive notifications when we detect price differences "
            "of 3% or more between Polymarket and Kalshi.\n\n"
            "Use /arbitrage to manage your subscription.",
            parse_mode=ParseMode.HTML,
        )

    elif action == "unsubscribe":
        await alerts_service.unsubscribe_arbitrage(telegram_id)
        await query.edit_message_text(
            "🔕 <b>Unsubscribed from Arbitrage Alerts</b>\n\n"
            "You won't receive arbitrage notifications anymore.\n\n"
            "Use /arbitrage to subscribe again.",
            parse_mode=ParseMode.HTML,
        )

    elif action == "check":
        await query.edit_message_text(
            "🔍 <b>Scanning for arbitrage across all 4 platforms...</b>",
            parse_mode=ParseMode.HTML,
        )

        opportunities = await alerts_service.find_arbitrage_opportunities()

        if not opportunities:
            await query.edit_message_text(
                "📊 <b>Arbitrage Scan Complete</b>\n\n"
                "No significant arbitrage opportunities found right now.\n\n"
                "We check for price differences of 3¢ or more between:\n"
                "• Polymarket\n• Kalshi\n• Limitless\n• Opinion Labs\n• Myriad",
                parse_mode=ParseMode.HTML,
            )
        else:
            # Platform display names
            platform_names = {
                Platform.POLYMARKET: "Poly",
                Platform.KALSHI: "Kalshi",
                Platform.LIMITLESS: "Limitless",
                Platform.OPINION: "Opinion",
                Platform.MYRIAD: "Myriad",
            }

            text = f"⚡ <b>Found {len(opportunities)} Opportunities!</b>\n\n"

            for opp in opportunities[:5]:  # Show max 5
                buy_name = platform_names.get(opp.buy_platform, opp.buy_platform.value)
                sell_name = platform_names.get(opp.sell_platform, opp.sell_platform.value)
                buy_price = int(opp.buy_price * 100)
                sell_price = int(opp.sell_price * 100)
                profit_str = f"+{opp.profit_potential:.1f}%" if opp.profit_potential > 0 else f"{opp.profit_potential:.1f}%"
                text += f"<b>{opp.market_title[:35]}...</b>\n"
                text += f"• {buy_name}: {buy_price}¢ → {sell_name}: {sell_price}¢\n"
                text += f"• Spread: {opp.spread_cents}¢ | Profit: {profit_str}\n\n"

            text += "<i>Subscribe to get instant alerts with trade buttons!</i>"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Subscribe for Auto-Alerts", callback_data="arbitrage:subscribe")],
            ])

            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )


async def handle_alerts_callback(query, action: str, telegram_id: int) -> None:
    """Handle alerts-related callback queries."""
    from src.services.alerts import alerts_service

    if action == "clear_all":
        # Clear all user alerts
        user_alerts = await alerts_service.get_user_alerts(telegram_id)
        for alert in user_alerts:
            await alerts_service.delete_alert(alert.id, telegram_id)

        await query.edit_message_text(
            "🗑️ <b>All alerts cleared!</b>\n\n"
            "Use /setalert to create new alerts.",
            parse_mode=ParseMode.HTML,
        )


async def handle_arb_trade(
    query, platform: str, market_id: str, outcome: str, side: str, telegram_id: int, context
) -> None:
    """
    Handle trade initiation from arbitrage alerts.
    Format: arb_trade:platform:market_id:outcome:side
    """
    try:
        # Convert platform string to Platform enum
        platform_enum = Platform(platform)

        # Get user
        user = await get_user_by_telegram_id(telegram_id)
        if not user:
            await query.edit_message_text("❌ Please /start first!")
            return

        # Get the platform client
        platform_client = get_platform(platform_enum)
        if not platform_client:
            await query.edit_message_text(f"❌ Platform {platform} is not available.")
            return

        # Get market info
        market = await platform_client.get_market(market_id)
        if not market:
            await query.edit_message_text("❌ Market not found. It may have expired or closed.")
            return

        # Get chain family for wallet
        chain_family = get_chain_family_for_platform(platform_enum)

        # Get wallet
        from src.db.database import get_user_wallets
        wallets = await get_user_wallets(user.id)
        wallet = next((w for w in wallets if w.chain_family == chain_family), None)

        if not wallet:
            await query.edit_message_text(
                f"❌ You don't have a {chain_family.value.upper()} wallet.\n\n"
                f"Use /wallet to create one first.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Get wallet balance
        wallet_info = await wallet_service.get_wallet_info(wallet)
        balance = wallet_info.usdc_balance if wallet_info else Decimal("0")

        # Build trading UI
        price = market.yes_price if outcome == "yes" else market.no_price
        price_cents = int(price * 100) if price else 0

        text = f"""
⚡ <b>Quick Trade from Arbitrage</b>

<b>Market:</b> {escape_html(market.title[:60])}...
<b>Platform:</b> {PLATFORM_INFO[platform_enum]['name']}
<b>Action:</b> {side.upper()} {outcome.upper()}
<b>Current Price:</b> {price_cents}¢

<b>Your Balance:</b> ${balance:.2f} USDC

Enter the amount you want to trade (in USDC):
"""

        # Store pending trade info in context
        context.user_data["pending_arb_trade"] = {
            "platform": platform,
            "market_id": market_id,
            "outcome": outcome,
            "side": side,
            "market_title": market.title,
        }

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("$5", callback_data=f"arb_amount:{platform}:{market_id}:{outcome}:{side}:5"),
                InlineKeyboardButton("$10", callback_data=f"arb_amount:{platform}:{market_id}:{outcome}:{side}:10"),
                InlineKeyboardButton("$25", callback_data=f"arb_amount:{platform}:{market_id}:{outcome}:{side}:25"),
            ],
            [
                InlineKeyboardButton("$50", callback_data=f"arb_amount:{platform}:{market_id}:{outcome}:{side}:50"),
                InlineKeyboardButton("$100", callback_data=f"arb_amount:{platform}:{market_id}:{outcome}:{side}:100"),
                InlineKeyboardButton("MAX", callback_data=f"arb_amount:{platform}:{market_id}:{outcome}:{side}:max"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_arb")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Failed to initiate arb trade", error=str(e))
        await query.edit_message_text(f"❌ Error: {friendly_error(str(e))}")


async def handle_view_market_from_arb(query, platform: str, market_id: str, telegram_id: int) -> None:
    """
    Handle viewing a market from arbitrage alert.
    Shows market details with trade buttons.
    """
    try:
        platform_enum = Platform(platform)
        await handle_market_view(query, platform, market_id, telegram_id)

    except Exception as e:
        logger.error("Failed to view market from arb", error=str(e))
        await query.edit_message_text(f"❌ Error: {friendly_error(str(e))}")


async def handle_arb_amount(
    query, platform: str, market_id: str, outcome: str, side: str, amount_str: str, telegram_id: int, context
) -> None:
    """
    Handle amount selection for arbitrage trade.
    Executes the trade with the selected amount.
    """
    from src.services.wallet import wallet_service
    from src.db.database import get_user_wallets

    try:
        platform_enum = Platform(platform)

        # Get user
        user = await get_user_by_telegram_id(telegram_id)
        if not user:
            await query.edit_message_text("❌ Please /start first!")
            return

        # Get chain family and wallet
        chain_family = get_chain_family_for_platform(platform_enum)
        wallets = await get_user_wallets(user.id)
        wallet = next((w for w in wallets if w.chain_family == chain_family), None)

        if not wallet:
            await query.edit_message_text("❌ Wallet not found. Use /wallet to create one.")
            return

        # Get wallet balance for MAX
        wallet_info = await wallet_service.get_wallet_info(wallet)
        balance = wallet_info.usdc_balance if wallet_info else Decimal("0")

        # Parse amount
        if amount_str.lower() == "max":
            # Use 95% of balance to leave room for fees
            amount = balance * Decimal("0.95")
            if amount < Decimal("1"):
                await query.edit_message_text("❌ Insufficient balance for trade.")
                return
        else:
            amount = Decimal(amount_str)

        if amount > balance:
            await query.edit_message_text(
                f"❌ Insufficient balance.\n\nYou have ${balance:.2f} USDC but tried to trade ${amount:.2f}.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Show processing message
        await query.edit_message_text(
            f"⏳ <b>Processing trade...</b>\n\n"
            f"Platform: {PLATFORM_INFO[platform_enum]['name']}\n"
            f"Action: {side.upper()} {outcome.upper()}\n"
            f"Amount: ${amount:.2f}",
            parse_mode=ParseMode.HTML,
        )

        # Get platform client
        platform_client = get_platform(platform_enum)

        # Get quote
        from src.platforms.base import Outcome
        outcome_enum = Outcome.YES if outcome == "yes" else Outcome.NO

        quote = await platform_client.get_quote(
            market_id=market_id,
            outcome=outcome_enum,
            side=side,
            amount=amount,
            wallet_address=wallet.public_key,
        )

        if not quote:
            await query.edit_message_text("❌ Failed to get quote. Market may be unavailable.")
            return

        # Execute trade
        result = await platform_client.execute_trade(
            quote=quote,
            wallet=wallet,
        )

        if result and result.success:
            # Create position record
            market = await platform_client.get_market(market_id)
            await create_position(
                user_id=user.id,
                platform=platform_enum,
                market_id=market_id,
                market_title=market.title if market else "Unknown",
                outcome=outcome,
                token_amount=str(result.output_amount or quote.expected_output),
                entry_price=str(quote.price),
            )

            # Check for marketing qualification postback (first trade over $5)
            try:
                from src.services.postback import check_and_send_trade_postback
                await check_and_send_trade_postback(
                    telegram_id=telegram_id,
                    trade_amount=amount,
                    fee_amount=Decimal("0"),  # No fee tracking for arb trades yet
                )
            except Exception as pb_error:
                logger.debug("Postback check failed", error=str(pb_error))

            # Show success
            output_amount = result.output_amount or quote.expected_output
            price_cents = int(quote.price * 100)

            text = f"""
✅ <b>Trade Executed!</b>

<b>Platform:</b> {PLATFORM_INFO[platform_enum]['name']}
<b>Action:</b> {side.upper()} {outcome.upper()}
<b>Amount:</b> ${amount:.2f}
<b>Price:</b> {price_cents}¢
<b>Tokens:</b> {output_amount:.2f}

<i>From arbitrage opportunity. Check /positions for your portfolio.</i>
"""
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Positions", callback_data="positions:view")],
            ])

            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            error_msg = result.error if result else "Unknown error"
            await query.edit_message_text(f"❌ Trade failed: {friendly_error(error_msg)}")

    except Exception as e:
        logger.error("Failed to execute arb trade", error=str(e))
        await query.edit_message_text(f"❌ Error: {friendly_error(str(e))}")


# ===================
# Admin Broadcast
# ===================

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to broadcast a message to all users."""
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id

    if not is_admin(telegram_id):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    context.user_data["awaiting_broadcast"] = True
    await update.message.reply_text(
        "📢 <b>Broadcast Message</b>\n\n"
        "Send me the message to broadcast. You can include a photo with caption, or just text.\n\n"
        "Send /cancel to abort.",
        parse_mode=ParseMode.HTML,
    )


async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the broadcast content (photo+caption or text) from admin."""
    if not update.effective_user or not update.message:
        return

    if not context.user_data.get("awaiting_broadcast"):
        return

    context.user_data.pop("awaiting_broadcast", None)

    user_ids = await get_all_user_telegram_ids()
    total = len(user_ids)

    await update.message.reply_text(f"📢 Broadcasting to {total} users...")

    has_photo = update.message.photo
    success = 0
    failed = 0

    for uid in user_ids:
        try:
            if has_photo:
                photo_file_id = update.message.photo[-1].file_id
                await context.bot.send_photo(
                    chat_id=uid,
                    photo=photo_file_id,
                    caption=update.message.caption or "",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await context.bot.send_message(
                    chat_id=uid,
                    text=update.message.text or "",
                    parse_mode=ParseMode.HTML,
                )
            success += 1
        except Forbidden:
            failed += 1
        except Exception as e:
            logger.warning("Broadcast send failed", user_id=uid, error=str(e))
            failed += 1
        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"✅ Broadcast complete!\n\n"
        f"Sent: {success}\n"
        f"Failed: {failed} (blocked/deleted)",
    )
