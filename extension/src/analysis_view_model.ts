import type { AnalysisEvidenceViewModel, AnalysisViewModel, ProductAnalysisData } from "./api/types";

type AnyRecord = Record<string, unknown>;

function isRecord(value: unknown): value is AnyRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNumber(value: unknown, fallback: number | null = null): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return fallback;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function safeArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function getPath(input: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => (isRecord(current) ? current[key] : undefined), input);
}

function firstValue(input: unknown, paths: string[]): unknown {
  for (const path of paths) {
    const value = getPath(input, path);
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return undefined;
}

function firstNumber(input: unknown, paths: string[], fallback: number | null = null): number | null {
  for (const path of paths) {
    const number = asNumber(getPath(input, path), null);
    if (number !== null) return number;
  }
  return fallback;
}

function firstString(input: unknown, paths: string[], fallback = ""): string {
  return asString(firstValue(input, paths), fallback);
}

function firstStringArray(input: unknown, paths: string[]): string[] {
  for (const path of paths) {
    const value = getPath(input, path);
    if (Array.isArray(value)) {
      return value.map((item) => (typeof item === "string" ? item : isRecord(item) ? asString(item.label ?? item.name ?? item.text ?? item.keyword) : "")).filter(Boolean);
    }
  }
  return [];
}

function firstRecordArray(input: unknown, paths: string[]): AnyRecord[] {
  for (const path of paths) {
    const value = getPath(input, path);
    if (Array.isArray(value)) return value.filter(isRecord);
  }
  return [];
}

function firstArray(input: unknown, paths: string[]): unknown[] {
  for (const path of paths) {
    const value = getPath(input, path);
    if (Array.isArray(value)) return value;
  }
  return [];
}

function commentCountFromNotes(notes: unknown[]): number | null {
  if (!notes.length) return null;
  return notes.reduce<number>((sum, note) => sum + safeArray(isRecord(note) ? note.comments : undefined).length, 0);
}

function unwrapAnalysis(input: unknown): unknown {
  return firstValue(input, [
    "analysis",
    "data.analysis",
    "result.analysis",
    "data.result.analysis",
    "raw.analysis",
    "raw.data.analysis",
  ]) ?? input;
}

function evidenceFromSource(source: ProductAnalysisData["top_sources"][number] | AnyRecord): AnalysisEvidenceViewModel {
  return {
    title: firstString(source, ["source_title", "title", "note_title"], "小红书代表性内容"),
    author: firstString(source, ["author_nickname", "author", "nickname"], "") || null,
    quote: firstString(source, ["quote", "summary", "context_text", "content"], "") || null,
    publish_time: firstString(source, ["publish_time", "published_at", "created_at"], "") || null,
    relevance_score: firstNumber(source, ["relevance_score", "score"], null),
    risk_score: firstNumber(source, ["risk_score"], null),
    source_url: firstString(source, ["source_url", "url", "note_url"], "") || null,
  };
}

function normalizeAttributes(input: unknown, aspects: AnyRecord[]): AnalysisViewModel["attributes"] {
  const records = firstRecordArray(input, [
    "llm_insights.product_attributes",
    "product_attributes",
    "attributes",
    "insights.product_attributes",
    "structured_data.product_attributes",
    "analysis.product_attributes",
  ]);
  const llmAttributes = firstStringArray(input, ["llm_insights.product_attributes"]);
  if (llmAttributes.length) {
    return llmAttributes.map((name) => ({ name, positive_mentions: null, negative_mentions: null }));
  }
  const source = records.length ? records : aspects;
  return source.slice(0, 8).map((item) => {
    const mentionCount = firstNumber(item, ["mention_count", "mentions", "count"], 0) ?? 0;
    const positive = firstNumber(item, ["positive_mentions", "positive_count"], null);
    const negative = firstNumber(item, ["negative_mentions", "negative_count"], null);
    return {
      name: firstString(item, ["aspect_label", "label", "name", "attribute", "aspect"], "暂无数据"),
      positive_mentions: positive ?? Math.round(mentionCount * (firstNumber(item, ["positive_ratio"], 0) ?? 0)),
      negative_mentions: negative ?? Math.round(mentionCount * (firstNumber(item, ["negative_ratio"], 0) ?? 0)),
    };
  });
}

function normalizeRiskReasons(input: unknown): AnalysisViewModel["risk_reasons"] {
  return firstRecordArray(input, ["risk_summary.risk_reason_distribution", "risk.risk_reason_distribution", "risk.reasons"]).map((item) => ({
    reason_code: firstString(item, ["reason_code", "code", "reason"], "unknown"),
    reason_label: firstString(item, ["reason_label", "label", "name", "reason"], "暂无数据"),
    count: firstNumber(item, ["count", "mentions"], 0) ?? 0,
  }));
}

export function normalizeAnalysisResult(input: ProductAnalysisData | unknown | null | undefined): AnalysisViewModel {
  const analysis = unwrapAnalysis(input);
  const aspects = firstRecordArray(analysis, ["aspects", "aspect_analysis", "statistics.aspects", "structured_data.aspects"]);
  const sources = firstRecordArray(analysis, ["representative_notes", "top_sources", "evidence", "sources"]).filter((source) => firstString(source, ["platform"], "xiaohongshu") === "xiaohongshu");
  const notes = firstArray(analysis, ["notes", "data.notes", "result.notes", "raw.notes", "raw.data.notes"]);
  const collectionNoteCount = firstNumber(analysis, [
    "collection.note_count",
    "data.collection.note_count",
    "result.collection.note_count",
    "raw.collection.note_count",
    "raw.data.collection.note_count",
  ], null);
  const legacyNoteCount = firstNumber(analysis, [
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
    "collected_notes",
  ], null);
  const noteCount = collectionNoteCount ?? (notes.length || null) ?? legacyNoteCount ?? 0;
  const collectionCommentCount = firstNumber(analysis, [
    "collection.comment_count",
    "data.collection.comment_count",
    "result.collection.comment_count",
    "raw.collection.comment_count",
    "raw.data.collection.comment_count",
  ], null);
  const summedNoteCommentCount = commentCountFromNotes(notes);
  const legacyRawCommentCount = firstNumber(analysis, [
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
    "collected_comments",
  ], null);
  const rawCommentCount = collectionCommentCount ?? summedNoteCommentCount ?? legacyRawCommentCount ?? (safeArray(getPath(analysis, "comments")).length || safeArray(getPath(analysis, "raw.comments")).length || null);
  const validCommentCount = firstNumber(analysis, [
    "collection.valid_comment_count",
    "data.collection.valid_comment_count",
    "result.collection.valid_comment_count",
    "raw.collection.valid_comment_count",
    "raw.data.collection.valid_comment_count",
    "sample.valid_comment_count",
    "sample.cleaned_comment_count",
    "statistics.valid_comment_count",
    "statistics.cleaned_comment_count",
    "statistics.effective_comment_count",
    "stats.valid_comment_count",
    "counts.valid_comments",
    "valid_comment_count",
    "cleaned_comment_count",
    "effective_comment_count",
  ], null);
  const totalContent = firstNumber(analysis, ["coverage.total_content_count"], null);
  const highRisk = firstNumber(analysis, ["risk_summary.high_risk_count", "risk.high_risk_count", "risk.negative_count"], 0) ?? 0;
  const confidence = firstNumber(analysis, ["overview.confidence", "confidence", "statistics.confidence"], null);
  const riskRatio = firstNumber(analysis, ["statistics.risk_ratio", "risk_summary.high_risk_ratio", "risk.high_risk_ratio", "risk.negative_ratio", "negative_ratio"], null);
  const sentimentDistribution = isRecord(getPath(analysis, "statistics.sentiment_distribution"))
    ? {
      positive: firstNumber(analysis, ["statistics.sentiment_distribution.positive"], null),
      neutral: firstNumber(analysis, ["statistics.sentiment_distribution.neutral"], null),
      negative: firstNumber(analysis, ["statistics.sentiment_distribution.negative"], null),
    }
    : null;
  const strengths = firstStringArray(analysis, ["llm_insights.pros", "strengths", "advantages", "pros", "insights.strengths", "summary.strengths"]);
  const weaknesses = firstStringArray(analysis, ["llm_insights.cons", "weaknesses", "disadvantages", "cons", "insights.weaknesses", "summary.weaknesses"]);
  const keywords = firstStringArray(analysis, ["statistics.keywords", "keywords", "high_frequency_keywords", "hot_keywords"]);
  const explicitScenes = firstStringArray(analysis, ["llm_insights.usage_scenarios", "usage_scenarios", "scenarios", "scenes", "insights.usage_scenarios"]);
  const explicitSuitable = firstStringArray(analysis, ["llm_insights.user_types", "suitable_users", "target_users", "user_types", "insights.suitable_users"]);
  const explicitUnsuitable = firstStringArray(analysis, ["llm_insights.unsuitable_users", "unsuitable_users", "not_suitable_users", "insights.unsuitable_users"]);
  const riskReasons = normalizeRiskReasons(analysis);
  const normalizedRawComments = rawCommentCount ?? totalContent ?? 0;
  const normalizedValidComments = validCommentCount ?? (totalContent !== null ? Math.max(0, totalContent - highRisk) : null);
  const hasLlmInsights = isRecord(getPath(analysis, "llm_insights"));
  const hasStatistics = isRecord(getPath(analysis, "statistics"));
  const analysisSource = firstString(analysis, ["analysis_source", "llm_source", "llm_insights.source", "llm_insights.analysis_source", "statistics.analysis_source"], "") || (hasLlmInsights ? "llm" : hasStatistics ? "statistics" : null);

  return {
    sample: {
      note_count: noteCount,
      raw_comment_count: normalizedRawComments,
      valid_comment_count: normalizedValidComments,
      risk_negative_ratio: riskRatio,
      sentiment_distribution: sentimentDistribution,
      analysis_source: analysisSource,
      confidence,
      low_confidence: confidence !== null ? confidence < 0.65 : normalizedRawComments < 20,
    },
    overall: firstString(analysis, ["llm_insights.overall_summary", "overall", "summary.overall", "summaries.trust_aware.one_sentence_summary", "summaries.raw.one_sentence_summary"], "暂无数据"),
    strengths,
    weaknesses,
    attributes: normalizeAttributes(analysis, aspects),
    scenes: explicitScenes,
    suitable_users: explicitSuitable,
    unsuitable_users: explicitUnsuitable,
    purchase_advice: firstString(analysis, ["llm_insights.purchase_advice", "purchase_advice", "buying_advice", "recommendation", "insights.purchase_advice", "summaries.trust_aware.one_sentence_summary"], "暂无数据"),
    keywords,
    risk_reasons: riskReasons,
    evidence: sources.map(evidenceFromSource),
    empty_message: noteCount === 0 ? "后端采集已完成，但未采集到小红书笔记。可以修改关键词后重新采集。" : null,
  };
}
