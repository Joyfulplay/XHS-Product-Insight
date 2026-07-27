"""Pure collection-to-frontend analysis pipeline.

Persistence and request orchestration belong to the connector service. This
module only transforms one completed collection dataset into analysis output.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from app.preprocess.cleaner import ContentCleaner
from app.schemas.analysis_result import (
    AnalysisCollectionSummary,
    AnalysisResult,
    KeywordItem,
    RepresentativeNote,
    SentimentDistribution,
    StatisticsSummary,
)
from app.schemas.llmoutput import XiaohongshuSummaryOutput
from app.schemas.crawler import CrawlNote
from app.LLM.service import XiaohongshuInsightService

# Reuse Uvicorn's configured error logger so this operational event is visible
# in the backend terminal without requiring an additional logging setup.
logger = logging.getLogger("uvicorn.error")

POSITIVE_WORDS = {
    "不错",
    "好用",
    "喜欢",
    "推荐",
    "舒服",
    "稳定",
    "清晰",
    "满意",
    "优秀",
    "值得",
    "nice",
    "good",
}
NEGATIVE_WORDS = {
    "不好",
    "一般",
    "失望",
    "难用",
    "贵",
    "踩雷",
    "退货",
    "发热",
    "闷",
    "差",
    "bad",
}
RISK_WORDS = {"广告", "推广", "水军", "虚假", "翻车", "踩雷", "避雷", "退货", "差评"}
STOPWORDS = {"一个", "这个", "真的", "感觉", "还是", "就是", "可以", "没有", "比较", "使用", "体验", "小红书"}
class AnalysisPipelineService:
    """Build a stable frontend response from one completed collection dataset."""

    def __init__(
        self,
        cleaner: ContentCleaner | None = None,
        insight_service_factory: Callable[[], XiaohongshuInsightService] | None = None,
    ) -> None:
        self.cleaner = cleaner or ContentCleaner()
        self.insight_service_factory = insight_service_factory

    def run(self, collection_dataset: dict[str, Any]) -> AnalysisResult:
        result, _ = self.run_with_llm_response(collection_dataset)
        return result

    def run_with_llm_response(
        self, collection_dataset: dict[str, Any]
    ) -> tuple[AnalysisResult, dict[str, Any] | None]:
        notes = [note for note in collection_dataset.get("notes", []) if isinstance(note, dict)]
        cleaned_notes = self._clean_notes(notes)

        all_texts = self._all_texts(cleaned_notes)
        llm_response = self._build_llm_response(collection_dataset, cleaned_notes)

        final_result = AnalysisResult(
            collection=self._collection_summary(collection_dataset, cleaned_notes),
            statistics=self._build_statistics(all_texts),
            representative_notes=self._representative_notes(cleaned_notes),
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

        return final_result, llm_response

    def _clean_notes(self, raw_notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        seen_texts: set[str] = set()

        for raw_dict in raw_notes:
            # 1. 适配并将裸数据转化为 CrawlNote 对象以配合 ContentCleaner 处理
            try:
                raw_note = CrawlNote.model_validate(raw_dict)
            except Exception:
                # 若无法校验为 Standard CrawlNote，自动构造防御性 fallback 对象
                continue

            # 2. 调用 ContentCleaner 的核心流程 process_note，完成去重、图片压缩与评论提取
            cleaned_note_model = self.cleaner.process_note(raw_note, seen_texts)
            if not cleaned_note_model:
                continue

            # 3. 转换为 Pipeline downstream 统一接受的字典格式
            note_dict = cleaned_note_model.model_dump()
            # 保证字典层兼容 Pipeline 内部字段表达
            cleaned.append({
                "note_id": str(note_dict.get("note_id", "")),
                "url": str(note_dict.get("url", "")),
                "title": note_dict.get("title", ""),
                "text": note_dict.get("text", ""),
                "images": note_dict.get("images", []),
                "comments": note_dict.get("comments", []),
                "likes": note_dict.get("likes", 0),
                "comments_count": len(note_dict.get("comments", [])),
                "tags": note_dict.get("tags", []),
                "publish_time": note_dict.get("publish_time"),
            })

        return cleaned

    def _collection_summary(
        self, dataset: dict[str, Any], cleaned_notes: list[dict[str, Any]]
    ) -> AnalysisCollectionSummary:
        raw_collection = dataset.get("collection", {})
        if not isinstance(raw_collection, dict):
            raw_collection = {}
        return AnalysisCollectionSummary(
            note_count=self._safe_int(raw_collection.get("note_count"), fallback=len(dataset.get("notes", []))),
            comment_count=self._safe_int(raw_collection.get("comment_count")),
            valid_comment_count=sum(len(note["comments"]) for note in cleaned_notes),
        )

    def _build_llm_response(
        self, dataset: dict[str, Any], cleaned_notes: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if not cleaned_notes:
            return None

        try:
            insight_service = self._get_insight_service()
        except Exception:
            return None

        raw_input = dataset.get("input") if isinstance(dataset.get("input"), dict) else {}
        product_name = str(raw_input.get("query") or raw_input.get("product_name") or "目标产品") # type: ignore

        try:
            logger.info(
                "[LLM_ANALYSIS_STARTED] 已开始大模型分析：product=%s, note_count=%d",
                product_name,
                min(len(cleaned_notes), 8),
            )
            batch_result = insight_service.analyze_batch(product_name, cleaned_notes[:8])
            summary_json = batch_result.get("summary", {})

            summary = XiaohongshuSummaryOutput.model_validate(summary_json)
            validated_batch_result = {
                **batch_result,
                "summary": summary.model_dump(mode="json"),
            }
            return validated_batch_result
        except Exception:
            logger.exception(
                "[LLM_ANALYSIS_FAILED] 大模型分析或汇总结果校验失败：product=%s",
                product_name,
            )
            return None

    def _get_insight_service(self) -> XiaohongshuInsightService:
        if self.insight_service_factory is not None:
            return self.insight_service_factory()

        from app.LLM.client import LLMClient

        return XiaohongshuInsightService(llm=LLMClient())

    def _build_statistics(self, texts: list[str]) -> StatisticsSummary:
        return StatisticsSummary(
            keywords=self._keywords(texts),
            sentiment_distribution=self._sentiment_distribution(texts),
            risk_ratio=self._risk_ratio(texts),
        )

    def _representative_notes(self, notes: list[dict[str, Any]]) -> list[RepresentativeNote]:
        candidates = [note for note in notes if note["note_id"] and note["url"]]
        if not candidates:
            return []
        max_score = max(self._note_score(note) for note in candidates) or 1
        ranked = sorted(candidates, key=self._note_score, reverse=True)[:5]
        return [
            RepresentativeNote(
                note_id=note["note_id"],
                title=note["title"] or "未命名笔记",
                url=note["url"],
                score=round(self._note_score(note) / max_score, 3),
                summary=self._trim(note["text"] or note["title"], 80) or None,
            )
            for note in ranked
        ]

    def _keywords(self, texts: list[str], limit: int = 20) -> list[KeywordItem]:
        counter: Counter[str] = Counter()
        for text in texts:
            counter.update(token for token in self._tokens(text) if token not in STOPWORDS)
        if not counter:
            return []
        most_common = counter.most_common(limit)
        max_count = most_common[0][1]
        return [KeywordItem(text=text, count=count, weight=round(count / max_count, 3)) for text, count in most_common]

    def _tokens(self, text: str) -> Iterable[str]:
        lowered = text.lower()
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_+-]{1,}|[\u4e00-\u9fff]{2,4}", lowered):
            yield token

    def _sentiment_distribution(self, texts: list[str]) -> SentimentDistribution | None:
        if not texts:
            return None
        counts = Counter(self._sentiment_for_text(text) for text in texts)
        total = sum(counts.values()) or 1
        positive = round(counts["positive"] / total, 4)
        neutral = round(counts["neutral"] / total, 4)
        negative = round(max(0.0, 1.0 - positive - neutral), 4)
        return SentimentDistribution(
            positive=positive,
            neutral=neutral,
            negative=negative,
        )

    def _sentiment_for_text(self, text: str) -> str:
        positive = sum(1 for word in POSITIVE_WORDS if word in text)
        negative = sum(1 for word in NEGATIVE_WORDS if word in text)
        if positive > negative:
            return "positive"
        if negative > positive:
            return "negative"
        return "neutral"

    def _risk_ratio(self, texts: list[str]) -> float | None:
        if not texts:
            return None
        risky = sum(1 for text in texts if any(word in text for word in RISK_WORDS))
        return round(risky / len(texts), 4)

    def _all_texts(self, notes: list[dict[str, Any]]) -> list[str]:
        texts: list[str] = []
        for note in notes:
            texts.extend(part for part in [note["title"], note["text"]] if part)
            texts.extend(
                comment.get("text", "") if isinstance(comment, dict) else str(getattr(comment, "text", ""))
                for comment in note["comments"]
            )
        return texts

    def _note_score(self, note: dict[str, Any]) -> int:
        return note["likes"] * 2 + note["comments_count"] + len(note["title"]) + min(len(note["text"]), 200)

    def _safe_int(self, value: Any, fallback: int = 0) -> int:
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return fallback

    def _trim(self, text: str, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."
