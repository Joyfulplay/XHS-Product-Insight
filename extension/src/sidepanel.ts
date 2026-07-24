import "./sidepanel.css";
import { ApiError, NetworkError, apiClient } from "./api/client";
import { crawlerClient } from "./api/crawler_client";
import { HttpRequestError } from "./api/http";
import { normalizeAnalysisResult } from "./analysis_view_model";
import {
  clampInteger,
  createInitialCollectionFlowState,
  defaultKeywordForProduct,
  renderCollectionFlow,
  validateCrawlReady,
  type CollectionFlowState,
} from "./collection_flow";
import { CLIENT_VERSION, USE_MOCK } from "./config";
import { parseSupportedProductPage } from "./product_page";
import type {
  AnalysisMode,
  AnalysisViewModel,
  Aspect,
  DemoProductScenario,
  DemoScenarioId,
  ErrorCode,
  EvidenceData,
  EvidenceQuery,
  CrawlStartRequest,
  CollectionResultResponse,
  FormattedCrawlerDataPreview,
  PageProduct,
  ProductAnalysisData,
  RefreshJobData,
  ResolveProductData,
} from "./api/types";

const appRoot = document.querySelector<HTMLDivElement>("#app");
if (!appRoot) throw new Error("Missing #app root");
const app: HTMLDivElement = appRoot;

type ViewState = "loading" | "restoring" | "unsupported" | "error" | "ready";

const state: {
  view: ViewState;
  pageProduct: PageProduct | null;
  resolve: ResolveProductData | null;
  analysis: ProductAnalysisData | null;
  collectionResult: unknown | null;
  mode: AnalysisMode;
  error: ApiError | NetworkError | null;
  evidence: EvidenceData | null;
  evidenceTitle: string;
  evidenceLoading: boolean;
  evidenceError: string | null;
  job: RefreshJobData | null;
  refreshing: boolean;
  notice: string | null;
  preferences: PreferenceWeights;
  collection: CollectionFlowState;
  demoScenarios: DemoProductScenario[];
  selectedDemoScenarioId: DemoScenarioId | null;
} = {
  view: "loading",
  pageProduct: null,
  resolve: null,
  analysis: null,
  collectionResult: null,
  mode: "trust_aware",
  error: null,
  evidence: null,
  evidenceTitle: "参考证据",
  evidenceLoading: false,
  evidenceError: null,
  job: null,
  refreshing: false,
  notice: null,
  preferences: { noise_cancellation: 5, sound_quality: 4, comfort: 3, battery_life: 3, microphone: 2, price_value: 3 },
  collection: createInitialCollectionFlowState(),
  demoScenarios: USE_MOCK && apiClient.getDemoScenarios ? apiClient.getDemoScenarios() : [],
  selectedDemoScenarioId: USE_MOCK && apiClient.getCurrentDemoScenarioId ? apiClient.getCurrentDemoScenarioId() : null,
};

type PreferenceKey = "noise_cancellation" | "sound_quality" | "comfort" | "battery_life" | "microphone" | "price_value";
type PreferenceWeights = Record<PreferenceKey, number>;

const preferenceLabels: Record<PreferenceKey, string> = {
  noise_cancellation: "通勤降噪",
  sound_quality: "音质",
  comfort: "长时间佩戴",
  battery_life: "续航",
  microphone: "通话效果",
  price_value: "性价比",
};

const controller = new AbortController();
window.addEventListener("beforeunload", () => controller.abort(), { once: true });
let initializationVersion = 0;
let crawlPollingVersion = 0;
let loginPollingVersion = 0;
let collectionRequestInFlight = false;
let collectionRestoreStarted = false;
let memoryStoredCollectionTask: StoredCollectionTask | null = null;
let currentProductKey: string | null = null;
const fetchedCompletedResults = new Set<string>();

const ACTIVE_COLLECTION_KEY = "trustlens.activeXhsCollection";
const PRODUCT_CACHE_INDEX_KEY = "trustlens.productResultIndex";
const PRODUCT_CACHE_KEY_PREFIX = "trustlens.productResult.";
const MAX_PRODUCT_CACHE_ENTRIES = 10;

interface StoredCollectionTask {
  jobId: string;
  query: string;
  pageUrl: string;
  sourceProductId: string | null;
  productKey?: string;
}

interface StoredProductResult {
  schemaVersion: 1;
  productKey: string;
  productTitle: string | null;
  productUrl: string;
  collectionJobId: string | null;
  taskStatus: CollectionFlowState["crawlJob"];
  crawlConfig: CollectionFlowState["config"];
  queryKeyword: string;
  rawCollectionResult: unknown | null;
  analysisResult: AnalysisViewModel | null;
  formattedPreview: FormattedCrawlerDataPreview | null;
  noteCount: number;
  commentCount: number;
  completedAt: string | null;
  savedAt: string;
}

type ChromeStorageLocal = typeof chrome.storage.local;

const platformNames: Record<string, string> = {
  xiaohongshu: "小红书",
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
  UPSTREAM_ERROR: { title: "小红书数据返回异常", detail: "暂时无法获取完整的小红书笔记与评论数据。" },
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

interface FitScoreResult {
  score: number | null;
  message: string | null;
  validAspectCount: number;
}

function clampScore(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function aspectScoreMap(analysis: ProductAnalysisData): Partial<Record<PreferenceKey, number>> {
  return Object.fromEntries(
    analysis.aspects
      .filter((aspect): aspect is Aspect & { aspect_code: PreferenceKey; trusted_sentiment_score: number } =>
        (Object.keys(preferenceLabels) as string[]).includes(aspect.aspect_code) && aspect.trusted_sentiment_score !== null,
      )
      .map((aspect) => [aspect.aspect_code, aspect.trusted_sentiment_score]),
  ) as Partial<Record<PreferenceKey, number>>;
}

function calculateFitScore(analysis: ProductAnalysisData, preferences = state.preferences): FitScoreResult {
  const scores = aspectScoreMap(analysis);
  const weighted = (Object.entries(preferences) as Array<[PreferenceKey, number]>)
    .filter(([key, weight]) => weight > 0 && scores[key] !== undefined)
    .map(([key, weight]) => ({ score: scores[key] ?? 0, weight }));

  if ((Object.values(preferences) as number[]).every((weight) => weight === 0)) {
    return { score: null, message: "请至少选择一个关注点", validAspectCount: 0 };
  }
  if (weighted.length < 2) {
    return { score: null, message: "数据不足，暂不能生成稳定推荐", validAspectCount: weighted.length };
  }

  const weightSum = weighted.reduce((sum, item) => sum + item.weight, 0);
  const fitScore = weighted.reduce((sum, item) => sum + item.score * item.weight, 0) / weightSum;
  return { score: clampScore(fitScore), message: null, validAspectCount: weighted.length };
}
function scoreFromSentimentDistribution(distribution: AnalysisViewModel["sample"]["sentiment_distribution"]): number | null {
  if (!distribution) return null;
  const positive = distribution.positive ?? 0;
  const neutral = distribution.neutral ?? 0;
  return clampScore(positive * 100 + neutral * 50);
}

function fitScoreFromCollectionView(view: AnalysisViewModel): FitScoreResult {
  const baseScore = scoreFromSentimentDistribution(view.sample.sentiment_distribution);
  if (baseScore === null) {
    return { score: null, message: "后端已完成采集，但当前结果缺少情感分布，暂不能生成推荐分。", validAspectCount: 0 };
  }
  if (view.sample.note_count < 3) {
    return { score: baseScore, message: "样本量偏少，推荐分仅作初步参考。", validAspectCount: view.attributes.length };
  }
  return { score: baseScore, message: null, validAspectCount: view.attributes.length };
}

function aspectCodeFromLabel(label: string, index: number): string {
  return `collection_aspect_${index}_${label.replace(/\s+/g, "_").slice(0, 24)}`;
}

function aspectsFromCollectionView(view: AnalysisViewModel): Aspect[] {
  const sentiment = view.sample.sentiment_distribution;
  const fallbackScore = scoreFromSentimentDistribution(sentiment);
  return view.attributes.slice(0, 8).map((attribute, index) => {
    const positive = attribute.positive_mentions ?? null;
    const negative = attribute.negative_mentions ?? null;
    const mentionCount = positive !== null || negative !== null ? (positive ?? 0) + (negative ?? 0) : view.sample.note_count;
    const positiveRatio = mentionCount > 0 && positive !== null ? positive / mentionCount : sentiment?.positive ?? null;
    const negativeRatio = mentionCount > 0 && negative !== null ? negative / mentionCount : sentiment?.negative ?? null;
    const neutralRatio = positiveRatio !== null && negativeRatio !== null ? Math.max(0, 1 - positiveRatio - negativeRatio) : sentiment?.neutral ?? null;
    const aspectScore = positiveRatio !== null && neutralRatio !== null ? clampScore(positiveRatio * 100 + neutralRatio * 50) : fallbackScore;
    return {
      aspect_code: aspectCodeFromLabel(attribute.name, index),
      aspect_label: attribute.name,
      mention_count: mentionCount,
      raw_sentiment_score: aspectScore,
      trusted_sentiment_score: aspectScore,
      positive_ratio: positiveRatio,
      neutral_ratio: neutralRatio,
      negative_ratio: negativeRatio,
      platform_disagreement_score: null,
      top_claim_ids: [],
      evidence_content_ids: [],
    };
  });
}

function recommendationGrade(value: number | null): string {
  if (value === null) return "待判断";
  if (value >= 85) return "强推荐";
  if (value >= 75) return "推荐";
  if (value >= 65) return "谨慎推荐";
  return "不优先推荐";
}

function recommendationReason(analysis: ProductAnalysisData): string {
  const scores = aspectScoreMap(analysis);
  const prioritized = (Object.entries(state.preferences) as Array<[PreferenceKey, number]>)
    .filter(([key, weight]) => weight > 0 && scores[key] !== undefined)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([key]) => `${preferenceLabels[key]} ${score(scores[key] ?? null)}`);
  return prioritized.length ? `当前权重下主要由 ${prioritized.join("、")} 拉动推荐分。` : "当前关注点不足，暂不能生成稳定推荐理由。";
}

function recommendationCaution(analysis: ProductAnalysisData): string {
  const scores = aspectScoreMap(analysis);
  const weakest = (Object.entries(state.preferences) as Array<[PreferenceKey, number]>)
    .filter(([key, weight]) => weight > 0 && scores[key] !== undefined)
    .sort((a, b) => (scores[a[0]] ?? 100) - (scores[b[0]] ?? 100))[0];
  return weakest ? `注意 ${preferenceLabels[weakest[0]]} 的可信评分为 ${score(scores[weakest[0]] ?? null)}，建议结合证据查看。` : "注意当前为演示数据，不代表当前页面商品的真实分析。";
}

function percent(value: number | null): string {
  return value === null ? "暂无数据" : `${Math.round(value * 100)}%`;
}

function dateTime(value: string | null): string {
  if (!value) return "暂无数据";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? text(value) : date.toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function countText(value: number | null): string {
  return value === null ? "暂无数据" : value.toLocaleString("zh-CN");
}

function listText(values: string[]): string {
  return values.length ? values.join("、") : "暂无数据";
}

function sentimentText(distribution: { positive: number | null; neutral: number | null; negative: number | null } | null): string {
  if (!distribution) return "暂无数据";
  return `正面 ${percent(distribution.positive)} / 中性 ${percent(distribution.neutral)} / 负面 ${percent(distribution.negative)}`;
}

function analysisSourceText(source: string | null): string {
  if (!source) return "分析来源：暂无数据";
  const normalized = source.toLowerCase();
  if (normalized.includes("llm") || normalized.includes("openai") || normalized.includes("model")) return "分析来源：正式 LLM";
  if (normalized.includes("rule") || normalized.includes("fallback")) return "分析来源：规则回退";
  if (normalized.includes("unavailable") || normalized.includes("disabled")) return "分析来源：暂不可用";
  return `分析来源：${source}`;
}

function attributeText(item: { name: string; positive_mentions: number | null; negative_mentions: number | null }): string {
  if (item.positive_mentions === null && item.negative_mentions === null) return escapeHtml(item.name);
  return `${escapeHtml(item.name)}：${item.positive_mentions ?? 0} 条正面提及，${item.negative_mentions ?? 0} 条负面提及`;
}

function resultPayload(result: unknown): unknown {
  if (!result || typeof result !== "object") return result;
  const record = result as { analysis?: unknown; data?: unknown; result?: unknown; raw?: unknown };
  return record.analysis ?? record.data ?? record.result ?? record.raw ?? result;
}

function numberAtPath(input: unknown, path: string): number | null {
  const value = path.split(".").reduce<unknown>((current, key) => {
    if (!current || typeof current !== "object") return undefined;
    return (current as Record<string, unknown>)[key];
  }, input);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function firstNumberAtPath(input: unknown, paths: string[]): number | null {
  for (const path of paths) {
    const value = numberAtPath(input, path);
    if (value !== null) return value;
  }
  return null;
}

function previewFromCollectionResult(result: unknown, request: CrawlStartRequest): FormattedCrawlerDataPreview {
  const view = normalizeAnalysisResult(result);
  return {
    product: request.page_product,
    keyword: request.keyword,
    preferences: request.preferences,
    note_count: view.sample.note_count,
    comment_count: view.sample.raw_comment_count ?? 0,
    generated_at: new Date().toISOString(),
  };
}

function previewFromCollectionResponse(result: CollectionResultResponse, request: CrawlStartRequest): FormattedCrawlerDataPreview {
  const payload = resultPayload(result);
  const normalizedPreview = previewFromCollectionResult(payload, request);
  const noteCount = firstNumberAtPath(payload, [
    "collection.note_count",
    "data.collection.note_count",
    "result.collection.note_count",
    "raw.collection.note_count",
    "raw.data.collection.note_count",
    "sample.note_count",
    "sample.notes_count",
    "statistics.note_count",
    "statistics.notes_count",
    "stats.note_count",
    "stats.notes_count",
    "counts.note_count",
    "counts.notes",
    "coverage.note_count",
    "coverage.notes_count",
    "note_count",
    "notes_count",
  ]);
  const commentCount = firstNumberAtPath(payload, [
    "collection.comment_count",
    "data.collection.comment_count",
    "result.collection.comment_count",
    "raw.collection.comment_count",
    "raw.data.collection.comment_count",
    "sample.raw_comment_count",
    "sample.comment_count",
    "sample.comments_count",
    "statistics.raw_comment_count",
    "statistics.comment_count",
    "statistics.comments_count",
    "stats.raw_comment_count",
    "stats.total_comments",
    "counts.raw_comments",
    "coverage.comment_count",
    "coverage.total_comment_count",
    "raw_comment_count",
    "comment_count",
    "comments_count",
  ]);
  return {
    ...normalizedPreview,
    ...result.formatted_preview,
    note_count: noteCount ?? result.formatted_preview?.note_count ?? normalizedPreview.note_count,
    comment_count: commentCount ?? result.formatted_preview?.comment_count ?? normalizedPreview.comment_count,
  };
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
        ${state.analysis ? `<div class="top-actions"><span class="data-badge data-demo">${USE_MOCK ? "演示数据" : modeLabel(state.analysis.data_status.mode)}</span><button class="icon-button" id="refresh-button" ${state.refreshing ? "disabled" : ""} title="更新分析" aria-label="更新分析">${state.refreshing ? "···" : "↻"}</button></div>` : ""}
      </header>
      ${content}
    </main>
    ${renderEvidenceDrawer()}
  `;
  bindEvents();
}

function render(): void {
  if (state.view === "restoring") {
    renderShell(`<section class="center-state"><div class="spinner"></div><h1>正在恢复上次结果</h1><p>先读取当前商品缓存，再检测采集服务状态…</p></section>`);
    return;
  }
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
  if (!state.analysis || !state.resolve || !state.pageProduct) return;

  const analysis = state.analysis;
  const pageProduct = state.pageProduct;
  const fallbackProduct = analysis.product ?? state.resolve.product;
  const collectionView = state.collectionResult ? normalizeAnalysisResult(state.collectionResult) : null;
  const summary = collectionView
    ? (collectionView.purchase_advice !== "暂无数据" ? collectionView.purchase_advice : collectionView.overall)
    : analysis.summaries[state.mode].one_sentence_summary;
  const collectionScore = collectionView ? scoreFromSentimentDistribution(collectionView.sample.sentiment_distribution) : null;
  const currentScore = collectionView ? collectionScore : (state.mode === "raw" ? analysis.overview.raw_sentiment_score : analysis.overview.trusted_sentiment_score);
  const rawScore = collectionView ? collectionScore : analysis.overview.raw_sentiment_score;
  const trustedScore = collectionView ? collectionScore : analysis.overview.trusted_sentiment_score;
  const confidence = collectionView ? collectionView.sample.confidence : analysis.overview.confidence;
  const fitScore = collectionView ? fitScoreFromCollectionView(collectionView) : calculateFitScore(analysis);
  const aspectRows = collectionView ? aspectsFromCollectionView(collectionView) : analysis.aspects;
  const failures = analysis.data_status.platform_failures ?? [];

  renderShell(`
    <div class="content">
      ${state.notice ? `<div class="notice"><span>!</span><p>${escapeHtml(state.notice)}</p><button id="dismiss-notice" aria-label="关闭">×</button></div>` : ""}
      ${analysis.data_status.mode === "cache" ? `<div class="status-banner">当前展示缓存数据${analysis.data_status.is_stale ? "，可能不是最新结果" : ""}。</div>` : ""}
      ${analysis.analysis_status === "partial" || failures.length ? `<div class="status-banner warning">部分小红书数据可用：${failures.length ? failures.map((item) => `${platformNames[item.platform] ?? "小红书"}（${item.reason}）`).join("；") : "小红书分析暂未完整完成"}</div>` : ""}

      <section class="product-card card">
        <div class="product-image"><span>TL</span></div>
        <div class="product-copy">
          <div class="eyebrow"><span class="match-dot"></span>当前浏览页面商品</div>
          <h1>${pageProduct.title ? escapeHtml(pageProduct.title) : "暂未识别商品标题"}</h1>
          <p class="product-details">${pageSourceLabel(pageProduct.page_url)} · 商品 ID：${text(pageProduct.source_product_id)} · ${text(pageProduct.brand)} · ${text(pageProduct.model)}</p>
          <p class="product-url" title="${escapeHtml(pageProduct.page_url)}">URL：${escapeHtml(pageProduct.page_url)}</p>
        </div>
      </section>

      <div class="category-banner"><strong>${USE_MOCK ? "试运行模式" : "真实采集模式"}</strong><span>${USE_MOCK ? "当前使用 Mock 数据完成 dry run。" : "当前插件已连接本地 FastAPI，并通过 /api/v1/xhs/collections 获取真实采集与分析结果。"}</span></div>
      <div class="category-banner"><strong>数据范围</strong><span>当前商品信息来自淘宝/天猫，评论分析数据仅来自小红书。</span></div>
      ${renderCollectionFlow(state.collection, pageProduct, state.preferences, USE_MOCK)}
      ${USE_MOCK ? `<div class="demo-banner"><strong>Mock 小红书数据</strong><span>当前分析结果为小红书笔记与评论 Mock 数据，不代表当前页面商品的真实分析。</span></div>` : ""}
      ${renderDemoSwitcher()}
      ${renderPreferenceControls()}
      ${collectionView ? renderCollectionRecommendationResult(collectionView, fitScore) : renderRecommendationResult(analysis, fitScore)}
      ${USE_MOCK ? renderSimilarProducts() : ""}

      <section class="summary-card card accent-card">
        <div class="section-heading"><div><span class="eyebrow">一句话购买参考</span><h2>${state.mode === "trust_aware" ? "可信感知结论" : "原始评价结论"}</h2></div>${renderToggle()}</div>
        <div class="demo-analysis-product"><span>${collectionView ? "当前真实采集商品" : "当前选择的演示分析商品"}</span><strong>${text(fallbackProduct.canonical_name)}</strong><small>${text(fallbackProduct.brand)} · ${text(fallbackProduct.model)}</small></div>
        <p class="summary-text">${text(summary)}</p>
        ${state.mode === "trust_aware" && analysis.summaries.changed_claims.length ? `<div class="change-box"><strong>为什么结论有变化？</strong>${analysis.summaries.changed_claims.map((claim) => `<button class="claim-link" data-claim="${escapeHtml(claim.claim_id)}"><span>${escapeHtml(claim.text)}</span>${escapeHtml(claim.reason)} <b>查看证据 →</b></button>`).join("")}</div>` : ""}
      </section>

      <section class="card">
        <div class="section-heading"><div><span class="eyebrow">小红书评论倾向</span><h2>情感与可信评分</h2></div><div class="score-orb"><b>${score(currentScore)}</b><small>/ 100</small></div></div>
        <div class="metric-grid">
          ${renderMetric("原始情感", rawScore, false)}
          ${renderMetric("可信情感", trustedScore, true)}
          ${renderMetric("按偏好推荐", fitScore.score, true)}
          <div class="confidence"><span>分析置信度</span><strong>${percent(confidence)}</strong></div>
        </div>
        <p class="fine-print">分数仅反映小红书笔记与评论中的评价倾向，并非商品客观质量分。</p>
      </section>

      ${renderXhsAnalysisOverview(state.collectionResult ?? analysis)}

      <section class="card">
        <div class="section-heading"><div><span class="eyebrow">具体表现</span><h2>方面评价</h2></div><small>点击查看证据</small></div>
        ${aspectRows.length ? `<div class="aspect-list">${aspectRows.map(renderAspect).join("")}</div>` : renderEmpty("暂无可展示的方面评价")}
      </section>

      ${collectionView ? renderCollectionRisk(collectionView) : renderRisk(analysis)}
      ${renderSources(state.collectionResult ?? analysis)}
      ${renderJob()}
      <footer><span>更新于 ${dateTime(analysis.updated_at)}</span><span>TrustLens · 仅供决策参考</span></footer>
    </div>
  `);
}

function renderDemoSwitcher(): string {
  if (!USE_MOCK || !state.demoScenarios.length) return "";
  return `<section class="card demo-switcher">
    <div class="section-heading"><div><span class="eyebrow">Mock dry run</span><h2>演示商品切换</h2></div></div>
    <p class="module-copy">切换演示商品，观察不同用户需求下的推荐结果变化。</p>
    <div class="demo-choice-list">
      ${state.demoScenarios.map((scenario) => {
        const selected = scenario.scenario_id === state.selectedDemoScenarioId;
        return `<button class="demo-choice ${selected ? "selected" : ""}" data-demo-scenario="${scenario.scenario_id}" aria-pressed="${selected}">
          <strong>${escapeHtml(scenario.display_name)}${selected ? " · 已选择" : ""}</strong>
          <span>${escapeHtml(scenario.description)}</span>
        </button>`;
      }).join("")}
    </div>
  </section>`;
}

function renderPreferenceControls(): string {
  return `<section class="card preference-card">
    <div class="section-heading"><div><span class="eyebrow">用户关注点</span><h2>偏好权重</h2></div></div>
    <div class="preference-controls">
      ${(Object.keys(preferenceLabels) as PreferenceKey[]).map((key) => `<label><span>${preferenceLabels[key]}</span><input type="range" min="0" max="5" step="1" value="${state.preferences[key]}" data-preference="${key}" /><b>${state.preferences[key]}</b></label>`).join("")}
    </div>
  </section>`;
}

function renderRecommendationResult(analysis: ProductAnalysisData, fitScore: FitScoreResult): string {
  return `<section class="card recommendation-card">
    <div class="section-heading"><div><span class="eyebrow">个性化推荐结果</span><h2>${recommendationGrade(fitScore.score)}</h2></div><div class="score-orb compact"><b>${score(fitScore.score)}</b><small>/ 100</small></div></div>
    ${fitScore.message ? `<div class="empty-state">${escapeHtml(fitScore.message)}</div>` : `<div class="recommendation-copy"><p><strong>推荐理由：</strong>${escapeHtml(recommendationReason(analysis))}</p><p><strong>注意事项：</strong>${escapeHtml(recommendationCaution(analysis))}</p></div>`}
  </section>`;
}
function renderCollectionRecommendationResult(view: AnalysisViewModel, fitScore: FitScoreResult): string {
  const reason = view.purchase_advice !== "暂无数据" ? view.purchase_advice : view.overall;
  const cautionParts = [
    view.weaknesses.length ? `主要顾虑：${listText(view.weaknesses)}` : "",
    view.sample.low_confidence ? "当前样本量或置信度偏低，建议结合代表性笔记一起判断。" : "",
  ].filter(Boolean);
  return `<section class="card recommendation-card">
    <div class="section-heading"><div><span class="eyebrow">个性化推荐结果</span><h2>${recommendationGrade(fitScore.score)}</h2></div><div class="score-orb compact"><b>${score(fitScore.score)}</b><small>/ 100</small></div></div>
    ${fitScore.message ? `<div class="status-banner warning">${escapeHtml(fitScore.message)}</div>` : ""}
    <div class="recommendation-copy"><p><strong>推荐理由：</strong>${escapeHtml(reason)}</p><p><strong>注意事项：</strong>${escapeHtml(cautionParts.join(" ") || "当前未发现明显高风险内容，仍建议查看代表性笔记原文。")}</p></div>
  </section>`;
}

function renderSimilarProducts(): string {
  const ranked = state.demoScenarios
    .map((scenario) => ({ scenario, fitScore: calculateFitScore(scenario.analysis).score }))
    .sort((a, b) => (b.fitScore ?? -1) - (a.fitScore ?? -1));
  return `<section class="card">
    <div class="section-heading"><div><span class="eyebrow">同类商品建议</span><h2>蓝牙耳机排序</h2></div></div>
    <div class="recommendation-list">
      ${ranked.map((item, index) => `<div class="recommendation-row ${item.scenario.scenario_id === state.selectedDemoScenarioId ? "current" : ""}"><span>${index + 1}</span><div><strong>${escapeHtml(item.scenario.analysis.product.canonical_name)}</strong><small>${escapeHtml(item.scenario.display_name)}${item.scenario.scenario_id === state.selectedDemoScenarioId ? " · 当前分析商品" : ""}</small></div><b>${score(item.fitScore)}</b></div>`).join("")}
    </div>
  </section>`;
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
    <div class="aspect-top"><div><strong>${escapeHtml(aspect.aspect_label)}</strong><small>${aspect.mention_count.toLocaleString("zh-CN")} 次提及 ${disagreement ? `<em>评论分歧较高</em>` : ""}</small></div><span class="aspect-score">${score(aspect.trusted_sentiment_score)}<small>/100</small></span></div>
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
function renderCollectionRisk(view: AnalysisViewModel): string {
  const riskCount = Math.round((view.sample.raw_comment_count ?? 0) * (view.sample.risk_negative_ratio ?? 0));
  return `<section class="card risk-card">
    <div class="section-heading"><div><span class="eyebrow">内容可信风险</span><h2>风险说明</h2></div><div class="risk-total"><b>${riskCount}</b><small>条 · ${percent(view.sample.risk_negative_ratio)}</small></div></div>
    ${view.risk_reasons.length ? `<div class="risk-reasons">${view.risk_reasons.map((reason) => `<div><span>${escapeHtml(reason.reason_label)}</span><b>${reason.count}</b></div>`).join("")}</div>` : `<p class="zero-risk">当前样本中未识别到高风险内容。</p>`}
    <div class="risk-note"><span>i</span><p>${text("风险/负面占比来自后端统计结果，仅提示内容需要谨慎参考，不代表评论一定虚假。")}</p></div>
  </section>`;
}

function renderXhsAnalysisOverview(analysis: ProductAnalysisData | unknown): string {
  const view = normalizeAnalysisResult(analysis);
  return `<section class="card xhs-result-card">
    <div class="section-heading"><div><span class="eyebrow">小红书评论分析</span><h2>分析结果</h2></div><small>${escapeHtml(analysisSourceText(view.sample.analysis_source))}</small></div>
    ${view.empty_message ? `<div class="status-banner warning">${escapeHtml(view.empty_message)}</div>` : ""}
    ${view.sample.low_confidence ? `<div class="status-banner warning">当前样本量或置信度偏低，购买建议仅作初步参考。</div>` : ""}
    <div class="xhs-stat-grid">
      <div><span>采集笔记数</span><strong>${view.sample.note_count.toLocaleString("zh-CN")}</strong></div>
      <div><span>原始评论数</span><strong>${countText(view.sample.raw_comment_count)}</strong></div>
      <div><span>清洗后有效评论数</span><strong>${countText(view.sample.valid_comment_count)}</strong></div>
      <div><span>风险/负面占比</span><strong>${percent(view.sample.risk_negative_ratio)}</strong></div>
    </div>
    <div class="xhs-insight-list">
      <p><strong>情感分布：</strong>${escapeHtml(sentimentText(view.sample.sentiment_distribution))}</p>
      <p><strong>总体评价：</strong>${escapeHtml(view.overall)}</p>
      <p><strong>高频优点：</strong>${escapeHtml(listText(view.strengths))}</p>
      <p><strong>高频缺点：</strong>${escapeHtml(listText(view.weaknesses))}</p>
      <p><strong>产品属性：</strong>${view.attributes.length ? view.attributes.map(attributeText).join("；") : "暂无数据"}</p>
      <p><strong>使用场景：</strong>${escapeHtml(listText(view.scenes))}</p>
      <p><strong>用户类型：</strong>${escapeHtml(listText(view.suitable_users))}</p>
      <p><strong>不适用人群：</strong>${escapeHtml(listText(view.unsuitable_users))}</p>
      <p><strong>购买建议：</strong>${escapeHtml(view.purchase_advice)}</p>
      <p><strong>高频关键词：</strong>${escapeHtml(view.keywords.length ? view.keywords.join(" / ") : "暂无数据")}</p>
    </div>
  </section>`;
}

function renderSources(analysis: ProductAnalysisData | unknown): string {
  const xhsSources = normalizeAnalysisResult(analysis).evidence;
  return `<section class="card">
    <div class="section-heading"><div><span class="eyebrow">${USE_MOCK ? "Mock 小红书内容" : "小红书内容"}</span><h2>小红书代表性内容</h2></div></div>
    <p class="field-hint">原文将在新标签页打开；若小红书网页要求登录，请在当前浏览器完成登录。该登录与采集服务登录相互独立。</p>
    ${xhsSources.length ? `<div class="source-list">${xhsSources.map((source) => `<button class="source-row external-link" data-source-url="${escapeHtml(source.source_url ?? "")}" ${source.source_url ? "" : "disabled"}><span class="source-platform">小红书</span><strong>${escapeHtml(source.title)}</strong><small>${dateTime(source.publish_time)} · 相关度 ${percent(source.relevance_score)}${source.risk_score === null ? "" : ` · 风险分数 ${source.risk_score.toFixed(2)}`}${source.quote ? ` · ${escapeHtml(source.quote)}` : ""}</small><i>↗</i></button>`).join("")}</div>` : renderEmpty("暂无小红书代表性内容")}
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
  document.querySelectorAll<HTMLInputElement>("[data-preference]").forEach((input) => {
    input.addEventListener("input", () => {
      const key = input.dataset.preference as PreferenceKey | undefined;
      if (!key) return;
      state.preferences[key] = Number(input.value);
      render();
    });
  });
  const keywordInput = document.querySelector<HTMLInputElement>("#crawler-keyword");
  keywordInput?.addEventListener("input", () => {
    const input = keywordInput;
    state.collection.keyword = input.value;
    state.collection.keywordTouched = true;
    state.collection.formError = validateCrawlReady(state.collection);
    render();
  });
  const maxNotesInput = document.querySelector<HTMLInputElement>("#crawler-max-notes");
  maxNotesInput?.addEventListener("change", () => {
    const input = maxNotesInput;
    state.collection.config.max_notes = clampInteger(Number(input.value), 1, 50);
    state.collection.formError = validateCrawlReady(state.collection);
    render();
  });
  const maxCommentsInput = document.querySelector<HTMLInputElement>("#crawler-max-comments");
  maxCommentsInput?.addEventListener("change", () => {
    const input = maxCommentsInput;
    state.collection.config.max_comments_per_note = clampInteger(Number(input.value), 0, 100);
    state.collection.formError = validateCrawlReady(state.collection);
    render();
  });
  document.querySelector<HTMLButtonElement>("#crawler-check-button")?.addEventListener("click", () => void checkCrawlerService());
  document.querySelector<HTMLButtonElement>("#xhs-login-button")?.addEventListener("click", () => void connectXiaohongshu());
  document.querySelector<HTMLButtonElement>("#start-crawl-button")?.addEventListener("click", () => void startCrawl());
  document.querySelector<HTMLButtonElement>("#cancel-crawl-button")?.addEventListener("click", () => void cancelCrawl());
  document.querySelector<HTMLButtonElement>("#back-crawl-button")?.addEventListener("click", resetCrawlTask);
  document.querySelector<HTMLButtonElement>("#submit-analysis-button")?.addEventListener("click", () => void submitFormattedPreview());
  document.querySelectorAll<HTMLButtonElement>("[data-demo-scenario]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!USE_MOCK || !apiClient.setDemoScenario) return;
      const scenarioId = button.dataset.demoScenario as DemoScenarioId | undefined;
      if (!scenarioId || scenarioId === state.selectedDemoScenarioId) return;
      state.selectedDemoScenarioId = scenarioId;
      state.analysis = apiClient.setDemoScenario(scenarioId);
      state.resolve = state.resolve ? { ...state.resolve, product: state.analysis.product } : state.resolve;
      state.evidence = null;
      state.evidenceError = null;
      state.evidenceLoading = false;
      render();
    });
  });
  document.querySelectorAll<HTMLButtonElement>("[data-aspect]").forEach((button) => {
    button.addEventListener("click", () => void openEvidence({ aspect_code: button.dataset.aspect }, `${button.dataset.label ?? "方面"} · 参考证据`));
  });
  document.querySelectorAll<HTMLButtonElement>("[data-claim]").forEach((button) => {
    button.addEventListener("click", () => void openEvidence({ claim_id: button.dataset.claim }, "结论变化 · 参考证据"));
  });
  document.querySelectorAll<HTMLButtonElement>("[data-source-url]").forEach((button) => {
    button.addEventListener("click", () => {
      const url = button.dataset.sourceUrl;
      if (url) openExternal(url);
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

function storageWarning(action: string, error?: unknown): void {
  console.warn(`[TrustLens] chrome.storage.local ${action} unavailable; using in-memory collection state.`, error);
}

function chromeStorageLocal(): ChromeStorageLocal | null {
  try {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) return chrome.storage.local;
  } catch (error: unknown) {
    storageWarning("check", error);
  }
  storageWarning("check");
  return null;
}

function storageGet<T>(keys?: string | string[] | Record<string, unknown> | null): Promise<T> {
  const storage = chromeStorageLocal();
  if (!storage) return Promise.resolve({} as T);
  return new Promise((resolve) => {
    try {
      storage.get(keys ?? null, (items) => {
        const runtimeError = chrome.runtime?.lastError;
        if (runtimeError) storageWarning("get", runtimeError.message);
        resolve((runtimeError ? {} : items) as T);
      });
    } catch (error: unknown) {
      storageWarning("get", error);
      resolve({} as T);
    }
  });
}

function storageSet(items: Record<string, unknown>): Promise<void> {
  const storage = chromeStorageLocal();
  if (!storage) return Promise.resolve();
  return new Promise((resolve) => {
    try {
      storage.set(items, () => {
        const runtimeError = chrome.runtime?.lastError;
        if (runtimeError) storageWarning("set", runtimeError.message);
        resolve();
      });
    } catch (error: unknown) {
      storageWarning("set", error);
      resolve();
    }
  });
}

function storageRemove(keys: string | string[]): Promise<void> {
  const storage = chromeStorageLocal();
  if (!storage) return Promise.resolve();
  return new Promise((resolve) => {
    try {
      storage.remove(keys, () => {
        const runtimeError = chrome.runtime?.lastError;
        if (runtimeError) storageWarning("remove", runtimeError.message);
        resolve();
      });
    } catch (error: unknown) {
      storageWarning("remove", error);
      resolve();
    }
  });
}

function normalizePageUrl(value: string): string {
  try {
    const url = new URL(value);
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (!["id", "itemId", "item_id"].includes(key)) url.searchParams.delete(key);
    }
    return url.toString();
  } catch {
    return value.trim();
  }
}

function productKeyFor(product: PageProduct): string {
  const stable = product.source_product_id?.trim() || normalizePageUrl(product.page_url) || product.title?.trim() || "unknown";
  return `taobao:${stable.toLowerCase()}`;
}

function productCacheKey(productKey: string): string {
  return `${PRODUCT_CACHE_KEY_PREFIX}${encodeURIComponent(productKey)}`;
}

async function saveProductResult(productKey: string, updates: Partial<StoredProductResult> = {}): Promise<void> {
  if (USE_MOCK || !state.pageProduct) return;
  const rawCollectionResult = updates.rawCollectionResult !== undefined ? updates.rawCollectionResult : state.collectionResult;
  const normalized = rawCollectionResult ? normalizeAnalysisResult(rawCollectionResult) : null;
  const preview = updates.formattedPreview !== undefined ? updates.formattedPreview : state.collection.formattedPreview;
  const now = new Date().toISOString();
  const record: StoredProductResult = {
    schemaVersion: 1,
    productKey,
    productTitle: state.pageProduct.title,
    productUrl: state.pageProduct.page_url,
    collectionJobId: state.collection.crawlJob.job_id,
    taskStatus: state.collection.crawlJob,
    crawlConfig: { ...state.collection.config },
    queryKeyword: state.collection.keyword,
    rawCollectionResult,
    analysisResult: normalized,
    formattedPreview: preview,
    noteCount: preview?.note_count ?? normalized?.sample.note_count ?? state.collection.crawlJob.collected_notes ?? 0,
    commentCount: preview?.comment_count ?? normalized?.sample.raw_comment_count ?? state.collection.crawlJob.collected_comments ?? 0,
    completedAt: ["completed", "succeeded"].includes(state.collection.crawlJob.status) ? (updates.completedAt ?? now) : (updates.completedAt ?? null),
    savedAt: now,
  };
  const indexItems = await storageGet<Record<string, string[]>>([PRODUCT_CACHE_INDEX_KEY]);
  const currentIndex = Array.isArray(indexItems[PRODUCT_CACHE_INDEX_KEY]) ? indexItems[PRODUCT_CACHE_INDEX_KEY] : [];
  const nextIndex = [productKey, ...currentIndex.filter((key) => key !== productKey)].slice(0, MAX_PRODUCT_CACHE_ENTRIES);
  const expiredKeys = currentIndex.filter((key) => !nextIndex.includes(key)).map(productCacheKey);
  await storageSet({ [productCacheKey(productKey)]: record, [PRODUCT_CACHE_INDEX_KEY]: nextIndex });
  if (expiredKeys.length) await storageRemove(expiredKeys);
}

async function loadProductResult(productKey: string): Promise<StoredProductResult | null> {
  if (USE_MOCK) return null;
  const items = await storageGet<Record<string, StoredProductResult>>([productCacheKey(productKey)]);
  const record = items[productCacheKey(productKey)];
  return record?.schemaVersion === 1 && record.productKey === productKey ? record : null;
}

function applyStoredProductResult(record: StoredProductResult): void {
  state.collection.config = { ...record.crawlConfig };
  state.collection.keyword = record.queryKeyword || state.collection.keyword;
  state.collection.keywordTouched = Boolean(record.queryKeyword);
  state.collection.crawlJob = { ...record.taskStatus };
  state.collection.formattedPreview = record.formattedPreview;
  state.collectionResult = record.rawCollectionResult;
  if (record.noteCount || record.commentCount) {
    state.collection.crawlJob = { ...state.collection.crawlJob, collected_notes: record.noteCount, collected_comments: record.commentCount };
  }
}

function getStoredCollectionTask(): Promise<StoredCollectionTask | null> {
  if (USE_MOCK) return Promise.resolve(null);
  const storage = chromeStorageLocal();
  if (!storage) return Promise.resolve(memoryStoredCollectionTask);
  return new Promise((resolve) => {
    try {
      storage.get(ACTIVE_COLLECTION_KEY, (items) => {
        const runtimeError = chrome.runtime?.lastError;
        if (runtimeError) {
          storageWarning("get", runtimeError.message);
          resolve(memoryStoredCollectionTask);
          return;
        }
        const value = items[ACTIVE_COLLECTION_KEY] as StoredCollectionTask | undefined;
        resolve(value?.jobId ? value : memoryStoredCollectionTask);
      });
    } catch (error: unknown) {
      storageWarning("get", error);
      resolve(memoryStoredCollectionTask);
    }
  });
}

function saveStoredCollectionTask(task: StoredCollectionTask): Promise<void> {
  if (USE_MOCK) return Promise.resolve();
  memoryStoredCollectionTask = task;
  const storage = chromeStorageLocal();
  if (!storage) return Promise.resolve();
  return new Promise((resolve) => {
    try {
      storage.set({ [ACTIVE_COLLECTION_KEY]: task }, () => {
        const runtimeError = chrome.runtime?.lastError;
        if (runtimeError) storageWarning("set", runtimeError.message);
        resolve();
      });
    } catch (error: unknown) {
      storageWarning("set", error);
      resolve();
    }
  });
}

function clearStoredCollectionTask(): Promise<void> {
  if (USE_MOCK) return Promise.resolve();
  memoryStoredCollectionTask = null;
  const storage = chromeStorageLocal();
  if (!storage) return Promise.resolve();
  return new Promise((resolve) => {
    try {
      storage.remove(ACTIVE_COLLECTION_KEY, () => {
        const runtimeError = chrome.runtime?.lastError;
        if (runtimeError) storageWarning("remove", runtimeError.message);
        resolve();
      });
    } catch (error: unknown) {
      storageWarning("remove", error);
      resolve();
    }
  });
}

function isSamePageTask(task: StoredCollectionTask, product: PageProduct): boolean {
  const productKey = productKeyFor(product);
  return task.productKey === productKey || task.pageUrl === product.page_url || (!!task.sourceProductId && task.sourceProductId === product.source_product_id);
}

function isCollectionRunning(status: string): boolean {
  return ["queued", "running", "crawling", "cleaning", "llm_extracting", "analyzing", "formatting"].includes(status);
}

function collectionTaskFromRequest(jobId: string, request: CrawlStartRequest): StoredCollectionTask {
  return {
    jobId,
    query: request.keyword,
    pageUrl: request.page_product.page_url,
    sourceProductId: request.page_product.source_product_id,
    productKey: productKeyFor(request.page_product),
  };
}

function findJobId(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  if ("job_id" in value && typeof (value as { job_id?: unknown }).job_id === "string") return (value as { job_id: string }).job_id;
  if ("jobId" in value && typeof (value as { jobId?: unknown }).jobId === "string") return (value as { jobId: string }).jobId;
  for (const nested of Object.values(value)) {
    const jobId = findJobId(nested);
    if (jobId) return jobId;
  }
  return null;
}

async function startRefresh(): Promise<void> {
  if (!state.resolve || state.refreshing) return;
  state.refreshing = true;
  state.notice = null;
  render();
  try {
    if (!USE_MOCK) {
      await checkCrawlerService();
      await restoreActiveCollectionTask();
      state.notice = "已重新检测服务和小红书登录状态。";
      return;
    }
    state.job = await apiClient.createRefreshJob(state.resolve.product.product_id, {
      platforms: ["xiaohongshu"],
      force: false,
      max_cache_age_hours: 24,
      requested_by: "chrome_extension",
      client_version: CLIENT_VERSION,
    }, controller.signal);
    render();
    let poll = 0;
    while (["queued", "running"].includes(state.job.status)) {
      await wait(Math.min(5000, 1000 + poll * 1000));
      state.job = await apiClient.getRefreshJob(state.job.job_id, controller.signal);
      poll += 1;
      render();
    }
    if (state.job.status === "succeeded" || state.job.status === "partially_succeeded") {
      if (state.job.status === "partially_succeeded") {
        const failed = state.job.platform_failures?.map((item) => platformNames[item.platform] ?? "小红书").join("、") ?? "小红书";
        state.notice = `分析已更新，但 ${failed} 更新失败，当前结果可能不完整。`;
      } else {
        state.notice = "分析已更新为最新结果。";
      }
      state.analysis = await apiClient.getProductAnalysis(state.resolve.product.product_id, { mode: "trust_aware" }, controller.signal);
    } else if (state.job.status === "failed") {
      state.notice = "更新任务失败，请稍后重试。";
    } else if (state.job.status === "cancelled") {
      state.notice = "更新任务已取消。";
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    state.notice = error instanceof ApiError
      ? (errorMessages[error.error.code]?.detail ?? "更新失败")
      : error instanceof NetworkError
        ? "无法连接服务，更新失败。"
        : error instanceof Error
          ? `更新失败：${error.message}`
          : "更新失败。";
  } finally {
    state.refreshing = false;
    render();
  }
}

function currentCrawlRequest(): CrawlStartRequest | null {
  if (!state.pageProduct) return null;
  return {
    keyword: state.collection.keyword.trim(),
    page_product: state.pageProduct,
    preferences: { ...state.preferences },
    config: { ...state.collection.config },
  };
}

async function checkCrawlerService(): Promise<void> {
  state.collection.service = { status: "checking", checked_at: null, message: "正在检测本地采集服务" };
  state.collection.formError = null;
  render();
  try {
    if (USE_MOCK) {
      state.collection.service = await crawlerClient.checkService(controller.signal);
    } else {
      let lastError: unknown = null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          const authStatus = await crawlerClient.getAuthStatus({}, controller.signal);
          applyAuthStatus(authStatus);
          lastError = null;
          break;
        } catch (error: unknown) {
          if (error instanceof DOMException && error.name === "AbortError") throw error;
          lastError = error;
          if (!(error instanceof HttpRequestError) || error.status !== null || attempt === 2) break;
          await wait(1000);
        }
      }
      if (lastError) {
        if (lastError instanceof HttpRequestError && lastError.status === null) {
          state.collection.service = { status: "not_started", checked_at: new Date().toISOString(), message: "无法连接服务：后端未启动或网络不可达" };
        } else {
          state.collection.service = { status: "connected", checked_at: new Date().toISOString(), message: "本地采集服务已连接，但认证状态检查失败" };
          state.collection.login = { ...state.collection.login, message: "认证状态暂时无法确认，已保留历史结果。" };
        }
      }
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    state.collection.service = { status: "not_started", checked_at: new Date().toISOString(), message: "无法连接服务：后端未启动或网络不可达" };
  } finally {
    state.collection.formError = validateCrawlReady(state.collection);
    render();
  }
}

async function connectXiaohongshu(): Promise<void> {
  if (["opening_browser", "waiting_for_login", "queued", "running", "succeeded"].includes(state.collection.login.status)) return;
  const version = ++loginPollingVersion;
  state.collection.login = { status: "opening_browser", message: "正在打开小红书登录窗口" };
  state.collection.submitMessage = null;
  render();
  try {
    const loginJob = await crawlerClient.startLogin("auto", true, controller.signal);
    if (!loginJob.job_id) throw new Error("登录任务创建失败：后端未返回 job_id");
    state.collection.login = { status: loginJob.status ?? "queued", message: loginJob.message ?? "登录任务已创建，请在打开的页面完成登录" };
    render();
    const deadline = Date.now() + 180_000;
    while (version === loginPollingVersion && Date.now() < deadline && ["queued", "running", "opening_browser", "waiting_for_login"].includes(state.collection.login.status)) {
      await wait(2000);
      const nextLoginJob = await crawlerClient.getLoginJob(loginJob.job_id, controller.signal);
      state.collection.login = { status: nextLoginJob.status, message: apiErrorText(nextLoginJob.error) ?? nextLoginJob.message ?? null };
      state.collection.formError = validateCrawlReady(state.collection);
      render();
      if (nextLoginJob.status === "succeeded") {
        const finalAuth = await crawlerClient.getAuthStatus({ refresh: true }, controller.signal);
        state.collection.login = finalAuth.authenticated === true
          ? { status: "logged_in", message: finalAuth.message ?? "已登录" }
          : { status: "error", message: apiErrorText(finalAuth.error) ?? finalAuth.message ?? "登录任务已完成，但认证状态仍未生效" };
        state.collection.formError = validateCrawlReady(state.collection);
        render();
        return;
      }
      if (nextLoginJob.status === "failed") {
        state.collection.login = { status: "error", message: apiErrorText(nextLoginJob.error) ?? nextLoginJob.message ?? "登录任务失败" };
        state.collection.formError = validateCrawlReady(state.collection);
        render();
        return;
      }
    }
    if (version === loginPollingVersion) {
      state.collection.login = { status: "error", message: "登录超时：3 分钟内未完成登录确认" };
      state.collection.formError = validateCrawlReady(state.collection);
      render();
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    state.collection.login = { status: "error", message: loginErrorMessage(error) };
    state.collection.formError = validateCrawlReady(state.collection);
    render();
  }
}

async function startCrawl(): Promise<void> {
  if (collectionRequestInFlight || state.collection.starting || isCollectionRunning(state.collection.crawlJob.status)) return;
  const request = currentCrawlRequest();
  if (!request) return;
  const validation = validateCrawlReady(state.collection);
  state.collection.formError = validation;
  if (validation) {
    render();
    return;
  }
  try {
    const authStatus = await crawlerClient.getAuthStatus({ refresh: true }, controller.signal);
    applyAuthStatus(authStatus);
    if (authStatus.authenticated !== true && authStatus.status !== "authenticated") {
      state.collection.login = { status: "expired", message: apiErrorText(authStatus.error) ?? authStatus.message ?? "小红书登录状态不存在或已过期，请重新登录" };
      state.collection.formError = validateCrawlReady(state.collection);
      render();
      return;
    }
  } catch (error: unknown) {
    if (isTemporaryAuthCheckError(error)) {
      state.collection.service = { status: error instanceof HttpRequestError && error.status === null ? "not_started" : "connected", checked_at: new Date().toISOString(), message: "采集服务认证检查暂时失败，历史结果已保留。" };
    } else {
      state.collection.login = { status: "error", message: loginErrorMessage(error) };
    }
    state.collection.formError = validateCrawlReady(state.collection);
    render();
    return;
  }
  const version = ++crawlPollingVersion;
  const requestProductKey = productKeyFor(request.page_product);
  collectionRequestInFlight = true;
  state.collection.starting = true;
  state.collection.formattedPreview = null;
  state.collection.submitMessage = null;
  state.collectionResult = null;
  state.collection.crawlJob = { job_id: null, status: "idle", stage: "waiting", progress: 0, collected_notes: 0, collected_comments: 0, error_message: null };
  render();
  try {
    const storedTask = await getStoredCollectionTask();
    if (storedTask && state.pageProduct && isSamePageTask(storedTask, state.pageProduct)) {
      state.collection.keyword = storedTask.query;
      await pollCollectionJob(storedTask.jobId, { ...request, keyword: storedTask.query }, version);
      return;
    }
    const startRequest = request;
    const startedJob = await crawlerClient.startCrawl(startRequest, controller.signal);
    if (startedJob.job_id) await saveStoredCollectionTask(collectionTaskFromRequest(startedJob.job_id, startRequest));
    state.collection.crawlJob = startedJob;
    await saveProductResult(requestProductKey);
    state.collection.starting = false;
    collectionRequestInFlight = false;
    render();
    if (startedJob.job_id) await pollCollectionJob(startedJob.job_id, startRequest, version);
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    if (error instanceof HttpRequestError && error.status === 409) {
      const existingJobId = findJobId(error.body);
      if (existingJobId) {
        await saveStoredCollectionTask(collectionTaskFromRequest(existingJobId, request));
        state.collection.starting = false;
        collectionRequestInFlight = false;
        await pollCollectionJob(existingJobId, request, version);
        return;
      }
    }
    state.collection.crawlJob = {
      job_id: state.collection.crawlJob.job_id,
      status: "failed",
      stage: "failed",
      progress: state.collection.crawlJob.progress,
      collected_notes: state.collection.crawlJob.collected_notes,
      collected_comments: state.collection.crawlJob.collected_comments,
      error_message: error instanceof HttpRequestError && error.status === 409 ? "已有采集任务正在运行，请等待任务完成后重试。" : collectionErrorMessage(error) || "采集任务启动或轮询失败",
    };
    await saveProductResult(requestProductKey);
    render();
  } finally {
    state.collection.starting = false;
    collectionRequestInFlight = false;
    render();
  }
}

async function pollCollectionJob(jobId: string, request: CrawlStartRequest, version: number): Promise<void> {
  const requestProductKey = productKeyFor(request.page_product);
  state.collection.crawlJob = { ...state.collection.crawlJob, job_id: jobId, status: state.collection.crawlJob.status === "idle" ? "queued" : state.collection.crawlJob.status };
  state.collection.formError = null;
  await saveProductResult(requestProductKey);
  render();
  while (version === crawlPollingVersion && isCollectionRunning(state.collection.crawlJob.status)) {
    await wait(1000);
    state.collection.crawlJob = await crawlerClient.getCrawlJob(jobId, controller.signal);
    if (currentProductKey === requestProductKey) await saveProductResult(requestProductKey);
    render();
  }
  if (version !== crawlPollingVersion) return;
  if (state.collection.crawlJob.status === "completed") {
    if (fetchedCompletedResults.has(jobId)) return;
    fetchedCompletedResults.add(jobId);
    const result = await crawlerClient.getCollectionResult(jobId, controller.signal);
    const payload = resultPayload(result);
    const preview = previewFromCollectionResponse(result, request);
    if (currentProductKey !== requestProductKey) {
      const previousPage = state.pageProduct;
      state.pageProduct = request.page_product;
      state.collectionResult = payload;
      state.collection.formattedPreview = preview;
      state.collection.crawlJob = { ...state.collection.crawlJob, collected_notes: preview.note_count, collected_comments: preview.comment_count };
      await saveProductResult(requestProductKey, { rawCollectionResult: payload, formattedPreview: preview, completedAt: new Date().toISOString() });
      state.pageProduct = previousPage;
      return;
    }
    state.collection.formattedPreview = preview;
    state.collectionResult = payload;
    state.collection.crawlJob = { ...state.collection.crawlJob, collected_notes: preview.note_count, collected_comments: preview.comment_count };
    await saveProductResult(requestProductKey, { rawCollectionResult: payload, formattedPreview: preview, completedAt: new Date().toISOString() });
    await clearStoredCollectionTask();
    render();
    return;
  }
  if (["failed", "timeout", "cancelled"].includes(state.collection.crawlJob.status)) {
    if (state.collection.crawlJob.status === "timeout") state.collection.crawlJob.error_message = state.collection.crawlJob.error_message ?? "任务超时，请重试。";
    await saveProductResult(requestProductKey);
    await clearStoredCollectionTask();
    render();
  }
}

async function restoreActiveCollectionTask(): Promise<void> {
  if (USE_MOCK || collectionRestoreStarted || !state.pageProduct) return;
  collectionRestoreStarted = true;
  try {
    const storedTask = await getStoredCollectionTask();
    if (!storedTask || !state.pageProduct || !isSamePageTask(storedTask, state.pageProduct)) return;
    const request = currentCrawlRequest();
    if (!request) return;
    const restoredRequest = { ...request, keyword: storedTask.query };
    state.collection.keyword = storedTask.query;
    const version = ++crawlPollingVersion;
    state.collection.crawlJob = await crawlerClient.getCrawlJob(storedTask.jobId, controller.signal);
    render();
    if (isCollectionRunning(state.collection.crawlJob.status)) {
      await saveProductResult(productKeyFor(state.pageProduct));
      await pollCollectionJob(storedTask.jobId, restoredRequest, version);
      return;
    }
    if (state.collection.crawlJob.status === "completed") {
      const result = await crawlerClient.getCollectionResult(storedTask.jobId, controller.signal);
      const payload = resultPayload(result);
      const preview = previewFromCollectionResponse(result, restoredRequest);
      state.collection.formattedPreview = preview;
      state.collectionResult = payload;
      state.collection.crawlJob = { ...state.collection.crawlJob, collected_notes: preview.note_count, collected_comments: preview.comment_count };
      await saveProductResult(productKeyFor(state.pageProduct), { rawCollectionResult: payload, formattedPreview: preview, completedAt: new Date().toISOString() });
      await clearStoredCollectionTask();
      render();
      return;
    }
    if (["failed", "timeout", "cancelled"].includes(state.collection.crawlJob.status)) {
      await clearStoredCollectionTask();
      await saveProductResult(productKeyFor(state.pageProduct));
      render();
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    if (error instanceof HttpRequestError && error.status === 404) await clearStoredCollectionTask();
    state.collection.crawlJob = {
      job_id: state.collection.crawlJob.job_id,
      status: "failed",
      stage: "failed",
      progress: state.collection.crawlJob.progress,
      collected_notes: state.collection.crawlJob.collected_notes,
      collected_comments: state.collection.crawlJob.collected_comments,
      error_message: collectionErrorMessage(error) || "恢复采集任务失败",
    };
    render();
  } finally {
    collectionRestoreStarted = false;
  }
}

async function cancelCrawl(): Promise<void> {
  const jobId = state.collection.crawlJob.job_id;
  crawlPollingVersion += 1;
  if (!jobId) {
    state.collection.crawlJob = { ...state.collection.crawlJob, status: "cancelled", stage: "cancelled", progress: 0 };
    render();
    return;
  }
  try {
    state.collection.crawlJob = await crawlerClient.cancelCrawl(jobId, controller.signal);
  } catch {
    state.collection.crawlJob = { ...state.collection.crawlJob, status: "cancelled", stage: "cancelled" };
  }
  state.collection.formattedPreview = null;
  void clearStoredCollectionTask();
  if (currentProductKey) void saveProductResult(currentProductKey);
  render();
}

function resetCrawlTask(): void {
  crawlPollingVersion += 1;
  state.collection.crawlJob = { job_id: null, status: "idle", stage: "waiting", progress: 0, collected_notes: 0, collected_comments: 0, error_message: null };
  state.collection.formattedPreview = null;
  state.collection.submitMessage = null;
  state.collection.starting = false;
  collectionRequestInFlight = false;
  void clearStoredCollectionTask();
  if (currentProductKey) void saveProductResult(currentProductKey);
  render();
}

async function submitFormattedPreview(): Promise<void> {
  if (!state.collection.formattedPreview || state.collection.submitting) return;
  state.collection.submitting = true;
  state.collection.submitMessage = null;
  render();
  try {
    await wait(200);
    state.collection.submitMessage = USE_MOCK ? "Mock：已模拟提交给后端分析。" : "后端已完成采集与分析，页面下方已展示真实分析结果。";
  } finally {
    state.collection.submitting = false;
    render();
  }
}

async function activePageProduct(): Promise<PageProduct | null> {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url || !parseSupportedProductPage(tab.url)?.sourceProductId) return null;
    const page = await chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_PRODUCT" });
    return isPageProduct(page) ? page : null;
  } catch {
    return null;
  }
}

function isPageProduct(value: unknown): value is PageProduct {
  return (
    typeof value === "object" &&
    value !== null &&
    "supported" in value &&
    "page_url" in value &&
    "source_product_id" in value &&
    typeof value.page_url === "string"
  );
}

function pageSourceLabel(pageUrl: string): "淘宝" | "天猫" {
  return parseSupportedProductPage(pageUrl)?.source === "tmall" ? "天猫" : "淘宝";
}

function fallbackResolveForPage(page: PageProduct): ResolveProductData {
  return {
    product: {
      product_id: page.source_product_id ?? page.page_url,
      canonical_name: page.title ?? "当前商品",
      brand: page.brand,
      model: page.model,
      display_image_url: null,
    },
    match_status: "page_title",
    match_confidence: null,
    requires_user_confirmation: false,
    candidates: [],
  };
}

function fallbackAnalysisForPage(page: PageProduct): ProductAnalysisData {
  const product = fallbackResolveForPage(page).product;
  return {
    analysis_id: `page-${product.product_id}`,
    product,
    analysis_status: "pending",
    data_status: { mode: "live", platform_failures: [] },
    coverage: { total_content_count: 0, platforms: ["xiaohongshu"] },
    overview: { raw_sentiment_score: null, trusted_sentiment_score: null, confidence: null },
    summaries: { raw: { one_sentence_summary: "开始采集后生成小红书评论分析。" }, trust_aware: { one_sentence_summary: "开始采集后生成小红书评论分析。" }, changed_claims: [] },
    platform_comparison: [],
    aspects: [],
    risk_summary: { high_risk_count: 0, high_risk_ratio: null, risk_reason_distribution: [], display_note: null },
    top_sources: [],
    updated_at: null,
  };
}

function collectionErrorMessage(error: unknown): string {
  if (error instanceof HttpRequestError) return error.message;
  if (error instanceof Error) return error.message;
  if (error instanceof DOMException && error.name === "AbortError") return "";
  return "后端业务失败：采集任务启动或轮询失败";
}

function apiErrorText(error: unknown): string | null {
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && "message" in error) return String((error as { message: unknown }).message);
  return null;
}

function applyAuthStatus(authStatus: Awaited<ReturnType<typeof crawlerClient.getAuthStatus>>): void {
  state.collection.service = { status: authStatus.service_status ?? "connected", checked_at: new Date().toISOString(), message: authStatus.message ?? "本地采集服务已连接" };
  if (authStatus.authenticated === true || authStatus.status === "authenticated") {
    state.collection.login = { status: "logged_in", message: authStatus.message ?? "采集服务已登录" };
    return;
  }
  const loginStatus = authStatus.login_status ?? (authStatus.status === "unavailable" ? "error" : "not_logged_in");
  state.collection.login = {
    status: loginStatus,
    message: apiErrorText(authStatus.error) ?? authStatus.message ?? state.collection.login.message,
  };
}

function isTemporaryAuthCheckError(error: unknown): boolean {
  return error instanceof HttpRequestError && (error.status === null || error.status >= 500);
}

function loginErrorMessage(error: unknown): string {
  if (error instanceof HttpRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "登录任务失败";
}

async function initialize(): Promise<void> {
  const version = ++initializationVersion;
  state.view = "restoring";
  state.error = null;
  render();
  try {
    const page = await activePageProduct();
    if (version !== initializationVersion) return;
    if (!page?.supported) {
      state.pageProduct = null;
      state.resolve = null;
      state.analysis = null;
      state.view = "unsupported";
      render();
      return;
    }
    const productChanged = state.pageProduct?.page_url !== page.page_url || state.pageProduct?.source_product_id !== page.source_product_id;
    const nextProductKey = productKeyFor(page);
    if (productChanged) {
      crawlPollingVersion += 1;
      currentProductKey = nextProductKey;
      state.collection.crawlJob = { job_id: null, status: "idle", stage: "waiting", progress: 0, collected_notes: 0, collected_comments: 0, error_message: null };
      state.collection.formattedPreview = null;
      state.collection.submitMessage = null;
      state.collectionResult = null;
      state.collection.keywordTouched = false;
    }
    state.pageProduct = page;
    if (!state.collection.keywordTouched) {
      state.collection.keyword = defaultKeywordForProduct(page);
    }
    if (USE_MOCK) {
      state.resolve = await apiClient.resolveProduct(page, controller.signal);
      if (version !== initializationVersion) return;
      state.analysis = await apiClient.getProductAnalysis(state.resolve.product.product_id, { mode: "trust_aware" }, controller.signal);
      if (version !== initializationVersion) return;
      if (state.analysis.analysis_status === "pending") {
        throw new ApiError({ code: "ANALYSIS_NOT_READY", message: "分析尚未准备", details: {}, retryable: false });
      }
    } else {
      state.resolve = fallbackResolveForPage(page);
      state.analysis = fallbackAnalysisForPage(page);
    }
    const cached = await loadProductResult(nextProductKey);
    if (version !== initializationVersion) return;
    if (cached) applyStoredProductResult(cached);
    state.view = "ready";
    render();
    if (!USE_MOCK) {
      await restoreActiveCollectionTask();
      if (version !== initializationVersion) return;
      await checkCrawlerService();
      if (version !== initializationVersion) return;
    }
    state.view = "ready";
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    state.error = error instanceof ApiError || error instanceof NetworkError ? error : new NetworkError();
    state.view = "error";
  }
  render();
}

chrome.tabs.onActivated.addListener(() => void initialize());
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.status === "complete" || changeInfo.url !== undefined)) {
    void initialize();
  }
});
window.addEventListener("focus", () => void initialize());

void initialize();
