/**
 * MV3 Background Service Worker.
 * Holds decrypted vault in memory, manages auto-lock via chrome.alarms,
 * and persists session data to chrome.storage.session for SW restart survival.
 *
 * Phase 2: Handles Polymarket trading via Spredd Bot API.
 * Private key stays in service worker — signs wallet auth messages,
 * then sends trade requests to the bot API which handles order signing
 * with builder codes and fee collection.
 */

import type { DecryptedVault, Message, MessageResponse } from "./core/types";
import { decryptVault } from "./core/vault";
import { ethers } from "ethers";
import { API_BASE } from "./services/polymarket";

const ALARM_NAME = "spredd-auto-lock";
const SESSION_KEY = "vault_session";
let DEFAULT_AUTO_LOCK_MINUTES = 15;

// In-memory decrypted vault (cleared on lock or SW termination without session backup)
let cachedVault: DecryptedVault | null = null;

// Platform API keys (fetched from Bot API, never in source code)
interface PlatformKeyConfig {
  base_url: string;
  header: string;
  key: string;
}
let platformKeys: Record<string, PlatformKeyConfig> | null = null;
let platformKeysLoading: Promise<void> | null = null;

// ──────────────────────────────────────────
// Session persistence (survives SW restarts)
// ──────────────────────────────────────────

async function saveSession(vault: DecryptedVault): Promise<void> {
  try {
    await chrome.storage.session.set({ [SESSION_KEY]: JSON.stringify(vault) });
  } catch {
    // session storage may not be available in all contexts
  }
}

async function loadSession(): Promise<DecryptedVault | null> {
  try {
    const result = await chrome.storage.session.get(SESSION_KEY);
    if (result[SESSION_KEY]) {
      return JSON.parse(result[SESSION_KEY]) as DecryptedVault;
    }
  } catch {
    // ignore
  }
  return null;
}

async function clearSession(): Promise<void> {
  try {
    await chrome.storage.session.remove(SESSION_KEY);
  } catch {
    // ignore
  }
}

// ──────────────────────────────────────────
// Auto-lock alarm
// ──────────────────────────────────────────

async function resetAutoLockAlarm(): Promise<void> {
  await chrome.alarms.clear(ALARM_NAME);
  if (DEFAULT_AUTO_LOCK_MINUTES > 0) {
    await chrome.alarms.create(ALARM_NAME, {
      delayInMinutes: DEFAULT_AUTO_LOCK_MINUTES,
    });
  }
}

async function lockWallet(): Promise<void> {
  cachedVault = null;
  platformKeys = null;
  await clearSession();
  await chrome.alarms.clear(ALARM_NAME);
}

// ──────────────────────────────────────────
// Wallet signature auth for Bot API
// ──────────────────────────────────────────

/** Create wallet signature auth headers for Bot API requests */
async function getAuthHeaders(): Promise<Record<string, string>> {
  if (!cachedVault) throw new Error("Wallet is locked");

  const wallet = new ethers.Wallet(cachedVault.evmPrivateKey);
  const address = wallet.address.toLowerCase();
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const message = `spredd-auth:${address}:${timestamp}`;

  const signature = await wallet.signMessage(message);

  return {
    "X-Wallet-Address": address,
    "X-Wallet-Signature": signature,
    "X-Wallet-Timestamp": timestamp,
    "Content-Type": "application/json",
  };
}

/** Make an authenticated request to the Bot API */
async function botApiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown; timeoutMs?: number } = {}
): Promise<T> {
  const headers = await getAuthHeaders();
  const url = `${API_BASE}${path}`;

  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    options.timeoutMs ?? 15000
  );

  try {
    const res = await fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API ${res.status}: ${text}`);
    }

    return res.json() as Promise<T>;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

// ──────────────────────────────────────────
// Platform API keys (fetched from Bot API on demand)
// ──────────────────────────────────────────

async function ensurePlatformKeys(): Promise<Record<string, PlatformKeyConfig>> {
  if (platformKeys) return platformKeys;

  // Avoid duplicate fetches
  if (platformKeysLoading) {
    await platformKeysLoading;
    if (platformKeys) return platformKeys;
  }

  platformKeysLoading = (async () => {
    try {
      const data = await botApiFetch<{ keys: Record<string, PlatformKeyConfig> }>(
        "/api/v1/config/platform-keys"
      );
      platformKeys = data.keys ?? {};
    } catch {
      platformKeys = {};
    }
  })();

  await platformKeysLoading;
  platformKeysLoading = null;
  return platformKeys!;
}

/** Fetch JSON directly from a platform API using cached keys */
async function platformFetch<T>(
  platform: string,
  path: string,
  timeoutMs = 12000
): Promise<T> {
  const keys = await ensurePlatformKeys();
  const config = keys[platform];
  if (!config) throw new Error(`No API key for ${platform}`);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(`${config.base_url}${path}`, {
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        [config.header]: config.key,
      },
    });
    if (!res.ok) throw new Error(`${platform} API ${res.status}`);
    return res.json() as Promise<T>;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw e;
  } finally {
    clearTimeout(timeout);
  }
}

// Platform-specific market fetchers

interface RawPlatformMarket {
  [key: string]: unknown;
}

async function fetchKalshiDirect(limit: number): Promise<RawPlatformMarket[]> {
  const data = await platformFetch<{ markets?: RawPlatformMarket[]; data?: RawPlatformMarket[] }>(
    "kalshi",
    `/api/v1/markets?limit=${Math.min(limit * 2, 200)}&status=active`
  );
  return (data?.markets ?? data?.data ?? []).slice(0, limit);
}

async function fetchOpinionDirect(limit: number): Promise<RawPlatformMarket[]> {
  const data = await platformFetch<{ result?: { list?: RawPlatformMarket[] } }>(
    "opinion",
    `/openapi/market?limit=${limit}&status=activated&sortBy=5`
  );
  return data?.result?.list ?? [];
}

async function fetchLimitlessDirect(limit: number): Promise<RawPlatformMarket[]> {
  const data = await platformFetch<RawPlatformMarket[] | { data?: RawPlatformMarket[]; markets?: RawPlatformMarket[] }>(
    "limitless",
    `/markets/active?limit=${Math.min(limit, 25)}&page=1`
  );
  if (Array.isArray(data)) return data.slice(0, limit);
  return (data?.data ?? data?.markets ?? []).slice(0, limit);
}

async function fetchMyriadDirect(limit: number): Promise<RawPlatformMarket[]> {
  const data = await platformFetch<{ data?: RawPlatformMarket[] }>(
    "myriad",
    `/markets?limit=${limit}&state=open&sort=volume_24h&order=desc&network_id=2741`
  );
  return data?.data ?? [];
}

async function fetchPlatformDirect(platform: string, limit: number): Promise<RawPlatformMarket[]> {
  switch (platform) {
    case "kalshi": return fetchKalshiDirect(limit);
    case "opinion": return fetchOpinionDirect(limit);
    case "limitless": return fetchLimitlessDirect(limit);
    case "myriad": return fetchMyriadDirect(limit);
    default: throw new Error(`Unknown platform: ${platform}`);
  }
}

async function searchPlatformDirect(platform: string, query: string, limit: number): Promise<RawPlatformMarket[]> {
  switch (platform) {
    case "kalshi": {
      // DFlow has no search endpoint — fetch and filter client-side
      const all = await fetchKalshiDirect(200);
      const q = query.toLowerCase();
      return all.filter((m) => {
        const title = String(m.title || m.question || m.ticker || "");
        return title.toLowerCase().includes(q);
      }).slice(0, limit);
    }
    case "opinion": {
      const data = await platformFetch<{ result?: { list?: RawPlatformMarket[] } }>(
        "opinion",
        `/openapi/market?keyword=${encodeURIComponent(query)}&limit=${limit}&status=activated`
      );
      return data?.result?.list ?? [];
    }
    case "limitless": {
      const data = await platformFetch<RawPlatformMarket[] | { data?: RawPlatformMarket[] }>(
        "limitless",
        `/markets/search?query=${encodeURIComponent(query)}&limit=${limit}`
      );
      if (Array.isArray(data)) return data.slice(0, limit);
      return (data?.data ?? []).slice(0, limit);
    }
    case "myriad": {
      const data = await platformFetch<{ data?: RawPlatformMarket[] }>(
        "myriad",
        `/markets?keyword=${encodeURIComponent(query)}&limit=${limit}&network_id=2741`
      );
      return data?.data ?? [];
    }
    default: throw new Error(`Unknown platform: ${platform}`);
  }
}

// ──────────────────────────────────────────
// Trading via Bot API
// ──────────────────────────────────────────

interface QuoteResponse {
  platform: string;
  market_id: string;
  outcome: string;
  side: string;
  input_amount: string;
  expected_output: string;
  price: number;
  price_impact?: number;
  fees: Record<string, string>;
}

interface OrderResponse {
  order_id: string;
  status: string;
  tx_hash?: string;
  message: string;
}

/** Get a trade quote from the Bot API */
async function getQuote(params: {
  platform: string;
  marketId: string;
  outcome: string;
  side: string;
  amount: string;
}): Promise<QuoteResponse> {
  return botApiFetch<QuoteResponse>("/api/v1/trading/quote", {
    method: "POST",
    body: {
      platform: params.platform,
      market_id: params.marketId,
      outcome: params.outcome,
      side: params.side,
      amount: params.amount,
    },
  });
}

/** Execute a trade via the Bot API */
async function executeTrade(params: {
  platform: string;
  marketId: string;
  outcome: string;
  side: string;
  amount: string;
  slippageBps?: number;
}): Promise<OrderResponse> {
  return botApiFetch<OrderResponse>("/api/v1/trading/execute", {
    method: "POST",
    body: {
      platform: params.platform,
      market_id: params.marketId,
      outcome: params.outcome,
      side: params.side,
      amount: params.amount,
      slippage_bps: params.slippageBps ?? 100,
    },
  });
}

/** Check if the wallet is linked (user exists in bot DB) */
async function checkWalletLinked(): Promise<boolean> {
  try {
    await botApiFetch("/api/v1/user/me");
    return true;
  } catch {
    return false;
  }
}

// ──────────────────────────────────────────
// Message handler
// ──────────────────────────────────────────

chrome.runtime.onMessage.addListener(
  (
    message: Message,
    _sender: chrome.runtime.MessageSender,
    sendResponse: (response: MessageResponse) => void
  ) => {
    handleMessage(message).then(sendResponse);
    return true; // keep message channel open for async response
  }
);

async function handleMessage(message: Message): Promise<MessageResponse> {
  switch (message.type) {
    case "UNLOCK_VAULT": {
      const { password } = message.payload as { password: string };
      try {
        const result = await chrome.storage.local.get("vault_encrypted");
        const encryptedHex = result.vault_encrypted;
        if (!encryptedHex) {
          return { success: false, error: "No vault found" };
        }
        const json = await decryptVault(encryptedHex, password);
        cachedVault = JSON.parse(json) as DecryptedVault;
        await saveSession(cachedVault);
        await resetAutoLockAlarm();
        return { success: true };
      } catch {
        return { success: false, error: "Wrong password" };
      }
    }

    case "LOCK_VAULT": {
      await lockWallet();
      return { success: true };
    }

    case "GET_SESSION": {
      // Restore from session storage if SW restarted
      if (!cachedVault) {
        cachedVault = await loadSession();
        if (cachedVault) {
          await resetAutoLockAlarm();
        }
      }
      const result = await chrome.storage.local.get("vault_encrypted");
      return {
        success: true,
        data: {
          unlocked: cachedVault !== null,
          hasVault: !!result.vault_encrypted,
        },
      };
    }

    case "GET_VAULT_DATA": {
      if (!cachedVault) {
        cachedVault = await loadSession();
      }
      if (!cachedVault) {
        return { success: false, error: "Vault is locked" };
      }
      await resetAutoLockAlarm();
      return { success: true, data: cachedVault };
    }

    case "RESET_TIMER": {
      if (cachedVault) {
        await resetAutoLockAlarm();
      }
      return { success: true };
    }

    case "SET_AUTO_LOCK": {
      const { minutes } = message.payload as { minutes: number };
      DEFAULT_AUTO_LOCK_MINUTES = minutes;
      const prefs = await chrome.storage.local.get("preferences");
      const current = prefs.preferences || {};
      await chrome.storage.local.set({
        preferences: { ...current, autoLockMinutes: minutes },
      });
      if (cachedVault) {
        await resetAutoLockAlarm();
      }
      return { success: true };
    }

    case "GET_AUTO_LOCK": {
      return { success: true, data: { minutes: DEFAULT_AUTO_LOCK_MINUTES } };
    }

    // ── Trading via Bot API ───────────────────

    case "GET_TRADE_QUOTE": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          platform: string;
          marketId: string;
          outcome: string;
          side: string;
          amount: string;
        };
        const quote = await getQuote(params);
        return { success: true, data: quote };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Quote failed",
        };
      }
    }

    case "EXECUTE_TRADE": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          platform: string;
          marketId: string;
          outcome: string;
          side: string;
          amount: string;
          slippageBps?: number;
        };
        const result = await executeTrade(params);
        return { success: true, data: result };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Trade failed",
        };
      }
    }

    case "CHECK_WALLET_LINKED": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const linked = await checkWalletLinked();
        return { success: true, data: { linked } };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Check failed",
        };
      }
    }

    // ── Multi-platform markets via Bot API ────────

    case "GET_BOT_MARKETS": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          platform?: string;
          limit?: number;
          active?: boolean;
        };
        const qs = new URLSearchParams();
        if (params.platform) qs.set("platform", params.platform);
        if (params.limit) qs.set("limit", String(params.limit));
        if (params.active !== undefined) qs.set("active", String(params.active));
        const markets = await botApiFetch(`/api/v1/markets?${qs.toString()}`);
        return { success: true, data: markets };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Failed to load markets",
        };
      }
    }

    case "SEARCH_BOT_MARKETS": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          query: string;
          platform?: string;
        };
        const qs = new URLSearchParams({ q: params.query });
        if (params.platform) qs.set("platform", params.platform);
        const raw = await botApiFetch<{ markets?: unknown[] }>(
          `/api/v1/markets/search?${qs.toString()}`
        );
        // API wraps results in { markets: [...] }
        const markets = raw?.markets ?? raw;
        return { success: true, data: markets };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Search failed",
        };
      }
    }

    case "GET_BOT_MARKET_DETAIL": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          platform: string;
          marketId: string;
        };
        const raw = await botApiFetch<{ market?: unknown }>(
          `/api/v1/markets/${params.platform}/${params.marketId}`
        );
        // API wraps result in { market: {...} }
        const market = raw?.market ?? raw;
        return { success: true, data: market };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Failed to load market",
        };
      }
    }

    // ── Direct platform market fetching ────────────

    case "FETCH_PLATFORM_MARKETS": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          platform: string;
          limit?: number;
        };
        const markets = await fetchPlatformDirect(params.platform, params.limit ?? 20);
        return { success: true, data: markets };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Failed to load markets",
        };
      }
    }

    case "SEARCH_PLATFORM_MARKETS": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          platform: string;
          query: string;
          limit?: number;
        };
        const markets = await searchPlatformDirect(params.platform, params.query, params.limit ?? 20);
        return { success: true, data: markets };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Search failed",
        };
      }
    }

    // ── Portfolio / Positions ─────────────────────

    case "GET_POSITIONS": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as {
          platform?: string;
          status?: string;
        };
        const qs = new URLSearchParams();
        if (params?.platform) qs.set("platform", params.platform);
        if (params?.status) qs.set("status", params.status);
        const positions = await botApiFetch(`/api/v1/positions?${qs.toString()}`);
        return { success: true, data: positions };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Failed to load positions",
        };
      }
    }

    case "GET_PNL_SUMMARY": {
      if (!cachedVault) cachedVault = await loadSession();
      if (!cachedVault) return { success: false, error: "Wallet is locked" };
      await resetAutoLockAlarm();

      try {
        const params = message.payload as { platform?: string } | undefined;
        const qs = new URLSearchParams();
        if (params?.platform) qs.set("platform", params.platform);
        const summary = await botApiFetch(`/api/v1/pnl/summary?${qs.toString()}`);
        return { success: true, data: summary };
      } catch (e) {
        return {
          success: false,
          error: e instanceof Error ? e.message : "Failed to load PnL",
        };
      }
    }

    default:
      return { success: false, error: "Unknown message type" };
  }
}

// ──────────────────────────────────────────
// Alarm listener
// ──────────────────────────────────────────

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === ALARM_NAME) {
    await lockWallet();
  }
});

// ──────────────────────────────────────────
// Initialization: restore auto-lock preference
// ──────────────────────────────────────────

(async () => {
  try {
    const result = await chrome.storage.local.get("preferences");
    if (result.preferences?.autoLockMinutes) {
      DEFAULT_AUTO_LOCK_MINUTES = result.preferences.autoLockMinutes;
    }
  } catch {
    // ignore
  }
})();
