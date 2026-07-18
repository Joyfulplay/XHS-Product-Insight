export type ProductPageSource = "taobao" | "tmall";

export interface SupportedProductPageUrl {
  url: URL;
  source: ProductPageSource;
  sourceProductId: string | null;
}

function parseUrl(rawUrl: string): URL | null {
  try {
    return new URL(rawUrl);
  } catch {
    return null;
  }
}

function isTaobaoProductPageUrl(url: URL): boolean {
  return url.protocol === "https:" && url.hostname === "item.taobao.com" && url.pathname === "/item.htm";
}

function isTmallProductPageUrl(url: URL): boolean {
  return (
    url.protocol === "https:" &&
    ["detail.tmall.com", "chaoshi.detail.tmall.com", "detail.m.tmall.com", "detail.tmall.hk"].includes(url.hostname) &&
    url.pathname === "/item.htm"
  );
}

export function isSupportedProductPage(rawUrl: string): boolean {
  const url = parseUrl(rawUrl);
  return Boolean(url && (isTaobaoProductPageUrl(url) || isTmallProductPageUrl(url)));
}

export function extractProductId(rawUrl: string): string | null {
  const id = parseUrl(rawUrl)?.searchParams.get("id")?.trim() ?? null;
  return id && /^\d+$/.test(id) ? id : null;
}

export function parseSupportedProductPage(rawUrl: string): SupportedProductPageUrl | null {
  const url = parseUrl(rawUrl);
  if (!url || !isSupportedProductPage(rawUrl)) return null;
  return {
    url,
    source: isTaobaoProductPageUrl(url) ? "taobao" : "tmall",
    sourceProductId: extractProductId(rawUrl),
  };
}
