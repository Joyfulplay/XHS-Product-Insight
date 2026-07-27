"""Batch service: analyze each Xiaohongshu post, then summarize the collection.

Input is the supplied CleanedDataset JSON object or CleanedNote JSONL. It uses
note_id, title, text, tags, images[{position, url}], and cleaned comments.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from app.LLM.client import LLMClient
from app.LLM.prompt.prompt import (
    IMAGE_ANALYSIS_SYSTEM_PROMPT,
    POST_ANALYSIS_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_image_prompt,
    build_post_prompt,
    build_summary_prompt,
)
from app.schemas.llmoutput import (
    ImageAnalysisOutput,
    PostAnalysisModelOutput,
    PostAnalysisOutput,
    XiaohongshuAnalysisOutput,
    XiaohongshuSummaryModelOutput,
    XiaohongshuSummaryOutput,
)


def load_cleaned_dataset(path: str | Path) -> list[dict[str, Any]]:
    """Load a CleanedDataset JSON document, or CleanedNote JSONL records."""
    source = Path(path)
    raw = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        payload = json.loads(raw)
        if isinstance(payload, dict) and isinstance(payload.get("notes"), list):
            return payload["notes"]
        if isinstance(payload, list):
            return payload
        raise ValueError("JSON 文件必须是含 notes 的 CleanedDataset 或 CleanedNote 数组")

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"第 {line_number} 行不是合法 JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"第 {line_number} 行必须是 JSON 对象")
        if isinstance(record.get("notes"), list):
            records.extend(record["notes"])
        else:
            records.append(record)
    return records


class XiaohongshuInsightService:
    def __init__(
        self,
        llm: LLMClient,
        *,
        max_workers: int | None = None,
        max_images_per_post: int | None = None,
    ) -> None:
        self.llm = llm
        self.max_workers = self._positive_int_setting(
            max_workers,
            env_name="LLM_POST_CONCURRENCY",
            default=4,
        )
        self.max_images_per_post = self._positive_int_setting(
            max_images_per_post,
            env_name="LLM_MAX_IMAGES_PER_POST",
            default=3,
        )

    @staticmethod
    def _positive_int_setting(value: int | None, *, env_name: str, default: int) -> int:
        raw_value: int | str = value if value is not None else os.getenv(env_name, str(default))
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{env_name} 必须是正整数") from exc
        if parsed < 1:
            raise ValueError(f"{env_name} 必须是正整数")
        return parsed

    def analyze_post(self, product_name: str, post: dict[str, Any]) -> dict[str, Any]:
        source_post_id = str(post.get("note_id", "unknown"))
        images = [
            image["url"] for image in post.get("images", [])
            if isinstance(image, dict) and image.get("url")
        ][:self.max_images_per_post]
        image_turn_text = build_image_prompt(post)
        if images:
            visual_analysis = self.llm.analyze_json(
                system_prompt=IMAGE_ANALYSIS_SYSTEM_PROMPT,
                text=image_turn_text,
                image_urls=images,
                response_model=ImageAnalysisOutput,
            )
        else:
            visual_analysis = ImageAnalysisOutput(
                note_id=source_post_id,
                image_observations=[],
                visible_product_details=[],
                visible_usage_or_result=[],
                image_caveats=["该帖子未提供可分析图片。"],
            ).model_dump(mode="json")
        result = self.llm.continue_json(
            system_prompt=POST_ANALYSIS_SYSTEM_PROMPT,
            previous_user_text=image_turn_text,
            previous_assistant_json=visual_analysis,
            next_user_text=build_post_prompt(product_name, post),
            response_model=PostAnalysisModelOutput,
        )
        # Provenance fields come from the collected record, not from model copies.
        result["post_id"] = source_post_id
        result["source"] = {
            "platform": "xiaohongshu",
            "title": str(post.get("title") or ""),
            "publish_time": str(post.get("publish_time") or "未提供"),
            "url": str(post.get("url") or ""),
        }
        result["image_analysis"] = visual_analysis
        return PostAnalysisOutput.model_validate(result).model_dump(mode="json")

    @staticmethod
    def _globalize_post_evidence_ids(
        analysis: dict[str, Any],
        post_number: int,
    ) -> dict[str, Any]:
        """Namespace model-local evidence IDs before cross-post aggregation."""

        post_id = str(analysis["post_id"])
        local_to_global = {
            item["evidence_id"]: f"p{post_number}::{post_id}::{item['evidence_id']}"
            for item in analysis.get("evidence_items", [])
        }
        for item in analysis.get("evidence_items", []):
            item["evidence_id"] = local_to_global[item["evidence_id"]]
        for aspect in analysis.get("aspects", []):
            aspect["evidence_ids"] = [
                local_to_global[evidence_id]
                for evidence_id in aspect.get("evidence_ids", [])
            ]
        return PostAnalysisOutput.model_validate(analysis).model_dump(mode="json")

    @staticmethod
    def _build_evidence_catalog(
        post_analyses: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Build immutable evidence details from validated per-post outputs."""

        catalog: dict[str, dict[str, Any]] = {}
        for analysis in post_analyses:
            source = analysis["source"]
            for item in analysis.get("evidence_items", []):
                evidence_id = item["evidence_id"]
                if evidence_id in catalog:
                    raise ValueError(f"duplicate global evidence_id: {evidence_id}")
                catalog[evidence_id] = {
                    "evidence_id": evidence_id,
                    "post_id": analysis["post_id"],
                    "platform": "xiaohongshu",
                    "title": source["title"],
                    "quote": item["quote"],
                    "context": item["context"],
                    "publish_time": source["publish_time"],
                    "sentiment": item["sentiment"],
                    "risk_level": item["risk_level"],
                    "risk_score": item["risk_score"],
                    "url": source["url"],
                }
        return catalog

    @staticmethod
    def _referenced_evidence_ids(summary: XiaohongshuSummaryModelOutput) -> list[str]:
        """Return referenced IDs in UI display order without duplicates."""

        candidates = list(summary.purchase_reference.evidence_ids)
        candidates.extend(
            evidence_id
            for aspect in summary.aspects
            for evidence_id in aspect.evidence_ids
        )
        candidates.extend(
            evidence_id
            for source in summary.recommended_sources
            for evidence_id in source.evidence_ids
        )
        return list(dict.fromkeys(candidates))

    def analyze_batch(self, product_name: str, posts: list[dict[str, Any]]) -> dict[str, Any]:
        stage_one_started_at = time.perf_counter()
        worker_count = min(self.max_workers, len(posts)) if posts else 1
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="llm-post",
        ) as executor:
            analyze_post = partial(self.analyze_post, product_name)
            post_analyses = list(executor.map(analyze_post, posts))
        post_analyses = [
            self._globalize_post_evidence_ids(analysis, post_number)
            for post_number, analysis in enumerate(post_analyses, start=1)
        ]
        evidence_catalog = self._build_evidence_catalog(post_analyses)
        stage_one_elapsed = time.perf_counter() - stage_one_started_at
        print(
            "[LLM_STAGE_1_COMPLETED] 第一阶段逐笔记分析完成："
            f"note_count={len(post_analyses)}, workers={worker_count}, "
            f"max_images_per_post={self.max_images_per_post}, elapsed={stage_one_elapsed:.2f}s",
            flush=True,
        )
        print("[LLM_STAGE_2_STARTED] 第二阶段聚合分析已开始", flush=True)
        summary = self.llm.analyze_json(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            text=build_summary_prompt(product_name, post_analyses, evidence_catalog),
            temperature=0.1,
            response_model=XiaohongshuSummaryModelOutput,
            validation_context={"allowed_evidence_ids": set(evidence_catalog)},
        )
        summary_model = XiaohongshuSummaryModelOutput.model_validate(
            summary,
            context={"allowed_evidence_ids": set(evidence_catalog)},
        )
        referenced_ids = self._referenced_evidence_ids(summary_model)
        summary_output = XiaohongshuSummaryOutput.model_validate(
            {
                **summary_model.model_dump(mode="json"),
                "evidence_details": [
                    evidence_catalog[evidence_id]
                    for evidence_id in referenced_ids
                ],
            }
        )
        return XiaohongshuAnalysisOutput.model_validate(
            {
                "product_name": product_name,
                "post_analyses": post_analyses,
                "summary": summary_output,
            }
        ).model_dump(mode="json")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="分析小红书产品评价 JSONL 数据")
    parser.add_argument("input", help="清洗后的 JSONL 文件")
    parser.add_argument("--product", required=True, help="待分析的产品名称")
    parser.add_argument("--output", default="analysis_result.json", help="输出 JSON 文件")
    args = parser.parse_args()

    result = XiaohongshuInsightService(LLMClient()).analyze_batch(args.product, load_cleaned_dataset(args.input))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"分析完成：{args.output}")
