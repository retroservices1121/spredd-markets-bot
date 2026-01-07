"""
Pytest configuration and fixtures.
"""

import pytest
import asyncio
from typing import Generator


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def encryption_key() -> str:
    """Provide a test encryption key."""
    from src.utils.encryption import generate_encryption_key
    return generate_encryption_key()


@pytest.fixture
def test_user_id() -> int:
    """Provide a test Telegram user ID."""
    return 123456789
