"""Frontend-facing schema for the collection analysis result."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnalysisCollectionSummary(AnalysisOutputModel):
    note_count: int = Field(default=0, ge=0)
    comment_count: int = Field(default=0, ge=0)
    valid_comment_count: int = Field(default=0, ge=0)


class LlmInsights(AnalysisOutputModel):
    overall_summary: str | None = None
    product_attributes: list[str] = Field(default_factory=list)
    usage_scenarios: list[str] = Field(default_factory=list)
    user_types: list[str] = Field(default_factory=list)
    unsuitable_users: list[str] = Field(default_factory=list)
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    purchase_advice: str | None = None


class KeywordItem(AnalysisOutputModel):
    text: str = Field(min_length=1)
    count: int = Field(ge=0)
    weight: float = Field(ge=0, le=1)


class SentimentDistribution(AnalysisOutputModel):
    positive: float = Field(ge=0, le=1)
    neutral: float = Field(ge=0, le=1)
    negative: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ratios_should_not_exceed_one(self) -> "SentimentDistribution":
        if self.positive + self.neutral + self.negative > 1.000_001:
            raise ValueError("sentiment ratios cannot exceed 1")
        return self


class StatisticsSummary(AnalysisOutputModel):
    keywords: list[KeywordItem] = Field(default_factory=list)
    sentiment_distribution: SentimentDistribution | None = None
    risk_ratio: float | None = Field(default=None, ge=0, le=1)


class RepresentativeNote(AnalysisOutputModel):
    note_id: str = Field(min_length=1)
    title: str
    url: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0, le=1)
    summary: str | None = None


class AnalysisResult(AnalysisOutputModel):
    schema_version: Literal["1.1"] = "1.1"
    collection: AnalysisCollectionSummary = Field(default_factory=AnalysisCollectionSummary)
    llm_insights: LlmInsights = Field(default_factory=LlmInsights)
    statistics: StatisticsSummary = Field(default_factory=StatisticsSummary)
    representative_notes: list[RepresentativeNote] = Field(default_factory=list)
    completed_at: str | None = None
