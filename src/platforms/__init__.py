"""
Platform registry for managing multiple prediction market platforms.
Routes operations to the correct platform based on user selection.
"""

from typing import Optional

from src.db.models import Platform, ChainFamily
from src.platforms.base import BasePlatform
from src.platforms.kalshi import kalshi_platform, KalshiPlatform
from src.platforms.polymarket import polymarket_platform, PolymarketPlatform
from src.platforms.opinion import opinion_platform, OpinionPlatform
from src.platforms.limitless import limitless_platform, LimitlessPlatform
from src.platforms.myriad import myriad_platform, MyriadPlatform
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Platform metadata for display
PLATFORM_INFO = {
    Platform.KALSHI: {
        "name": "Kalshi",
        "emoji": "🇺🇸",
        "chain": "Solana",
        "chain_family": ChainFamily.SOLANA,
        "description": "CFTC-regulated prediction markets",
        "collateral": "USDC",
        "features": ["Regulated", "US Legal", "Sports", "Politics", "Economics"],
    },
    Platform.POLYMARKET: {
        "name": "Polymarket",
        "emoji": "🔮",
        "chain": "Polygon",
        "chain_family": ChainFamily.EVM,
        "description": "World's largest prediction market",
        "collateral": "USDC",
        "features": ["High Liquidity", "Wide Coverage", "Politics", "Crypto", "Sports"],
    },
    Platform.OPINION: {
        "name": "Opinion Labs",
        "emoji": "🤖",
        "chain": "BNB Chain",
        "chain_family": ChainFamily.EVM,
        "description": "AI-oracle powered prediction markets",
        "collateral": "USDT",
        "features": ["AI Oracles", "BSC Native", "Macro", "Economic Data"],
    },
    Platform.LIMITLESS: {
        "name": "Limitless",
        "emoji": "♾️",
        "chain": "Base",
        "chain_family": ChainFamily.EVM,
        "description": "Fast prediction market on Base",
        "collateral": "USDC",
        "features": ["Base L2", "Low Fees", "Fast Settlement", "Politics", "Crypto"],
    },
    Platform.MYRIAD: {
        "name": "Myriad",
        "emoji": "🌀",
        "chain": "Abstract",
        "chain_family": ChainFamily.EVM,
        "description": "Multi-chain prediction markets",
        "collateral": "USDC.e",
        "features": ["Multi-chain", "Abstract", "Linea", "BNB Chain", "Sports", "Crypto"],
    },
}


class PlatformRegistry:
    """Registry for all prediction market platforms."""
    
    def __init__(self):
        self._platforms: dict[Platform, BasePlatform] = {
            Platform.KALSHI: kalshi_platform,
            Platform.POLYMARKET: polymarket_platform,
            Platform.OPINION: opinion_platform,
            Platform.LIMITLESS: limitless_platform,
            Platform.MYRIAD: myriad_platform,
        }
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize all platforms."""
        for platform_id, platform in self._platforms.items():
            try:
                await platform.initialize()
                logger.info(f"Initialized platform: {platform_id.value}")
            except Exception as e:
                logger.error(f"Failed to initialize {platform_id.value}", error=str(e))
        
        self._initialized = True
    
    async def close(self) -> None:
        """Close all platform connections."""
        for platform in self._platforms.values():
            try:
                await platform.close()
            except Exception as e:
                logger.error("Failed to close platform", error=str(e))
        
        self._initialized = False
    
    def get(self, platform: Platform) -> BasePlatform:
        """Get a platform by ID."""
        if platform not in self._platforms:
            raise ValueError(f"Unknown platform: {platform}")
        return self._platforms[platform]
    
    def get_info(self, platform: Platform) -> dict:
        """Get platform metadata."""
        return PLATFORM_INFO.get(platform, {})
    
    def get_chain_family(self, platform: Platform) -> ChainFamily:
        """Get the chain family for a platform."""
        info = self.get_info(platform)
        return info.get("chain_family", ChainFamily.EVM)
    
    @property
    def all_platforms(self) -> list[Platform]:
        """Get list of all platform IDs."""
        return list(self._platforms.keys())
    
    def format_platform_list(self) -> str:
        """Format platform list for display."""
        lines = []
        for platform_id in self.all_platforms:
            info = PLATFORM_INFO[platform_id]
            lines.append(
                f"{info['emoji']} <b>{info['name']}</b> ({info['chain']})\n"
                f"   └ {info['description']}"
            )
        return "\n\n".join(lines)
    
    def format_platform_selector(self) -> list[tuple[str, str]]:
        """Format platforms for inline keyboard."""
        buttons = []
        for platform_id in self.all_platforms:
            info = PLATFORM_INFO[platform_id]
            label = f"{info['emoji']} {info['name']} ({info['chain']})"
            callback = f"platform:{platform_id.value}"
            buttons.append((label, callback))
        return buttons


# Singleton instance
platform_registry = PlatformRegistry()


def get_platform(platform: Platform) -> BasePlatform:
    """Convenience function to get a platform."""
    return platform_registry.get(platform)


def get_platform_info(platform: Platform) -> dict:
    """Convenience function to get platform info."""
    return platform_registry.get_info(platform)


def get_chain_family_for_platform(platform: Platform) -> ChainFamily:
    """Get the chain family needed for a platform."""
    return platform_registry.get_chain_family(platform)
