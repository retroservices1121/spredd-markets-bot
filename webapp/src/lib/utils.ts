import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPrice(price: number | null | undefined): string {
  if (price === null || price === undefined) return "-";
  return `${(price * 100).toFixed(0)}¢`;
}

export function formatUSD(amount: string | number): string {
  const num = typeof amount === "string" ? parseFloat(amount) : amount;
  if (isNaN(num)) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num);
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function formatNumber(value: number | string): string {
  const num = typeof value === "string" ? parseFloat(value) : value;
  if (isNaN(num)) return "0";

  if (num >= 1_000_000) {
    return `${(num / 1_000_000).toFixed(1)}M`;
  }
  if (num >= 1_000) {
    return `${(num / 1_000).toFixed(1)}K`;
  }
  return num.toFixed(2);
}

export function shortenAddress(address: string, chars = 4): string {
  if (!address) return "";
  return `${address.slice(0, chars + 2)}...${address.slice(-chars)}`;
}

export function getPlatformColor(platform: string): string {
  switch (platform.toLowerCase()) {
    case "kalshi":
      return "#6366f1"; // Indigo
    case "polymarket":
      return "#8b5cf6"; // Purple
    case "opinion":
      return "#06b6d4"; // Cyan
    default:
      return "#F97316"; // Orange (Spredd)
  }
}

export function getPlatformName(platform: string): string {
  switch (platform.toLowerCase()) {
    case "kalshi":
      return "Kalshi";
    case "polymarket":
      return "Polymarket";
    case "opinion":
      return "Opinion";
    default:
      return platform;
  }
}

export function formatShares(amount: string | number): string {
  const num = typeof amount === "string" ? parseFloat(amount) : amount;
  if (isNaN(num)) return "0";

  // If the number is very large (like wei - 18 decimals), convert it
  if (num > 1e15) {
    return formatNumber(num / 1e18);
  }
  // 6-decimal tokens (Kalshi shares, USDC) - values > 100,000 are likely raw
  // This handles cases where 1 share = 1,000,000 (6 decimals)
  if (num > 1e5) {
    return formatNumber(num / 1e6);
  }

  // Normal formatting for small human-readable amounts
  if (num >= 1000) {
    return formatNumber(num);
  }
  return num.toFixed(2);
}

export function getChainName(chain: string): string {
  const chainLower = chain.toLowerCase();
  switch (chainLower) {
    case "polygon":
      return "Polygon";
    case "base":
      return "Base";
    case "bsc":
    case "binance":
    case "bnb":
      return "BNB Chain";
    case "monad":
      return "Monad";
    case "solana":
      return "Solana";
    case "arbitrum":
      return "Arbitrum";
    case "native":
      return "Native";
    default:
      return chain;
  }
}

export function getTokenSymbol(token: string, chain?: string): string {
  const tokenLower = token.toLowerCase();
  const chainLower = chain?.toLowerCase() || "";

  // Handle native tokens
  if (tokenLower === "native" || tokenLower === "eth" || tokenLower === "matic" || tokenLower === "pol" || tokenLower === "bnb" || tokenLower === "sol") {
    switch (chainLower) {
      case "polygon":
        return "POL";
      case "base":
      case "arbitrum":
        return "ETH";
      case "bsc":
        return "BNB";
      case "solana":
        return "SOL";
      case "monad":
        return "MON";
      default:
        return token.toUpperCase();
    }
  }

  // If token looks like an address, return appropriate symbol
  if (token.startsWith("0x") || token.length > 20) {
    // Known USDC.e (bridged) addresses
    const usdceAddresses = [
      "0x2791bca1f2de4661ed88a30c99a7a9449aa84174", // USDC.e Polygon
    ];

    // Known native USDC addresses
    const usdcAddresses = [
      "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", // Polygon native USDC
      "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", // Base USDC
      "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", // BSC USDC
      "epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v", // Solana USDC
    ];

    if (usdceAddresses.includes(tokenLower)) {
      return "USDC.e";
    }
    if (usdcAddresses.includes(tokenLower)) {
      return "USDC";
    }

    // Default for unknown addresses based on chain
    return "USDC";
  }

  // Return token as-is if it's already a symbol
  return token.toUpperCase();
}
