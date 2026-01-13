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

  // If the number is very large (like wei), convert it
  if (num > 1e15) {
    return (num / 1e18).toFixed(4);
  }
  if (num > 1e9) {
    return (num / 1e6).toFixed(4);
  }

  // Normal formatting
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
      return "BSC";
    case "monad":
      return "Monad";
    case "solana":
      return "Solana";
    case "native":
      return "";
    default:
      return chain;
  }
}

export function getTokenSymbol(token: string, _chain?: string): string {
  // If token looks like an address, return appropriate symbol
  if (token.startsWith("0x") || token.length > 20) {
    // Check for known USDC addresses
    const usdcAddresses = [
      "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", // Polygon
      "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", // Base
      "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d", // BSC
      "0x2791bca1f2de4661ed88a30c99a7a9449aa84174", // USDC.e Polygon
      "epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v", // Solana
    ];
    if (usdcAddresses.includes(token.toLowerCase())) {
      return "USDC";
    }
    return "USDC"; // Default assumption for unknown token addresses
  }
  return token;
}
