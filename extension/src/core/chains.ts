import type { ChainConfig, ChainId } from "./types";

export const CHAINS: Record<ChainId, ChainConfig> = {
  polygon: {
    id: "polygon",
    name: "Polygon",
    family: "evm",
    chainId: 137,
    rpcUrl: "https://rpc.ankr.com/polygon",
    explorerUrl: "https://polygonscan.com",
    nativeSymbol: "POL",
    nativeDecimals: 18,
    color: "#8247E5",
    tokens: [
      {
        symbol: "POL",
        name: "POL",
        address: "native",
        decimals: 18,
        isNative: true,
        logo: "https://assets.coingecko.com/coins/images/4713/small/polygon.png",
      },
      {
        symbol: "USDC",
        name: "USD Coin",
        address: "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        decimals: 6,
        logo: "https://assets.coingecko.com/coins/images/6319/small/usdc.png",
      },
      {
        symbol: "USDC.e",
        name: "Bridged USDC",
        address: "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
        decimals: 6,
        logo: "https://assets.coingecko.com/coins/images/6319/small/usdc.png",
      },
    ],
  },
  base: {
    id: "base",
    name: "Base",
    family: "evm",
    chainId: 8453,
    rpcUrl: "https://mainnet.base.org",
    explorerUrl: "https://basescan.org",
    nativeSymbol: "ETH",
    nativeDecimals: 18,
    color: "#0052FF",
    tokens: [
      {
        symbol: "ETH",
        name: "Ethereum",
        address: "native",
        decimals: 18,
        isNative: true,
        logo: "https://assets.coingecko.com/coins/images/279/small/ethereum.png",
      },
      {
        symbol: "USDC",
        name: "USD Coin",
        address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        decimals: 6,
        logo: "https://assets.coingecko.com/coins/images/6319/small/usdc.png",
      },
    ],
  },
  bsc: {
    id: "bsc",
    name: "BNB Chain",
    family: "evm",
    chainId: 56,
    rpcUrl: "https://bsc-dataseed.binance.org",
    explorerUrl: "https://bscscan.com",
    nativeSymbol: "BNB",
    nativeDecimals: 18,
    color: "#F3BA2F",
    tokens: [
      {
        symbol: "BNB",
        name: "BNB",
        address: "native",
        decimals: 18,
        isNative: true,
        logo: "https://assets.coingecko.com/coins/images/825/small/bnb-icon2_2x.png",
      },
      {
        symbol: "USDC",
        name: "USD Coin",
        address: "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        decimals: 18,
        logo: "https://assets.coingecko.com/coins/images/6319/small/usdc.png",
      },
      {
        symbol: "USDT",
        name: "Tether USD",
        address: "0x55d398326f99059fF775485246999027B3197955",
        decimals: 18,
        logo: "https://assets.coingecko.com/coins/images/325/small/Tether.png",
      },
    ],
  },
  arbitrum: {
    id: "arbitrum",
    name: "Arbitrum",
    family: "evm",
    chainId: 42161,
    rpcUrl: "https://arb1.arbitrum.io/rpc",
    explorerUrl: "https://arbiscan.io",
    nativeSymbol: "ETH",
    nativeDecimals: 18,
    color: "#28A0F0",
    tokens: [
      {
        symbol: "ETH",
        name: "Ethereum",
        address: "native",
        decimals: 18,
        isNative: true,
        logo: "https://assets.coingecko.com/coins/images/279/small/ethereum.png",
      },
      {
        symbol: "USDC",
        name: "USD Coin",
        address: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        decimals: 6,
        logo: "https://assets.coingecko.com/coins/images/6319/small/usdc.png",
      },
    ],
  },
  abstract: {
    id: "abstract",
    name: "Abstract",
    family: "evm",
    chainId: 2741,
    rpcUrl: "https://api.mainnet.abs.xyz",
    explorerUrl: "https://abscan.org",
    nativeSymbol: "ETH",
    nativeDecimals: 18,
    color: "#00D4AA",
    tokens: [
      {
        symbol: "ETH",
        name: "Ethereum",
        address: "native",
        decimals: 18,
        isNative: true,
        logo: "https://assets.coingecko.com/coins/images/279/small/ethereum.png",
      },
      {
        symbol: "USDC.e",
        name: "Bridged USDC",
        address: "0x84A71ccD554Cc1b02749b35d22F684CC8ec987e1",
        decimals: 6,
        logo: "https://assets.coingecko.com/coins/images/6319/small/usdc.png",
      },
    ],
  },
  solana: {
    id: "solana",
    name: "Solana",
    family: "solana",
    chainId: 0,
    rpcUrl: "https://solana-rpc.publicnode.com",
    explorerUrl: "https://solscan.io",
    nativeSymbol: "SOL",
    nativeDecimals: 9,
    color: "#9945FF",
    tokens: [
      {
        symbol: "SOL",
        name: "Solana",
        address: "native",
        decimals: 9,
        isNative: true,
        logo: "https://assets.coingecko.com/coins/images/4128/small/solana.png",
      },
      {
        symbol: "USDC",
        name: "USD Coin",
        address: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        decimals: 6,
        logo: "https://assets.coingecko.com/coins/images/6319/small/usdc.png",
      },
    ],
  },
};

export const ALL_CHAIN_IDS = Object.keys(CHAINS) as ChainId[];

export const EVM_CHAIN_IDS = ALL_CHAIN_IDS.filter(
  (id) => CHAINS[id].family === "evm"
);

export function getChain(id: ChainId): ChainConfig {
  return CHAINS[id];
}
