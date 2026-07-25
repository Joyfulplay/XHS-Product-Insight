export function sourceLinkProblem(value: string, expiresAt: string | null): string | null {
  try {
    const url = new URL(value);
    const isTemporaryXhsLink =
      (url.hostname === "127.0.0.1" || url.hostname === "localhost")
      && /^\/api\/v1\/xhs\/collections\/[^/]+\/notes\/[^/]+\/open$/.test(url.pathname);
    if (!isTemporaryXhsLink) return null;
  } catch {
    return null;
  }
  if (!expiresAt) return "本次采集未获得可用原文链接，请重新采集。";
  const expiresAtMs = Date.parse(expiresAt);
  return Number.isFinite(expiresAtMs) && expiresAtMs > Date.now()
    ? null
    : "原文链接已过期，请重新采集。";
}
