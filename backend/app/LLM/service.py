"""Batch service: analyze each Xiaohongshu post, then summarize the collection.

Input is the supplied CleanedDataset JSON object or CleanedNote JSONL. It uses
note_id, title, text, tags, images[{position, url}], and cleaned comments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from client import LLMClient
from prompt.prompt import (
    IMAGE_ANALYSIS_SYSTEM_PROMPT,
    POST_ANALYSIS_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_image_prompt,
    build_post_prompt,
    build_summary_prompt,
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
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def analyze_post(self, product_name: str, post: dict[str, Any]) -> dict[str, Any]:
        images: Iterable[str] = [
            image["url"] for image in post.get("images", [])
            if isinstance(image, dict) and image.get("url")
        ]
        image_turn_text = build_image_prompt(post)
        if images:
            visual_analysis = self.llm.analyze_json(
                system_prompt=IMAGE_ANALYSIS_SYSTEM_PROMPT,
                text=image_turn_text,
                image_urls=images,
            )
        else:
            visual_analysis = {
                "note_id": str(post.get("note_id", "unknown")),
                "image_observations": [],
                "visible_product_details": [],
                "visible_usage_or_result": [],
                "image_caveats": ["该帖子未提供可分析图片。"],
            }
        result = self.llm.continue_json(
            system_prompt=POST_ANALYSIS_SYSTEM_PROMPT,
            previous_user_text=image_turn_text,
            previous_assistant_json=visual_analysis,
            next_user_text=build_post_prompt(product_name, post),
        )
        # Let downstream aggregation reliably trace a model response to source data.
        result.setdefault("post_id", str(post.get("note_id", "unknown")))
        result["image_analysis"] = visual_analysis
        return result

    def analyze_batch(self, product_name: str, posts: list[dict[str, Any]]) -> dict[str, Any]:
        post_analyses = [self.analyze_post(product_name, post) for post in posts]
        summary = self.llm.analyze_json(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            text=build_summary_prompt(product_name, post_analyses),
            temperature=0.1,
        )
        return {"product_name": product_name, "post_analyses": post_analyses, "summary": summary}


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
