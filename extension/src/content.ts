import type { PageProduct } from "./api/types";

const PRODUCT_HOSTS = new Set(["item.taobao.com"]);

function readMeta(selector: string): string | null {
  return document.querySelector<HTMLMetaElement>(selector)?.content?.trim() || null;
}

function readText(selectors: string[]): string | null {
  for (const selector of selectors) {
    const text = document.querySelector<HTMLElement>(selector)?.innerText?.trim();
    if (text) return text;
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

function extractPageProduct(): PageProduct {
  const url = new URL(location.href);
  const supported = PRODUCT_HOSTS.has(url.hostname) && url.pathname.endsWith("/item.htm");
  const sourceProductId = url.searchParams.get("id");

  return {
    supported: supported && Boolean(sourceProductId),
    platform: "taobao",
    page_url: location.href,
    source_product_id: sourceProductId,
    title: (
      readMeta('meta[property="og:title"]') ??
      readText(["[data-title]", ".ItemTitle--mainTitle--3CIjqW5", "h1"]) ??
      document.title.replace(/[-_]淘宝网.*$/, "").trim()
    ) || null,
    brand: findLabelValue("品牌"),
    model: findLabelValue("型号"),
    variant: {},
    page_language: document.documentElement.lang || "zh-CN",
  };
}

chrome.runtime.onMessage.addListener((message: unknown, _sender, sendResponse) => {
  if (typeof message === "object" && message !== null && "type" in message && message.type === "GET_PAGE_PRODUCT") {
    sendResponse(extractPageProduct());
  }
});
