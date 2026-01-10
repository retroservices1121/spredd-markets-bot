"""
Telegram bot command handlers.
Handles all user interactions with platform selection and trading.
"""

from decimal import Decimal, InvalidOperation
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from src.config import settings
from src.db.database import (
    get_or_create_user,
    get_user_by_telegram_id,
    update_user_platform,
    get_user_positions,
    get_user_orders,
    get_or_create_referral_code,
    get_user_by_referral_code,
    set_user_referrer,
    get_referral_stats,
    get_fee_balance,
    process_withdrawal,
)
from src.db.models import Platform, ChainFamily, PositionStatus
from src.platforms import (
    platform_registry,
    get_platform,
    get_platform_info,
    get_chain_family_for_platform,
    PLATFORM_INFO,
)
from src.services.wallet import wallet_service, WalletInfo
from src.services.fee import format_usdc, can_withdraw, MIN_WITHDRAWAL_USDC, process_trade_fee, calculate_fee
from src.utils.logging import get_logger

logger = get_logger(__name__)


# ===================
# Helper Functions
# ===================

def escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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

    # Check for referral code in start parameter
    referral_code = None
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referral_code = arg[4:]  # Remove "ref_" prefix

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

    welcome_text = f"""
🎯 <b>Welcome to Spredd Markets!</b>
{referral_message}
Trade prediction markets across multiple platforms:

{platform_registry.format_platform_list()}

<b>Choose your platform to get started:</b>
"""

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML,
        reply_markup=platform_keyboard(),
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

<b>Account</b>
/balance - Check all balances
/referral - Referral hub & earn commissions
/export - Export private keys (use carefully!)
/settings - Trading preferences

<b>Help</b>
/faq - Frequently asked questions

<b>Platform Info</b>
• <b>Kalshi</b> (Solana)
• <b>Polymarket</b> (Polygon)
• <b>Opinion</b> (BNB Chain)

Need help? @spreddterminal
"""

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


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
        [InlineKeyboardButton("⚠️ Security warnings", callback_data="faq:security")],
        [InlineKeyboardButton("« Back", callback_data="menu:main")],
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
        context.user_data["pending_wallet_pin"] = {"confirm": False}

        text = """
🔐 <b>Create Secure Wallet</b>

To protect your funds, please set a 4-6 digit PIN.

<b>Important:</b>
• Your PIN is NEVER stored on our servers
• Only you can access your funds
• If you forget your PIN, your funds are LOST
• This makes your wallet truly non-custodial

<b>Enter your PIN (4-6 digits):</b>
"""
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # Has wallets - show them
    wallets_dict = {w.chain_family: WalletInfo(chain_family=w.chain_family, public_key=w.public_key) for w in existing_wallets}

    # Get balances
    balances = await wallet_service.get_all_balances(user.id)

    # Format wallet info
    solana_wallet = wallets_dict.get(ChainFamily.SOLANA)
    evm_wallet = wallets_dict.get(ChainFamily.EVM)

    # Check if PIN protected
    is_pin_protected = any(w.pin_protected for w in existing_wallets)

    text = "💰 <b>Your Wallets</b>"
    if is_pin_protected:
        text += " 🔐"
    text += "\n\n"

    # Solana wallet (for Kalshi)
    if solana_wallet:
        text += f"<b>🟣 Solana</b> (Kalshi)\n"
        text += f"<code>{solana_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.SOLANA, []):
            text += f"  • {bal.formatted}\n"
        text += "\n"

    # EVM wallet (for Polymarket & Opinion)
    if evm_wallet:
        text += f"<b>🔷 EVM</b> (Polymarket + Opinion)\n"
        text += f"<code>{evm_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.EVM, []):
            text += f"  • {bal.formatted} ({bal.chain.value})\n"

    text += "\n<i>Tap address to copy. Send funds to deposit.</i>"

    if is_pin_protected:
        text += "\n\n🔐 <i>PIN-protected: Only you can sign transactions</i>"
    else:
        text += "\n\n⚠️ <i>Wallet not PIN-protected. Create a new secure wallet to trade.</i>"

    # Buttons
    buttons = [
        [InlineKeyboardButton("🔄 Refresh Balances", callback_data="wallet:refresh")],
    ]

    if not is_pin_protected:
        buttons.append([InlineKeyboardButton("🔐 Create New Secure Wallet", callback_data="wallet:create_new")])

    buttons.append([InlineKeyboardButton("📤 Export Keys", callback_data="wallet:export")])

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


async def markets_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /markets command - show trending markets."""
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
    
    try:
        markets = await platform.get_trending_markets(limit=10)
        
        if not markets:
            await update.message.reply_text(
                f"No markets found on {platform_info['name']}. Try /search [query]",
                parse_mode=ParseMode.HTML,
            )
            return
        
        text = f"{platform_info['emoji']} <b>Trending on {platform_info['name']}</b>\n\n"
        
        buttons = []
        for i, market in enumerate(markets, 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            
            text += f"<b>{i}.</b> {title}\n"
            text += f"   YES: {yes_prob} • Vol: {format_usd(market.volume_24h)}\n\n"
            
            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:{user.active_platform.value}:{market.market_id[:20]}"
                )
            ])
        
        buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="markets:refresh")])
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        
    except Exception as e:
        logger.error("Failed to get markets", error=str(e))
        await update.message.reply_text(
            f"❌ Failed to load markets: {escape_html(str(e))}",
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
            
            text += f"<b>{i}.</b> {title}\n"
            text += f"   YES: {yes_prob}\n\n"
            
            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:{user.active_platform.value}:{market.market_id[:20]}"
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
            f"❌ Search failed: {escape_html(str(e))}",
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
    
    positions = await get_user_positions(
        user_id=user.id,
        platform=user.active_platform,
        status=PositionStatus.OPEN,
    )
    
    platform_info = PLATFORM_INFO[user.active_platform]
    
    if not positions:
        await update.message.reply_text(
            f"📊 <b>No Open Positions</b>\n\n"
            f"You don't have any open positions on {platform_info['name']}.\n\n"
            f"Use /markets or /search to find markets and trade!",
            parse_mode=ParseMode.HTML,
        )
        return
    
    text = f"📊 <b>Your {platform_info['name']} Positions</b>\n\n"
    
    for pos in positions:
        title = escape_html(pos.market_title[:40] + "..." if len(pos.market_title) > 40 else pos.market_title)
        outcome = pos.outcome.value.upper()
        entry = format_price(pos.entry_price)
        current = format_price(pos.current_price) if pos.current_price else "N/A"
        
        # Calculate P&L
        if pos.current_price and pos.entry_price:
            pnl_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
            pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
            pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
        else:
            pnl_str = "N/A"
            pnl_emoji = "⚪"
        
        text += f"<b>{title}</b>\n"
        text += f"  {outcome} • Entry: {entry} • Now: {current}\n"
        text += f"  {pnl_emoji} P&L: {pnl_str}\n\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /orders command - show order history."""
    if not update.effective_user or not update.message:
        return
    
    user = await get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first!")
        return
    
    orders = await get_user_orders(
        user_id=user.id,
        platform=user.active_platform,
        limit=10,
    )
    
    platform_info = PLATFORM_INFO[user.active_platform]
    
    if not orders:
        await update.message.reply_text(
            f"📋 <b>No Order History</b>\n\n"
            f"You haven't placed any orders on {platform_info['name']} yet.",
            parse_mode=ParseMode.HTML,
        )
        return
    
    text = f"📋 <b>Recent Orders on {platform_info['name']}</b>\n\n"
    
    status_emoji = {
        "confirmed": "✅",
        "pending": "⏳",
        "submitted": "📤",
        "failed": "❌",
        "cancelled": "🚫",
    }
    
    for order in orders:
        side = order.side.value.upper()
        outcome = order.outcome.value.upper()
        status = status_emoji.get(order.status.value, "❓")
        amount = format_usd(Decimal(order.input_amount) / Decimal(10**6))
        
        text += f"{status} {side} {outcome} • {amount}\n"
        if order.tx_hash:
            text += f"   <a href='{get_platform(user.active_platform).get_explorer_url(order.tx_hash)}'>View TX</a>\n"
        text += "\n"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
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

    # Get fee balance
    fee_balance = await get_fee_balance(user.id)

    # Format amounts
    claimable = format_usdc(fee_balance.claimable_usdc) if fee_balance else "$0.00"
    total_earned = format_usdc(fee_balance.total_earned_usdc) if fee_balance else "$0.00"

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
├ Claimable: <b>{claimable}</b> USDC
└ Total Earned: <b>{total_earned}</b> USDC

⚠️ <i>Minimum withdrawal: ${MIN_WITHDRAWAL_USDC} USDC</i>
"""

    # Build keyboard
    buttons = [
        [InlineKeyboardButton("📋 Copy Invite Link", callback_data="referral:copy")],
    ]

    # Add withdraw button if balance meets minimum
    if fee_balance and can_withdraw(fee_balance.claimable_usdc):
        buttons.append([InlineKeyboardButton("💸 Withdraw Earnings", callback_data="referral:withdraw")])

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
        if action == "platform":
            await handle_platform_select(query, parts[1], update.effective_user.id)
        
        elif action == "market":
            await handle_market_view(query, parts[1], parts[2], update.effective_user.id)
        
        elif action == "buy":
            await handle_buy_start(query, parts[1], parts[2], parts[3], update.effective_user.id, context)

        elif action == "confirm_buy":
            # Format: confirm_buy:platform:market_id:outcome:amount:pin (pin may be empty)
            user_pin = parts[5] if len(parts) > 5 else ""
            await handle_buy_confirm(query, parts[1], parts[2], parts[3], parts[4], update.effective_user.id, user_pin)

        elif action == "wallet":
            if parts[1] == "refresh":
                await handle_wallet_refresh(query, update.effective_user.id)
            elif parts[1] == "export":
                await handle_wallet_export(query, update.effective_user.id)
            elif parts[1] == "create_new":
                await handle_wallet_create_new(query, update.effective_user.id, context)
            elif parts[1] == "confirm_create":
                await handle_wallet_confirm_create(query, update.effective_user.id, context)

        elif action == "export":
            await handle_export_key(query, parts[1], update.effective_user.id, context)

        elif action == "markets":
            if parts[1] == "refresh":
                await handle_markets_refresh(query, update.effective_user.id)
        
        elif action == "menu":
            if parts[1] == "main":
                await handle_main_menu(query, update.effective_user.id)
            elif parts[1] == "platform":
                await handle_platform_menu(query, update.effective_user.id)

        elif action == "faq":
            await handle_faq_topic(query, parts[1])

        elif action == "referral":
            await handle_referral_action(query, parts[1], update.effective_user.id, context)

    except Exception as e:
        logger.error("Callback handler error", error=str(e), data=data)
        await query.edit_message_text(
            f"❌ Error: {escape_html(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_platform_select(query, platform_value: str, telegram_id: int) -> None:
    """Handle platform selection."""
    try:
        platform = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform selection.")
        return
    
    await update_user_platform(telegram_id, platform)
    
    info = PLATFORM_INFO[platform]
    chain_family = get_chain_family_for_platform(platform)
    
    # Get user and ensure wallet exists
    user = await get_user_by_telegram_id(telegram_id)
    if user:
        wallets = await wallet_service.get_or_create_wallets(user.id, telegram_id)
        wallet = wallets.get(chain_family)
        wallet_addr = wallet.public_key if wallet else "Not created"
    else:
        wallet_addr = "Not created"
    
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
    
    text = f"""
{info['emoji']} <b>{escape_html(market.title)}</b>

📊 <b>Current Prices</b>
YES: {format_probability(market.yes_price)} ({format_price(market.yes_price)})
NO: {format_probability(market.no_price)} ({format_price(market.no_price)})

📈 <b>Stats</b>
Volume (24h): {format_usd(market.volume_24h)}
Liquidity: {format_usd(market.liquidity)}
Status: {"🟢 Active" if market.is_active else "🔴 Closed"}
"""
    
    if market.description:
        text += f"\n📝 {escape_html(market.description[:200])}..."
    
    # Buy buttons
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
        [InlineKeyboardButton("« Back to Markets", callback_data="markets:refresh")],
    ])
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
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

    # Check if wallet is PIN protected
    user = await get_user_by_telegram_id(telegram_id)
    if user:
        is_pin_protected = await wallet_service.is_wallet_pin_protected(user.id, chain_family)
    else:
        is_pin_protected = False

    # Store buy context for message handler
    context.user_data["pending_buy"] = {
        "platform": platform_value,
        "market_id": market_id,
        "outcome": outcome,
        "pin_protected": is_pin_protected,
    }

    text = f"""
💰 <b>Buy {outcome.upper()} Position</b>

Platform: {info['name']}
Collateral: {info['collateral']}

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

    await query.edit_message_text("🔄 Refreshing balances...")

    # Get existing wallets from DB to check PIN status
    from src.db.database import get_user_wallets
    existing_wallets = await get_user_wallets(user.id)
    is_pin_protected = any(w.pin_protected for w in existing_wallets) if existing_wallets else False

    wallets = await wallet_service.get_or_create_wallets(user.id, telegram_id)
    balances = await wallet_service.get_all_balances(user.id)

    solana_wallet = wallets.get(ChainFamily.SOLANA)
    evm_wallet = wallets.get(ChainFamily.EVM)

    text = "💰 <b>Your Wallets</b>"
    if is_pin_protected:
        text += " 🔐"
    text += "\n\n"

    if solana_wallet:
        text += f"<b>🟣 Solana</b> (Kalshi)\n"
        text += f"<code>{solana_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.SOLANA, []):
            text += f"  • {bal.formatted}\n"
        text += "\n"

    if evm_wallet:
        text += f"<b>🔷 EVM</b> (Polymarket + Opinion)\n"
        text += f"<code>{evm_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.EVM, []):
            text += f"  • {bal.formatted} ({bal.chain.value})\n"

    if is_pin_protected:
        text += "\n🔐 <i>PIN-protected: Only you can sign transactions</i>"
    else:
        text += "\n⚠️ <i>Wallet not PIN-protected. Create a new secure wallet to trade.</i>"

    # Build buttons
    buttons = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="wallet:refresh")],
    ]

    if not is_pin_protected:
        buttons.append([InlineKeyboardButton("🔐 Create New Secure Wallet", callback_data="wallet:create_new")])

    buttons.append([InlineKeyboardButton("📤 Export Keys", callback_data="wallet:export")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])

    keyboard = InlineKeyboardMarkup(buttons)

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
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

    # Check if wallet exists and is PIN protected
    is_pin_protected = await wallet_service.is_wallet_pin_protected(user.id, chain_family)

    if is_pin_protected:
        # Store export request and ask for PIN
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
        # No PIN protection - export directly (shouldn't normally happen)
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
            await query.edit_message_text(f"❌ Export failed: {escape_html(str(e))}")


async def handle_markets_refresh(query, telegram_id: int) -> None:
    """Refresh markets list."""
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
    
    try:
        markets = await platform.get_trending_markets(limit=10)
        
        if not markets:
            await query.edit_message_text(
                f"No markets found on {platform_info['name']}.",
                parse_mode=ParseMode.HTML,
            )
            return
        
        text = f"{platform_info['emoji']} <b>Trending on {platform_info['name']}</b>\n\n"
        
        buttons = []
        for i, market in enumerate(markets, 1):
            title = escape_html(market.title[:50] + "..." if len(market.title) > 50 else market.title)
            yes_prob = format_probability(market.yes_price)
            
            text += f"<b>{i}.</b> {title}\n"
            text += f"   YES: {yes_prob} • Vol: {format_usd(market.volume_24h)}\n\n"
            
            buttons.append([
                InlineKeyboardButton(
                    f"{i}. {market.title[:30]}...",
                    callback_data=f"market:{user.active_platform.value}:{market.market_id[:20]}"
                )
            ])
        
        buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="markets:refresh")])
        buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error("Failed to refresh markets", error=str(e))
        await query.edit_message_text(
            f"❌ Failed to load markets: {escape_html(str(e))}",
            parse_mode=ParseMode.HTML,
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
                ("⚠️ Security warnings", "faq:security"),
            ],
        },
        "noncustodial": {
            "title": "🔐 Is this non-custodial?",
            "text": """<b>Yes, Spredd is non-custodial.</b>

Your private keys are encrypted with YOUR PIN, which is never stored on our servers.

<b>What this means:</b>
• We cannot access your funds
• We cannot sign transactions for you
• We cannot recover your wallet if you forget your PIN
• Even if our database is hacked, attackers cannot steal funds without your PIN

<b>How it works:</b>
Your wallet's private key is encrypted using:
<code>Key = MasterKey + TelegramID + YourPIN</code>

Without your PIN, decryption is mathematically impossible.

<b>You are fully in control of your funds.</b>""",
        },
        "pin": {
            "title": "🔑 Why do I need a PIN?",
            "text": """<b>Your PIN makes the bot non-custodial.</b>

Without a PIN, the bot operator could theoretically access your funds. With a PIN, only YOU can sign transactions.

<b>PIN requirements:</b>
• 4-6 digits
• Used to encrypt your private key
• Required for every trade
• Never stored anywhere

<b>Important:</b>
• Choose a PIN you'll remember
• Don't share it with anyone
• If you forget it, your funds are LOST
• There is NO recovery option

<b>This is the same security model used by hardware wallets like Ledger and Trezor.</b>""",
        },
        "fees": {
            "title": "💰 What are the fees?",
            "text": """<b>Fee Structure:</b>

<b>Spredd Bot Fees:</b>
• <b>1% transaction fee</b> on all trades
• No deposit/withdrawal fees
• Fee supports referral program rewards

<b>Referral Rewards (from our 1% fee):</b>
• Tier 1 referrers earn 25% of fee
• Tier 2 referrers earn 5% of fee
• Tier 3 referrers earn 3% of fee

<b>Platform Fees (charged by markets):</b>
• <b>Kalshi:</b> ~2% on winnings
• <b>Polymarket:</b> ~2% trading fee
• <b>Opinion Labs:</b> Varies by market

<b>Network Fees (blockchain gas):</b>
• <b>Solana:</b> ~$0.001 per transaction
• <b>Polygon:</b> ~$0.01 per transaction
• <b>BSC:</b> ~$0.10 per transaction

<b>Note:</b> You need native tokens (SOL, MATIC, BNB) in your wallet to pay gas fees.""",
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

<b>Important:</b>
• Double-check the network before sending
• Your EVM address works on both Polygon and BSC
• Start with small amounts to test""",
        },
        "security": {
            "title": "⚠️ Security Warnings",
            "text": """<b>Keep Your Funds Safe:</b>

🔴 <b>NEVER share your PIN</b>
Anyone with your PIN can access your funds

🔴 <b>NEVER share your private keys</b>
Use /export only for backup purposes

🔴 <b>Remember your PIN</b>
Lost PIN = Lost funds (no recovery)

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


async def handle_referral_action(query, action: str, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        await handle_referral_withdraw(query, telegram_id, context)


async def handle_referral_hub(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the referral hub (refresh)."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get or create referral code
    referral_code = await get_or_create_referral_code(user.id)

    # Get referral stats
    stats = await get_referral_stats(user.id)

    # Get fee balance
    fee_balance = await get_fee_balance(user.id)

    # Format amounts
    claimable = format_usdc(fee_balance.claimable_usdc) if fee_balance else "$0.00"
    total_earned = format_usdc(fee_balance.total_earned_usdc) if fee_balance else "$0.00"

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
├ Claimable: <b>{claimable}</b> USDC
└ Total Earned: <b>{total_earned}</b> USDC

⚠️ <i>Minimum withdrawal: ${MIN_WITHDRAWAL_USDC} USDC</i>
"""

    # Build keyboard
    buttons = [
        [InlineKeyboardButton("📋 Copy Invite Link", callback_data="referral:copy")],
    ]

    # Add withdraw button if balance meets minimum
    if fee_balance and can_withdraw(fee_balance.claimable_usdc):
        buttons.append([InlineKeyboardButton("💸 Withdraw Earnings", callback_data="referral:withdraw")])

    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="referral:refresh")])
    buttons.append([InlineKeyboardButton("« Back", callback_data="menu:main")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_referral_withdraw(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle withdrawal of referral earnings."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return

    # Get fee balance
    fee_balance = await get_fee_balance(user.id)
    if not fee_balance or not can_withdraw(fee_balance.claimable_usdc):
        await query.edit_message_text(
            f"❌ <b>Cannot Withdraw</b>\n\n"
            f"Minimum withdrawal is ${MIN_WITHDRAWAL_USDC} USDC.\n"
            f"Your balance: {format_usdc(fee_balance.claimable_usdc) if fee_balance else '$0.00'}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("« Back to Referrals", callback_data="referral:refresh")],
            ]),
        )
        return

    # Show withdrawal confirmation
    claimable = format_usdc(fee_balance.claimable_usdc)

    # Store pending withdrawal state
    context.user_data["pending_withdrawal"] = {
        "amount": fee_balance.claimable_usdc,
    }

    text = f"""
💸 <b>Withdraw Referral Earnings</b>

Amount: <b>{claimable}</b> USDC

Withdrawals are sent to your EVM wallet (Polygon USDC).

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

async def handle_buy_confirm(query, platform_value: str, market_id: str, outcome: str, amount_str: str, telegram_id: int, user_pin: str = "") -> None:
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
        # Get wallet
        wallets = await wallet_service.get_or_create_wallets(user.id, telegram_id)
        wallet = wallets.get(chain_family)

        if not wallet:
            await query.edit_message_text("❌ Wallet not found. Please try again.")
            return

        # Get fresh quote
        from src.db.models import Outcome as OutcomeEnum
        outcome_enum = OutcomeEnum.YES if outcome == "yes" else OutcomeEnum.NO

        quote = await platform.get_quote(
            market_id=market_id,
            outcome=outcome_enum,
            side="buy",
            amount=amount,
        )

        # Get private key (with PIN if provided)
        try:
            private_key = await wallet_service.get_private_key(user.id, telegram_id, chain_family, user_pin)
        except Exception as decrypt_error:
            if "Decryption failed" in str(decrypt_error):
                await query.edit_message_text(
                    "❌ <b>Invalid PIN</b>\n\nThe PIN you entered is incorrect. Please try again.",
                    parse_mode=ParseMode.HTML,
                )
                return
            raise

        # Execute trade
        result = await platform.execute_trade(quote, private_key)

        if result.success:
            # Process trading fee and distribute to referrers
            order_id = result.tx_hash or f"order_{telegram_id}_{market_id}"
            fee_result = await process_trade_fee(
                trader_telegram_id=telegram_id,
                order_id=order_id,
                trade_amount_usdc=str(amount),
            )

            fee_amount = fee_result.get("fee", "0")
            fee_display = format_usdc(fee_amount) if Decimal(fee_amount) > 0 else ""
            fee_line = f"\n💸 Fee: {fee_display}" if fee_display else ""

            text = f"""
✅ <b>Order Executed!</b>

Bought {outcome.upper()} position
Amount: {amount} {platform_info['collateral']}{fee_line}
Received: ~{quote.expected_output:.2f} tokens

<a href="{result.explorer_url}">View Transaction</a>
"""
        else:
            text = f"""
❌ <b>Order Failed</b>

{escape_html(result.error_message or 'Unknown error')}

Please check your wallet balance and try again.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Back to Markets", callback_data="markets:refresh")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        ])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error("Trade execution failed", error=str(e))
        await query.edit_message_text(
            f"❌ Trade failed: {escape_html(str(e))}",
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
    is_pin_protected = pending.get("pin_protected", False)

    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await update.message.reply_text("Invalid platform.")
        del context.user_data["pending_buy"]
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
            del context.user_data["pending_buy"]
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

        # If PIN protected, ask for PIN before confirming
        if is_pin_protected:
            # Store quote info for PIN confirmation
            context.user_data["pending_buy"]["amount"] = str(amount)
            context.user_data["pending_buy"]["awaiting_pin"] = True

            text = f"""
📋 <b>Order Quote</b>

Market: {escape_html(market.title[:50])}...
Side: BUY {outcome.upper()}

💰 <b>You Pay:</b> {amount} {platform_info['collateral']}
💸 <b>Fee (1%):</b> {fee_display}
📦 <b>You Receive:</b> ~{expected_tokens:.2f} {outcome.upper()} tokens
📊 <b>Price:</b> {format_probability(price)} per token

🔐 <b>Enter your PIN to confirm:</b>
<i>(Your PIN is never stored and only you know it)</i>

Type /cancel to cancel.
"""
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        else:
            # No PIN - show confirm button
            del context.user_data["pending_buy"]

            text = f"""
📋 <b>Order Quote</b>

Market: {escape_html(market.title[:50])}...
Side: BUY {outcome.upper()}

💰 <b>You Pay:</b> {amount} {platform_info['collateral']}
💸 <b>Fee (1%):</b> {fee_display}
📦 <b>You Receive:</b> ~{expected_tokens:.2f} {outcome.upper()} tokens
📊 <b>Price:</b> {format_probability(price)} per token

<i>⚠️ This is a quote. Actual execution may vary slightly.</i>
"""

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm Order", callback_data=f"confirm_buy:{platform_value}:{market_id}:{outcome}:{amount}:")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"market:{platform_value}:{market_id}")],
            ])

            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

    except Exception as e:
        logger.error("Quote failed", error=str(e))
        del context.user_data["pending_buy"]
        await update.message.reply_text(
            f"❌ Failed to get quote: {escape_html(str(e))}",
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
        del context.user_data["pending_buy"]
        return

    platform_value = pending["platform"]
    market_id = pending["market_id"]
    outcome = pending["outcome"]
    amount_str = pending["amount"]

    # Clear pending state
    del context.user_data["pending_buy"]

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

        # Execute trade
        result = await platform.execute_trade(quote, private_key)

        if result.success:
            # Process trading fee and distribute to referrers
            order_id = result.tx_hash or f"order_{update.effective_user.id}_{market_id}"
            fee_result = await process_trade_fee(
                trader_telegram_id=update.effective_user.id,
                order_id=order_id,
                trade_amount_usdc=str(amount),
            )

            fee_amount = fee_result.get("fee", "0")
            fee_display = format_usdc(fee_amount) if Decimal(fee_amount) > 0 else ""
            fee_line = f"\n💸 Fee: {fee_display}" if fee_display else ""

            text = f"""
✅ <b>Order Executed!</b>

Bought {outcome.upper()} position
Amount: {amount} {platform_info['collateral']}{fee_line}
Received: ~{quote.expected_output:.2f} tokens

<a href="{result.explorer_url}">View Transaction</a>
"""
        else:
            text = f"""
❌ <b>Order Failed</b>

{escape_html(result.error_message or 'Unknown error')}

Please check your wallet balance and try again.
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 Back to Markets", callback_data="markets:refresh")],
            [InlineKeyboardButton("💰 View Wallet", callback_data="wallet:refresh")],
        ])

        await executing_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )

    except Exception as e:
        logger.error("Trade with PIN failed", error=str(e))
        await executing_msg.edit_text(
            f"❌ Trade failed: {escape_html(str(e))}",
            parse_mode=ParseMode.HTML,
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

<b>🔷 EVM</b> (Polymarket + Opinion)
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
                f"❌ Failed to create wallets: {escape_html(str(e))}",
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
    """Export private key with user's PIN."""
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
        "🔐 Decrypting private key...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get private key with PIN (export returns string, not account object)
        try:
            private_key = await wallet_service.export_private_key(user.id, update.effective_user.id, chain_family, pin)
        except Exception as decrypt_error:
            if "Decryption failed" in str(decrypt_error):
                await status_msg.edit_text(
                    "❌ <b>Invalid PIN</b>\n\nThe PIN you entered is incorrect.",
                    parse_mode=ParseMode.HTML,
                )
                return
            raise

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
            f"❌ Export failed: {escape_html(str(e))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_withdrawal_with_pin(update: Update, context: ContextTypes.DEFAULT_TYPE, pin: str) -> None:
    """Process withdrawal with user's PIN."""
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

    # Clear pending state
    del context.user_data["pending_withdrawal"]

    # Delete the PIN message for security
    try:
        await update.message.delete()
    except:
        pass

    # Send processing message
    status_msg = await update.effective_chat.send_message(
        "⏳ Processing withdrawal...",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Verify PIN by trying to get private key
        chain_family = ChainFamily.EVM
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

        # Process the withdrawal in database
        withdrawal = await process_withdrawal(
            user_id=user.id,
            amount_usdc=amount,
            withdrawal_address=None,  # Will be set when actual transfer happens
            tx_hash=None,  # Will be set when actual transfer happens
        )

        if withdrawal:
            claimable_formatted = format_usdc(amount)
            text = f"""
✅ <b>Withdrawal Processed!</b>

Amount: <b>{claimable_formatted}</b> USDC

Your referral earnings have been marked for withdrawal.

<i>Note: Actual USDC transfer to your wallet will be processed shortly.</i>
"""
        else:
            text = "❌ <b>Withdrawal Failed</b>\n\nUnable to process withdrawal. Please try again."

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back to Referrals", callback_data="referral:refresh")],
        ])

        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.error("Withdrawal failed", error=str(e))
        await status_msg.edit_text(
            f"❌ Withdrawal failed: {escape_html(str(e))}",
            parse_mode=ParseMode.HTML,
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
            del context.user_data["pending_buy"]
            await update.message.reply_text("Order cancelled.")
        elif "pending_wallet_pin" in context.user_data:
            del context.user_data["pending_wallet_pin"]
            await update.message.reply_text("Wallet creation cancelled.")
        elif "pending_withdrawal" in context.user_data:
            del context.user_data["pending_withdrawal"]
            await update.message.reply_text("Withdrawal cancelled.")
        elif "pending_export" in context.user_data:
            del context.user_data["pending_export"]
            await update.message.reply_text("Export cancelled.")
        else:
            await update.message.reply_text("Nothing to cancel.")
        return

    # Check if user is setting up a new wallet with PIN
    if "pending_wallet_pin" in context.user_data and not text.startswith("/"):
        await handle_wallet_pin_setup(update, context, text)
        return

    # Check if user has a pending export
    if "pending_export" in context.user_data and not text.startswith("/"):
        await handle_export_with_pin(update, context, text)
        return

    # Check if user has a pending withdrawal
    if "pending_withdrawal" in context.user_data and not text.startswith("/"):
        await handle_withdrawal_with_pin(update, context, text)
        return

    # Check if user has a pending buy order
    if "pending_buy" in context.user_data and not text.startswith("/"):
        pending = context.user_data["pending_buy"]

        # If awaiting PIN, process PIN input
        if pending.get("awaiting_pin"):
            await handle_buy_with_pin(update, context, text)
            return

        # Otherwise, process amount input
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
                
                response += f"<b>{i}.</b> {title}\n   YES: {yes_prob}\n\n"
                
                buttons.append([
                    InlineKeyboardButton(
                        f"{i}. View Market",
                        callback_data=f"market:{user.active_platform.value}:{market.market_id[:20]}"
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
                f"❌ Search failed: {escape_html(str(e))}",
                parse_mode=ParseMode.HTML,
            )
