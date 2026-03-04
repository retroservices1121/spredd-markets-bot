import { scanHeadlines } from "./scanner";
import { injectBadge, removeAllBadges } from "./overlay";
import type { HeadlineMatch } from "../core/types";

let overlayActive = false;

async function checkEnabled(): Promise<boolean> {
  try {
    const res = await chrome.runtime.sendMessage({
      type: "GET_OVERLAY_ENABLED",
    });
    return res?.success && res?.data?.enabled === true;
  } catch {
    return false;
  }
}

async function matchAndInject(): Promise<void> {
  const headlines = scanHeadlines();
  if (headlines.length === 0) return;

  const entries = headlines.map((h) => ({
    text: h.text,
    elementId: h.elementId,
  }));

  try {
    const res = await chrome.runtime.sendMessage({
      type: "MATCH_HEADLINES",
      payload: { headlines: entries },
    });

    if (res?.success && Array.isArray(res.data)) {
      for (const match of res.data as HeadlineMatch[]) {
        injectBadge(match);
      }
    }
  } catch {
    // Wallet likely locked or extension context invalidated — silently fail
  }
}

async function activate(): Promise<void> {
  if (overlayActive) return;
  overlayActive = true;
  await matchAndInject();
  startObserver();
}

function deactivate(): void {
  overlayActive = false;
  stopObserver();
  removeAllBadges();
}

// MutationObserver for SPA / infinite scroll
let observer: MutationObserver | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function startObserver(): void {
  if (observer) return;
  observer = new MutationObserver(() => {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (overlayActive) matchAndInject();
    }, 5000);
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

function stopObserver(): void {
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = null;
  }
}

// Listen for live toggle changes
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.preferences) return;
  const newEnabled = changes.preferences.newValue?.overlayEnabled ?? false;
  if (newEnabled && !overlayActive) {
    activate();
  } else if (!newEnabled && overlayActive) {
    deactivate();
  }
});

// Initial load with delay
setTimeout(async () => {
  const enabled = await checkEnabled();
  if (enabled) {
    activate();
  }
}, 2000);
