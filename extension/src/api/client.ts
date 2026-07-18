import { API_BASE_URL, CLIENT_VERSION, USE_MOCK } from "../config";
import { mockApiClient } from "./mock_client";
import type {
  AnalysisMode,
  ApiResponse,
  ErrorBody,
  ErrorResponse,
  EvidenceData,
  EvidenceQuery,
  DemoProductScenario,
  DemoScenarioId,
  PageProduct,
  ProductAnalysisData,
  RefreshJobData,
  RefreshRequest,
  ResolveProductData,
  ResolveProductRequest,
} from "./types";

export interface TrustLensApiClient {
  resolveProduct(page: PageProduct, signal?: AbortSignal): Promise<ResolveProductData>;
  getProductAnalysis(productId: string, options: { mode: AnalysisMode }, signal?: AbortSignal): Promise<ProductAnalysisData>;
  getEvidence(productId: string, filters: EvidenceQuery, signal?: AbortSignal): Promise<EvidenceData>;
  createRefreshJob(productId: string, request: RefreshRequest, signal?: AbortSignal): Promise<RefreshJobData>;
  getRefreshJob(jobId: string, signal?: AbortSignal): Promise<RefreshJobData>;
  getDemoScenarios?(): DemoProductScenario[];
  getCurrentDemoScenarioId?(): DemoScenarioId;
  setDemoScenario?(scenarioId: DemoScenarioId): ProductAnalysisData;
}

export class ApiError extends Error {
  constructor(
    public readonly error: ErrorBody,
    public readonly requestId?: string,
  ) {
    super(error.message);
    this.name = "ApiError";
  }
}

export class NetworkError extends Error {
  constructor(message = "无法连接分析服务") {
    super(message);
    this.name = "NetworkError";
  }
}

async function request<T>(path: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError();
  }

  if (!response.ok) {
    let body: ErrorResponse | null = null;
    try {
      body = (await response.json()) as ErrorResponse;
    } catch {
      // Preserve HTTP failure even if the upstream body is not JSON.
    }
    if (body?.error) throw new ApiError(body.error, body.meta?.request_id);
    throw new NetworkError(`服务返回异常（HTTP ${response.status}）`);
  }

  const body = (await response.json()) as ApiResponse<T>;
  return body.data;
}

const realApiClient: TrustLensApiClient = {
  resolveProduct(page: PageProduct, signal?: AbortSignal): Promise<ResolveProductData> {
    const payload: ResolveProductRequest = { ...page, client_version: CLIENT_VERSION };
    const { supported: _supported, ...requestBody } = payload as ResolveProductRequest & { supported?: boolean };
    return request("/api/v1/products/resolve", { method: "POST", body: JSON.stringify(requestBody) }, signal);
  },

  getProductAnalysis(productId: string, options: { mode: AnalysisMode }, signal?: AbortSignal): Promise<ProductAnalysisData> {
    return request(`/api/v1/products/${encodeURIComponent(productId)}/analysis?mode=${options.mode}`, { method: "GET" }, signal);
  },

  getEvidence(productId: string, query: EvidenceQuery, signal?: AbortSignal): Promise<EvidenceData> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) params.set(key, String(value));
    }
    return request(`/api/v1/products/${encodeURIComponent(productId)}/evidence?${params}`, { method: "GET" }, signal);
  },

  createRefreshJob(productId: string, refreshRequest: RefreshRequest, signal?: AbortSignal): Promise<RefreshJobData> {
    return request(`/api/v1/products/${encodeURIComponent(productId)}/refresh`, { method: "POST", body: JSON.stringify(refreshRequest) }, signal);
  },

  getRefreshJob(jobId: string, signal?: AbortSignal): Promise<RefreshJobData> {
    return request(`/api/v1/jobs/${encodeURIComponent(jobId)}`, { method: "GET" }, signal);
  },
};

export const apiClient: TrustLensApiClient = USE_MOCK ? mockApiClient : realApiClient;
