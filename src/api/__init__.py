"""
REST API module for Spredd Mini App.
Provides endpoints for the Telegram Mini App frontend.
"""

from .routes import router, create_api_app

__all__ = ["router", "create_api_app"]
