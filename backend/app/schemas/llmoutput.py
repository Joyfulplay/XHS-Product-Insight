"""Pydantic v2 contracts for Xiaohongshu LLM analysis output.

These models validate the outputs defined in ``prompt.py``.  Scores use the
0–100 range; ratios use the 0–1 range.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Sentiment = Literal["positive", "neutral", "negative", "mixed", "unknown"]
AspectSentiment = Literal["positive", "neutral", "negative", "mixed"]
RiskLevel = Literal["low", "medium", "high"]
SourceType = Literal["post", "comment", "image"]


class OutputModel(BaseModel):
    """Reject unexpected LLM fields so output remains safe for UI consumption."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class XiaohongshuSource(OutputModel):
    platform: Literal["xiaohongshu"] = "xiaohongshu"
    title: str = ""
    publish_time: str = "未提供"
    url: str = ""


class ProductMention(OutputModel):
    name: str = ""
    variant: str = "未提及"


class AspectOpinion(OutputModel):
    aspect: str = Field(min_length=1)
    sentiment: AspectSentiment
    opinion: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class CommentOverview(OutputModel):
    total: int = Field(default=0, ge=0)
    positive: int = Field(default=0, ge=0)
    neutral: int = Field(default=0, ge=0)
    negative: int = Field(default=0, ge=0)
    mixed: int = Field(default=0, ge=0)
    key_questions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def counts_cannot_exceed_total(self) -> "CommentOverview":
        if self.positive + self.neutral + self.negative + self.mixed > self.total:
            raise ValueError("comment sentiment counts cannot exceed total")
        return self


class ContentRisk(OutputModel):
    level: RiskLevel
    score: int = Field(ge=0, le=100)
    reasons: list[str] = Field(default_factory=list)


class EvidenceItem(OutputModel):
    evidence_id: str = Field(min_length=1)
    aspect: str = Field(min_length=1)
    source_type: SourceType
    source_ref: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    context: str = ""
    sentiment: Sentiment
    risk_level: RiskLevel
    risk_score: int = Field(ge=0, le=100)
    risk_reasons: list[str] = Field(default_factory=list)


class ImageAnalysisOutput(OutputModel):
    note_id: str = Field(min_length=1)
    image_observations: list[str] = Field(default_factory=list)
    visible_product_details: list[str] = Field(default_factory=list)
    visible_usage_or_result: list[str] = Field(default_factory=list)
    image_caveats: list[str] = Field(default_factory=list)


class PostAnalysisOutput(OutputModel):
    post_id: str = Field(min_length=1)
    source: XiaohongshuSource
    post_sentiment: Sentiment
    post_summary: str = ""
    product_mentions: list[ProductMention] = Field(default_factory=list)
    aspects: list[AspectOpinion] = Field(default_factory=list)
    comment_overview: CommentOverview
    image_observations: list[str] = Field(default_factory=list)
    content_risk: ContentRisk
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    purchase_intent: Literal["recommend", "consider", "not_recommend", "unknown"]
    risks_or_caveats: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    image_analysis: ImageAnalysisOutput

    @model_validator(mode="after")
    def evidence_references_must_exist(self) -> "PostAnalysisOutput":
        known_ids = {item.evidence_id for item in self.evidence_items}
        used_ids = {evidence_id for aspect in self.aspects for evidence_id in aspect.evidence_ids}
        missing_ids = used_ids - known_ids
        if missing_ids:
            raise ValueError(f"unknown aspect evidence_ids: {sorted(missing_ids)}")
        return self


class PurchaseReference(OutputModel):
    trust_aware_one_liner: str = "数据不足"
    raw_one_liner: str = "数据不足"
    recommended_default_mode: Literal["trust_aware", "raw"]
    reasons_for_difference: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class SampleOverview(OutputModel):
    posts_analyzed: int = Field(ge=0)
    comment_count: int = Field(ge=0)
    coverage_note: str = ""


class SentimentScores(OutputModel):
    raw: float = Field(ge=0, le=100)
    trust_aware: float = Field(ge=0, le=100)
    analysis_confidence: float = Field(ge=0, le=100)
    score_disclaimer: Literal["分数反映评价情感倾向，不是商品客观质量分。"]


class XiaohongshuPlatformMetrics(OutputModel):
    name: Literal["xiaohongshu"] = "xiaohongshu"
    content_count: int = Field(ge=0)
    raw_score: float = Field(ge=0, le=100)
    trust_aware_score: float = Field(ge=0, le=100)
    high_risk_content_ratio: float = Field(ge=0, le=1)


class AspectSummary(OutputModel):
    name: str = Field(min_length=1)
    trust_aware_score: float = Field(ge=0, le=100)
    mention_count: int = Field(ge=0)
    positive_ratio: float = Field(ge=0, le=1)
    neutral_ratio: float = Field(ge=0, le=1)
    negative_ratio: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def sentiment_ratios_are_valid(self) -> "AspectSummary":
        if self.positive_ratio + self.neutral_ratio + self.negative_ratio > 1.000_001:
            raise ValueError("aspect sentiment ratios cannot exceed 1")
        return self


class RiskReasonCount(OutputModel):
    reason: str = Field(min_length=1)
    count: int = Field(ge=0)


class RiskOverview(OutputModel):
    high_risk_content_count: int = Field(ge=0)
    high_risk_content_ratio: float = Field(ge=0, le=1)
    reason_distribution: list[RiskReasonCount] = Field(default_factory=list)
    caution: Literal["风险分数表示内容需要谨慎参考，不代表评论一定虚假。"]


class RecommendedSource(OutputModel):
    post_id: str = Field(min_length=1)
    platform: Literal["xiaohongshu"] = "xiaohongshu"
    title: str = ""
    publish_time: str = "未提供"
    relevance: float = Field(ge=0, le=100)
    risk_score: float = Field(ge=0, le=100)
    url: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceDetail(OutputModel):
    evidence_id: str = Field(min_length=1)
    post_id: str = Field(min_length=1)
    platform: Literal["xiaohongshu"] = "xiaohongshu"
    title: str = ""
    quote: str = Field(min_length=1)
    context: str = ""
    publish_time: str = "未提供"
    sentiment: Sentiment
    risk_level: RiskLevel
    risk_score: float = Field(ge=0, le=100)
    url: str = ""


class XiaohongshuSummaryOutput(OutputModel):
    purchase_reference: PurchaseReference
    sample_overview: SampleOverview
    sentiment_scores: SentimentScores
    platform: XiaohongshuPlatformMetrics
    aspects: list[AspectSummary] = Field(default_factory=list)
    risk_overview: RiskOverview
    recommended_sources: list[RecommendedSource] = Field(default_factory=list)
    evidence_details: list[EvidenceDetail] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class XiaohongshuAnalysisOutput(OutputModel):
    """The complete object returned by ``XiaohongshuInsightService.analyze_batch``."""

    product_name: str = Field(min_length=1)
    post_analyses: list[PostAnalysisOutput] = Field(default_factory=list)
    summary: XiaohongshuSummaryOutput
