"""
Spredd Markets Bot - Multi-platform prediction market trading on Telegram.

Supports:
- Kalshi (Solana) via DFlow API
- Polymarket (Polygon) via CLOB API
- Opinion Labs (BSC) via CLOB SDK
"""

import asyncio
import signal
import sys
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from src.config import settings
from src.db.database import init_db, create_tables, close_db
from src.platforms import platform_registry
from src.services.wallet import wallet_service
from src.handlers.commands import (
    start_command,
    help_command,
    faq_command,
    platform_command,
    wallet_command,
    balance_command,
    markets_command,
    search_command,
    positions_command,
    orders_command,
    referral_command,
    callback_handler,
    message_handler,
)
from src.utils.logging import setup_logging, get_logger

logger = get_logger(__name__)

# Global application reference for shutdown
app: Optional[Application] = None


async def post_init(application: Application) -> None:
    """Called after bot starts - services already initialized in run_bot."""
    logger.info("Bot application initialized")


async def post_shutdown(application: Application) -> None:
    """Cleanup on shutdown."""
    logger.info("Shutting down services...")
    
    # Close platforms
    await platform_registry.close()
    
    # Close wallet service
    await wallet_service.close()
    
    # Close database
    await close_db()
    
    logger.info("Shutdown complete")


async def error_handler(update: object, context) -> None:
    """Handle errors in the bot."""
    logger.error(
        "Exception while handling update",
        error=str(context.error),
        update=str(update)[:100] if update else None,
    )
    
    # Notify user if possible
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An error occurred. Please try again or use /help."
            )
        except Exception:
            pass


def setup_handlers(application: Application) -> None:
    """Register all command and callback handlers."""

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("faq", faq_command))
    application.add_handler(CommandHandler("platform", platform_command))
    application.add_handler(CommandHandler("wallet", wallet_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("markets", markets_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("positions", positions_command))
    application.add_handler(CommandHandler("orders", orders_command))
    application.add_handler(CommandHandler("referral", referral_command))

    # Callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Message handler for search queries and trading input
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )
    
    # Error handler
    application.add_error_handler(error_handler)


def create_application() -> Application:
    """Create and configure the Telegram application."""
    
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    setup_handlers(application)
    
    return application


async def run_bot() -> None:
    """Run the bot with graceful shutdown support."""
    global app

    logger.info("Starting Spredd Markets Bot...")

    # Initialize services before starting the bot
    logger.info("Initializing database...")
    await init_db(settings.database_url)
    await create_tables()
    logger.info("Database ready")

    logger.info("Initializing wallet service...")
    await wallet_service.initialize()

    logger.info("Initializing platforms...")
    await platform_registry.initialize()

    app = create_application()

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        if app:
            asyncio.create_task(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            signal.signal(sig, lambda s, f: signal_handler())

    # Run the bot
    async with app:
        await app.start()

        # Set up menu button with commands
        from telegram import BotCommand
        commands = [
            BotCommand("start", "Welcome & get started"),
            BotCommand("markets", "Browse trending markets"),
            BotCommand("search", "Search for markets"),
            BotCommand("wallet", "View your wallets & balances"),
            BotCommand("positions", "View open positions"),
            BotCommand("orders", "View order history"),
            BotCommand("referral", "Referral hub & earnings"),
            BotCommand("platform", "Switch trading platform"),
            BotCommand("faq", "Frequently asked questions"),
            BotCommand("help", "Get help & commands"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Bot menu commands set")

        logger.info("Bot started! Press Ctrl+C to stop.")

        # Start polling
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )

        # Wait until stopped
        await asyncio.Event().wait()


def main() -> None:
    """Main entry point."""
    # Setup logging
    setup_logging(settings.log_level)
    
    logger.info(
        "Spredd Markets Bot",
        version="1.0.0",
        log_level=settings.log_level,
    )
    
    # Run the bot
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error("Fatal error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
