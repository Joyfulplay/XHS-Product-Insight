import type { AnalysisEvidenceViewModel, AnalysisViewModel, ProductAnalysisData } from "./api/types";

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function safeArray<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function evidenceFromSource(source: ProductAnalysisData["top_sources"][number]): AnalysisEvidenceViewModel {
  const record = source as ProductAnalysisData["top_sources"][number] & { author_nickname?: string | null; quote?: string | null };
  return {
    title: asString(source.source_title, "小红书代表性内容"),
    author: record.author_nickname ?? null,
    quote: record.quote ?? null,
    publish_time: source.publish_time ?? null,
    relevance_score: source.relevance_score ?? null,
    risk_score: source.risk_score ?? null,
    source_url: source.source_url || null,
  };
}

export function normalizeAnalysisResult(input: ProductAnalysisData | null | undefined): AnalysisViewModel {
  const aspects = safeArray(input?.aspects);
  const sources = safeArray(input?.top_sources).filter((source) => source.platform === "xiaohongshu");
  const total = asNumber(input?.coverage?.total_content_count, 0);
  const highRisk = asNumber(input?.risk_summary?.high_risk_count, 0);
  const valid = Math.max(0, total - highRisk);
  const confidence = typeof input?.overview?.confidence === "number" ? input.overview.confidence : null;
  const strengths = aspects
    .filter((aspect) => asNumber(aspect.trusted_sentiment_score, 0) >= 78)
    .slice(0, 5)
    .map((aspect) => aspect.aspect_label);
  const weaknesses = aspects
    .filter((aspect) => asNumber(aspect.trusted_sentiment_score, 100) < 72)
    .slice(0, 5)
    .map((aspect) => aspect.aspect_label);
  const keywords = aspects
    .slice()
    .sort((a, b) => asNumber(b.mention_count) - asNumber(a.mention_count))
    .slice(0, 8)
    .map((aspect) => aspect.aspect_label);

  return {
    sample: {
      note_count: total > 0 ? Math.max(1, Math.round(total / 42)) : 0,
      raw_comment_count: total,
      valid_comment_count: valid,
      confidence,
      low_confidence: confidence !== null ? confidence < 0.65 : total < 20,
    },
    overall: input?.summaries?.trust_aware?.one_sentence_summary ?? input?.summaries?.raw?.one_sentence_summary ?? "暂无总体评价。",
    strengths,
    weaknesses,
    attributes: aspects.slice(0, 6).map((aspect) => ({
      name: aspect.aspect_label,
      positive_mentions: Math.round(asNumber(aspect.mention_count) * asNumber(aspect.positive_ratio)),
      negative_mentions: Math.round(asNumber(aspect.mention_count) * asNumber(aspect.negative_ratio)),
    })),
    scenes: keywords.includes("降噪") ? ["通勤", "办公室", "日常佩戴"] : ["日常使用", "轻度通勤"],
    suitable_users: strengths.length ? [`重视${strengths.slice(0, 2).join("、")}的用户`] : ["需要更多小红书评论后判断"],
    unsuitable_users: weaknesses.length ? [`对${weaknesses.slice(0, 2).join("、")}非常敏感的用户`] : ["暂无明确不适用人群"],
    purchase_advice: input?.summaries?.trust_aware?.one_sentence_summary ?? "等待后端返回购买建议。",
    keywords,
    risk_reasons: safeArray(input?.risk_summary?.risk_reason_distribution),
    evidence: sources.map(evidenceFromSource),
    empty_message: total === 0 && aspects.length === 0 ? "暂无足够小红书评论样本生成稳定分析。" : null,
  };
}
