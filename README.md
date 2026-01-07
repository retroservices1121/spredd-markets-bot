# 🎯 Spredd Markets Bot

**Multi-platform prediction market trading on Telegram**

Trade prediction markets across Kalshi, Polymarket, and Opinion Labs from a single Telegram bot with non-custodial wallets.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://telegram.org/)

## ✨ Features

### 🏦 Multi-Platform Support

| Platform | Chain | Status | Collateral |
|----------|-------|--------|------------|
| **Kalshi** | Solana | ✅ Live | USDC |
| **Polymarket** | Polygon | ✅ Live | USDC |
| **Opinion Labs** | BNB Chain | ✅ Live | USDT |

### 🔐 Security

- **Non-custodial** - Your keys, your coins
- **AES-256-GCM** encryption for private keys
- **User-specific** key derivation (PBKDF2)
- **No central storage** of plaintext keys

### 💰 Smart Wallet System

- **One wallet per chain family**:
  - 🟣 **Solana wallet** → Kalshi
  - 🔷 **EVM wallet** → Polymarket + Opinion Labs (shared)
- Automatic wallet creation on first use
- Export keys anytime for backup

### 📊 Trading Features

- Browse trending markets
- Search across platforms
- Real-time pricing
- Position tracking with P&L
- Order history with explorer links

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL database
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

```bash
# Clone the repository
git clone https://github.com/spreddmarkets/spredd-telegram-bot.git
cd spredd-telegram-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your values
nano .env  # or your preferred editor
```

### Configuration

Edit `.env` with your values:

```env
# Required
TELEGRAM_BOT_TOKEN=your_bot_token
DATABASE_URL=postgresql://user:pass@host:5432/db
ENCRYPTION_KEY=your_64_char_hex_key

# Platform APIs (optional but recommended)
DFLOW_API_KEY=your_dflow_key
OPINION_API_KEY=your_opinion_key
```

Generate encryption key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Run Locally

```bash
python -m src.main
```

## 📱 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome & platform selection |
| `/platform` | Switch prediction market platform |
| `/wallet` | View/create wallets |
| `/balance` | Check all balances |
| `/markets` | Browse trending markets |
| `/search [query]` | Search for markets |
| `/positions` | View open positions |
| `/orders` | Order history |
| `/help` | Show help |

## 🏗️ Architecture

```
spredd-markets-bot/
├── src/
│   ├── main.py              # Entry point
│   ├── config.py            # Settings management
│   ├── db/
│   │   ├── models.py        # SQLAlchemy models
│   │   └── database.py      # Database operations
│   ├── platforms/
│   │   ├── base.py          # Platform interface
│   │   ├── kalshi.py        # Kalshi/DFlow implementation
│   │   ├── polymarket.py    # Polymarket implementation
│   │   └── opinion.py       # Opinion Labs implementation
│   ├── services/
│   │   └── wallet.py        # Wallet management
│   ├── handlers/
│   │   └── commands.py      # Telegram handlers
│   └── utils/
│       ├── encryption.py    # AES-256-GCM encryption
│       └── logging.py       # Structured logging
├── requirements.txt
├── Dockerfile
├── railway.toml
└── .env.example
```

## 🗄️ Database Schema

### Models

- **User** - Telegram user with platform preferences
- **Wallet** - Encrypted wallets by chain family
- **Position** - Open/closed positions with P&L
- **Order** - Order history with transaction links
- **MarketCache** - Cached market data

### Chain Families

```
ChainFamily.SOLANA → Kalshi (Solana)
ChainFamily.EVM    → Polymarket (Polygon) + Opinion (BSC)
```

## 🚂 Deploy to Railway

### One-Click Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template/spredd-markets)

### Manual Deploy

1. Create Railway project
2. Add PostgreSQL service
3. Set environment variables
4. Deploy from GitHub

```bash
# Railway CLI
railway login
railway init
railway add postgresql
railway variables set TELEGRAM_BOT_TOKEN=xxx
railway up
```

## 🔑 Platform API Keys

### Kalshi / DFlow

1. Apply at [pond.dflow.net](https://pond.dflow.net)
2. Get builder code at [kalshi.com/builders](https://kalshi.com/builders)
3. Set `DFLOW_API_KEY` and `KALSHI_BUILDER_CODE`

### Polymarket

1. Apply at [docs.polymarket.com/developers/builders](https://docs.polymarket.com/developers/builders)
2. Set `POLYMARKET_BUILDER_KEY`, `POLYMARKET_BUILDER_SECRET`, `POLYMARKET_BUILDER_PASSPHRASE`

### Opinion Labs

1. Apply at [forms.gle/9oBLs9wns6sJVm87A](https://forms.gle/9oBLs9wns6sJVm87A)
2. Set `OPINION_API_KEY`

## 💵 Revenue Model

Earn fees through builder programs:

| Platform | Program | Revenue |
|----------|---------|---------|
| Kalshi | Builder Code | Fee share on volume |
| Polymarket | Builder API | Fee share on trades |
| Opinion | Builder Program | Grants + usage rewards |

## 🔒 Security Considerations

### Encryption

- Private keys encrypted with AES-256-GCM
- User-specific keys derived via PBKDF2 (100,000 iterations)
- Master key + User ID → Unique encryption key per user

### Best Practices

1. **Never commit `.env`** - Use `.env.example` as template
2. **Rotate encryption key** - Generate new key for production
3. **Use Railway Variables** - Not GitHub secrets for sensitive data
4. **Backup user data** - Regular PostgreSQL backups

## 📊 Supported Markets

### Kalshi
- Politics & Elections
- Economics & Fed
- Sports
- Entertainment
- Weather

### Polymarket
- Politics
- Crypto
- Sports
- Pop Culture
- Science

### Opinion Labs
- Macro Economics
- Fed Decisions
- CPI/Inflation
- Global Events

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push branch (`git push origin feature/amazing`)
5. Open Pull Request

## 📝 License

MIT License - see [LICENSE](LICENSE) file.

## ⚠️ Disclaimer

This software is for educational purposes. Prediction market trading involves significant risk. Only trade what you can afford to lose. Check your local laws regarding prediction market participation.

## 🔗 Links

- **Twitter**: [@spreddterminal](https://twitter.com/spreddterminal)
- **Kalshi**: [kalshi.com](https://kalshi.com)
- **Polymarket**: [polymarket.com](https://polymarket.com)
- **Opinion Labs**: [opinion.trade](https://opinion.trade)

---

Built with ❤️ by Spredd Markets
