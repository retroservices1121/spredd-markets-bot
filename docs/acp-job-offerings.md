# Spredd Markets - ACP Job Offerings

This document contains all job offerings for the Spredd Markets ACP agent. Copy each section into the ACP dashboard when creating jobs.

---

## Job 1: Execute Trade

### Basic Info

| Field | Value |
|-------|-------|
| **Job Name** | `executeTrade` |
| **Job Description** | Execute a prediction market trade on Kalshi, Polymarket, Opinion Labs, or Limitless. Supports buy/sell orders for YES/NO outcomes with slippage protection. Returns transaction hash, execution price, and explorer link. |
| **Require Funds** | Yes |
| **Price (USD)** | Fixed: `0.01` |
| **SLA** | 0 Hours, 5 Minutes |

### Service Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "platform": {
      "type": "string",
      "description": "Trading platform: kalshi, polymarket, opinion, or limitless"
    },
    "market_id": {
      "type": "string",
      "description": "Platform-specific market identifier"
    },
    "outcome": {
      "type": "string",
      "description": "Outcome to trade: yes or no"
    },
    "side": {
      "type": "string",
      "description": "Order side: buy or sell"
    },
    "amount": {
      "type": "number",
      "description": "USDC amount to trade"
    },
    "max_slippage_bps": {
      "type": "number",
      "description": "Maximum slippage in basis points (optional, default 100)"
    }
  },
  "required": ["platform", "market_id", "outcome", "side", "amount"]
}
```

### Deliverable Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "success": {
      "type": "boolean",
      "description": "Whether the trade executed successfully"
    },
    "tx_hash": {
      "type": "string",
      "description": "Blockchain transaction hash"
    },
    "input_amount": {
      "type": "number",
      "description": "Amount of USDC spent"
    },
    "output_amount": {
      "type": "number",
      "description": "Amount of outcome tokens received"
    },
    "price": {
      "type": "number",
      "description": "Execution price per token"
    },
    "explorer_url": {
      "type": "string",
      "description": "Link to transaction on block explorer"
    },
    "error": {
      "type": "string",
      "description": "Error message if trade failed"
    }
  },
  "required": ["success"]
}
```

### Sample Request

```json
{
  "platform": "kalshi",
  "market_id": "KXBTC15M-26JAN211500",
  "outcome": "yes",
  "side": "buy",
  "amount": 50.00,
  "max_slippage_bps": 100
}
```

### Sample Deliverable

```json
{
  "success": true,
  "tx_hash": "5Kj2mN8xVqRtYpLsWcHgBnJkFdSaQzXvMrTyUiOpKlMn",
  "input_amount": 50.00,
  "output_amount": 125.0,
  "price": 0.40,
  "explorer_url": "https://solscan.io/tx/5Kj2mN8xVqRtYpLsWcHgBnJkFdSaQzXvMrTyUiOpKlMn"
}
```

---

## Job 2: Get Quote

### Basic Info

| Field | Value |
|-------|-------|
| **Job Name** | `getQuote` |
| **Job Description** | Get a real-time trade quote without executing. Returns expected output amount, price per token, price impact, and platform fees. Use this to evaluate trades before committing funds. |
| **Require Funds** | No |
| **Price (USD)** | Fixed: `0.001` |
| **SLA** | 0 Hours, 1 Minutes |

### Service Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "platform": {
      "type": "string",
      "description": "Trading platform: kalshi, polymarket, opinion, or limitless"
    },
    "market_id": {
      "type": "string",
      "description": "Platform-specific market identifier"
    },
    "outcome": {
      "type": "string",
      "description": "Outcome to quote: yes or no"
    },
    "side": {
      "type": "string",
      "description": "Order side: buy or sell"
    },
    "amount": {
      "type": "number",
      "description": "USDC amount to quote"
    }
  },
  "required": ["platform", "market_id", "outcome", "side", "amount"]
}
```

### Deliverable Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "input_amount": {
      "type": "number",
      "description": "Amount of USDC to spend"
    },
    "expected_output": {
      "type": "number",
      "description": "Expected outcome tokens to receive"
    },
    "price": {
      "type": "number",
      "description": "Price per token"
    },
    "price_impact_bps": {
      "type": "number",
      "description": "Price impact in basis points"
    },
    "fee_amount": {
      "type": "number",
      "description": "Platform fee amount in USDC"
    },
    "expires_at": {
      "type": "string",
      "description": "Quote expiration timestamp (ISO 8601)"
    }
  },
  "required": ["input_amount", "expected_output", "price"]
}
```

### Sample Request

```json
{
  "platform": "polymarket",
  "market_id": "0x1234567890abcdef",
  "outcome": "yes",
  "side": "buy",
  "amount": 100.00
}
```

### Sample Deliverable

```json
{
  "input_amount": 100.00,
  "expected_output": 250.0,
  "price": 0.40,
  "price_impact_bps": 15,
  "fee_amount": 0.50,
  "expires_at": "2026-01-21T15:00:00Z"
}
```

---

## Job 3: Search Markets

### Basic Info

| Field | Value |
|-------|-------|
| **Job Name** | `searchMarkets` |
| **Job Description** | Search prediction markets across Kalshi, Polymarket, Opinion Labs, and Limitless. Returns market ID, title, current YES/NO prices, 24h volume, and expiration date. Filter by platform or search all. |
| **Require Funds** | No |
| **Price (USD)** | Fixed: `0.001` |
| **SLA** | 0 Hours, 2 Minutes |

### Service Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Search query (e.g., 'bitcoin price', 'super bowl')"
    },
    "platforms": {
      "type": "array",
      "description": "Optional filter: ['kalshi', 'polymarket', 'opinion', 'limitless']"
    },
    "limit": {
      "type": "number",
      "description": "Maximum results to return (default 10, max 50)"
    }
  },
  "required": ["query"]
}
```

### Deliverable Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "markets": {
      "type": "array",
      "description": "Array of matching markets"
    }
  },
  "required": ["markets"]
}
```

**Markets Array Item Schema:**
```json
{
  "platform": "string",
  "market_id": "string",
  "title": "string",
  "yes_price": "number",
  "no_price": "number",
  "volume_24h": "number",
  "end_date": "string"
}
```

### Sample Request

```json
{
  "query": "bitcoin price",
  "platforms": ["kalshi", "polymarket"],
  "limit": 5
}
```

### Sample Deliverable

```json
{
  "markets": [
    {
      "platform": "kalshi",
      "market_id": "KXBTC15M-26JAN211500",
      "title": "BTC price up in next 15 mins?",
      "yes_price": 0.45,
      "no_price": 0.55,
      "volume_24h": 15000,
      "end_date": "2026-01-21T15:15:00Z"
    },
    {
      "platform": "polymarket",
      "market_id": "0xabc123",
      "title": "Will Bitcoin reach $150k by March?",
      "yes_price": 0.32,
      "no_price": 0.68,
      "volume_24h": 250000,
      "end_date": "2026-03-31T23:59:59Z"
    }
  ]
}
```

---

## Job 4: Get Portfolio

### Basic Info

| Field | Value |
|-------|-------|
| **Job Name** | `getPortfolio` |
| **Job Description** | Retrieve your agent's current prediction market positions held with Spredd. Returns position details including platform, market, outcome, entry price, current price, and unrealized P&L. |
| **Require Funds** | No |
| **Price (USD)** | Fixed: `0.001` |
| **SLA** | 0 Hours, 1 Minutes |

### Service Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "platforms": {
      "type": "array",
      "description": "Optional filter by platforms: ['kalshi', 'polymarket', 'opinion', 'limitless']"
    }
  },
  "required": []
}
```

### Deliverable Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "positions": {
      "type": "array",
      "description": "Array of current positions"
    },
    "total_value": {
      "type": "number",
      "description": "Total portfolio value in USDC"
    },
    "total_pnl": {
      "type": "number",
      "description": "Total unrealized P&L in USDC"
    }
  },
  "required": ["positions", "total_value", "total_pnl"]
}
```

**Positions Array Item Schema:**
```json
{
  "platform": "string",
  "market_id": "string",
  "market_title": "string",
  "outcome": "string",
  "amount": "number",
  "entry_price": "number",
  "current_price": "number",
  "pnl": "number"
}
```

### Sample Request

```json
{
  "platforms": ["kalshi"]
}
```

### Sample Deliverable

```json
{
  "positions": [
    {
      "platform": "kalshi",
      "market_id": "KXBTC15M-26JAN211500",
      "market_title": "BTC price up in next 15 mins?",
      "outcome": "yes",
      "amount": 100,
      "entry_price": 0.40,
      "current_price": 0.55,
      "pnl": 15.00
    }
  ],
  "total_value": 155.00,
  "total_pnl": 15.00
}
```

---

## Job 5: Bridge USDC

### Basic Info

| Field | Value |
|-------|-------|
| **Job Name** | `bridgeUsdc` |
| **Job Description** | Bridge USDC between supported chains: Base, Polygon, Arbitrum, Optimism, and Ethereum. Uses LI.FI and Circle CCTP for secure, fast cross-chain transfers with minimal slippage. |
| **Require Funds** | Yes |
| **Price (USD)** | Fixed: `0.50` |
| **SLA** | 0 Hours, 15 Minutes |

### Service Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "source_chain": {
      "type": "string",
      "description": "Source chain: base, polygon, arbitrum, optimism, or ethereum"
    },
    "dest_chain": {
      "type": "string",
      "description": "Destination chain: base, polygon, arbitrum, optimism, or ethereum"
    },
    "amount": {
      "type": "number",
      "description": "USDC amount to bridge"
    }
  },
  "required": ["source_chain", "dest_chain", "amount"]
}
```

### Deliverable Requirements Schema (JSON)

```json
{
  "type": "object",
  "properties": {
    "success": {
      "type": "boolean",
      "description": "Whether the bridge completed successfully"
    },
    "source_tx_hash": {
      "type": "string",
      "description": "Transaction hash on source chain"
    },
    "dest_tx_hash": {
      "type": "string",
      "description": "Transaction hash on destination chain"
    },
    "amount_sent": {
      "type": "number",
      "description": "USDC amount sent from source"
    },
    "amount_received": {
      "type": "number",
      "description": "USDC amount received on destination"
    },
    "explorer_url": {
      "type": "string",
      "description": "Link to transaction on block explorer"
    },
    "error": {
      "type": "string",
      "description": "Error message if bridge failed"
    }
  },
  "required": ["success"]
}
```

### Sample Request

```json
{
  "source_chain": "base",
  "dest_chain": "polygon",
  "amount": 500.00
}
```

### Sample Deliverable

```json
{
  "success": true,
  "source_tx_hash": "0xabc123def456...",
  "dest_tx_hash": "0x789ghi012jkl...",
  "amount_sent": 500.00,
  "amount_received": 499.50,
  "explorer_url": "https://basescan.org/tx/0xabc123def456..."
}
```

---

## Summary

| Job | Require Funds | Price | SLA |
|-----|--------------|-------|-----|
| `executeTrade` | Yes | $0.01 | 5 min |
| `getQuote` | No | $0.001 | 1 min |
| `searchMarkets` | No | $0.001 | 2 min |
| `getPortfolio` | No | $0.001 | 1 min |
| `bridgeUsdc` | Yes | $0.50 | 15 min |

---

## Supported Platforms

| Platform | Chain | Collateral | Market Types |
|----------|-------|------------|--------------|
| Kalshi | Solana | USDC | Sports, Politics, Crypto, Economics |
| Polymarket | Polygon | USDC | Politics, Crypto, World Events |
| Opinion Labs | BSC | USDT | Asian Markets, Crypto |
| Limitless | Base | USDC | DeFi, Crypto |

---

## Notes

1. **Fund-Transfer Jobs** (`executeTrade`, `bridgeUsdc`): Buyer must deposit funds into escrow before job execution.

2. **Service Jobs** (`getQuote`, `searchMarkets`, `getPortfolio`): No funds required beyond the service fee.

3. **Agent Balance Tracking**: Each agent's funds are tracked separately. Use `getPortfolio` to check your positions.

4. **Slippage Protection**: Default max slippage is 100 bps (1%). Can be customized per trade.
