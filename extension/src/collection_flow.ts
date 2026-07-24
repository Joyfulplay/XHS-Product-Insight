import type {
  CrawlConfig,
  CrawlJobData,
  CrawlerServiceState,
  FormattedCrawlerDataPreview,
  PageProduct,
  XiaohongshuLoginState,
} from "./api/types";

export type PreferenceWeightsForCollection = Record<string, number>;

export interface CollectionFlowState {
  service: CrawlerServiceState;
  login: XiaohongshuLoginState;
  keyword: string;
  keywordTouched: boolean;
  config: CrawlConfig;
  crawlJob: CrawlJobData;
  formattedPreview: FormattedCrawlerDataPreview | null;
  starting: boolean;
  submitting: boolean;
  submitMessage: string | null;
  formError: string | null;
}

export function createInitialCollectionFlowState(): CollectionFlowState {
  return {
    service: { status: "checking", checked_at: null, message: "正在检测本地采集服务" },
    login: { status: "not_logged_in", message: null },
    keyword: "",
    keywordTouched: false,
    config: { max_notes: 10, max_comments_per_note: 20 },
    crawlJob: { job_id: null, status: "idle", stage: "waiting", progress: 0, collected_notes: 0, collected_comments: 0, error_message: null },
    formattedPreview: null,
    starting: false,
    submitting: false,
    submitMessage: null,
    formError: null,
  };
}

export function defaultKeywordForProduct(product: PageProduct): string {
  const parts = [product.brand, product.model, product.title]
    .map((item) => item?.trim())
    .filter((item): item is string => Boolean(item));
  const deduped = parts.filter((item, index) => parts.findIndex((candidate) => candidate === item) === index);
  return deduped.join(" ").replace(/\s+/g, " ").trim();
}

export function clampInteger(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, Math.round(value)));
}

export function validateCrawlReady(state: CollectionFlowState): string | null {
  if (state.service.status !== "connected") return "请先连接本地采集服务";
  if (state.login.status !== "logged_in") return "请先连接小红书";
  if (!state.keyword.trim()) return "请输入搜索关键词";
  if (state.config.max_notes < 1 || state.config.max_notes > 50) return "最大笔记数需在 1 到 50 之间";
  if (state.config.max_comments_per_note < 0 || state.config.max_comments_per_note > 100) return "每篇最大评论数需在 0 到 100 之间";
  return null;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char] ?? char);
}

function statusDot(status: string): string {
  return status === "connected" || status === "logged_in" || status === "ready" || status === "completed" || status === "succeeded" ? "ok" : status === "not_started" || status === "backend_disconnected" || status === "auth_required" || status === "error" || status === "failed" || status === "expired" ? "bad" : "busy";
}

function serviceLabel(status: CrawlerServiceState["status"]): string {
  return ({ checking: "正在检测", connected: "已连接", not_started: "未启动" })[status];
}

function loginLabel(status: XiaohongshuLoginState["status"]): string {
  return ({
    not_logged_in: "未连接",
    opening_browser: "正在打开浏览器",
    waiting_for_login: "等待扫码",
    logged_in: "已登录",
    queued: "登录任务排队中",
    running: "等待登录完成",
    succeeded: "登录已确认",
    failed: "登录失败",
    expired: "登录已过期",
    error: "登录异常",
  })[status];
}

function crawlStageLabel(job: CrawlJobData): string {
  const label = ({
    idle: "等待开始",
    backend_disconnected: "服务连接失败",
    auth_required: "需要登录小红书",
    waiting_login: "等待登录",
    ready: "准备就绪",
    queued: "已排队",
    running: "正在采集笔记和评论",
    crawling: "正在采集笔记和评论",
    cleaning: "正在清洗数据",
    llm_extracting: "正在进行 LLM 抽取",
    analyzing: "正在统计分析",
    formatting: "正在格式化数据",
    succeeded: "采集完成",
    completed: "采集完成",
    failed: "采集失败",
    cancelled: "已取消",
    timeout: "任务超时",
  })[job.status];
  return job.message || job.error_message || label || job.stage || job.status;
}

function preferencePreview(preferences: PreferenceWeightsForCollection): string {
  return Object.entries(preferences)
    .filter(([, value]) => value > 0)
    .map(([key, value]) => `${key}:${value}`)
    .join(" / ");
}

export function renderCollectionFlow(
  state: CollectionFlowState,
  product: PageProduct,
  preferences: PreferenceWeightsForCollection,
  useMock: boolean,
): string {
  const validation = validateCrawlReady(state);
  const runningStatuses = ["queued", "running", "crawling", "cleaning", "llm_extracting", "analyzing", "formatting"];
  const canStart = !validation && !runningStatuses.includes(state.crawlJob.status);
  const isRunning = runningStatuses.includes(state.crawlJob.status);
  const startLabel = state.starting ? (["failed", "timeout"].includes(state.crawlJob.status) ? "正在重试..." : "正在创建...") : "开始采集";
  const retryLabel = state.starting ? "正在重试..." : "重试";
  const progress = Math.round(state.crawlJob.progress * 100);
  const productName = product.title || product.model || product.brand || "暂未识别商品名称";

  return `<section class="card collection-card">
    <div class="section-heading">
      <div><span class="eyebrow">${useMock ? "小红书采集 Mock" : "真实接口"}</span><h2>登录与评论采集</h2></div>
      <span class="collection-pill ${statusDot(state.service.status)}">${serviceLabel(state.service.status)}</span>
    </div>

    <div class="collection-block">
      <div class="collection-row">
        <div><strong>本地采集服务</strong><small>${escapeHtml(state.service.message ?? "用于连接本机 Python 爬虫桥接服务")}</small></div>
        <button class="secondary-button" id="crawler-check-button" ${state.service.status === "checking" ? "disabled" : ""}>重新检测</button>
      </div>
    </div>

    <div class="collection-block">
      <div class="collection-row">
        <div><strong>小红书登录</strong><small>${escapeHtml(state.login.message ?? loginLabel(state.login.status))}</small></div>
        <span class="collection-pill ${statusDot(state.login.status)}">${loginLabel(state.login.status)}</span>
      </div>
        <button class="primary-button inline" id="xhs-login-button" ${["opening_browser", "waiting_for_login", "queued", "running", "succeeded"].includes(state.login.status) ? "disabled" : ""}>${state.login.status === "logged_in" ? "重新登录" : "连接小红书"}</button>
    </div>

    <div class="collection-block">
      <label class="field-label" for="crawler-keyword">搜索关键词</label>
      <input class="text-input" id="crawler-keyword" value="${escapeHtml(state.keyword)}" placeholder="输入小红书搜索关键词" />
      <p class="field-hint">当前识别商品：${escapeHtml(productName)}</p>
    </div>

    <div class="collection-grid">
      <label class="field-label">最大笔记数<input class="number-input" id="crawler-max-notes" type="number" min="1" max="50" step="1" value="${state.config.max_notes}" /></label>
      <label class="field-label">每篇最大评论数<input class="number-input" id="crawler-max-comments" type="number" min="0" max="100" step="1" value="${state.config.max_comments_per_note}" /></label>
    </div>
    ${state.formError ? `<div class="form-error">${escapeHtml(state.formError)}</div>` : ""}

    <div class="collection-actions">
      ${["failed", "timeout"].includes(state.crawlJob.status) ? `<button class="primary-button inline" id="start-crawl-button" ${validation || state.starting ? "disabled" : ""}>${retryLabel}</button>` : `<button class="primary-button inline" id="start-crawl-button" ${canStart && !state.starting ? "" : "disabled"}>${startLabel}</button>`}
      ${state.crawlJob.status === "cancelled" ? `<button class="secondary-button" id="back-crawl-button">返回</button>` : ""}
      ${isRunning ? `<button class="secondary-button danger" id="cancel-crawl-button">取消采集</button>` : ""}
      ${validation && !isRunning ? `<small>${escapeHtml(validation)}</small>` : ""}
    </div>

    ${state.crawlJob.status !== "idle" ? `<div class="crawl-progress">
      <div><span>${crawlStageLabel(state.crawlJob)}</span><strong>${progress}%</strong></div>
      <div class="job-bar"><i style="width:${progress}%"></i></div>
      <small>已采集 ${state.crawlJob.collected_notes} 篇笔记，${state.crawlJob.collected_comments} 条评论${state.crawlJob.error_message ? ` · ${escapeHtml(state.crawlJob.error_message)}` : ""}</small>
    </div>` : ""}

    ${state.formattedPreview ? `<div class="formatted-preview">
      <div class="section-heading"><div><span class="eyebrow">格式化数据预览</span><h2>待提交后端</h2></div></div>
      <dl>
        <div><dt>商品信息</dt><dd>${escapeHtml(productName)}</dd></div>
        <div><dt>搜索关键词</dt><dd>${escapeHtml(state.formattedPreview.keyword)}</dd></div>
        <div><dt>用户偏好</dt><dd>${escapeHtml(preferencePreview(preferences) || "未设置")}</dd></div>
        <div><dt>笔记数量</dt><dd>${state.formattedPreview.note_count}</dd></div>
        <div><dt>评论数量</dt><dd>${state.formattedPreview.comment_count}</dd></div>
      </dl>
      <button class="primary-button inline" id="submit-analysis-button" ${state.submitting ? "disabled" : ""}>${state.submitting ? "正在模拟提交" : "提交给后端分析"}</button>
      ${state.submitMessage ? `<p class="field-hint strong">${escapeHtml(state.submitMessage)}</p>` : ""}
    </div>` : ""}
  </section>`;
}
