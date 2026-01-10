"""
Configuration management using Pydantic Settings.
All environment variables are validated at startup.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # ===================
    # Telegram Configuration
    # ===================
    telegram_bot_token: str = Field(..., description="Telegram bot token from @BotFather")
    admin_telegram_ids: str = Field(default="", description="Comma-separated admin Telegram IDs")
    
    # ===================
    # Database Configuration
    # ===================
    database_url: str = Field(..., description="PostgreSQL connection string")
    
    # ===================
    # Security Configuration
    # ===================
    encryption_key: str = Field(..., min_length=64, max_length=64, description="64-char hex key for wallet encryption")
    
    # ===================
    # Solana Configuration (for Kalshi/DFlow)
    # ===================
    solana_rpc_url: str = Field(
        default="https://api.mainnet-beta.solana.com",
        description="Solana RPC endpoint"
    )
    solana_ws_url: str = Field(
        default="wss://api.mainnet-beta.solana.com",
        description="Solana WebSocket endpoint"
    )
    
    # ===================
    # EVM Configuration (shared for Polygon & BSC)
    # ===================
    polygon_rpc_url: str = Field(
        default="https://polygon-rpc.com",
        description="Polygon RPC endpoint"
    )
    bsc_rpc_url: str = Field(
        default="https://bsc-dataseed.binance.org",
        description="BSC RPC endpoint"
    )
    
    # ===================
    # Kalshi / DFlow Configuration
    # ===================
    dflow_api_key: Optional[str] = Field(default=None, description="DFlow API key")
    dflow_api_base_url: str = Field(
        default="https://c.quote-api.dflow.net",
        description="DFlow trading API base URL"
    )
    dflow_metadata_url: str = Field(
        default="https://c.prediction-markets-api.dflow.net",
        description="DFlow metadata API URL"
    )
    kalshi_fee_account: Optional[str] = Field(
        default=None,
        description="Solana wallet address to receive platform fees (must be valid Solana address)"
    )
    kalshi_fee_bps: int = Field(
        default=100,
        description="Platform fee in basis points (100 = 1%)"
    )

    # ===================
    # Treasury Configuration (for referral withdrawals)
    # ===================
    # EVM Treasury (Polygon USDC)
    treasury_evm_private_key: Optional[str] = Field(
        default=None,
        description="Private key for EVM treasury wallet (hex format, for referral payouts on Polygon)"
    )
    treasury_evm_rpc_url: str = Field(
        default="https://polygon-rpc.com",
        description="RPC URL for EVM treasury transactions (Polygon)"
    )
    usdc_contract_polygon: str = Field(
        default="0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        description="USDC contract address on Polygon"
    )

    # Solana Treasury (Solana USDC)
    treasury_solana_private_key: Optional[str] = Field(
        default=None,
        description="Private key for Solana treasury wallet (base58 format, for referral payouts on Solana)"
    )
    treasury_solana_rpc_url: str = Field(
        default="https://api.mainnet-beta.solana.com",
        description="RPC URL for Solana treasury transactions"
    )
    usdc_mint_solana: str = Field(
        default="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        description="USDC mint address on Solana"
    )

    # Legacy alias for backwards compatibility
    @property
    def treasury_private_key(self) -> Optional[str]:
        """Legacy alias for EVM treasury key."""
        return self.treasury_evm_private_key

    @property
    def treasury_rpc_url(self) -> str:
        """Legacy alias for EVM treasury RPC."""
        return self.treasury_evm_rpc_url

    # ===================
    # Polymarket Configuration
    # ===================
    polymarket_api_url: str = Field(
        default="https://clob.polymarket.com",
        description="Polymarket CLOB API URL"
    )
    polymarket_builder_key: Optional[str] = Field(default=None, description="Polymarket builder API key")
    polymarket_builder_secret: Optional[str] = Field(default=None, description="Polymarket builder secret")
    polymarket_builder_passphrase: Optional[str] = Field(default=None, description="Polymarket builder passphrase")
    
    # ===================
    # Opinion Labs Configuration
    # ===================
    opinion_api_url: str = Field(
        default="https://proxy.opinion.trade:8443",
        description="Opinion Labs API URL"
    )
    opinion_api_key: Optional[str] = Field(default=None, description="Opinion Labs API key")
    opinion_multi_sig_addr: Optional[str] = Field(default=None, description="Opinion Labs multi-sig address")
    
    # ===================
    # Rate Limiting
    # ===================
    max_requests_per_minute: int = Field(default=30, ge=1, le=100)
    
    # ===================
    # Logging
    # ===================
    log_level: str = Field(default="INFO")
    
    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, v: str) -> str:
        """Ensure encryption key is valid hex."""
        try:
            bytes.fromhex(v)
        except ValueError:
            raise ValueError("Encryption key must be a valid 64-character hex string")
        return v
    
    @property
    def admin_ids(self) -> list[int]:
        """Parse admin IDs from comma-separated string."""
        if not self.admin_telegram_ids:
            return []
        return [int(id.strip()) for id in self.admin_telegram_ids.split(",") if id.strip()]
    
    def get_chain_rpc(self, chain: str) -> str:
        """Get RPC URL for a specific chain."""
        rpcs = {
            "solana": self.solana_rpc_url,
            "polygon": self.polygon_rpc_url,
            "bsc": self.bsc_rpc_url,
        }
        return rpcs.get(chain.lower(), "")
    
    def is_platform_configured(self, platform: str) -> bool:
        """Check if a platform has required configuration."""
        platform = platform.lower()
        if platform == "kalshi":
            return bool(self.dflow_api_key)
        elif platform == "polymarket":
            return True  # Public API works without auth for basic operations
        elif platform == "opinion":
            return bool(self.opinion_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience export
settings = get_settings()
