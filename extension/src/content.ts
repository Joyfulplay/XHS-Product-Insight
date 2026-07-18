import type { PageProduct } from "./api/types";
import { parseSupportedProductPage } from "./product_page";

function readMeta(selector: string): string | null {
  return document.querySelector<HTMLMetaElement>(selector)?.content?.trim() || null;
}

function readFirstMeta(selectors: string[]): string | null {
  for (const selector of selectors) {
    const value = readMeta(selector);
    if (value) return value;
  }
  return null;
}

function readText(selectors: string[]): string | null {
  for (const selector of selectors) {
    const text = document.querySelector<HTMLElement>(selector)?.innerText?.trim();
    if (text) return text;
  }
  return null;
}

function readJsonLdTitle(): string | null {
  const scripts = Array.from(document.querySelectorAll<HTMLScriptElement>("script[type='application/ld+json']"));
  for (const script of scripts) {
    try {
      const parsed = JSON.parse(script.textContent ?? "") as unknown;
      const nodes = Array.isArray(parsed) ? parsed : [parsed];
      for (const node of nodes) {
        if (typeof node !== "object" || node === null) continue;
        const record = node as Record<string, unknown>;
        if (typeof record.name === "string" && record.name.trim()) return record.name.trim();
        if (typeof record.headline === "string" && record.headline.trim()) return record.headline.trim();
      }
    } catch {
      // Ignore invalid merchant-injected JSON-LD and continue with other sources.
    }
  }
  return null;
}

function findLabelValue(label: string): string | null {
  const candidates = Array.from(document.querySelectorAll<HTMLElement>("li, div, span"));
  const row = candidates.find((node) => {
    const text = node.innerText?.trim() ?? "";
    return text.startsWith(`${label}：`) || text.startsWith(`${label}:`);
  });
  return row?.innerText?.split(/[：:]/).slice(1).join(":").trim() || null;
}

function extractVariant(): Record<string, string> {
  const variant: Record<string, string> = {};
  const selectedNodes = Array.from(document.querySelectorAll<HTMLElement>(
    ".sku-item.selected, [class*='Sku'] [class*='selected'], [class*='sku'] [class*='selected'], [aria-checked='true']",
  ));

  selectedNodes.forEach((node, index) => {
    const value = node.innerText?.trim();
    if (!value) return;
    const group = node.closest<HTMLElement>("dl, [class*='Sku'], [class*='sku']");
    const label = group?.querySelector<HTMLElement>("dt, [class*='Label'], [class*='label']")?.innerText?.replace(/[：:]/g, "").trim();
    variant[label || `variant_${index + 1}`] = value;
  });

  return variant;
}

function cleanProductTitle(value: string): string | null {
  const cleaned = value
    .replace(/\s*[-_|]\s*(?:天猫(?:tmall(?:\.com)?)?|淘宝网|淘宝)(?:\s*.*)?$/iu, "")
    .replace(/\s+(?:天猫|淘宝网)\s*$/u, "")
    .trim();
  return cleaned || null;
}

function extractPageProduct(): PageProduct {
  const page = parseSupportedProductPage(location.href);
  const rawTitle =
    readJsonLdTitle() ??
    readFirstMeta(["meta[property='og:title']", "meta[name='title']", "meta[itemprop='name']"]) ??
    readText(["[data-title]", "[itemprop='name']", ".tb-detail-hd h1", ".ItemTitle--mainTitle--3CIjqW5", "h1"]) ??
    document.title;

  return {
    supported: Boolean(page?.sourceProductId),
    platform: "taobao",
    page_source: page?.source ?? "taobao",
    page_url: location.href,
    source_product_id: page?.sourceProductId ?? null,
    title: cleanProductTitle(rawTitle),
    brand: findLabelValue("品牌"),
    model: findLabelValue("型号"),
    variant: extractVariant(),
    page_language: document.documentElement.lang || "zh-CN",
  };
}

chrome.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
  if (typeof message === "object" && message !== null && "type" in message && message.type === "GET_PAGE_PRODUCT") {
    sendResponse(extractPageProduct());
  }
});
