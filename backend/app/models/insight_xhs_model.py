from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from app.schemas.insight_xhs import XhsSentimentInput, XhsSentimentOutput
from app.services.llm_service import LLMService

PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "xhs_insight_prompt.md"
)


def _read_prompt_template() -> str:
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _build_prompt(payload: XhsSentimentInput) -> str:
    prompt_template = _read_prompt_template()
    return prompt_template.format(
        post_id=payload.post_id,
        title=payload.title,
        content=payload.content,
        platform=payload.platform,
        author=payload.author or "unknown",
        likes=payload.likes or 0,
        collects=payload.collects or 0,
        comments=payload.comments or 0,
        views=payload.views or 0,
        publish_time=payload.publish_time or "unknown",
        tags=", ".join(payload.tags) or "none",
        image_urls="\n".join(payload.image_urls) or "none",
    )


def _extract_json_from_response(response_text: str) -> dict:
    if not response_text:
        raise ValueError("LLM response is empty.")

    fenced_match = re.search(r"```(?:json)?\s*(.*?)```", response_text, re.DOTALL)
    if fenced_match:
        response_text = fenced_match.group(1).strip()

    start = response_text.find("{")
    end = response_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        response_text = response_text[start : end + 1]

    return json.loads(response_text)


def analyze_xhs_sentiment(
    payload: XhsSentimentInput,
    llm_service: Optional[LLMService] = None,
) -> XhsSentimentOutput:
    """
    Use the configured LLM service to analyze a single XHS post and return a
    strict structured result aligned with the XhsSentimentOutput schema.
    """
    service = llm_service or LLMService()
    prompt = _build_prompt(payload)
    llm_response = service.generate(prompt)
    parsed_json = _extract_json_from_response(llm_response)
    return XhsSentimentOutput.model_validate(parsed_json)
