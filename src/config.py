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
    telegram_bot_username: str = Field(default="", description="Telegram bot username (without @)")
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
    # EVM Configuration (shared for Polygon, BSC & L2s)
    # ===================
    polygon_rpc_url: str = Field(
        default="https://rpc.ankr.com/polygon",
        description="Polygon RPC endpoint"
    )
    polygon_rpc_fallbacks: str = Field(
        default="https://polygon-bor-rpc.publicnode.com,https://1rpc.io/matic,https://polygon-mainnet.public.blastapi.io",
        description="Comma-separated fallback Polygon RPC endpoints"
    )
    bsc_rpc_url: str = Field(
        default="https://bsc-dataseed.binance.org",
        description="BSC RPC endpoint"
    )
    base_rpc_url: str = Field(
        default="https://mainnet.base.org",
        description="Base L2 RPC endpoint"
    )
    arbitrum_rpc_url: str = Field(
        default="https://arb1.arbitrum.io/rpc",
        description="Arbitrum One RPC endpoint"
    )
    optimism_rpc_url: str = Field(
        default="https://mainnet.optimism.io",
        description="Optimism RPC endpoint"
    )
    ethereum_rpc_url: str = Field(
        default="https://eth.llamarpc.com",
        description="Ethereum mainnet RPC endpoint"
    )
    monad_rpc_url: str = Field(
        default="https://rpc.monad.xyz",
        description="Monad mainnet RPC endpoint"
    )

    # ===================
    # Cross-Chain Bridge Configuration
    # ===================
    auto_bridge_enabled: bool = Field(
        default=True,
        description="Enable automatic cross-chain bridging via CCTP"
    )
    bridge_source_chains: str = Field(
        default="base",
        description="Comma-separated list of source chains for auto-bridging (base,arbitrum,optimism)"
    )

    @property
    def enabled_bridge_chains(self) -> list[str]:
        """Parse enabled bridge chains from config."""
        if not self.bridge_source_chains:
            return []
        return [c.strip().lower() for c in self.bridge_source_chains.split(",") if c.strip()]

    @property
    def polygon_rpc_urls(self) -> list[str]:
        """Get all Polygon RPC URLs (primary + fallbacks)."""
        urls = [self.polygon_rpc_url]
        if self.polygon_rpc_fallbacks:
            urls.extend([u.strip() for u in self.polygon_rpc_fallbacks.split(",") if u.strip()])
        return urls

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
        default=200,
        description="Platform fee in basis points (200 = 2%)"
    )

    # EVM Fee Collection (Polymarket/Opinion/Limitless/Myriad)
    evm_fee_account: Optional[str] = Field(
        default=None,
        description="EVM wallet address to receive platform fees"
    )
    evm_fee_bps: int = Field(
        default=200,
        description="Platform fee in basis points for EVM platforms (200 = 2%)"
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
    # Limitless Exchange Configuration
    # ===================
    limitless_api_key: Optional[str] = Field(
        default=None,
        description="Limitless API key (format: lmts_...). Required after Feb 17, 2026. Get from https://limitless.exchange profile -> Api keys"
    )
    limitless_api_url: str = Field(
        default="https://api.limitless.exchange",
        description="Limitless Exchange API URL"
    )

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
    # Myriad Protocol Configuration
    # ===================
    myriad_api_key: Optional[str] = Field(default=None, description="Myriad Protocol API key")
    myriad_api_url: str = Field(
        default="https://api-v2.myriadprotocol.com",
        description="Myriad Protocol API base URL (use staging: https://api-v2.staging.myriadprotocol.com)"
    )
    myriad_referral_code: str = Field(
        default="spredd",
        description="Myriad builder code for revenue sharing"
    )
    # Myriad network configuration - Abstract is primary
    myriad_network_id: int = Field(
        default=2741,
        description="Myriad network ID (2741=Abstract mainnet)"
    )
    # Contract addresses for Abstract mainnet
    myriad_prediction_market_contract: str = Field(
        default="0x3e0F5F8F5Fb043aBFA475C0308417Bf72c463289",
        description="Myriad PredictionMarket contract address"
    )
    myriad_querier_contract: str = Field(
        default="0x1d5773Cd0dC74744C1F7a19afEeECfFE64f233Ff",
        description="Myriad PredictionMarketQuerier contract address"
    )
    myriad_collateral_token: str = Field(
        default="0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",
        description="Myriad collateral token (USDC.e on Abstract)"
    )
    # Abstract RPC
    abstract_rpc_url: str = Field(
        default="https://api.mainnet.abs.xyz",
        description="Abstract chain RPC URL"
    )
    # Linea RPC
    linea_rpc_url: str = Field(
        default="https://rpc.linea.build",
        description="Linea chain RPC URL"
    )

    # ===================
    # LI.FI Bridge Configuration
    # ===================
    lifi_api_key: Optional[str] = Field(default=None, description="LI.FI API key for cross-chain bridging")

    # ===================
    # Mini App Configuration
    # ===================
    miniapp_url: Optional[str] = Field(
        default=None,
        validation_alias="MINIAPP_URL",
        description="URL for Telegram Mini App (e.g., https://your-domain.com/webapp)"
    )

    # ===================
    # FactsAI Configuration (AI Research Partner)
    # ===================
    factsai_api_key: Optional[str] = Field(
        default=None,
        description="FactsAI API key for AI research features"
    )
    factsai_api_url: str = Field(
        default="https://factsai.org",
        description="FactsAI API base URL"
    )

    # $SPRDD Token Configuration for premium features
    sprdd_token_address: str = Field(
        default="0xAC0E8f7e3dF7239f5D0f0AE55cf85962d007Cc5F",
        description="$SPRDD token contract address on Base"
    )
    sprdd_min_balance: int = Field(
        default=5000000,
        description="Minimum $SPRDD tokens required for AI research access (5 million)"
    )
    ai_research_min_volume: int = Field(
        default=1000,
        description="Minimum trading volume ($) for AI research access"
    )

    # ===================
    # Dome API Configuration (Market Data & Analytics)
    # ===================
    dome_api_key: Optional[str] = Field(
        default=None,
        description="Dome API key for market data, charts, and cross-platform matching"
    )
    dome_api_url: str = Field(
        default="https://api.domeapi.io/v1",
        description="Dome API base URL"
    )
    dome_ws_url: str = Field(
        default="wss://ws.domeapi.io",
        description="Dome WebSocket URL for real-time data"
    )

    # ===================
    # Marketing Postback Configuration (t3nzu Attribution)
    # ===================
    postback_url: Optional[str] = Field(
        default="https://receiver.t3nzu.com/direct/",
        description="Base URL for marketing postbacks"
    )
    postback_adv_id: Optional[str] = Field(
        default="17",
        description="Advertiser ID assigned by marketing partner"
    )
    postback_min_qualification_amount: float = Field(
        default=5.0,
        description="Minimum trade amount in USD to trigger trade postback"
    )

    # ===================
    # Virtuals ACP Configuration (Agent Commerce Protocol)
    # ===================
    acp_enabled: bool = Field(
        default=False,
        description="Enable Virtuals ACP service for AI agent commerce"
    )
    acp_agent_wallet_private_key: Optional[str] = Field(
        default=None,
        description="Private key for ACP EVM wallet (hex without 0x prefix)"
    )
    acp_agent_wallet_address: Optional[str] = Field(
        default=None,
        description="ACP EVM wallet address"
    )
    acp_solana_private_key: Optional[str] = Field(
        default=None,
        description="Private key for ACP Solana wallet (base58 format) for Kalshi trades"
    )
    acp_entity_id: Optional[int] = Field(
        default=None,
        description="ACP entity ID from registration (must be a numeric integer)"
    )
    acp_environment: str = Field(
        default="sandbox",
        description="ACP environment: sandbox or production"
    )

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
            "base": self.base_rpc_url,
            "arbitrum": self.arbitrum_rpc_url,
            "optimism": self.optimism_rpc_url,
            "ethereum": self.ethereum_rpc_url,
            "abstract": self.abstract_rpc_url,
            "linea": self.linea_rpc_url,
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
        elif platform == "limitless":
            return bool(self.limitless_api_key)  # API key required after Feb 17, 2026
        elif platform == "myriad":
            return bool(self.myriad_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience export
settings = get_settings()
