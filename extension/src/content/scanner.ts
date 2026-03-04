export interface ScannedHeadline {
  text: string;
  elementId: string;
  element: Element;
}

const SKIP_ANCESTORS = ["nav", "footer", "aside", "header"];
const SELECTORS = [
  "article h1", "article h2", "article h3",
  "main h1", "main h2", "main h3",
  "h1", "h2", "h3",
  "[class*='headline']", "[class*='title']",
  "[role='heading']",
];

let idCounter = 0;

function isInsideSkippedAncestor(el: Element): boolean {
  let parent = el.parentElement;
  while (parent) {
    if (SKIP_ANCESTORS.includes(parent.tagName.toLowerCase())) return true;
    parent = parent.parentElement;
  }
  return false;
}

export function scanHeadlines(): ScannedHeadline[] {
  const seen = new Set<string>();
  const results: ScannedHeadline[] = [];

  for (const selector of SELECTORS) {
    let elements: NodeListOf<Element>;
    try {
      elements = document.querySelectorAll(selector);
    } catch {
      continue;
    }

    for (const el of elements) {
      // Skip already processed
      if (el.getAttribute("data-spredd-id")) continue;
      if (isInsideSkippedAncestor(el)) continue;

      const text = (el.textContent || "").trim();
      // Filter: 4+ words, <200 chars, no duplicates
      const wordCount = text.split(/\s+/).length;
      if (wordCount < 4 || text.length > 200) continue;
      if (seen.has(text)) continue;
      seen.add(text);

      const elementId = `spredd-h-${idCounter++}`;
      el.setAttribute("data-spredd-id", elementId);

      results.push({ text, elementId, element: el });

      if (results.length >= 20) return results;
    }
  }

  return results;
}
