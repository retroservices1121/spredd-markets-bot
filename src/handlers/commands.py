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
    
    user = await get_or_create_user(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
        last_name=update.effective_user.last_name,
    )
    
    welcome_text = f"""
🎯 <b>Welcome to Spredd Markets!</b>

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
/export - Export private keys (use carefully!)
/settings - Trading preferences

<b>Platform Info</b>
• <b>Kalshi</b> - CFTC regulated, US legal (Solana)
• <b>Polymarket</b> - Largest market (Polygon)
• <b>Opinion</b> - AI oracles (BNB Chain)

Need help? @spreddterminal
"""
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


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
    
    # Get or create wallets
    wallets = await wallet_service.get_or_create_wallets(
        user_id=user.id,
        telegram_id=update.effective_user.id,
    )
    
    # Get balances
    balances = await wallet_service.get_all_balances(user.id)
    
    # Format wallet info
    solana_wallet = wallets.get(ChainFamily.SOLANA)
    evm_wallet = wallets.get(ChainFamily.EVM)
    
    text = "💰 <b>Your Wallets</b>\n\n"
    
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
    
    # Buttons
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Balances", callback_data="wallet:refresh")],
        [InlineKeyboardButton("📤 Export Keys", callback_data="wallet:export")],
    ])
    
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
            await handle_buy_start(query, parts[1], parts[2], parts[3], update.effective_user.id)
        
        elif action == "wallet":
            if parts[1] == "refresh":
                await handle_wallet_refresh(query, update.effective_user.id)
            elif parts[1] == "export":
                await handle_wallet_export(query, update.effective_user.id)
        
        elif action == "markets":
            if parts[1] == "refresh":
                await handle_markets_refresh(query, update.effective_user.id)
        
        elif action == "menu":
            if parts[1] == "main":
                await handle_main_menu(query, update.effective_user.id)
            elif parts[1] == "platform":
                await handle_platform_menu(query, update.effective_user.id)
        
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


async def handle_buy_start(query, platform_value: str, market_id: str, outcome: str, telegram_id: int) -> None:
    """Handle starting a buy order."""
    try:
        platform_enum = Platform(platform_value)
    except ValueError:
        await query.edit_message_text("Invalid platform.")
        return
    
    info = PLATFORM_INFO[platform_enum]
    
    # Store context for next message
    context_data = {
        "action": "buy",
        "platform": platform_value,
        "market_id": market_id,
        "outcome": outcome,
    }
    
    # We'll need to handle this in message handler
    text = f"""
💰 <b>Buy {outcome.upper()} Position</b>

Platform: {info['name']}
Collateral: {info['collateral']}

Enter the amount in {info['collateral']} you want to spend:

<i>Example: 10 (for 10 {info['collateral']})</i>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data=f"market:{platform_value}:{market_id}")],
    ])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

    # Note: In a full implementation, we'd store context and handle the amount input
    # in the message handler. For now, this shows the flow.


async def handle_wallet_refresh(query, telegram_id: int) -> None:
    """Refresh wallet balances."""
    user = await get_user_by_telegram_id(telegram_id)
    if not user:
        await query.edit_message_text("Please /start first!")
        return
    
    await query.edit_message_text("🔄 Refreshing balances...")
    
    wallets = await wallet_service.get_or_create_wallets(user.id, telegram_id)
    balances = await wallet_service.get_all_balances(user.id)
    
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
        text += f"<b>🔷 EVM</b> (Polymarket + Opinion)\n"
        text += f"<code>{evm_wallet.public_key}</code>\n"
        for bal in balances.get(ChainFamily.EVM, []):
            text += f"  • {bal.formatted} ({bal.chain.value})\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="wallet:refresh")],
        [InlineKeyboardButton("📤 Export Keys", callback_data="wallet:export")],
        [InlineKeyboardButton("« Back", callback_data="menu:main")],
    ])

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
    ])
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


# ===================
# Message Handler
# ===================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages (for search and trading input)."""
    if not update.effective_user or not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    
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
