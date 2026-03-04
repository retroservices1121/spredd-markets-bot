import type { HeadlineMatch } from "../core/types";

const PLATFORM_COLORS: Record<string, string> = {
  polymarket: "#6366f1",
  kalshi: "#f59e0b",
  opinion: "#10b981",
  limitless: "#3b82f6",
  myriad: "#8b5cf6",
};

const BADGE_CLASS = "spredd-overlay-badge";

export function injectBadge(match: HeadlineMatch): void {
  const el = document.querySelector(`[data-spredd-id="${match.elementId}"]`);
  if (!el) return;

  // Don't double-inject
  if (el.querySelector(`.${BADGE_CLASS}`)) return;

  const pct = Math.round(match.yesPrice * 100);
  const color = PLATFORM_COLORS[match.platform] || "#6366f1";

  const badge = document.createElement("span");
  badge.className = BADGE_CLASS;
  badge.title = `${match.platform}: ${match.question}`;
  badge.textContent = `${pct}% Yes`;

  // All inline styles to avoid CSS conflicts
  badge.style.cssText = [
    `background-color: ${color}`,
    "color: #fff",
    "font-size: 11px",
    "font-weight: 600",
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "padding: 2px 8px",
    "border-radius: 12px",
    "margin-left: 8px",
    "cursor: pointer",
    "display: inline-block",
    "vertical-align: middle",
    "line-height: 18px",
    "white-space: nowrap",
    "text-decoration: none",
    "opacity: 0.95",
  ].join("; ");

  badge.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    chrome.runtime.sendMessage({
      type: "OVERLAY_BADGE_CLICK",
      payload: { platform: match.platform, marketId: match.marketId },
    });
  });

  el.appendChild(badge);
}

export function removeAllBadges(): void {
  const badges = document.querySelectorAll(`.${BADGE_CLASS}`);
  for (const badge of badges) {
    badge.remove();
  }
  // Also clear data-spredd-id attributes
  const tagged = document.querySelectorAll("[data-spredd-id]");
  for (const el of tagged) {
    el.removeAttribute("data-spredd-id");
  }
}
