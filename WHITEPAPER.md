# Spredd Markets
## The Universal Prediction Market Trading Platform

**Version 1.0 | January 2026**

---

## Executive Summary

Spredd Markets is a unified, non-custodial prediction market trading platform that aggregates multiple prediction markets into a single, accessible interface through Telegram. By bridging the gap between fragmented prediction market platforms across different blockchains, Spredd enables users to discover, trade, and manage positions across Kalshi (Solana), Polymarket (Polygon), Limitless (Base), and Opinion Labs (BSC)—all without leaving Telegram's 800M+ user ecosystem.

Our platform addresses three critical problems in the prediction market space:
1. **Fragmentation** - Users must manage multiple wallets, interfaces, and accounts across platforms
2. **Accessibility** - Existing platforms require technical knowledge and desktop access
3. **Liquidity Isolation** - Each platform operates in a silo, limiting market discovery

Spredd solves these by providing a single entry point with non-custodial wallets, cross-chain USDC bridging, and unified market discovery—making prediction markets accessible to mainstream users.

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Problem Statement](#2-problem-statement)
3. [Solution Overview](#3-solution-overview)
4. [Technical Architecture](#4-technical-architecture)
5. [Platform Integrations](#5-platform-integrations)
6. [Core Features](#6-core-features)
7. [Security Model](#7-security-model)
8. [Revenue Model](#8-revenue-model)
9. [Roadmap](#9-roadmap)
10. [Conclusion](#10-conclusion)

---

## 1. Introduction

Prediction markets represent one of the most promising applications of blockchain technology—enabling users to trade on the outcomes of real-world events while providing valuable price discovery and forecasting signals. The global prediction market industry has grown exponentially, with platforms like Polymarket facilitating billions in trading volume.

However, the current landscape is highly fragmented. Users who want exposure to prediction markets must:
- Create accounts on multiple platforms
- Manage separate wallets for different blockchains
- Navigate complex web interfaces
- Manually track positions across platforms
- Bridge funds between chains

Spredd Markets eliminates these friction points by aggregating multiple prediction market platforms into a unified Telegram-based interface, making prediction market trading as simple as sending a message.

---

## 2. Problem Statement

### 2.1 Platform Fragmentation

The prediction market ecosystem is split across multiple blockchains and platforms:

| Platform | Blockchain | Focus |
|----------|------------|-------|
| Kalshi | Solana | US-regulated, economic events |
| Polymarket | Polygon | Global, political/crypto |
| Limitless | Base | Crypto-native, sports |
| Opinion Labs | BSC | Multi-category |

Each platform requires separate:
- Wallet setup and funding
- Account verification
- Interface learning curve
- Position management

### 2.2 Poor Mobile Experience

Most prediction market platforms are designed for desktop users with web3 wallet extensions. Mobile users face:
- Complex wallet connection flows
- Poor responsive design
- No native mobile apps
- Difficult trade execution on small screens

### 2.3 Liquidity and Discovery Limitations

Users typically only trade on one platform, missing:
- Better odds on alternative platforms
- Markets not available on their primary platform
- Arbitrage opportunities across platforms
- Comprehensive market coverage

### 2.4 Technical Barriers

Mainstream users are deterred by:
- Seed phrase management
- Gas fee complexity
- Cross-chain bridging
- Smart contract interactions

---

## 3. Solution Overview

Spredd Markets is a Telegram-native prediction market aggregator that provides:

### 3.1 Unified Interface
One bot to access all major prediction markets. Users interact through familiar Telegram messages and buttons—no web3 knowledge required.

### 3.2 Non-Custodial Wallets
Automatic wallet generation with military-grade encryption. Users maintain full control of their funds while enjoying a seamless experience.

### 3.3 Cross-Chain Infrastructure
Built-in USDC bridging via Circle CCTP enables automatic liquidity movement between chains. Users don't need to understand bridging—funds flow where needed.

### 3.4 Smart Market Discovery
Search across all platforms simultaneously. View trending markets, compare odds, and discover opportunities across the entire prediction market ecosystem.

### 3.5 Portfolio Management
Track all positions, orders, and P&L from a single dashboard. Generate shareable P&L cards for social proof.

---

## 4. Technical Architecture

### 4.1 System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    TELEGRAM INTERFACE                        │
│              (800M+ potential users)                         │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                   SPREDD CORE ENGINE                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Handlers   │  │   Services   │  │  Platforms   │       │
│  │  (Commands)  │  │  (Business)  │  │ (Adapters)   │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                   DATA & BLOCKCHAIN LAYER                    │
│  ┌──────────────┐  ┌──────────────────────────────────┐     │
│  │  PostgreSQL  │  │      Multi-Chain RPC Access      │     │
│  │   Database   │  │  Solana | Polygon | Base | BSC   │     │
│  └──────────────┘  └──────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Platform Abstraction Layer

All prediction market platforms implement a common interface (`BasePlatform`), enabling:

```python
class BasePlatform:
    async def get_markets(limit, offset, active_only) -> list[Market]
    async def search_markets(query, limit) -> list[Market]
    async def get_orderbook(market_id, outcome) -> OrderBook
    async def get_quote(market_id, outcome, side, amount) -> Quote
    async def execute_trade(quote, private_key) -> TradeResult
    async def redeem_position(market_id, outcome, amount, key) -> Result
```

This abstraction enables:
- Seamless addition of new platforms
- Unified error handling
- Consistent user experience
- Platform-agnostic portfolio tracking

### 4.3 Wallet Architecture

**Chain Family Model:**
- **Solana Family**: One wallet for Solana-based platforms (Kalshi)
- **EVM Family**: One wallet shared across EVM chains (Polygon, Base, BSC)

This reduces complexity—users manage at most 2 wallets regardless of how many platforms they use.

**Encryption Stack:**
- AES-256-GCM authenticated encryption
- PBKDF2 key derivation (100,000 iterations)
- User-specific key material (master key + user ID + optional PIN)
- Private keys never stored in plaintext

### 4.4 Cross-Chain Bridge Integration

Circle CCTP (Cross-Chain Transfer Protocol) enables native USDC transfers:

**Supported Routes:**
- Ethereum ↔ Polygon ↔ Base ↔ Arbitrum ↔ Optimism ↔ Avalanche ↔ Monad

**Auto-Bridge Feature:**
When a user initiates a trade on a platform where they lack funds, Spredd can automatically bridge USDC from configured source chains.

### 4.5 Database Schema

Core entities tracked:
- **Users**: Telegram identity, preferences, referral relationships
- **Wallets**: Encrypted keys per chain family
- **Positions**: Cross-platform position tracking with P&L
- **Orders**: Complete trade history with status tracking
- **MarketCache**: Cached market metadata for performance
- **FeeBalance**: Per-user earned fees and withdrawals

---

## 5. Platform Integrations

### 5.1 Kalshi (Solana)

**Integration**: DFlow API
**Collateral**: USDC
**Specialty**: US-regulated prediction market, economic and political events

Features:
- Real-time orderbook access
- Market and limit orders
- Event-based market grouping
- Category filtering (Crypto, Politics, Economics, Sports)

### 5.2 Polymarket (Polygon)

**Integration**: CLOB API with EIP-712 signing
**Collateral**: USDC
**Specialty**: Global prediction market, high liquidity political markets

Features:
- Builder program integration
- Multi-outcome market support
- Conditional token framework
- High-volume markets

### 5.3 Limitless (Base)

**Integration**: REST API + CLOB
**Collateral**: USDC
**Specialty**: Crypto-native markets, sports, daily/hourly markets

Features:
- Group markets (multi-outcome)
- Market and limit order support
- NegRisk market grouping
- Real-time orderbook

### 5.4 Opinion Labs (BSC)

**Integration**: REST API
**Collateral**: USDT
**Specialty**: Multi-category prediction markets

Features:
- Binary and multi-outcome markets
- Player props support
- Category-based discovery

---

## 6. Core Features

### 6.1 Market Discovery

**Trending Markets**: View top markets by volume across all platforms
**Search**: Full-text search across all platforms simultaneously
**Categories**: Browse by category (Crypto, Politics, Sports, etc.)
**Multi-Outcome Support**: Navigate complex markets with multiple outcomes

### 6.2 Trading

**Quote Generation**: See expected output before confirming trades
**Order Types**: Market orders (instant) and limit orders (GTC)
**Slippage Protection**: Configurable slippage tolerance
**Position Tracking**: Real-time position status and P&L

### 6.3 Portfolio Management

**Unified Dashboard**: All positions across all platforms
**P&L Tracking**: Real-time profit/loss calculation
**Order History**: Complete trade history with transaction links
**P&L Cards**: Generate shareable images for social media

### 6.4 Wallet Management

**Auto-Generation**: Wallets created on first use
**Balance Checking**: View all balances across chains
**Key Export**: Backup encrypted wallet data
**PIN Protection**: Optional second factor for transactions

### 6.5 Cross-Chain Operations

**USDC Bridging**: Transfer between supported chains
**Auto-Bridge**: Automatic liquidity routing
**Multi-Chain Balance**: Aggregated balance view

### 6.6 AI Research (FactsAI Integration)

**Market Analysis**: AI-powered research on market outcomes
**Access Tiers**:
- $SPRDD token holders (5M+ tokens)
- Active traders ($1,000+ volume)

---

## 7. Security Model

### 7.1 Non-Custodial Design

Spredd never has access to user funds. Private keys are:
1. Generated client-side
2. Encrypted before storage
3. Decrypted only during signing
4. Never transmitted in plaintext

### 7.2 Encryption Architecture

```
Master Key (Environment) + User ID + PIN (Optional)
                    │
                    ▼
            PBKDF2 (100,000 iterations)
                    │
                    ▼
              Derived Key
                    │
                    ▼
            AES-256-GCM Encryption
                    │
                    ▼
         Encrypted Private Key (Stored)
```

### 7.3 Access Control

- **User Level**: Wallet access, trading, portfolio viewing
- **Admin Level**: System configuration, analytics, support
- **Rate Limiting**: Configurable request limits per user

### 7.4 Transaction Security

- Quote validation before execution
- Price impact warnings
- Transaction signing with user confirmation
- Transaction hash tracking and verification

---

## 8. Revenue Model

### 8.1 Platform Fees

**Transaction Fee**: 2% on all trades (configurable)

Fee distribution:
- Platform revenue
- Referral commissions
- Partner revenue share

### 8.2 Referral Program

**Three-Tier Commission Structure:**
| Tier | Relationship | Commission |
|------|--------------|------------|
| Tier 1 | Direct referral | 25% of fee (0.5% of trade) |
| Tier 2 | Referrer's referrer | 5% of fee (0.1% of trade) |
| Tier 3 | Third level | 3% of fee (0.06% of trade) |

Users can withdraw earned commissions (minimum 5 USDC).

### 8.3 Partner Program

Partners (influencers, communities, groups) can:
- Create custom referral codes
- Earn revenue share on attributed users
- Track performance via dashboard
- Receive configurable revenue share (default 10%)

### 8.4 Builder Program Revenue

Spredd participates in platform builder programs:
- Kalshi builder rewards
- Polymarket builder fees
- Limitless trading incentives

---

## 9. Roadmap

### Phase 1: Foundation (Completed)

- [x] Multi-platform integration (Kalshi, Polymarket, Limitless, Opinion)
- [x] Non-custodial wallet system
- [x] Cross-chain USDC bridging
- [x] Referral and partner programs
- [x] P&L tracking and card generation
- [x] AI research integration

### Phase 2: Enhanced Trading (Q1 2026)

- [ ] Advanced order types (stop-loss, take-profit)
- [ ] Portfolio analytics dashboard
- [ ] Price alerts and notifications
- [ ] Automated trading strategies
- [ ] Additional platform integrations

### Phase 3: Telegram Mini App (Q2 2026)

- [ ] Full-featured Mini App interface
- [ ] Native Telegram Wallet integration
- [ ] Enhanced mobile trading UX
- [ ] Social features (leaderboards, following)
- [ ] Mini App-exclusive features

### Phase 4: Web Application (Q3 2026)

- [ ] Responsive web application
- [ ] Advanced charting and analytics
- [ ] API access for developers
- [ ] Institutional features
- [ ] White-label solutions

### Phase 5: Ecosystem Expansion (Q4 2026)

- [ ] Additional blockchain integrations
- [ ] DEX prediction market aggregation
- [ ] Options and derivatives markets
- [ ] Mobile native applications
- [ ] SDK for third-party integrations

---

## 10. Conclusion

Spredd Markets represents the next evolution in prediction market accessibility. By unifying fragmented platforms into a single, user-friendly interface, we're making prediction markets accessible to the masses.

Our technical innovations—non-custodial wallets, cross-chain bridging, and platform abstraction—create a foundation for sustainable growth while maintaining the security and trustlessness that blockchain enables.

As prediction markets continue to gain mainstream adoption, Spredd is positioned to be the gateway that brings the next million users on-chain.

---

## Contact & Resources

- **Telegram Bot**: [@SpreddMarketsBot](https://t.me/SpreddMarketsBot)
- **Website**: [spredd.io](https://spredd.io)
- **Documentation**: [docs.spredd.io](https://docs.spredd.io)
- **GitHub**: [github.com/spredd](https://github.com/spredd)

---

*This document is for informational purposes only and does not constitute financial advice. Prediction market trading involves risk, and users should only trade with funds they can afford to lose.*
