import { MOCK_SCENARIO, USE_MOCK } from "../config";
import { delay, requestJson } from "./http";
import { apiPaths } from "./paths";
import type {
  AuthStatusResponse,
  BrowserChoice,
  CrawlJobData,
  CrawlStartRequest,
  CrawlerServiceState,
  CollectionJobResponse,
  CollectionResultResponse,
  CollectionStartResponse,
  FormattedCrawlerDataPreview,
  LoginJobResponse,
  LoginStartResponse,
  PageProduct,
  XiaohongshuLoginState,
} from "./types";

export interface CrawlerApiClient {
  checkService(signal?: AbortSignal): Promise<CrawlerServiceState>;
  getAuthStatus(signal?: AbortSignal): Promise<AuthStatusResponse>;
  startLogin(browser?: BrowserChoice, signal?: AbortSignal): Promise<LoginStartResponse>;
  getLoginJob(jobId: string, signal?: AbortSignal): Promise<LoginJobResponse>;
  getLoginStatus(signal?: AbortSignal): Promise<XiaohongshuLoginState>;
  startCollection(source: PageProduct, queryOverride?: string, signal?: AbortSignal): Promise<CollectionStartResponse>;
  getCollectionJob(jobId: string, signal?: AbortSignal): Promise<CollectionJobResponse>;
  getCollectionResult(jobId: string, signal?: AbortSignal): Promise<CollectionResultResponse>;
  startCrawl(request: CrawlStartRequest, signal?: AbortSignal): Promise<CrawlJobData>;
  getCrawlJob(jobId: string, signal?: AbortSignal): Promise<CrawlJobData>;
  cancelCrawl(jobId: string, signal?: AbortSignal): Promise<CrawlJobData>;
  createFormattedPreview(request: CrawlStartRequest, job: CrawlJobData): FormattedCrawlerDataPreview;
}

let mockLoginPollCount = 0;
let mockCrawlPollCount = 0;
let mockCancelled = false;
let lastRequest: CrawlStartRequest | null = null;

function previewFrom(request: CrawlStartRequest, job: CrawlJobData): FormattedCrawlerDataPreview {
  return {
    product: request.page_product,
    keyword: request.keyword,
    preferences: request.preferences,
    note_count: job.collected_notes,
    comment_count: job.collected_comments,
    generated_at: new Date().toISOString(),
  };
}

function errorText(error: unknown): string | null {
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && "message" in error) return String((error as { message: unknown }).message);
  return null;
}

function crawlJobFromCollection(job: CollectionStartResponse | CollectionJobResponse, fallbackJobId: string | null = null): CrawlJobData {
  const status = job.status === "succeeded" ? "completed" : job.status;
  const errorValue = "error_message" in job ? job.error_message : null;
  const errorMessage = typeof errorValue === "string" ? errorValue : errorText(job.error);
  return {
    job_id: job.job_id ?? fallbackJobId,
    status,
    stage: job.stage ?? status,
    progress: job.progress ?? (status === "completed" ? 1 : 0),
    collected_notes: "collected_notes" in job ? (job.collected_notes ?? 0) : 0,
    collected_comments: "collected_comments" in job ? (job.collected_comments ?? 0) : 0,
    error_message: errorMessage ?? job.message ?? null,
    message: job.message ?? null,
  };
}

function loginStateFromAuthStatus(status: AuthStatusResponse): XiaohongshuLoginState {
  if (status.authenticated === true) return { status: "logged_in", message: status.message ?? "已登录" };
  return { status: status.status === "unavailable" ? "error" : (status.login_status ?? "not_logged_in"), message: errorText(status.error) ?? status.message ?? null };
}

function assertLoginJob(response: LoginStartResponse): LoginStartResponse {
  if (!response.job_id || typeof response.job_id !== "string") {
    throw new Error("登录任务创建失败：后端未返回 job_id");
  }
  return response;
}

const mockCrawlerClient: CrawlerApiClient = {
  async checkService(signal?: AbortSignal): Promise<CrawlerServiceState> {
    await delay(300, signal);
    if (MOCK_SCENARIO === "backend_down") return { status: "not_started", checked_at: new Date().toISOString(), message: "Mock：后端未启动" };
    return { status: "connected", checked_at: new Date().toISOString(), message: "Mock 本地采集服务已连接" };
  },

  async getAuthStatus(signal?: AbortSignal): Promise<AuthStatusResponse> {
    await delay(220, signal);
    if (MOCK_SCENARIO === "backend_down") return { service_status: "not_started", login_status: "error", message: "Mock：后端未启动" };
    if (MOCK_SCENARIO === "cookie_expired") return { service_status: "connected", login_status: "expired", message: "Mock：Cookie 已过期，请重新登录" };
    return { service_status: "connected", login_status: "not_logged_in", message: "Mock：等待连接小红书" };
  },

  async startLogin(_browser: BrowserChoice = "auto", signal?: AbortSignal): Promise<LoginStartResponse> {
    await delay(280, signal);
    mockLoginPollCount = 0;
    return { job_id: `mock-login-${Date.now()}`, status: "opening_browser", message: "正在打开小红书登录窗口" };
  },

  async getLoginJob(jobId: string, signal?: AbortSignal): Promise<LoginJobResponse> {
    await delay(520, signal);
    mockLoginPollCount += 1;
    if (MOCK_SCENARIO === "cookie_expired") return { job_id: jobId, status: "expired", progress: 1, message: "Cookie 已过期，请重新登录" };
    if (mockLoginPollCount === 1) return { job_id: jobId, status: "waiting_for_login", progress: 0.5, message: "等待扫码确认登录" };
    return { job_id: jobId, status: "logged_in", progress: 1, message: "已连接小红书" };
  },

  async getLoginStatus(signal?: AbortSignal): Promise<XiaohongshuLoginState> {
    const job = await this.getLoginJob("mock-login-status", signal);
    return { status: job.status, message: job.message ?? null };
  },

  async startCollection(source: PageProduct, queryOverride?: string, signal?: AbortSignal): Promise<CollectionStartResponse> {
    const job = await this.startCrawl({ keyword: queryOverride?.trim() || source.title || "", page_product: source, preferences: {}, config: { max_notes: 10, max_comments_per_note: 20 } }, signal);
    return { ...job, job_id: job.job_id ?? `mock-crawl-${Date.now()}` };
  },

  async getCollectionJob(jobId: string, signal?: AbortSignal): Promise<CollectionJobResponse> {
    const job = await this.getCrawlJob(jobId, signal);
    return { ...job, job_id: job.job_id ?? jobId };
  },

  async getCollectionResult(jobId: string, signal?: AbortSignal): Promise<CollectionResultResponse> {
    await delay(180, signal);
    if (!lastRequest) throw new Error("No mock collection request");
    const job = await this.getCrawlJob(jobId, signal);
    return { job_id: jobId, formatted_preview: previewFrom(lastRequest, job), analysis: null };
  },

  async startCrawl(request: CrawlStartRequest, signal?: AbortSignal): Promise<CrawlJobData> {
    await delay(260, signal);
    mockCrawlPollCount = 0;
    mockCancelled = false;
    lastRequest = request;
    return {
      job_id: `mock-crawl-${Date.now()}`,
      status: "queued",
      stage: "waiting",
      progress: 0.08,
      collected_notes: 0,
      collected_comments: 0,
      error_message: null,
    };
  },

  async getCrawlJob(jobId: string, signal?: AbortSignal): Promise<CrawlJobData> {
    await delay(650, signal);
    if (mockCancelled) {
      return { job_id: jobId, status: "cancelled", stage: "cancelled", progress: 0, collected_notes: 0, collected_comments: 0, error_message: null };
    }
    mockCrawlPollCount += 1;
    const maxNotes = lastRequest?.config.max_notes ?? 10;
    const maxComments = (lastRequest?.config.max_comments_per_note ?? 20) * maxNotes;
    if (MOCK_SCENARIO === "crawler_failed" && mockCrawlPollCount >= 3) {
      return {
        job_id: jobId,
        status: "timeout",
        stage: "timeout",
        progress: 0.48,
        collected_notes: Math.max(1, Math.round(maxNotes * 0.45)),
        collected_comments: Math.round(maxComments * 0.35),
        error_message: "Mock 采集失败：上游平台暂时不可用",
      };
    }
    if (MOCK_SCENARIO === "task_timeout" && mockCrawlPollCount >= 3) {
      return {
        job_id: jobId,
        status: "failed",
        stage: "failed",
        progress: 0.34,
        collected_notes: Math.max(1, Math.round(maxNotes * 0.25)),
        collected_comments: Math.round(maxComments * 0.18),
        error_message: "Mock 任务超时：后端长时间未返回新进度",
      };
    }
    if (mockCrawlPollCount >= 7) {
      return { job_id: jobId, status: "completed", stage: "completed", progress: 1, collected_notes: maxNotes, collected_comments: maxComments, error_message: null };
    }
    if (mockCrawlPollCount === 6) {
      return { job_id: jobId, status: "formatting", stage: "formatting_dataset", progress: 0.92, collected_notes: maxNotes, collected_comments: Math.round(maxComments * 0.96), error_message: null };
    }
    if (mockCrawlPollCount === 5) {
      return { job_id: jobId, status: "analyzing", stage: "statistical_analysis", progress: 0.82, collected_notes: maxNotes, collected_comments: Math.round(maxComments * 0.92), error_message: null };
    }
    if (mockCrawlPollCount === 4) {
      return { job_id: jobId, status: "llm_extracting", stage: "llm_extracting", progress: 0.68, collected_notes: maxNotes, collected_comments: Math.round(maxComments * 0.86), error_message: null };
    }
    if (mockCrawlPollCount === 3) {
      return { job_id: jobId, status: "cleaning", stage: "cleaning_data", progress: 0.54, collected_notes: maxNotes, collected_comments: Math.round(maxComments * 0.74), error_message: null };
    }
    const ratio = Math.min(0.75, 0.18 + mockCrawlPollCount * 0.18);
    return {
      job_id: jobId,
      status: "crawling",
      stage: "crawling_notes",
      progress: ratio,
      collected_notes: Math.max(1, Math.round(maxNotes * ratio)),
      collected_comments: Math.round(maxComments * ratio * 0.82),
      error_message: null,
    };
  },

  async cancelCrawl(jobId: string, signal?: AbortSignal): Promise<CrawlJobData> {
    await delay(180, signal);
    mockCancelled = true;
    return { job_id: jobId, status: "cancelled", stage: "cancelled", progress: 0, collected_notes: 0, collected_comments: 0, error_message: null };
  },

  createFormattedPreview(request: CrawlStartRequest, job: CrawlJobData): FormattedCrawlerDataPreview {
    return previewFrom(request, job);
  },
};

const realCrawlerClient: CrawlerApiClient = {
  async checkService(signal?: AbortSignal): Promise<CrawlerServiceState> {
    try {
      const status = await this.getAuthStatus(signal);
      return { status: status.service_status ?? "connected", checked_at: new Date().toISOString(), message: status.message ?? "本地采集服务已连接" };
    } catch {
      return { status: "not_started", checked_at: new Date().toISOString(), message: "本地采集服务未启动" };
    }
  },

  getAuthStatus(signal?: AbortSignal): Promise<AuthStatusResponse> {
    return requestJson(apiPaths.crawler.authStatus, {}, signal);
  },

  startLogin(browser: BrowserChoice = "auto", signal?: AbortSignal): Promise<LoginStartResponse> {
    return requestJson<LoginStartResponse>(apiPaths.crawler.login, { method: "POST", body: JSON.stringify({ browser }) }, signal).then(assertLoginJob);
  },

  getLoginJob(jobId: string, signal?: AbortSignal): Promise<LoginJobResponse> {
    return requestJson(apiPaths.crawler.loginJob(jobId), {}, signal);
  },

  async getLoginStatus(signal?: AbortSignal): Promise<XiaohongshuLoginState> {
    const status = await this.getAuthStatus(signal);
    return loginStateFromAuthStatus(status);
  },

  startCollection(source: PageProduct, queryOverride?: string, signal?: AbortSignal): Promise<CollectionStartResponse> {
    const title = source.title?.trim() ?? "";
    const query = queryOverride?.trim() || title;
    return requestJson(apiPaths.crawler.collection, { method: "POST", body: JSON.stringify({ source: query || source.page_url, query_override: query || null }) }, signal);
  },

  getCollectionJob(jobId: string, signal?: AbortSignal): Promise<CollectionJobResponse> {
    return requestJson(apiPaths.crawler.collectionJob(jobId), {}, signal);
  },

  getCollectionResult(jobId: string, signal?: AbortSignal): Promise<CollectionResultResponse> {
    return requestJson(apiPaths.crawler.collectionResult(jobId), {}, signal);
  },

  async startCrawl(request: CrawlStartRequest, signal?: AbortSignal): Promise<CrawlJobData> {
    return crawlJobFromCollection(await this.startCollection(request.page_product, request.keyword, signal));
  },

  async getCrawlJob(jobId: string, signal?: AbortSignal): Promise<CrawlJobData> {
    return crawlJobFromCollection(await this.getCollectionJob(jobId, signal), jobId);
  },

  cancelCrawl(jobId: string, signal?: AbortSignal): Promise<CrawlJobData> {
    return requestJson(`${apiPaths.crawler.collectionJob(jobId)}/cancel`, { method: "POST" }, signal);
  },

  createFormattedPreview(request: CrawlStartRequest, job: CrawlJobData): FormattedCrawlerDataPreview {
    return previewFrom(request, job);
  },
};

export const crawlerClient: CrawlerApiClient = USE_MOCK ? mockCrawlerClient : realCrawlerClient;
