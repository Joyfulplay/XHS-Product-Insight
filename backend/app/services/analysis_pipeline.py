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
    LlmInsights,
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
ATTRIBUTE_HINTS = ["降噪", "音质", "续航", "舒适", "重量", "价格", "做工", "屏幕", "拍照", "性能", "散热"]
SCENARIO_HINTS = ["通勤", "办公室", "学习", "旅行", "运动", "宿舍", "上课", "出差", "游戏"]
USER_HINTS = ["学生", "上班族", "宝妈", "新手", "敏感肌", "预算", "女生", "男生"]


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
        comment_texts = [comment["text"] for note in cleaned_notes for comment in note["comments"]]

        fallback_insights = self._build_rule_insights(all_texts, comment_texts)
        llm_insights, llm_response = self._build_llm_insights(collection_dataset, cleaned_notes)

        final_result = AnalysisResult(
            collection=self._collection_summary(collection_dataset, cleaned_notes),
            llm_insights=llm_insights or fallback_insights,
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

    def _build_rule_insights(self, all_texts: list[str], comment_texts: list[str]) -> LlmInsights:
        joined = " ".join(all_texts)
        positive_examples = self._sentences_with_words(comment_texts or all_texts, POSITIVE_WORDS, limit=3)
        negative_examples = self._sentences_with_words(comment_texts or all_texts, NEGATIVE_WORDS, limit=3)
        attributes = [word for word in ATTRIBUTE_HINTS if word in joined]
        scenarios = [word for word in SCENARIO_HINTS if word in joined]
        user_types = [word for word in USER_HINTS if word in joined]

        return LlmInsights(
            overall_summary=self._summary_sentence(joined, attributes, positive_examples, negative_examples),
            product_attributes=attributes,
            usage_scenarios=scenarios,
            user_types=user_types,
            unsuitable_users=["预算有限的用户"] if "贵" in joined or "价格" in joined else [],
            pros=positive_examples,
            cons=negative_examples,
            purchase_advice=self._purchase_advice(positive_examples, negative_examples),
        )

    def _build_llm_insights(
        self, dataset: dict[str, Any], cleaned_notes: list[dict[str, Any]]
    ) -> tuple[LlmInsights | None, dict[str, Any] | None]:
        if not cleaned_notes:
            return None, None

        try:
            insight_service = self._get_insight_service()
        except Exception:
            return None, None

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
            return self._frontend_insights_from_summary(summary), validated_batch_result
        except Exception:
            logger.exception(
                "[LLM_ANALYSIS_FAILED] 大模型分析或汇总结果校验失败：product=%s",
                product_name,
            )
            return None, None

    @staticmethod
    def _frontend_insights_from_summary(summary: XiaohongshuSummaryOutput) -> LlmInsights:
        """Adapt the validated LLM summary to the current frontend contract."""

        return LlmInsights(
            overall_summary=summary.purchase_reference.trust_aware_one_liner,
            product_attributes=[aspect.name for aspect in summary.aspects],
            purchase_advice=summary.purchase_reference.trust_aware_one_liner,
        )

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

    def _sentences_with_words(self, texts: list[str], words: set[str], limit: int) -> list[str]:
        result: list[str] = []
        for text in texts:
            if any(word in text for word in words):
                result.append(self._trim(text, 36))
            if len(result) >= limit:
                break
        return result

    def _summary_sentence(self, joined: str, attributes: list[str], pros: list[str], cons: list[str]) -> str | None:
        if not joined:
            return None
        focus = "、".join(attributes[:4]) if attributes else "整体体验"
        if pros and cons:
            return f"用户主要讨论{focus}，正向反馈和负向顾虑同时存在。"
        if pros:
            return f"用户主要讨论{focus}，整体反馈偏正向。"
        if cons:
            return f"用户主要讨论{focus}，需要重点关注负向反馈。"
        return f"用户主要讨论{focus}，当前样本情绪倾向不明显。"

    def _purchase_advice(self, pros: list[str], cons: list[str]) -> str | None:
        if pros and not cons:
            return "当前样本反馈偏正向，可结合价格和个人需求进一步判断。"
        if cons and not pros:
            return "当前样本存在较多顾虑，建议查看代表性笔记后再决定。"
        if pros and cons:
            return "适合重视优点且能接受主要缺点的用户，建议重点对照代表性笔记。"
        return None

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
