"""
Virtuals ACP (Agent Commerce Protocol) Integration.

This module enables Spredd Markets to act as a service provider
in the Virtuals AI agent ecosystem, allowing other AI agents to
request prediction market trading services.
"""

from src.services.acp.client import acp_service, SpreddACPService
from src.services.acp.schemas import (
    JobType,
    EXECUTE_TRADE_SCHEMA,
    GET_QUOTE_SCHEMA,
    SEARCH_MARKETS_SCHEMA,
    GET_PORTFOLIO_SCHEMA,
    BRIDGE_USDC_SCHEMA,
)

__all__ = [
    "acp_service",
    "SpreddACPService",
    "JobType",
    "EXECUTE_TRADE_SCHEMA",
    "GET_QUOTE_SCHEMA",
    "SEARCH_MARKETS_SCHEMA",
    "GET_PORTFOLIO_SCHEMA",
    "BRIDGE_USDC_SCHEMA",
]
