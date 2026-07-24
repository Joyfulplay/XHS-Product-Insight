import evidenceFixture from "../../mocks/evidence_response.json";
import upstreamErrorFixture from "../../mocks/error_response.json";
import unidentifiedFixture from "../../mocks/product_not_identified_response.json";
import refreshFixture from "../../mocks/refresh_job_response.json";
import refreshPartialFixture from "../../mocks/refresh_partial_response.json";
import resolveFixture from "../../mocks/product_resolve_response.json";
import { MOCK_SCENARIO } from "../config";
import { demoProductScenarios } from "../mocks/demo_product_scenarios";
import { ApiError, type TrustLensApiClient } from "./client";
import type {
  AnalysisMode,
  ApiResponse,
  DemoProductScenario,
  DemoScenarioId,
  ErrorResponse,
  EvidenceData,
  EvidenceQuery,
  PageProduct,
  ProductAnalysisData,
  RefreshJobData,
  RefreshRequest,
  ResolveProductData,
} from "./types";

const resolveResponse = resolveFixture as unknown as ApiResponse<ResolveProductData>;
const evidenceResponse = evidenceFixture as unknown as ApiResponse<EvidenceData>;
const refreshResponse = refreshFixture as unknown as ApiResponse<RefreshJobData>;
const partialRefreshResponse = refreshPartialFixture as unknown as ApiResponse<RefreshJobData>;
const upstreamError = upstreamErrorFixture as unknown as ErrorResponse;
const unidentifiedError = unidentifiedFixture as unknown as ErrorResponse;

let jobPollCount = 0;
let currentDemoScenarioId: DemoScenarioId = "commute_noise_cancelling";

function currentDemoScenario(): DemoProductScenario {
  const scenario = demoProductScenarios.find((item) => item.scenario_id === currentDemoScenarioId);
  if (scenario) return scenario;
  const fallback = demoProductScenarios[0];
  if (fallback) return fallback;
  throw new Error("No demo product scenarios configured");
}

function delay(signal?: AbortSignal, milliseconds = 280): Promise<void> {
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

function clone<T>(value: T): T {
  return structuredClone(value);
}

function scenarioAnalysis(): ProductAnalysisData {
  const data = clone(currentDemoScenario().analysis);
  if (MOCK_SCENARIO === "partial_cache") {
    data.analysis_status = "partial";
    data.data_status = {
      mode: "cache",
      is_stale: true,
      platform_failures: [{ platform: "xiaohongshu", reason: "小红书采集暂时不可用" }],
    };
    data.platform_comparison = [];
  }
  if (MOCK_SCENARIO === "empty") {
    data.aspects = [];
    data.platform_comparison = [];
    data.top_sources = [];
    data.coverage.total_content_count = 0;
  }
  if (MOCK_SCENARIO === "zero_risk") {
    data.risk_summary.high_risk_count = 0;
    data.risk_summary.high_risk_ratio = 0;
    data.risk_summary.risk_reason_distribution = [];
  }
  return data;
}

export const mockApiClient: TrustLensApiClient = {
  getDemoScenarios(): typeof demoProductScenarios {
    return clone(demoProductScenarios);
  },

  getCurrentDemoScenarioId(): DemoScenarioId {
    return currentDemoScenarioId;
  },

  setDemoScenario(scenarioId: DemoScenarioId): ProductAnalysisData {
    const scenario = demoProductScenarios.find((item) => item.scenario_id === scenarioId);
    if (scenario) currentDemoScenarioId = scenario.scenario_id;
    return scenarioAnalysis();
  },

  async resolveProduct(page: PageProduct, signal?: AbortSignal): Promise<ResolveProductData> {
    await delay(signal);
    if (MOCK_SCENARIO === "product_not_identified") {
      throw new ApiError(unidentifiedError.error, unidentifiedError.meta.request_id);
    }
    const data = clone(resolveResponse.data);
    data.product = clone(currentDemoScenario().analysis.product);
    return data;
  },

  async getProductAnalysis(productId: string, _options: { mode: AnalysisMode }, signal?: AbortSignal): Promise<ProductAnalysisData> {
    await delay(signal);
    if (MOCK_SCENARIO === "upstream_unavailable") {
      throw new ApiError(upstreamError.error, upstreamError.meta.request_id);
    }
    const data = scenarioAnalysis();
    data.product.product_id = productId;
    return data;
  },

  async getEvidence(_productId: string, _query: EvidenceQuery, signal?: AbortSignal): Promise<EvidenceData> {
    await delay(signal, 220);
    return clone(evidenceResponse.data);
  },

  async createRefreshJob(_productId: string, _request: RefreshRequest, signal?: AbortSignal): Promise<RefreshJobData> {
    await delay(signal, 220);
    jobPollCount = 0;
    return clone(refreshResponse.data);
  },

  async getRefreshJob(_jobId: string, signal?: AbortSignal): Promise<RefreshJobData> {
    await delay(signal, 180);
    jobPollCount += 1;
    if (jobPollCount >= 3) {
      if (MOCK_SCENARIO === "refresh_partial" || MOCK_SCENARIO === "partial_cache") {
        return clone(partialRefreshResponse.data);
      }
      return { ...clone(refreshResponse.data), status: "succeeded", stage: "completed", progress: 1, estimated_seconds: 0 };
    }
    const progress = Math.min(0.9, 0.18 + jobPollCount * 0.28);
    const stages: RefreshJobData["stage"][] = ["collecting", "matching", "modeling", "summarizing"];
    return {
      ...clone(refreshResponse.data),
      progress,
      stage: stages[Math.min(jobPollCount, stages.length - 1)] ?? "collecting",
      estimated_seconds: Math.max(2, 24 - jobPollCount * 7),
    };
  },
};
