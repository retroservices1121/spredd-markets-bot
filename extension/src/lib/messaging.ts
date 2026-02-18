/**
 * Typed message passing between popup and background service worker.
 */

import type { Message, MessageResponse, MessageType } from "@/core/types";
import type { BotQuoteResponse, BotOrderResponse, Position, PnlSummaryData } from "@/core/markets";
import type { BotApiMarket } from "@/services/markets";

/**
 * Send a typed message to the background service worker and await a response.
 */
export function sendMessage<T = unknown>(
  type: MessageType,
  payload?: unknown
): Promise<MessageResponse<T>> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type, payload } as Message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({
          success: false,
          error: chrome.runtime.lastError.message ?? "Unknown error",
        });
        return;
      }
      resolve(response as MessageResponse<T>);
    });
  });
}

/** Convenience: unlock the vault */
export function unlockVault(password: string) {
  return sendMessage("UNLOCK_VAULT", { password });
}

/** Convenience: lock the vault */
export function lockVault() {
  return sendMessage("LOCK_VAULT");
}

/** Convenience: get current session state */
export function getSession() {
  return sendMessage<{ unlocked: boolean; hasVault: boolean }>("GET_SESSION");
}

/** Convenience: get decrypted vault data (only when unlocked) */
export function getVaultData() {
  return sendMessage("GET_VAULT_DATA");
}

/** Convenience: reset the auto-lock timer */
export function resetTimer() {
  return sendMessage("RESET_TIMER");
}

/** Convenience: set auto-lock timeout */
export function setAutoLock(minutes: number) {
  return sendMessage("SET_AUTO_LOCK", { minutes });
}

/** Convenience: get auto-lock timeout */
export function getAutoLock() {
  return sendMessage<{ minutes: number }>("GET_AUTO_LOCK");
}

// ── Trading via Bot API ───────────────────────────────────

/** Get a trade quote from the Bot API (signed by background worker) */
export function getTradeQuote(params: {
  platform: string;
  marketId: string;
  outcome: string;
  side: string;
  amount: string;
}) {
  return sendMessage<BotQuoteResponse>("GET_TRADE_QUOTE", params);
}

/** Execute a trade via the Bot API (signed by background worker) */
export function executeTrade(params: {
  platform: string;
  marketId: string;
  outcome: string;
  side: string;
  amount: string;
  slippageBps?: number;
}) {
  return sendMessage<BotOrderResponse>("EXECUTE_TRADE", params);
}

/** Check if the extension wallet is linked to a Spredd bot account */
export function checkWalletLinked() {
  return sendMessage<{ linked: boolean }>("CHECK_WALLET_LINKED");
}

// ── Multi-platform markets via Bot API ─────────────────────

/** Fetch markets from Bot API (non-Polymarket platforms, or all) */
export function getBotMarkets(params: {
  platform?: string;
  limit?: number;
  active?: boolean;
}) {
  return sendMessage<BotApiMarket[]>("GET_BOT_MARKETS", params);
}

/** Search markets via Bot API */
export function searchBotMarkets(params: { query: string; platform?: string }) {
  return sendMessage<BotApiMarket[]>("SEARCH_BOT_MARKETS", params);
}

/** Fetch a single market detail from Bot API */
export function getBotMarketDetail(params: {
  platform: string;
  marketId: string;
}) {
  return sendMessage<BotApiMarket>("GET_BOT_MARKET_DETAIL", params);
}

// ── Portfolio / Positions ──────────────────────────────────

/** Fetch user positions */
export function getPositions(params?: {
  platform?: string;
  status?: string;
}) {
  return sendMessage<Position[]>("GET_POSITIONS", params);
}

/** Fetch PnL summary */
export function getPnlSummary(params?: { platform?: string }) {
  return sendMessage<PnlSummaryData>("GET_PNL_SUMMARY", params);
}
