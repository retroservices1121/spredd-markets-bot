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
)
from src.utils.geo_blocking import (
    is_country_blocked,
    get_blocked_message,
    needs_reverification,
    get_country_name,
)
from src.db.models import Platform, ChainFamily, Chain, PositionStatus, OrderStatus
from src.platforms import (
    platform_registry,
    get_platform,
    get_platform_info,
    get_chain_family_for_platform,
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
    """Convert technical error messages to user-friendly plain English."""
    error_lower = error.lower()

    # Common error patterns and their friendly versions
    if "insufficient" in error_lower and "conditional token" in error_lower:
        return "You don't have the tokens needed to sell. The position may not have been purchased successfully."
    if "insufficient" in error_lower and ("balance" in error_lower or "fund" in error_lower):
        return "You don't have enough funds in your wallet. Please deposit more and try again."
    if "allowance" in error_lower:
        return "Wallet approval is pending. Please wait a moment and try again."
    if "gas" in error_lower or "fee" in error_lower and "estimate" in error_lower:
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
    if any(x in cleaned.lower() for x in ["traceback", "0x", "bytes", "uint", "abi", "keccak"]):
        return "Something went wrong. Please try again or contact support if the issue persists."

    return cleaned if len(cleaned) < 200 else cleaned[:200] + "..."


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
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referral_code = arg[4:]  # Remove "ref_" prefix
        elif arg == "geo_verified":
            geo_verified = True

    user = await get_or_create_user(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )

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

You can still trade on other platforms like Polymarket, Opinion, and Limitless.
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

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless)
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

    # EVM wallet (for Polymarket, Opinion & Monad)
    if evm_wallet:
        text += f"<b>🔷 EVM</b> (Polymarket + Opinion + Limitless)\n"
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
        # Fetch one extra to check if there's a next page
        markets = await platform.get_markets(limit=per_page + 1, offset=0, active_only=True)

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
            lookup_id = pos.event_id if pos.event_id else pos.market_id
            market = await platform.get_market(lookup_id, search_title=pos.market_title)
            if not market and pos.event_id:
                market = await platform.get_market(pos.market_id, search_title=pos.market_title)

            if not market:
                # Market not found - likely expired/delisted
                # Auto-close these positions to clean up database and speed up future queries
                await update_position(pos.id, status=PositionStatus.EXPIRED, token_amount="0")
                logger.info(f"Auto-closed position {pos.id} - market {pos.market_id} not found (likely expired)")
                continue

            # Check market resolution status
            resolution = await platform.get_market_resolution(lookup_id)

            if resolution.is_resolved:
                # Auto-close resolved positions
                outcome_str = pos.outcome.upper() if isinstance(pos.outcome, str) else pos.outcome.value.upper()
                if resolution.winning_outcome and resolution.winning_outcome.upper() == outcome_str:
                    # Won - mark as redeemable but still show for redemption
                    active_positions.append(pos)
                else:
                    # Lost - auto-close the position
                    await update_position(pos.id, status=PositionStatus.CLOSED, token_amount="0")
                    logger.info(f"Auto-closed losing position {pos.id} for resolved market {pos.market_id}")
            else:
                # Market still active
                active_positions.append(pos)
        except Exception as e:
            # If we can't check, skip the position to avoid errors
            logger.debug(f"Could not verify position {pos.id}: {e}")
            continue

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
        try:
            # Try event_id (slug) first for Limitless, then fall back to market_id with title search
            lookup_id = pos.event_id if pos.event_id else pos.market_id
            market = await platform.get_market(lookup_id, search_title=pos.market_title)
            if not market and pos.event_id:
                # Fallback to numeric ID with title search if slug lookup failed
                market = await platform.get_market(pos.market_id, search_title=pos.market_title)
            if market:
                # Get the price for the outcome the user holds
                if outcome_str == "YES":
                    current_price = market.yes_price
                else:
                    current_price = market.no_price
        except Exception:
            pass

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
        text += f"  {outcome_str} ({spent_str}) • Entry: {entry} • Now: {current}\n"
        text += f"  {pnl_emoji} P&L: {pnl_str}\n\n"

    # Build buttons - sell/redeem button for each position + pagination
    buttons = []

    # Add sell or redeem buttons for each position on current page
    for pos in positions:
        short_title = pos.market_title[:20] + "..." if len(pos.market_title) > 20 else pos.market_title
        outcome_str = pos.outcome.upper() if isinstance(pos.outcome, str) else pos.outcome.value.upper()

        # Check if market is resolved for redemption - try event_id (slug) first for Limitless
        try:
            resolution_market_id = pos.event_id if pos.event_id else pos.market_id
            resolution = await platform.get_market_resolution(resolution_market_id)
            if resolution.is_resolved:
                # Show Redeem button for resolved markets
                if resolution.winning_outcome and resolution.winning_outcome.upper() == outcome_str:
                    buttons.append([
                        InlineKeyboardButton(
                            f"🏆 Redeem {outcome_str}: {short_title}",
                            callback_data=f"redeem:{pos.id}"
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
                        f"💰 Sell {outcome_str}: {short_title}",
                        callback_data=f"sell:{pos.id}"
                    )
                ])
        except Exception:
            # Default to Sell if we can't check resolution
            buttons.append([
                InlineKeyboardButton(
                    f"💰 Sell {outcome_str}: {short_title}",
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
            text += f"   <a href='{get_platform(user.active_platform).get_explorer_url(order.tx_hash)}'>View TX</a>\n"
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
            current_price = None
            try:
                lookup_id = pos.event_id if pos.event_id else pos.market_id
                market = await platform.get_market(lookup_id, search_title=pos.market_title)
                if not market and pos.event_id:
                    market = await platform.get_market(pos.market_id, search_title=pos.market_title)
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
        [InlineKeyboardButton("🔮 Kalshi", callback_data="pnlcard:kalshi")],
        [InlineKeyboardButton("🔷 Polymarket", callback_data="pnlcard:polymarket")],
        [InlineKeyboardButton("💬 Opinion", callback_data="pnlcard:opinion")],
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

<b>🔷 EVM (Polymarket/Opinion/Limitless)</b>
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
            # Format: bridge:start:source_chain, bridge:amount:chain:percent, bridge:custom:chain, bridge:speed:chain:mode
            logger.info("Bridge callback received", callback_data=data, parts=parts)
            if parts[1] == "start":
                # bridge:start:source_chain - user selected a chain to bridge from
                await handle_bridge_start(query, parts[2], update.effective_user.id, context)
            elif parts[1] == "amount":
                # bridge:amount:chain:percentage - user selected preset amount
                await handle_bridge_amount(query, parts[2], int(parts[3]), update.effective_user.id, context)
            elif parts[1] == "custom":
                # bridge:custom:chain - user wants to enter custom amount
                await handle_bridge_custom(query, parts[2], update.effective_user.id, context)
            elif parts[1] == "speed":
                # bridge:speed:chain:mode - user selected fast or standard
                await handle_bridge_speed(query, parts[2], parts[3], update.effective_user.id, context)
            else:
                # bridge:source_chain - legacy format
                logger.info("Using legacy bridge format", chain=parts[1])
                await handle_bridge_start(query, parts[1], update.effective_user.id, context)

        elif action == "export":
            await handle_export_key(query, parts[1], update.effective_user.id, context)

        elif action == "markets":
            if parts[1] == "refresh":
                await handle_markets_refresh(query, update.effective_user.id, page=0)
            elif parts[1] == "page":
                page = int(parts[2]) if len(parts) > 2 else 0
                await handle_markets_refresh(query, update.effective_user.id, page=page)

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

    except Exception as e:
        logger.error("Callback handler error", error=str(e), data=data)
        await query.edit_message_text(
            f"❌ Error: {friendly_error(str(e))}",
            parse_mode=ParseMode.HTML,
        )


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

    # Check geo-blocking for Kalshi
    if platform == Platform.KALSHI:
        # Check if user needs IP-based verification
        if not user.country or needs_reverification(user.country_verified_at):
            # Generate verification token and show link
            await show_geo_verification(query, telegram_id, platform_value)
            return

        if is_country_blocked(Platform.KALSHI, user.country):
            # User's country is blocked
            message = get_blocked_message(Platform.KALSHI, user.country)
            country_name = get_country_name(user.country)

            # Build re-verify button - use WebAppInfo if Mini App is configured
            buttons = [[InlineKeyboardButton("🔄 Select Different Platform", callback_data="menu:platform")]]
            if settings.miniapp_url:
                # Point to geo check page which shows verification result
                reverify_url = f"{settings.miniapp_url.rstrip('/')}/api/v1/geo/check"
                buttons.append([InlineKeyboardButton("🔄 Re-verify Location", web_app=WebAppInfo(url=reverify_url))])

            keyboard = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(
                f"🚫 <b>Access Restricted</b>\n\n"
                f"Your verified location ({country_name}) is restricted from accessing Kalshi "
                f"due to regulatory requirements.\n\n"
                f"Please select a different platform.",
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
        text = f"""
{info['emoji']} <b>{escape_html(market.title)}</b>

📊 <b>Options ({len(related_markets)} choices)</b>
"""
        # Add each outcome with its probability
        for i, rm in enumerate(related_markets, 1):
            prob = format_probability(rm.yes_price)
            name = rm.outcome_name or rm.title
            # Truncate long names
            if len(name) > 30:
                name = name[:27] + "..."
            text += f"{i}. {escape_html(name)}: {prob}\n"

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

        # Create buy buttons for each outcome (up to 8 to fit Telegram limits)
        buttons = []
        for rm in related_markets[:8]:
            name = rm.outcome_name or rm.title
            if len(name) > 20:
                name = name[:17] + "..."
            prob = format_probability(rm.yes_price)
            # Truncate market_id to fit callback_data limit (64 bytes)
            short_id = rm.market_id[:40]
            buttons.append([
                InlineKeyboardButton(
                    f"{escape_html(name)} ({prob})",
                    callback_data=f"buy:{platform_value}:{short_id}:yes"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🤖 AI Research",
                callback_data=f"ai_research:{platform_value}:{market_id}"
            ),
        ])
        buttons.append([InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")])
        keyboard = InlineKeyboardMarkup(buttons)
    else:
        # Binary market - show YES/NO
        text = f"""
{info['emoji']} <b>{escape_html(market.title)}</b>

📊 <b>Current Prices</b>
YES: {format_probability(market.yes_price)} ({format_price(market.yes_price)})
NO: {format_probability(market.no_price)} ({format_price(market.no_price)})

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

        # Buy buttons for binary market
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"🟢 Buy YES ({format_probability(market.yes_price)})",
                    callback_data=f"buy:{platform_value}:{market_id}:yes"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🔴 Buy NO ({format_probability(market.no_price)})",
                    callback_data=f"buy:{platform_value}:{market_id}:no"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🤖 AI Research",
                    callback_data=f"ai_research:{platform_value}:{market_id}"
                ),
            ],
            [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
        ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def handle_ai_research(query, platform_value: str, market_id: str, telegram_id: int) -> None:
    """Handle AI research request for a market."""
    from src.services.factsai import factsai_service
    from src.db.database import get_user_trading_volume, get_wallet

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
                [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{market_id}")],
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
                [InlineKeyboardButton("🔄 Retry", callback_data=f"ai_research:{platform_value}:{market_id}")],
                [InlineKeyboardButton("« Back to Market", callback_data=f"market:{platform_value}:{market_id}")],
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
            [InlineKeyboardButton("🔄 Refresh Analysis", callback_data=f"ai_research:{platform_value}:{market_id}")],
            [InlineKeyboardButton("« Back to Market", callback_data=f"market:{platform_value}:{market_id}")],
        ]),
    )


async def handle_buy_start(query, platform_value: str, market_id: str, outcome: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle starting a buy order."""
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
            main_loop = asyncio.get_event_loop()  # Capture main event loop

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
                    [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{market_id}")],
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

    # Store buy context for message handler
    context.user_data["pending_buy"] = {
        "platform": platform_value,
        "market_id": market_id,
        "outcome": outcome,
    }

    text = f"""
💰 <b>Buy {outcome.upper()} Position</b>

Platform: {info['name']}
Collateral: {info['collateral']}{swap_note}

Enter the amount in {info['collateral']} you want to spend:

<i>Example: 10 (for 10 {info['collateral']})</i>

Type /cancel to cancel.
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{market_id}")],
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

    text = "💰 <b>Your Wallets</b>\n\n"

    if solana_wallet:
        text += f"<b>🟣 Solana</b> (Kalshi)\n"
        text += f"<code>{solana_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.SOLANA, []):
            text += f"  • {bal.formatted}\n"
        text += "\n"

    if evm_wallet:
        text += f"<b>🔷 EVM</b> (Polymarket + Opinion + Limitless)\n"
        text += f"<code>{evm_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.EVM, []):
            text += f"  • {bal.formatted} ({bal.chain.value})\n"

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
    """Show bridge menu with available source chains."""
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

        if not evm_wallet:
            await query.edit_message_text(
                "❌ No EVM wallet found. Please /start to create one.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Get balances on all chains
        balances = bridge_service.get_all_usdc_balances(evm_wallet.public_key)

        text = "🌉 <b>Bridge USDC to Polygon</b>\n\n"
        text += "Bridge USDC from other chains to Polygon for trading.\n\n"
        text += "<b>Your USDC Balances:</b>\n"

        buttons = []
        for chain, balance in balances.items():
            chain_emoji = {
                BridgeChain.BASE: "🔵",
                BridgeChain.ARBITRUM: "🔷",
                BridgeChain.OPTIMISM: "🔴",
                BridgeChain.ETHEREUM: "⚪",
                BridgeChain.POLYGON: "🟣",
                BridgeChain.MONAD: "🟢",
            }.get(chain, "🔹")

            text += f"{chain_emoji} {chain.value.title()}: ${float(balance):.2f}\n"

            # Only show bridge button for chains with balance (excluding Polygon)
            if chain != BridgeChain.POLYGON and balance > 0:
                buttons.append([
                    InlineKeyboardButton(
                        f"{chain_emoji} Bridge from {chain.value.title()} (${float(balance):.2f})",
                        callback_data=f"bridge:start:{chain.value}"
                    )
                ])

        if not buttons:
            text += "\n<i>No bridgeable balance found on other chains.</i>"

        text += "\n\n<i>Bridging uses Circle CCTP (native USDC, ~10-15 min)</i>"

        buttons.append([InlineKeyboardButton("« Back to Wallet", callback_data="wallet:refresh")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        error_str = str(e)
        # Ignore "Message is not modified" error - it's harmless
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
            pass  # Ignore edit errors


async def handle_bridge_start(query, source_chain: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start manual bridge - show amount selection."""
    logger.info("Bridge start called", source_chain=source_chain, telegram_id=telegram_id)

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    try:
        from src.services.bridge import bridge_service, BridgeChain
        from src.db.database import get_user_wallets

        # Get chain enum
        try:
            chain = BridgeChain(source_chain.lower())
        except ValueError:
            await query.edit_message_text(f"Invalid chain: {source_chain}")
            return

        # Get user's wallet
        wallets = await get_user_wallets(user.id)
        evm_wallet = next((w for w in wallets if w.chain_family == ChainFamily.EVM), None)

        if not evm_wallet:
            await query.edit_message_text("❌ No EVM wallet found.")
            return

        # Get balance on source chain
        if not bridge_service._initialized:
            bridge_service.initialize()

        balance = bridge_service.get_usdc_balance(chain, evm_wallet.public_key)

        if balance <= 0:
            await query.edit_message_text(
                f"❌ No USDC balance on {chain.value.title()}.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
                ]),
            )
            return

        # Store pending bridge info for amount selection
        context.user_data["pending_bridge"] = {
            "source_chain": source_chain,
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

        text = f"""
🌉 <b>Bridge USDC to Polygon</b>

Source: {chain.value.title()}
Available: <b>${float(balance):.2f} USDC</b>

Select amount to bridge or enter a custom amount:
"""

        buttons = [
            [
                InlineKeyboardButton(f"25% (${float(amounts['25%']):.2f})", callback_data=f"bridge:amount:{source_chain}:25"),
                InlineKeyboardButton(f"50% (${float(amounts['50%']):.2f})", callback_data=f"bridge:amount:{source_chain}:50"),
            ],
            [
                InlineKeyboardButton(f"75% (${float(amounts['75%']):.2f})", callback_data=f"bridge:amount:{source_chain}:75"),
                InlineKeyboardButton(f"100% (${float(amounts['100%']):.2f})", callback_data=f"bridge:amount:{source_chain}:100"),
            ],
            [InlineKeyboardButton("✏️ Custom Amount", callback_data=f"bridge:custom:{source_chain}")],
            [InlineKeyboardButton("« Back", callback_data="wallet:bridge")],
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


async def handle_bridge_amount(query, source_chain: str, percentage: int, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bridge amount selection - show speed options."""
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
    context.user_data["pending_bridge"]["awaiting_amount"] = False

    from src.services.bridge import BridgeChain, bridge_service
    from src.db.database import get_wallet
    chain = BridgeChain(source_chain.lower())

    # Get fast bridge quote for fee display
    evm_wallet = await get_wallet(user.id, ChainFamily.EVM)
    fast_quote = None
    if evm_wallet:
        fast_quote = bridge_service.get_fast_bridge_quote(
            chain, BridgeChain.POLYGON, amount, evm_wallet.public_key
        )

    # Show speed selection
    fee_text = ""
    if fast_quote and not fast_quote.error:
        fee_display = f"${float(fast_quote.fee_amount):.2f}" if fast_quote.fee_amount > 0 else f"{fast_quote.fee_percent:.1f}%"
        receive_amount = f"${float(fast_quote.output_amount):.2f}"
        fee_text = f"\n<b>🚀 Fast:</b> ~30 seconds, {fee_display} fee → receive {receive_amount}"
    else:
        fee_text = "\n<b>🚀 Fast:</b> ~30 seconds (small fee)"

    text = f"""
🌉 <b>Bridge USDC - Select Speed</b>

From: {chain.value.title()}
To: Polygon
Amount: <b>${float(amount):.2f} USDC</b>

<b>Choose bridge speed:</b>
{fee_text}
<b>🐢 Standard:</b> ~10-15 min, FREE (Circle CCTP)
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Fast (~30s)", callback_data=f"bridge:speed:{source_chain}:fast")],
        [InlineKeyboardButton("🐢 Standard (Free)", callback_data=f"bridge:speed:{source_chain}:standard")],
        [InlineKeyboardButton("« Back", callback_data=f"bridge:start:{source_chain}")],
    ])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def handle_bridge_custom(query, source_chain: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt user to enter custom bridge amount."""
    pending = context.user_data.get("pending_bridge")
    if not pending:
        await query.edit_message_text("No pending bridge. Please start again.")
        return

    max_balance = Decimal(pending["max_balance"])

    from src.services.bridge import BridgeChain
    chain = BridgeChain(source_chain.lower())

    context.user_data["pending_bridge"]["awaiting_custom_amount"] = True

    text = f"""
🌉 <b>Bridge USDC - Custom Amount</b>

Source: {chain.value.title()}
Available: <b>${float(max_balance):.2f} USDC</b>

<b>Enter the amount in USDC to bridge:</b>
<i>(e.g., 10, 25.50, 100)</i>
"""
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def handle_bridge_custom_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE, amount_str: str) -> None:
    """Handle custom bridge amount input from user - show speed selection."""
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

    # Update pending bridge with amount
    context.user_data["pending_bridge"]["amount"] = str(amount)
    context.user_data["pending_bridge"]["awaiting_custom_amount"] = False

    from src.services.bridge import BridgeChain, bridge_service
    from src.db.database import get_wallet
    chain = BridgeChain(source_chain.lower())

    # Get fast bridge quote for fee display
    evm_wallet = await get_wallet(user.id, ChainFamily.EVM)
    fast_quote = None
    if evm_wallet:
        fast_quote = bridge_service.get_fast_bridge_quote(
            chain, BridgeChain.POLYGON, amount, evm_wallet.public_key
        )

    # Show speed selection
    fee_text = ""
    if fast_quote and not fast_quote.error:
        fee_display = f"${float(fast_quote.fee_amount):.2f}" if fast_quote.fee_amount > 0 else f"{fast_quote.fee_percent:.1f}%"
        receive_amount = f"${float(fast_quote.output_amount):.2f}"
        fee_text = f"\n<b>🚀 Fast:</b> ~30 seconds, {fee_display} fee → receive {receive_amount}"
    else:
        fee_text = "\n<b>🚀 Fast:</b> ~30 seconds (small fee)"

    text = f"""
🌉 <b>Bridge USDC - Select Speed</b>

From: {chain.value.title()}
To: Polygon
Amount: <b>${float(amount):.2f} USDC</b>

<b>Choose bridge speed:</b>
{fee_text}
<b>🐢 Standard:</b> ~10-15 min, FREE (Circle CCTP)
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 Fast (~30s)", callback_data=f"bridge:speed:{source_chain}:fast")],
        [InlineKeyboardButton("🐢 Standard (Free)", callback_data=f"bridge:speed:{source_chain}:standard")],
        [InlineKeyboardButton("« Back", callback_data=f"bridge:start:{source_chain}")],
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def handle_bridge_speed(query, source_chain: str, speed: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bridge speed selection (fast or standard)."""
    pending = context.user_data.get("pending_bridge")
    if not pending:
        await query.edit_message_text("No pending bridge. Please start again.")
        return

    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    amount = Decimal(pending["amount"])

    # Store the speed choice
    context.user_data["pending_bridge"]["speed"] = speed

    # Execute bridge directly (no PIN required)
    await execute_bridge(query, user.id, telegram_id, source_chain, amount, context)


async def execute_bridge(query, user_id: str, telegram_id: int, source_chain: str, amount: Decimal, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute the bridge operation (fast or standard based on pending_bridge settings)."""
    try:
        from src.services.bridge import bridge_service, BridgeChain
        import asyncio

        chain = BridgeChain(source_chain.lower())
        chain_family = ChainFamily.EVM

        # Get speed from pending bridge (default to standard)
        pending = context.user_data.get("pending_bridge", {})
        use_fast_bridge = pending.get("speed") == "fast"

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

        # Show progress message
        speed_label = "🚀 Fast" if use_fast_bridge else "🐢 Standard"
        await query.edit_message_text(
            f"🌉 <b>Bridging USDC ({speed_label})</b>\n\n"
            f"From: {chain.value.title()}\n"
            f"To: Polygon\n"
            f"Amount: ${float(amount):.2f}\n\n"
            f"⏳ Initiating transfer...",
            parse_mode=ParseMode.HTML,
        )

        # Create progress callback
        main_loop = asyncio.get_event_loop()
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

        # Execute bridge in thread (fast or standard)
        if use_fast_bridge:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc_fast,
                private_key,
                chain,
                BridgeChain.POLYGON,
                amount,
                sync_progress_callback,
            )
        else:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc,
                private_key,
                chain,
                BridgeChain.POLYGON,
                amount,
                sync_progress_callback,
            )

        if result.success:
            if use_fast_bridge:
                text = f"""
✅ <b>Fast Bridge Complete!</b>

From: {chain.value.title()}
To: Polygon
Amount: ${float(result.amount):.2f} USDC (after fees)

TX: <code>{result.burn_tx_hash[:16] if result.burn_tx_hash else 'pending'}...</code>

🚀 Funds are arriving on Polygon now!
"""
            else:
                text = f"""
✅ <b>Bridge Initiated!</b>

From: {chain.value.title()}
To: Polygon
Amount: ${float(amount):.2f} USDC

Burn TX: <code>{result.burn_tx_hash[:16]}...</code>
"""
                if result.mint_tx_hash:
                    text += f"Mint TX: <code>{result.mint_tx_hash[:16]}...</code>\n"
                    text += "\n✅ Bridge complete! Funds are now on Polygon."
                else:
                    text += "\n⏳ Waiting for Circle attestation. Funds will arrive on Polygon in ~10-15 minutes."

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
    """Handle PIN entry for bridge operation (fast or standard)."""
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
    amount = Decimal(pending["amount"])
    use_fast_bridge = pending.get("speed") == "fast"
    speed_label = "🚀 Fast" if use_fast_bridge else "🐢 Standard"

    # Send initial status
    status_msg = await update.message.reply_text(
        f"🌉 <b>Starting Bridge ({speed_label})</b>\n\n⏳ Verifying PIN and initiating transfer...",
        parse_mode=ParseMode.HTML,
    )

    # Clear pending bridge before executing
    del context.user_data["pending_bridge"]

    # Execute the bridge using the status message as query
    try:
        from src.services.bridge import bridge_service, BridgeChain
        import asyncio

        chain = BridgeChain(source_chain.lower())
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

        # Show progress message
        await status_msg.edit_text(
            f"🌉 <b>Bridging USDC ({speed_label})</b>\n\n"
            f"From: {chain.value.title()}\n"
            f"To: Polygon\n"
            f"Amount: ${float(amount):.2f}\n\n"
            f"⏳ Initiating transfer...",
            parse_mode=ParseMode.HTML,
        )

        # Create progress callback
        main_loop = asyncio.get_event_loop()
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

        # Execute bridge in thread (fast or standard)
        if use_fast_bridge:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc_fast,
                private_key,
                chain,
                BridgeChain.POLYGON,
                amount,
                sync_progress_callback,
            )
        else:
            result = await asyncio.to_thread(
                bridge_service.bridge_usdc,
                private_key,
                chain,
                BridgeChain.POLYGON,
                amount,
                sync_progress_callback,
            )

        if result.success:
            if use_fast_bridge:
                text = f"""
✅ <b>Fast Bridge Complete!</b>

From: {chain.value.title()}
To: Polygon
Amount: ${float(result.amount):.2f} USDC (after fees)

TX: <code>{result.burn_tx_hash[:16] if result.burn_tx_hash else 'pending'}...</code>

🚀 Funds are arriving on Polygon now!
"""
            else:
                text = f"""
✅ <b>Bridge Initiated!</b>

From: {chain.value.title()}
To: Polygon
Amount: ${float(amount):.2f} USDC

Burn TX: <code>{result.burn_tx_hash[:16]}...</code>
"""
                if result.mint_tx_hash:
                    text += f"Mint TX: <code>{result.mint_tx_hash[:16]}...</code>\n"
                    text += "\n✅ Bridge complete! Funds are now on Polygon."
                else:
                    text += "\n⏳ Waiting for Circle attestation. Funds will arrive on Polygon in ~10-15 minutes."

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
• <b>EVM</b> (for Polymarket & Opinion)

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
        # Fetch one extra to check if there's a next page
        markets = await platform.get_markets(limit=per_page + 1, offset=offset, active_only=True)

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

    # Only Polymarket, Limitless, Kalshi, and Opinion support categories currently
    if user.active_platform not in (Platform.POLYMARKET, Platform.LIMITLESS, Platform.KALSHI, Platform.OPINION):
        await query.edit_message_text(
            "📂 <b>Categories</b>\n\n"
            "Categories are currently only available for Polymarket, Limitless, Kalshi, and Opinion.\n\n"
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

<b>🔷 EVM (Polymarket/Opinion/Limitless)</b>
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

    platform = get_platform(platform_enum)
    platform_info = PLATFORM_INFO[platform_enum]
    chain_family = get_chain_family_for_platform(platform_enum)

    await query.edit_message_text(
        f"⏳ Executing order...\n\nBuying {outcome.upper()} with {amount} {platform_info['collateral']}",
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

        # Get market title from quote data or fetch market
        market_title = None
        if quote.quote_data and "market" in quote.quote_data:
            market_data = quote.quote_data["market"]
            market_title = market_data.get("title") or market_data.get("market_title") or market_data.get("question")
        if not market_title:
            market = await platform.get_market(market_id)
            if market:
                market_title = market.title

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

                # Create position record
                try:
                    market = await platform.get_market(market_id)
                    market_title = market.title if market else market_id

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

                text = f"""
✅ <b>Order Executed!</b>

Bought {outcome.upper()} position
Amount: {amount} {platform_info['collateral']}{fee_line}
Received: ~{actual_output:.2f} tokens

<a href="{result.explorer_url}">View Transaction</a>
"""
            else:
                # Order was placed in orderbook but not filled
                text = f"""
⏳ <b>Limit Order Placed</b>

Your {outcome.upper()} order has been placed in the orderbook.
Amount: {amount} {platform_info['collateral']}
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
            [InlineKeyboardButton("🔄 Retry", callback_data=f"buy_start:{platform_value}:{market_id}:{outcome}")],
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

    try:
        percent = int(percent_str)
    except ValueError:
        await query.edit_message_text("❌ Invalid percentage.")
        return

    platform = get_platform(position.platform)
    platform_info = PLATFORM_INFO[position.platform]
    chain_family = get_chain_family_for_platform(position.platform)

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

            text = f"""
✅ <b>Sold Successfully!</b>

Sold {percent}% of {outcome_str} position
Tokens Sold: ~{sell_amount:.4f}
Received: ~${quote.expected_output:.2f} USDC{fee_line}

<a href="{result.explorer_url}">View Transaction</a>
"""
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

    await update.message.reply_text(
        f"⏳ Getting quote for {amount} {platform_info['collateral']}...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get market info
        market = await platform.get_market(market_id)
        if not market:
            context.user_data.pop("pending_buy", None)
            await update.message.reply_text("❌ Market not found.")
            return

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

        text = f"""
📋 <b>Order Quote</b>

Market: {escape_html(market.title[:50])}...
Side: BUY {outcome.upper()}

💰 <b>You Pay:</b> {amount} {platform_info['collateral']}
💸 <b>Fee (2%):</b> {fee_display}
📦 <b>You Receive:</b> ~{expected_tokens:.2f} {outcome.upper()} tokens
📊 <b>Price:</b> {format_probability(price)} per token
"""

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
        main_loop = asyncio.get_event_loop()  # Capture main event loop

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

        context.user_data["pending_buy"] = {
            "platform": platform_value,
            "market_id": market_id,
            "outcome": outcome,
            "pin_protected": True,
            "verified_pin": pin,  # Store PIN for trade execution
        }

        info = PLATFORM_INFO[Platform(platform_value)]

        text = f"""
💰 <b>Buy {outcome.upper()} Position</b>

Platform: {info['name']}
Collateral: {info['collateral']}{swap_note}

Enter the amount in {info['collateral']} you want to spend:

<i>Example: 10 (for 10 {info['collateral']})</i>

Type /cancel to cancel.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{market_id}")],
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

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Send executing message (use chat.send_message since original may be deleted)
    executing_msg = await update.effective_chat.send_message(
        f"⏳ Executing order...\n\nBuying {outcome.upper()} with {amount_str} {platform_info['collateral']}",
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

        # Get market title from quote data or fetch market
        market_title = None
        if quote.quote_data and "market" in quote.quote_data:
            market_data = quote.quote_data["market"]
            market_title = market_data.get("title") or market_data.get("market_title") or market_data.get("question")
        if not market_title:
            market = await platform.get_market(market_id)
            if market:
                market_title = market.title

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

                # Create position record
                try:
                    market = await platform.get_market(market_id)
                    market_title = market.title if market else market_id

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

                text = f"""
✅ <b>Order Executed!</b>

Bought {outcome.upper()} position
Amount: {amount} {platform_info['collateral']}{fee_line}
Received: ~{actual_output:.2f} tokens

<a href="{result.explorer_url}">View Transaction</a>
"""
            else:
                # Order was placed in orderbook but not filled
                text = f"""
⏳ <b>Limit Order Placed</b>

Your {outcome.upper()} order has been placed in the orderbook.
Amount: {amount} {platform_info['collateral']}
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
            [InlineKeyboardButton("🔄 Retry", callback_data=f"buy_start:{platform_value}:{market_id}:{outcome}")],
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

            text = f"""
✅ <b>Sold Successfully!</b>

Sold {percent}% of {outcome_str} position
Tokens Sold: ~{sell_amount:.4f}
Received: ~{quote.expected_output:.2f} {platform_info['collateral']}{fee_line}

<a href="{result.explorer_url}">View Transaction</a>
"""
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

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 View Positions", callback_data="positions:0")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        ])

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

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless)
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

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless)
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

<b>🔷 EVM</b> (Polymarket + Opinion + Limitless)
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
        else:
            await update.message.reply_text("Nothing to cancel.")
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
