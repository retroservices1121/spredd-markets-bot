"""
Run the Spredd Mini App API server.

This runs independently from the Telegram bot.
You can run both simultaneously:
  - Bot: python -m src.main
  - API: python run_api.py

Or use the combined runner (see run_all.py)
"""

import asyncio
import os
import sys

import uvicorn

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.api import create_api_app
from src.db.database import init_db


async def startup():
    """Initialize database on startup."""
    await init_db()


def main():
    """Run the API server."""
    app = create_api_app()

    # Add startup event
    @app.on_event("startup")
    async def on_startup():
        await startup()

    # Get port from environment or default
    port = int(os.environ.get("API_PORT", 8000))
    host = os.environ.get("API_HOST", "0.0.0.0")

    print(f"Starting Spredd Mini App API on {host}:{port}")
    print(f"API docs available at http://{host}:{port}/docs")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
