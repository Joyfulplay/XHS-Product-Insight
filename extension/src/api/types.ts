export type Platform = "taobao" | "xiaohongshu" | "bilibili";
export type AnalysisMode = "raw" | "trust_aware";

export interface PageProduct {
  supported: boolean;
  platform: "taobao";
  page_url: string;
  source_product_id: string | null;
  title: string | null;
  brand: string | null;
  model: string | null;
  variant: Record<string, string>;
  page_language: string;
}

export interface ResolveProductRequest {
  platform: "taobao";
  page_url: string;
  source_product_id: string | null;
  title: string | null;
  brand: string | null;
  model: string | null;
  variant: Record<string, string>;
  page_language: string;
  client_version: string;
}

export interface Product {
  product_id: string;
  canonical_name: string;
  brand: string | null;
  model: string | null;
  display_image_url: string | null;
}

export interface ResolveProductData {
  product: Product;
  match_status: string;
  match_confidence: number | null;
  requires_user_confirmation: boolean;
  candidates: Product[];
}

export interface DataStatus {
  mode: "live" | "cache" | "demo";
  is_stale?: boolean;
  platform_failures?: Array<{ platform: Platform; reason: string }>;
}

export interface Coverage {
  total_content_count: number;
  platforms: Platform[];
}

export interface Overview {
  raw_sentiment_score: number | null;
  trusted_sentiment_score: number | null;
  confidence: number | null;
}

export interface SummaryVariant {
  one_sentence_summary: string | null;
}

export interface ChangedClaim {
  claim_id: string;
  text: string;
  reason: string;
}

export interface Summaries {
  raw: SummaryVariant;
  trust_aware: SummaryVariant;
  changed_claims: ChangedClaim[];
}

export interface PlatformComparison {
  platform: Platform;
  content_count: number;
  raw_sentiment_score: number | null;
  trusted_sentiment_score: number | null;
  high_risk_ratio: number | null;
}

export interface Aspect {
  aspect_code: string;
  aspect_label: string;
  mention_count: number;
  raw_sentiment_score: number | null;
  trusted_sentiment_score: number | null;
  positive_ratio: number | null;
  neutral_ratio: number | null;
  negative_ratio: number | null;
  platform_disagreement_score: number | null;
  top_claim_ids: string[];
  evidence_content_ids: string[];
}

export interface RiskReason {
  reason_code: string;
  reason_label: string;
  count: number;
}

export interface RiskSummary {
  high_risk_count: number;
  high_risk_ratio: number | null;
  risk_reason_distribution: RiskReason[];
  display_note: string | null;
}

export interface TopSource {
  content_id: string;
  platform: Platform;
  source_title: string;
  source_url: string;
  publish_time: string | null;
  relevance_score: number | null;
  risk_score: number | null;
}

export interface ProductAnalysisData {
  analysis_id: string;
  product: Product;
  analysis_status: "ready" | "partial" | "pending";
  data_status: DataStatus;
  coverage: Coverage;
  overview: Overview;
  summaries: Summaries;
  platform_comparison: PlatformComparison[];
  aspects: Aspect[];
  risk_summary: RiskSummary;
  top_sources: TopSource[];
  updated_at: string | null;
}

export interface EvidenceItem {
  content_id: string;
  platform: Platform;
  source_title: string;
  quote: string | null;
  context_text: string | null;
  source_url: string;
  publish_time: string | null;
  sentiment: "positive" | "neutral" | "negative" | null;
  risk_score: number | null;
  risk_level: "low" | "medium" | "high" | null;
}

export interface EvidenceData {
  items: EvidenceItem[];
  next_cursor: string | null;
}

export interface EvidenceQuery {
  claim_id?: string;
  aspect_code?: string;
  platform?: Platform;
  risk_level?: "low" | "medium" | "high";
  cursor?: string;
  limit?: number;
}

export interface RefreshRequest {
  platforms: Platform[];
  force: boolean;
  max_cache_age_hours: number;
  requested_by: "chrome_extension";
  client_version: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "partially_succeeded" | "failed" | "cancelled";
export type JobStage = "waiting" | "collecting" | "cleaning" | "matching" | "modeling" | "summarizing" | "persisting" | "completed";

export interface RefreshJobData {
  job_id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  estimated_seconds: number | null;
  platform_failures?: Array<{ platform: Platform; reason: string }>;
}

export interface ApiMeta {
  schema_version: string;
  request_id: string;
  timestamp?: string;
}

export interface ApiResponse<T> {
  data: T;
  meta: ApiMeta;
}

export type ErrorCode =
  | "INVALID_REQUEST"
  | "PRODUCT_NOT_FOUND"
  | "ANALYSIS_NOT_READY"
  | "UNSUPPORTED_PLATFORM"
  | "PRODUCT_NOT_IDENTIFIED"
  | "RATE_LIMITED"
  | "UPSTREAM_ERROR"
  | "UPSTREAM_UNAVAILABLE"
  | "MODEL_UNAVAILABLE"
  | "INTERNAL_ERROR";

export interface ErrorBody {
  code: ErrorCode;
  message: string;
  details: Record<string, unknown>;
  retryable: boolean;
}

export interface ErrorResponse {
  error: ErrorBody;
  meta: ApiMeta;
}
