"""Collection-to-frontend analysis pipeline.

The extension currently polls collection jobs, so backend integration returns
the final insight contract from the existing collection result endpoint.
"""

from __future__ import annotations

import json
import os
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
LLM_INSIGHTS_SYSTEM_PROMPT = """????????????????????????????????????????????????????????

???
1. ???????????????????????????
2. ????????????? null??????? []?
3. ?????????????????????????????? pros ? cons?
4. ???? JSON??? Markdown????????

?????
{
  "overall_summary": "string|null",
  "product_attributes": ["string"],
  "usage_scenarios": ["string"],
  "user_types": ["string"],
  "unsuitable_users": ["string"],
  "pros": ["string"],
  "cons": ["string"],
  "purchase_advice": "string|null"
}
"""


class AnalysisPipelineService:
    """Build a stable frontend response from one completed collection dataset."""

    def __init__(self, cleaner: ContentCleaner | None = None, llm_client_factory: Callable[[], Any] | None = None) -> None:
        self.cleaner = cleaner or ContentCleaner()
        self.llm_client_factory = llm_client_factory

    def run(self, collection_dataset: dict[str, Any]) -> AnalysisResult:
        notes = [note for note in collection_dataset.get("notes", []) if isinstance(note, dict)]
        cleaned_notes = self._clean_notes(notes)
        all_texts = self._all_texts(cleaned_notes)
        comment_texts = [comment["text"] for note in cleaned_notes for comment in note["comments"]]

        fallback_insights = self._build_rule_insights(all_texts, comment_texts)

        return AnalysisResult(
            collection=self._collection_summary(collection_dataset, cleaned_notes),
            llm_insights=self._build_llm_insights(collection_dataset, cleaned_notes) or fallback_insights,
            statistics=self._build_statistics(all_texts),
            representative_notes=self._representative_notes(cleaned_notes),
            completed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def _clean_notes(self, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        seen_content: set[str] = set()
        for note in notes:
            title = self.cleaner.clean_text(str(note.get("title") or ""))
            text = self.cleaner.clean_text(str(note.get("text") or ""))
            dedupe_key = f"{title}\n{text}".strip()
            if not dedupe_key or dedupe_key in seen_content:
                continue
            seen_content.add(dedupe_key)

            comments = self._clean_comments(note.get("comments", []))
            engagement = note.get("engagement") if isinstance(note.get("engagement"), dict) else {}
            cleaned.append(
                {
                    "note_id": str(note.get("note_id") or ""),
                    "url": str(note.get("url") or ""),
                    "title": title,
                    "text": text,
                    "comments": comments,
                    "likes": self._safe_int(engagement.get("likes")),
                    "comments_count": len(comments),
                    "tags": note.get("tags") if isinstance(note.get("tags"), list) else [],
                    "publish_time": note.get("publish_time"),
                }
            )
        return cleaned

    def _clean_comments(self, raw_comments: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_comments, list):
            return []
        comments: list[dict[str, Any]] = []
        for comment in raw_comments:
            if not isinstance(comment, dict):
                continue
            text = self.cleaner.clean_text(str(comment.get("text") or ""))
            if len(text) < 4:
                continue
            comments.append(
                {
                    "comment_id": str(comment.get("comment_id") or ""),
                    "text": text,
                    "likes": self._safe_int(comment.get("likes")),
                }
            )
        comments.sort(key=lambda item: item["likes"], reverse=True)
        return comments[:10]

    def _collection_summary(self, dataset: dict[str, Any], cleaned_notes: list[dict[str, Any]]) -> AnalysisCollectionSummary:
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

    def _build_llm_insights(self, dataset: dict[str, Any], cleaned_notes: list[dict[str, Any]]) -> LlmInsights | None:
        if not cleaned_notes:
            return None
        try:
            client = self._llm_client()
        except Exception:
            return None
        payload = self._llm_payload(dataset, cleaned_notes)
        try:
            raw_result = client.analyze_json(
                system_prompt=LLM_INSIGHTS_SYSTEM_PROMPT,
                text=json.dumps(payload, ensure_ascii=False),
                temperature=0.1,
            )
            return LlmInsights.model_validate(raw_result)
        except Exception:
            return None

    def _llm_client(self) -> Any:
        if self.llm_client_factory is not None:
            return self.llm_client_factory()
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not configured")
        from app.LLM.client import LLMClient

        return LLMClient()

    def _llm_payload(self, dataset: dict[str, Any], cleaned_notes: list[dict[str, Any]]) -> dict[str, Any]:
        raw_input = dataset.get("input") if isinstance(dataset.get("input"), dict) else {}
        return {
            "product_query": raw_input.get("query"),
            "collection": dataset.get("collection", {}),
            "notes": [self._llm_note_payload(note) for note in cleaned_notes[:8]],
        }

    def _llm_note_payload(self, note: dict[str, Any]) -> dict[str, Any]:
        return {
            "note_id": note["note_id"],
            "title": note["title"],
            "text": self._trim(note["text"], 600),
            "tags": note.get("tags", []),
            "publish_time": note.get("publish_time"),
            "likes": note["likes"],
            "comments": [
                {
                    "comment_id": comment["comment_id"],
                    "text": self._trim(comment["text"], 180),
                    "likes": comment["likes"],
                }
                for comment in note["comments"][:8]
            ],
        }

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
        return SentimentDistribution(
            positive=round(counts["positive"] / total, 4),
            neutral=round(counts["neutral"] / total, 4),
            negative=round(counts["negative"] / total, 4),
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
            texts.extend(comment["text"] for comment in note["comments"])
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
