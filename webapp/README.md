# Spredd Mini App

Telegram Mini App frontend for Spredd Markets Bot.

## Setup

### Prerequisites
- Node.js 18+
- pnpm, npm, or yarn

### Installation

```bash
cd webapp
npm install
```

### Development

```bash
# Start the dev server (port 3000)
npm run dev
```

The dev server proxies `/api` requests to `http://localhost:8000` where the FastAPI backend runs.

### Building

```bash
npm run build
```

Output is in `webapp/dist/`.

## Running with the Bot

### Option 1: Run separately
```bash
# Terminal 1 - Run the bot
python -m src.main

# Terminal 2 - Run the API
python run_api.py

# Terminal 3 - Run the webapp
cd webapp && npm run dev
```

### Option 2: Run bot + API together
```bash
# Terminal 1 - Run bot and API
python run_all.py

# Terminal 2 - Run the webapp
cd webapp && npm run dev
```

## Telegram Mini App Setup

1. Talk to [@BotFather](https://t.me/BotFather)
2. Select your bot
3. Go to "Bot Settings" > "Menu Button"
4. Set the Web App URL to your deployed webapp URL
5. Or use "Configure Mini App" to set up the full Mini App

### Local Testing

For local development, you can use [ngrok](https://ngrok.com/) to expose your local server:

```bash
ngrok http 3000
```

Then set the ngrok URL as your Mini App URL in BotFather.

## Project Structure

```
webapp/
├── src/
│   ├── components/
│   │   ├── layout/         # Layout components
│   │   ├── markets/        # Market-related components
│   │   └── ui/             # shadcn/ui components
│   ├── contexts/
│   │   └── TelegramContext.tsx  # Telegram WebApp integration
│   ├── lib/
│   │   ├── api.ts          # API client
│   │   └── utils.ts        # Utility functions
│   ├── pages/
│   │   ├── MarketsPage.tsx
│   │   ├── MarketDetailsPage.tsx
│   │   ├── WalletPage.tsx
│   │   ├── PositionsPage.tsx
│   │   └── ProfilePage.tsx
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── package.json
├── vite.config.ts
├── tailwind.config.js
└── tsconfig.json
```

## Features

- **Markets**: Browse and search prediction markets
- **Trading**: Buy/sell YES/NO shares with quotes
- **Wallet**: View balances across chains
- **Positions**: Track open and closed positions
- **Profile**: User info, referral program

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- shadcn/ui
- React Query
- Framer Motion
- React Router
