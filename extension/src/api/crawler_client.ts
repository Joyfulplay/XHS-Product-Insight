import { CRAWLER_BASE_URL, MOCK_SCENARIO, USE_MOCK } from "../config";
import type {
  CrawlJobData,
  CrawlStartRequest,
  CrawlerServiceState,
  FormattedCrawlerDataPreview,
  XiaohongshuLoginState,
} from "./types";

export interface CrawlerApiClient {
  checkService(signal?: AbortSignal): Promise<CrawlerServiceState>;
  startLogin(signal?: AbortSignal): Promise<XiaohongshuLoginState>;
  getLoginStatus(signal?: AbortSignal): Promise<XiaohongshuLoginState>;
  startCrawl(request: CrawlStartRequest, signal?: AbortSignal): Promise<CrawlJobData>;
  getCrawlJob(jobId: string, signal?: AbortSignal): Promise<CrawlJobData>;
  cancelCrawl(jobId: string, signal?: AbortSignal): Promise<CrawlJobData>;
  createFormattedPreview(request: CrawlStartRequest, job: CrawlJobData): FormattedCrawlerDataPreview;
}

let mockLoginPollCount = 0;
let mockCrawlPollCount = 0;
let mockCancelled = false;
let lastRequest: CrawlStartRequest | null = null;

function delay(signal?: AbortSignal, milliseconds = 350): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = window.setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

async function getJson<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${CRAWLER_BASE_URL}${path}`, {
    ...init,
    signal,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) throw new Error(`Crawler service returned HTTP ${response.status}`);
  return (await response.json()) as T;
}

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

const mockCrawlerClient: CrawlerApiClient = {
  async checkService(signal?: AbortSignal): Promise<CrawlerServiceState> {
    await delay(signal, 300);
    return { status: "connected", checked_at: new Date().toISOString(), message: "Mock 本地采集服务已连接" };
  },

  async startLogin(signal?: AbortSignal): Promise<XiaohongshuLoginState> {
    await delay(signal, 280);
    mockLoginPollCount = 0;
    return { status: "opening_browser", message: "正在打开小红书登录窗口" };
  },

  async getLoginStatus(signal?: AbortSignal): Promise<XiaohongshuLoginState> {
    await delay(signal, 520);
    mockLoginPollCount += 1;
    if (mockLoginPollCount === 1) return { status: "waiting_for_login", message: "等待扫码确认登录" };
    return { status: "logged_in", message: "已连接小红书" };
  },

  async startCrawl(request: CrawlStartRequest, signal?: AbortSignal): Promise<CrawlJobData> {
    await delay(signal, 260);
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
    await delay(signal, 650);
    if (mockCancelled) {
      return { job_id: jobId, status: "cancelled", stage: "cancelled", progress: 0, collected_notes: 0, collected_comments: 0, error_message: null };
    }
    mockCrawlPollCount += 1;
    const maxNotes = lastRequest?.config.max_notes ?? 10;
    const maxComments = (lastRequest?.config.max_comments_per_note ?? 20) * maxNotes;
    if (MOCK_SCENARIO === "crawler_failed" && mockCrawlPollCount >= 3) {
      return {
        job_id: jobId,
        status: "failed",
        stage: "failed",
        progress: 0.48,
        collected_notes: Math.max(1, Math.round(maxNotes * 0.45)),
        collected_comments: Math.round(maxComments * 0.35),
        error_message: "Mock 采集失败：上游平台暂时不可用",
      };
    }
    if (mockCrawlPollCount >= 5) {
      return { job_id: jobId, status: "completed", stage: "completed", progress: 1, collected_notes: maxNotes, collected_comments: maxComments, error_message: null };
    }
    if (mockCrawlPollCount >= 4) {
      return { job_id: jobId, status: "formatting", stage: "formatting_dataset", progress: 0.86, collected_notes: maxNotes, collected_comments: Math.round(maxComments * 0.9), error_message: null };
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
    await delay(signal, 180);
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
      return await getJson<CrawlerServiceState>("/api/v1/crawler/health", {}, signal);
    } catch {
      return { status: "not_started", checked_at: new Date().toISOString(), message: "本地采集服务未启动" };
    }
  },

  startLogin(signal?: AbortSignal): Promise<XiaohongshuLoginState> {
    return getJson("/api/v1/crawler/xhs/login", { method: "POST" }, signal);
  },

  getLoginStatus(signal?: AbortSignal): Promise<XiaohongshuLoginState> {
    return getJson("/api/v1/crawler/xhs/login/status", {}, signal);
  },

  startCrawl(request: CrawlStartRequest, signal?: AbortSignal): Promise<CrawlJobData> {
    return getJson("/api/v1/crawler/xhs/jobs", { method: "POST", body: JSON.stringify(request) }, signal);
  },

  getCrawlJob(jobId: string, signal?: AbortSignal): Promise<CrawlJobData> {
    return getJson(`/api/v1/crawler/xhs/jobs/${encodeURIComponent(jobId)}`, {}, signal);
  },

  cancelCrawl(jobId: string, signal?: AbortSignal): Promise<CrawlJobData> {
    return getJson(`/api/v1/crawler/xhs/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }, signal);
  },

  createFormattedPreview(request: CrawlStartRequest, job: CrawlJobData): FormattedCrawlerDataPreview {
    return previewFrom(request, job);
  },
};

export const crawlerClient: CrawlerApiClient = USE_MOCK ? mockCrawlerClient : realCrawlerClient;
