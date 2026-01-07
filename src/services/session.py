"""
Session management for conversation state.
Handles multi-step flows like trading and configuration.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional
from collections import defaultdict

from src.utils.logging import get_logger

logger = get_logger(__name__)


class SessionState(str, Enum):
    """Possible session states."""
    IDLE = "idle"
    AWAITING_AMOUNT = "awaiting_amount"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_SEARCH = "awaiting_search"
    AWAITING_EXPORT_CONFIRM = "awaiting_export_confirm"


@dataclass
class UserSession:
    """User session with conversation state."""
    telegram_id: int
    state: SessionState = SessionState.IDLE
    data: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(minutes=30))
    
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.utcnow() > self.expires_at
    
    def touch(self) -> None:
        """Update session timestamp and extend expiry."""
        self.updated_at = datetime.utcnow()
        self.expires_at = datetime.utcnow() + timedelta(minutes=30)
    
    def reset(self) -> None:
        """Reset session to idle state."""
        self.state = SessionState.IDLE
        self.data = {}
        self.touch()
    
    def set_state(self, state: SessionState, **kwargs) -> None:
        """Set session state with optional data."""
        self.state = state
        self.data.update(kwargs)
        self.touch()


class SessionManager:
    """
    Manages user sessions for conversation state.
    Thread-safe with automatic cleanup of expired sessions.
    """
    
    def __init__(self, cleanup_interval: int = 300):
        self._sessions: dict[int, UserSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the session manager with cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session manager started")
    
    async def stop(self) -> None:
        """Stop the session manager."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Session manager stopped")
    
    async def _cleanup_loop(self) -> None:
        """Periodically clean up expired sessions."""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Session cleanup error", error=str(e))
    
    async def _cleanup_expired(self) -> None:
        """Remove expired sessions."""
        async with self._lock:
            expired = [
                tid for tid, session in self._sessions.items()
                if session.is_expired()
            ]
            for tid in expired:
                del self._sessions[tid]
            
            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired sessions")
    
    async def get(self, telegram_id: int) -> UserSession:
        """Get or create a session for a user."""
        async with self._lock:
            if telegram_id not in self._sessions:
                self._sessions[telegram_id] = UserSession(telegram_id=telegram_id)
            
            session = self._sessions[telegram_id]
            
            # Reset if expired
            if session.is_expired():
                session.reset()
            
            return session
    
    async def set_state(
        self,
        telegram_id: int,
        state: SessionState,
        **kwargs,
    ) -> UserSession:
        """Set session state for a user."""
        session = await self.get(telegram_id)
        session.set_state(state, **kwargs)
        return session
    
    async def reset(self, telegram_id: int) -> None:
        """Reset a user's session."""
        session = await self.get(telegram_id)
        session.reset()
    
    async def get_state(self, telegram_id: int) -> SessionState:
        """Get current state for a user."""
        session = await self.get(telegram_id)
        return session.state
    
    async def get_data(self, telegram_id: int, key: str) -> Any:
        """Get session data value."""
        session = await self.get(telegram_id)
        return session.data.get(key)
    
    async def set_data(self, telegram_id: int, key: str, value: Any) -> None:
        """Set session data value."""
        session = await self.get(telegram_id)
        session.data[key] = value
        session.touch()


# Singleton instance
session_manager = SessionManager()


# ===================
# Trading Flow States
# ===================

@dataclass
class BuyFlowData:
    """Data for buy trading flow."""
    platform: str
    market_id: str
    outcome: str  # "yes" or "no"
    market_title: Optional[str] = None
    amount: Optional[str] = None
    quote: Optional[Any] = None


async def start_buy_flow(
    telegram_id: int,
    platform: str,
    market_id: str,
    outcome: str,
    market_title: Optional[str] = None,
) -> UserSession:
    """Start a buy trading flow."""
    return await session_manager.set_state(
        telegram_id,
        SessionState.AWAITING_AMOUNT,
        flow="buy",
        platform=platform,
        market_id=market_id,
        outcome=outcome,
        market_title=market_title,
    )


async def set_buy_amount(
    telegram_id: int,
    amount: str,
    quote: Any,
) -> UserSession:
    """Set amount and quote for confirmation."""
    session = await session_manager.get(telegram_id)
    session.data["amount"] = amount
    session.data["quote"] = quote
    session.state = SessionState.AWAITING_CONFIRMATION
    session.touch()
    return session


async def get_buy_flow_data(telegram_id: int) -> Optional[BuyFlowData]:
    """Get current buy flow data."""
    session = await session_manager.get(telegram_id)
    
    if session.data.get("flow") != "buy":
        return None
    
    return BuyFlowData(
        platform=session.data.get("platform", ""),
        market_id=session.data.get("market_id", ""),
        outcome=session.data.get("outcome", ""),
        market_title=session.data.get("market_title"),
        amount=session.data.get("amount"),
        quote=session.data.get("quote"),
    )


async def clear_flow(telegram_id: int) -> None:
    """Clear any active flow."""
    await session_manager.reset(telegram_id)
