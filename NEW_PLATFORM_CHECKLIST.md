# New Platform Integration Checklist

This checklist covers everything needed to add a new prediction market platform to the Spredd Markets Bot.

---

## 1. Database Models (`src/db/models.py`)

- [ ] Add platform to `Platform` enum:
  ```python
  class Platform(str, Enum):
      KALSHI = "kalshi"
      POLYMARKET = "polymarket"
      OPINION = "opinion"
      LIMITLESS = "limitless"
      NEWPLATFORM = "newplatform"  # Add here
  ```

- [ ] Add chain to `Chain` enum (if new chain):
  ```python
  class Chain(str, Enum):
      SOLANA = "solana"
      POLYGON = "polygon"
      BSC = "bsc"
      BASE = "base"
      NEWCHAIN = "newchain"  # Add if needed
  ```

- [ ] Determine `ChainFamily` (SOLANA or EVM) - most EVM chains use the same wallet

---

## 2. Platform Implementation (`src/platforms/newplatform.py`)

Create a new file implementing `BasePlatform` from `src/platforms/base.py`:

### Required Class Attributes:
- [ ] `platform = Platform.NEWPLATFORM`
- [ ] `chain = Chain.NEWCHAIN`
- [ ] `name = "Platform Name"`
- [ ] `description = "Short description"`
- [ ] `website = "https://..."`
- [ ] `collateral_symbol = "USDC"` (or USDT, etc.)
- [ ] `collateral_decimals = 6`

### Required Methods:

#### Lifecycle:
- [ ] `async def initialize(self) -> None` - Initialize API clients
- [ ] `async def close(self) -> None` - Cleanup connections

#### Market Discovery:
- [ ] `async def get_markets(limit, offset, active_only) -> list[Market]`
- [ ] `async def search_markets(query, limit) -> list[Market]`
- [ ] `async def get_market(market_id, search_title) -> Optional[Market]`
- [ ] `async def get_trending_markets(limit) -> list[Market]`
- [ ] `async def get_related_markets(event_id) -> list[Market]` (for multi-outcome)

#### Order Book:
- [ ] `async def get_orderbook(market_id, outcome) -> OrderBook`

#### Trading:
- [ ] `async def get_quote(market_id, outcome, side, amount, token_id) -> Quote`
- [ ] `async def execute_trade(quote, private_key) -> TradeResult`

#### Optional (Redemption):
- [ ] `async def get_market_resolution(market_id) -> MarketResolution`
- [ ] `async def redeem_position(market_id, outcome, token_amount, private_key) -> RedemptionResult`

### Categories (if platform supports):
- [ ] `def get_available_categories() -> list[dict]`
- [ ] `async def get_markets_by_category(category, limit) -> list[Market]`

### Market Parsing:
- [ ] Implement `_parse_market(data) -> Market` helper
- [ ] Set `outcome_name` for multi-outcome markets
- [ ] Set `is_multi_outcome` and `related_market_count`
- [ ] Include `raw_data` for debugging

### Create singleton:
```python
newplatform_platform = NewPlatform()
```

---

## 3. Platform Registry (`src/platforms/__init__.py`)

- [ ] Import the new platform:
  ```python
  from src.platforms.newplatform import newplatform_platform, NewPlatform
  ```

- [ ] Add to `PLATFORM_INFO` dict:
  ```python
  Platform.NEWPLATFORM: {
      "name": "Platform Name",
      "emoji": "🆕",
      "chain": "Chain Name",
      "chain_family": ChainFamily.EVM,  # or SOLANA
      "description": "Short description",
      "collateral": "USDC",
      "features": ["Feature1", "Feature2", "Feature3"],
  },
  ```

- [ ] Add to `PlatformRegistry._platforms`:
  ```python
  self._platforms: dict[Platform, BasePlatform] = {
      ...
      Platform.NEWPLATFORM: newplatform_platform,
  }
  ```

---

## 4. Configuration (`src/config.py`)

Add any platform-specific settings:

- [ ] API keys:
  ```python
  newplatform_api_key: Optional[str] = Field(default=None, description="...")
  ```

- [ ] API URLs:
  ```python
  newplatform_api_url: str = Field(default="https://api.newplatform.com", description="...")
  ```

- [ ] Fee settings:
  ```python
  newplatform_fee_account: Optional[str] = Field(default=None, description="...")
  newplatform_fee_bps: int = Field(default=100, description="...")
  ```

- [ ] Update `.env.example` with new environment variables

---

## 5. Fee Service (`src/services/fee.py`)

- [ ] Update `get_chain_family_for_platform()` if needed:
  ```python
  def get_chain_family_for_platform(platform: Platform) -> ChainFamily:
      if platform == Platform.KALSHI:
          return ChainFamily.SOLANA
      else:
          # All EVM platforms
          return ChainFamily.EVM
  ```

---

## 6. Wallet Service (`src/services/wallet.py`)

- [ ] Add USDC/collateral token address if new chain:
  ```python
  USDC_ADDRESSES = {
      Chain.SOLANA: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      Chain.POLYGON: "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
      Chain.BASE: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      Chain.NEWCHAIN: "0x...",  # Add here
  }
  ```

- [ ] Add RPC URL in config if new chain

---

## 7. Geo-Blocking (`src/utils/geo_blocking.py`)

If platform has country restrictions:

- [ ] Add blocked countries list:
  ```python
  NEWPLATFORM_BLOCKED_COUNTRIES = {
      "US", "KP", ...  # ISO 3166-1 alpha-2 codes
  }
  ```

- [ ] Add to `PLATFORM_BLOCKED_COUNTRIES`:
  ```python
  PLATFORM_BLOCKED_COUNTRIES = {
      ...
      Platform.NEWPLATFORM: NEWPLATFORM_BLOCKED_COUNTRIES,
  }
  ```

---

## 8. Command Handlers (`src/handlers/commands.py`)

Most platform handling is automatic, but check:

- [ ] Geo-blocking check in `handle_market_view()` if platform needs IP verification
- [ ] Player prop detection works with platform's `raw_data` structure
- [ ] Market title extraction works for positions/orders

---

## 9. PnL Card (`src/services/pnl_card.py`)

- [ ] Add platform logo/colors if customizing PnL card appearance
- [ ] Check `get_platform_display_name()` or similar functions

---

## 10. Withdrawal Service (`src/services/withdrawal.py`)

- [ ] Add chain to `CHAIN_CONFIGS` if new chain:
  ```python
  Chain.NEWCHAIN: ChainConfig(
      rpc_url=settings.newchain_rpc_url,
      usdc_address="0x...",
      chain_id=12345,
      explorer_url="https://explorer.newchain.com/tx/",
  ),
  ```

---

## 11. Testing

- [ ] Test market listing/search
- [ ] Test orderbook price fetching
- [ ] Test quote generation
- [ ] Test trade execution (with small amount)
- [ ] Test position tracking
- [ ] Test PnL calculation
- [ ] Test redemption (if applicable)
- [ ] Test categories (if applicable)
- [ ] Test geo-blocking (if applicable)

---

## 12. Documentation

- [ ] Update README if public
- [ ] Add platform to help command output
- [ ] Document any platform-specific quirks

---

## Quick Reference: Key Files to Modify

| File | Changes |
|------|---------|
| `src/db/models.py` | Add to Platform/Chain enums |
| `src/platforms/newplatform.py` | **NEW FILE** - Platform implementation |
| `src/platforms/__init__.py` | Import, PLATFORM_INFO, registry |
| `src/config.py` | API keys, URLs, fee settings |
| `src/services/fee.py` | Chain family mapping (if needed) |
| `src/services/wallet.py` | USDC address (if new chain) |
| `src/utils/geo_blocking.py` | Country restrictions (if needed) |
| `.env.example` | New environment variables |

---

## Notes

- **EVM Platforms**: Most EVM chains (Polygon, Base, BSC, etc.) share the same wallet. Users get one EVM wallet that works across all EVM platforms.

- **Solana Platforms**: Solana uses separate wallet infrastructure. Currently only Kalshi uses Solana.

- **Multi-Outcome Markets**: Set `is_multi_outcome=True`, `event_id`, `outcome_name`, and `related_market_count` in `_parse_market()`.

- **Player Props Detection**: The bot auto-detects player props by looking for "over/under" or "o/u" in:
  - `market.title`
  - `market.outcome_name`
  - `market.raw_data` (check both Polymarket and Kalshi structures)

- **Orderbook Prices**: The display always fetches orderbook ask prices, not mid-prices. Implement `get_orderbook()` accurately.

- **Fee Collection**: If platform supports fee collection, add fee account and bps settings to config.
