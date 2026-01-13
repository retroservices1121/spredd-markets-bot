"""
Run both the Telegram Bot and Mini App API simultaneously.

This script starts both services in parallel:
- Telegram Bot (polling or webhook mode)
- FastAPI server for Mini App

Usage:
    python run_all.py
"""

import asyncio
import os
import sys
import signal

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def run_bot():
    """Run the Telegram bot."""
    from src.main import main as bot_main
    await bot_main()


async def run_api():
    """Run the API server."""
    import uvicorn
    from src.api import create_api_app
    from src.db.database import init_db

    await init_db()

    app = create_api_app()
    # Railway uses PORT, fallback to API_PORT or 8000
    port = int(os.environ.get("PORT", os.environ.get("API_PORT", 8000)))
    host = os.environ.get("API_HOST", "0.0.0.0")

    print(f"Starting API server on {host}:{port}")

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Run both bot and API concurrently."""
    print("=" * 50)
    print("Starting Spredd Markets")
    print("  - Telegram Bot")
    print("  - Mini App API")
    print("=" * 50)

    # Create tasks for both services
    bot_task = asyncio.create_task(run_bot())
    api_task = asyncio.create_task(run_api())

    # Wait for both (they run forever until cancelled)
    try:
        await asyncio.gather(bot_task, api_task)
    except asyncio.CancelledError:
        print("\nShutting down...")
        bot_task.cancel()
        api_task.cancel()


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    print("\nReceived shutdown signal...")
    sys.exit(0)


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the main async function
    asyncio.run(main())
