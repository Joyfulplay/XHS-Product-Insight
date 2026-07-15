import "./sidepanel.css";
import { ApiError, NetworkError, apiClient } from "./api/client";
import type {
  AnalysisMode,
  Aspect,
  ErrorCode,
  EvidenceData,
  EvidenceQuery,
  PageProduct,
  ProductAnalysisData,
  RefreshJobData,
  ResolveProductData,
} from "./api/types";

const appRoot = document.querySelector<HTMLDivElement>("#app");
if (!appRoot) throw new Error("Missing #app root");
const app: HTMLDivElement = appRoot;

type ViewState = "loading" | "unsupported" | "error" | "ready";

const state: {
  view: ViewState;
  resolve: ResolveProductData | null;
  analysis: ProductAnalysisData | null;
  mode: AnalysisMode;
  error: ApiError | NetworkError | null;
  evidence: EvidenceData | null;
  evidenceTitle: string;
  evidenceLoading: boolean;
  evidenceError: string | null;
  job: RefreshJobData | null;
  refreshing: boolean;
  notice: string | null;
} = {
  view: "loading",
  resolve: null,
  analysis: null,
  mode: "trust_aware",
  error: null,
  evidence: null,
  evidenceTitle: "参考证据",
  evidenceLoading: false,
  evidenceError: null,
  job: null,
  refreshing: false,
  notice: null,
};

const controller = new AbortController();
window.addEventListener("beforeunload", () => controller.abort(), { once: true });

const platformNames: Record<string, string> = {
  taobao: "淘宝",
  xiaohongshu: "小红书",
  bilibili: "B站",
};

const stageNames: Record<string, string> = {
  waiting: "等待开始",
  collecting: "采集内容",
  cleaning: "清洗内容",
  matching: "匹配商品",
  modeling: "分析评价",
  summarizing: "生成摘要",
  persisting: "保存结果",
  completed: "已完成",
};

const errorMessages: Record<ErrorCode, { title: string; detail: string }> = {
  INVALID_REQUEST: { title: "请求信息不完整", detail: "请重新打开商品页后再试。" },
  PRODUCT_NOT_FOUND: { title: "未找到商品", detail: "当前商品可能尚未收录。" },
  ANALYSIS_NOT_READY: { title: "分析尚未准备", detail: "可以点击更新分析创建分析任务。" },
  UNSUPPORTED_PLATFORM: { title: "暂不支持此平台", detail: "目前仅支持淘宝商品详情页。" },
  PRODUCT_NOT_IDENTIFIED: { title: "无法识别商品", detail: "请确认已打开带有商品 ID 的淘宝详情页。" },
  RATE_LIMITED: { title: "请求过于频繁", detail: "请稍后再试。" },
  UPSTREAM_ERROR: { title: "部分来源返回异常", detail: "暂时无法获取完整的跨平台数据。" },
  UPSTREAM_UNAVAILABLE: { title: "数据来源暂不可用", detail: "服务恢复后可以重试。" },
  MODEL_UNAVAILABLE: { title: "分析服务暂不可用", detail: "已采集内容不会丢失，请稍后重试。" },
  INTERNAL_ERROR: { title: "服务出现异常", detail: "请稍后重试；若持续发生可提供请求编号。" },
};

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char] ?? char);
}

function text(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "暂无数据" : escapeHtml(value);
}

function score(value: number | null): string {
  return value === null ? "暂无数据" : String(Math.round(value));
}

function percent(value: number | null): string {
  return value === null ? "暂无数据" : `${Math.round(value * 100)}%`;
}

function dateTime(value: string | null): string {
  if (!value) return "暂无数据";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? text(value) : date.toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function safeExternalUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function modeLabel(mode: string): string {
  return ({ live: "实时", cache: "缓存", demo: "演示" })[mode] ?? "未知";
}

function renderShell(content: string): void {
  app.innerHTML = `
    <main class="shell">
      <header class="topbar">
        <div class="brand"><span class="brand-mark">T</span><span>TrustLens</span></div>
        ${state.analysis ? `<div class="top-actions"><span class="data-badge data-${state.analysis.data_status.mode}">${modeLabel(state.analysis.data_status.mode)}</span><button class="icon-button" id="refresh-button" ${state.refreshing ? "disabled" : ""} title="更新分析" aria-label="更新分析">${state.refreshing ? "···" : "↻"}</button></div>` : ""}
      </header>
      ${content}
    </main>
    ${renderEvidenceDrawer()}
  `;
  bindEvents();
}

function render(): void {
  if (state.view === "loading") {
    renderShell(`<section class="center-state"><div class="spinner"></div><h1>正在识别当前商品</h1><p>读取页面信息并准备分析结果…</p></section>`);
    return;
  }
  if (state.view === "unsupported") {
    renderShell(`<section class="center-state"><div class="state-icon">⌁</div><h1>不支持当前页面</h1><p>请打开淘宝商品详情页（item.taobao.com/item.htm?id=…）后再使用 TrustLens。</p></section>`);
    return;
  }
  if (state.view === "error" && state.error) {
    renderShell(renderError(state.error));
    return;
  }
  if (!state.analysis || !state.resolve) return;

  const analysis = state.analysis;
  const product = analysis.product ?? state.resolve.product;
  const summary = analysis.summaries[state.mode].one_sentence_summary;
  const currentScore = state.mode === "raw" ? analysis.overview.raw_sentiment_score : analysis.overview.trusted_sentiment_score;
  const failures = analysis.data_status.platform_failures ?? [];

  renderShell(`
    <div class="content">
      ${state.notice ? `<div class="notice"><span>!</span><p>${escapeHtml(state.notice)}</p><button id="dismiss-notice" aria-label="关闭">×</button></div>` : ""}
      ${analysis.data_status.mode === "cache" ? `<div class="status-banner">当前展示缓存数据${analysis.data_status.is_stale ? "，可能不是最新结果" : ""}。</div>` : ""}
      ${analysis.analysis_status === "partial" || failures.length ? `<div class="status-banner warning">部分数据可用：${failures.length ? failures.map((item) => `${platformNames[item.platform]}（${item.reason}）`).join("；") : "部分平台分析失败"}</div>` : ""}
      ${renderJob()}

      <section class="product-card card">
        <div class="product-image">${product.display_image_url ? `<img src="${escapeHtml(product.display_image_url)}" alt="" />` : `<span>TL</span>`}</div>
        <div class="product-copy">
          <div class="eyebrow"><span class="match-dot"></span>${state.resolve.requires_user_confirmation ? "识别结果待确认" : state.resolve.match_status === "matched" ? "商品已识别" : text(state.resolve.match_status)} · ${percent(state.resolve.match_confidence)}</div>
          <h1>${text(product.canonical_name)}</h1>
          <p>${text(product.brand)} · ${text(product.model)}</p>
        </div>
      </section>

      <section class="summary-card card accent-card">
        <div class="section-heading"><div><span class="eyebrow">一句话购买参考</span><h2>${state.mode === "trust_aware" ? "可信感知结论" : "原始评价结论"}</h2></div>${renderToggle()}</div>
        <p class="summary-text">${text(summary)}</p>
        ${state.mode === "trust_aware" && analysis.summaries.changed_claims.length ? `<div class="change-box"><strong>为什么结论有变化？</strong>${analysis.summaries.changed_claims.map((claim) => `<button class="claim-link" data-claim="${escapeHtml(claim.claim_id)}"><span>${escapeHtml(claim.text)}</span>${escapeHtml(claim.reason)} <b>查看证据 →</b></button>`).join("")}</div>` : ""}
      </section>

      <section class="card">
        <div class="section-heading"><div><span class="eyebrow">总体评价倾向</span><h2>综合评分</h2></div><div class="score-orb"><b>${score(currentScore)}</b><small>/ 100</small></div></div>
        <div class="metric-grid">
          ${renderMetric("Raw", analysis.overview.raw_sentiment_score, false)}
          ${renderMetric("Trust-aware", analysis.overview.trusted_sentiment_score, true)}
          <div class="confidence"><span>分析置信度</span><strong>${percent(analysis.overview.confidence)}</strong></div>
        </div>
        <p class="fine-print">分数反映已分析评价的情感倾向，并非商品客观质量分。</p>
      </section>

      <section class="card">
        <div class="section-heading"><div><span class="eyebrow">跨平台观察</span><h2>平台对比</h2></div><small>${analysis.coverage.total_content_count.toLocaleString("zh-CN")} 条内容</small></div>
        ${analysis.platform_comparison.length ? `<div class="platform-list">${analysis.platform_comparison.map((item) => `
          <div class="platform-row">
            <div class="platform-meta"><span class="platform-icon platform-${item.platform}">${platformNames[item.platform]?.slice(0, 1)}</span><div><strong>${platformNames[item.platform] ?? item.platform}</strong><small>${item.content_count.toLocaleString("zh-CN")} 条</small></div></div>
            <div class="mini-scores"><span>Raw <b>${score(item.raw_sentiment_score)}</b></span><span>可信 <b>${score(item.trusted_sentiment_score)}</b></span></div>
            <div class="risk-cell"><small>高风险</small><b>${percent(item.high_risk_ratio)}</b></div>
          </div>`).join("")}</div>` : renderEmpty("暂无平台对比数据")}
      </section>

      <section class="card">
        <div class="section-heading"><div><span class="eyebrow">具体表现</span><h2>方面评价</h2></div><small>点击查看证据</small></div>
        ${analysis.aspects.length ? `<div class="aspect-list">${analysis.aspects.map(renderAspect).join("")}</div>` : renderEmpty("暂无可展示的方面评价")}
      </section>

      ${renderRisk(analysis)}
      ${renderSources(analysis)}
      <footer><span>更新于 ${dateTime(analysis.updated_at)}</span><span>TrustLens · 仅供决策参考</span></footer>
    </div>
  `);
}

function renderToggle(): string {
  return `<div class="toggle" role="group" aria-label="分析模式">
    <button data-mode="raw" class="${state.mode === "raw" ? "active" : ""}">Raw</button>
    <button data-mode="trust_aware" class="${state.mode === "trust_aware" ? "active" : ""}">Trust-aware</button>
  </div>`;
}

function renderMetric(label: string, value: number | null, trusted: boolean): string {
  const width = value === null ? 0 : Math.max(0, Math.min(100, value));
  return `<div class="metric"><div><span>${label}</span><strong>${score(value)}</strong></div><div class="bar"><i class="${trusted ? "trusted" : ""}" style="width:${width}%"></i></div></div>`;
}

function renderAspect(aspect: Aspect): string {
  const disagreement = aspect.platform_disagreement_score !== null && aspect.platform_disagreement_score >= 0.45;
  return `<button class="aspect-row" data-aspect="${escapeHtml(aspect.aspect_code)}" data-label="${escapeHtml(aspect.aspect_label)}">
    <div class="aspect-top"><div><strong>${escapeHtml(aspect.aspect_label)}</strong><small>${aspect.mention_count.toLocaleString("zh-CN")} 次提及 ${disagreement ? `<em>平台分歧较高</em>` : ""}</small></div><span class="aspect-score">${score(aspect.trusted_sentiment_score)}<small>/100</small></span></div>
    <div class="sentiment-bar" aria-label="正面 ${percent(aspect.positive_ratio)}，中性 ${percent(aspect.neutral_ratio)}，负面 ${percent(aspect.negative_ratio)}">
      <i class="positive" style="width:${(aspect.positive_ratio ?? 0) * 100}%"></i><i class="neutral" style="width:${(aspect.neutral_ratio ?? 0) * 100}%"></i><i class="negative" style="width:${(aspect.negative_ratio ?? 0) * 100}%"></i>
    </div>
    <div class="legend"><span>正面 ${percent(aspect.positive_ratio)}</span><span>中性 ${percent(aspect.neutral_ratio)}</span><span>负面 ${percent(aspect.negative_ratio)}</span></div>
  </button>`;
}

function renderRisk(analysis: ProductAnalysisData): string {
  const risk = analysis.risk_summary;
  return `<section class="card risk-card">
    <div class="section-heading"><div><span class="eyebrow">内容可信风险</span><h2>风险说明</h2></div><div class="risk-total"><b>${risk.high_risk_count}</b><small>条 · ${percent(risk.high_risk_ratio)}</small></div></div>
    ${risk.risk_reason_distribution.length ? `<div class="risk-reasons">${risk.risk_reason_distribution.map((reason) => `<div><span>${escapeHtml(reason.reason_label)}</span><b>${reason.count}</b></div>`).join("")}</div>` : `<p class="zero-risk">当前样本中未识别到高风险内容。</p>`}
    <div class="risk-note"><span>i</span><p>${text(risk.display_note ?? "风险分数表示内容需要谨慎参考，不代表评论一定虚假。")}</p></div>
  </section>`;
}

function renderSources(analysis: ProductAnalysisData): string {
  return `<section class="card">
    <div class="section-heading"><div><span class="eyebrow">延伸阅读</span><h2>推荐来源</h2></div></div>
    ${analysis.top_sources.length ? `<div class="source-list">${analysis.top_sources.map((source, index) => `<button class="source-row external-link" data-source-index="${index}"><span class="source-platform">${platformNames[source.platform] ?? source.platform}</span><strong>${escapeHtml(source.source_title)}</strong><small>${dateTime(source.publish_time)} · 相关度 ${percent(source.relevance_score)} · 风险分数 ${source.risk_score === null ? "暂无数据" : source.risk_score.toFixed(2)}</small><i>↗</i></button>`).join("")}</div>` : renderEmpty("暂无推荐来源")}
  </section>`;
}

function renderJob(): string {
  if (!state.job || !state.refreshing) return "";
  const progress = Math.round(state.job.progress * 100);
  return `<section class="job-card"><div><span>正在更新分析</span><strong>${stageNames[state.job.stage] ?? state.job.stage} · ${progress}%</strong></div><div class="job-bar"><i style="width:${progress}%"></i></div><small>${state.job.estimated_seconds === null ? "正在估算剩余时间" : `预计还需 ${state.job.estimated_seconds} 秒`}</small></section>`;
}

function renderEmpty(message: string): string {
  return `<div class="empty-state"><span>—</span>${escapeHtml(message)}</div>`;
}

function renderError(error: ApiError | NetworkError): string {
  if (error instanceof ApiError) {
    const copy = errorMessages[error.error.code] ?? { title: "暂时无法显示分析", detail: "请稍后再试。" };
    return `<section class="center-state error-state"><div class="state-icon">!</div><h1>${copy.title}</h1><p>${copy.detail}</p>${error.requestId ? `<small>请求编号：${escapeHtml(error.requestId)}</small>` : ""}${error.error.code === "ANALYSIS_NOT_READY" && state.resolve ? `<button class="primary-button" id="refresh-button">更新分析</button>` : error.error.retryable ? `<button class="primary-button" id="retry-button">重试</button>` : ""}</section>`;
  }
  return `<section class="center-state error-state"><div class="state-icon">!</div><h1>后端不可用</h1><p>无法连接 TrustLens 分析服务，请检查服务是否已启动。</p><button class="primary-button" id="retry-button">重试</button></section>`;
}

function renderEvidenceDrawer(): string {
  if (!state.evidenceLoading && !state.evidence && !state.evidenceError) return "";
  let body = "";
  if (state.evidenceLoading) body = `<div class="drawer-loading"><div class="spinner"></div><p>正在加载证据…</p></div>`;
  else if (state.evidenceError) body = `<div class="empty-state">${escapeHtml(state.evidenceError)}</div>`;
  else if (!state.evidence?.items.length) body = renderEmpty("暂无相关证据") ;
  else body = `<div class="evidence-list">${state.evidence.items.map((item, index) => `<article class="evidence-item"><div><span class="source-platform">${platformNames[item.platform] ?? item.platform}</span><span class="risk-level risk-${item.risk_level ?? "unknown"}">${item.risk_level === "high" ? "高风险" : item.risk_level === "medium" ? "中风险" : item.risk_level === "low" ? "低风险" : "风险暂无"}</span></div><h3>${escapeHtml(item.source_title)}</h3><blockquote>${text(item.quote)}</blockquote>${item.context_text ? `<p>${escapeHtml(item.context_text)}</p>` : ""}<footer><span>${dateTime(item.publish_time)} · 风险分数 ${item.risk_score === null ? "暂无数据" : item.risk_score.toFixed(2)}</span><button class="evidence-link" data-evidence-index="${index}">查看原文 ↗</button></footer></article>`).join("")}</div>`;
  return `<div class="drawer-backdrop" id="drawer-backdrop"></div><aside class="drawer" aria-label="参考证据"><header><div><span class="eyebrow">可追溯依据</span><h2>${escapeHtml(state.evidenceTitle)}</h2></div><button id="close-drawer" aria-label="关闭">×</button></header>${body}<p class="drawer-note">证据用于解释分析结论；风险分数不代表内容一定虚假。</p></aside>`;
}

function bindEvents(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode === "raw" ? "raw" : "trust_aware";
      render();
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-aspect]").forEach((button) => {
    button.addEventListener("click", () => void openEvidence({ aspect_code: button.dataset.aspect }, `${button.dataset.label ?? "方面"} · 参考证据`));
  });
  document.querySelectorAll<HTMLButtonElement>("[data-claim]").forEach((button) => {
    button.addEventListener("click", () => void openEvidence({ claim_id: button.dataset.claim }, "结论变化 · 参考证据"));
  });
  document.querySelectorAll<HTMLButtonElement>("[data-source-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const source = state.analysis?.top_sources[Number(button.dataset.sourceIndex)];
      if (source) openExternal(source.source_url);
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-evidence-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const item = state.evidence?.items[Number(button.dataset.evidenceIndex)];
      if (item) openExternal(item.source_url);
    });
  });
  document.querySelector<HTMLButtonElement>("#refresh-button")?.addEventListener("click", () => void startRefresh());
  document.querySelector<HTMLButtonElement>("#retry-button")?.addEventListener("click", () => void initialize());
  document.querySelector<HTMLButtonElement>("#dismiss-notice")?.addEventListener("click", () => { state.notice = null; render(); });
  document.querySelector<HTMLButtonElement>("#close-drawer")?.addEventListener("click", closeEvidence);
  document.querySelector<HTMLDivElement>("#drawer-backdrop")?.addEventListener("click", closeEvidence);
}

function openExternal(value: string): void {
  const url = safeExternalUrl(value);
  if (url) void chrome.tabs.create({ url });
}

function closeEvidence(): void {
  state.evidence = null;
  state.evidenceError = null;
  state.evidenceLoading = false;
  render();
}

async function openEvidence(query: EvidenceQuery, title: string): Promise<void> {
  if (!state.resolve) return;
  state.evidenceTitle = title;
  state.evidence = null;
  state.evidenceError = null;
  state.evidenceLoading = true;
  render();
  try {
    state.evidence = await apiClient.getEvidence(state.resolve.product.product_id, { ...query, limit: 20 }, controller.signal);
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    state.evidenceError = error instanceof ApiError ? (errorMessages[error.error.code]?.detail ?? "证据加载失败") : "无法连接服务，请稍后重试";
  } finally {
    state.evidenceLoading = false;
    render();
  }
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, milliseconds);
    controller.signal.addEventListener("abort", () => { window.clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
  });
}

async function startRefresh(): Promise<void> {
  if (!state.resolve || state.refreshing) return;
  state.refreshing = true;
  state.notice = null;
  render();
  try {
    state.job = await apiClient.createRefresh(state.resolve.product.product_id, controller.signal);
    render();
    let poll = 0;
    while (["queued", "running"].includes(state.job.status)) {
      await wait(Math.min(5000, 1000 + poll * 1000));
      state.job = await apiClient.getJob(state.job.job_id, controller.signal);
      poll += 1;
      render();
    }
    if (state.job.status === "succeeded" || state.job.status === "partially_succeeded") {
      if (state.job.status === "partially_succeeded") {
        const failed = state.job.platform_failures?.map((item) => platformNames[item.platform] ?? item.platform).join("、") ?? "部分平台";
        state.notice = `分析已更新，但 ${failed} 更新失败，当前结果可能不完整。`;
      } else {
        state.notice = "分析已更新为最新结果。";
      }
      state.analysis = await apiClient.getAnalysis(state.resolve.product.product_id, "trust_aware", controller.signal);
    } else if (state.job.status === "failed") {
      state.notice = "更新任务失败，请稍后重试。";
    } else if (state.job.status === "cancelled") {
      state.notice = "更新任务已取消。";
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    state.notice = error instanceof ApiError ? (errorMessages[error.error.code]?.detail ?? "更新失败") : "无法连接服务，更新失败。";
  } finally {
    state.refreshing = false;
    render();
  }
}

async function activePageProduct(): Promise<PageProduct | null> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url) return null;
  const url = new URL(tab.url);
  if (url.hostname !== "item.taobao.com" || !url.pathname.endsWith("/item.htm") || !url.searchParams.get("id")) return null;
  try {
    return (await chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_PRODUCT" })) as PageProduct;
  } catch {
    return null;
  }
}

async function initialize(): Promise<void> {
  state.view = "loading";
  state.error = null;
  render();
  try {
    const page = await activePageProduct();
    if (!page?.supported) {
      state.view = "unsupported";
      render();
      return;
    }
    state.resolve = await apiClient.resolveProduct(page, controller.signal);
    state.analysis = await apiClient.getAnalysis(state.resolve.product.product_id, "trust_aware", controller.signal);
    if (state.analysis.analysis_status === "pending") {
      throw new ApiError({ code: "ANALYSIS_NOT_READY", message: "分析尚未准备", details: {}, retryable: false });
    }
    state.view = "ready";
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    state.error = error instanceof ApiError || error instanceof NetworkError ? error : new NetworkError();
    state.view = "error";
  }
  render();
}

void initialize();
