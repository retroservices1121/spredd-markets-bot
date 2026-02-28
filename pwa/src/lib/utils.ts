import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
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

export function formatPercent(price: number): string {
  return `${Math.round(price * 100)}%`;
}

export function formatVolume(volume: number): string {
  if (volume >= 1_000_000) return `$${(volume / 1_000_000).toFixed(1)}M`;
  if (volume >= 1_000) return `$${(volume / 1_000).toFixed(1)}K`;
  return `$${volume.toFixed(0)}`;
}

export function timeUntil(dateStr: string): string {
  if (!dateStr) return "";
  const diff = new Date(dateStr).getTime() - Date.now();
  if (diff <= 0) return "Ended";
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  const hours = Math.floor((diff / (1000 * 60 * 60)) % 24);
  if (days > 30) return `${Math.floor(days / 30)}mo`;
  if (days > 0) return `${days}d`;
  return `${hours}h`;
}

export function platformLabel(platform: string): string {
  const labels: Record<string, string> = {
    polymarket: "Polymarket",
    kalshi: "Kalshi",
    limitless: "Limitless",
    jupiter: "Jupiter",
    myriad: "Myriad",
    opinion: "Opinion",
  };
  return labels[platform] || platform;
}
