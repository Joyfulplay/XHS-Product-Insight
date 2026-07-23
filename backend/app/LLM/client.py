"""OpenAI-compatible client used by the Xiaohongshu analysis service."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable, cast

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam


class LLMClient:
    """Small wrapper that returns validated JSON dictionaries from an LLM."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ) -> None:
        self.model = model or os.getenv("LLM_MODEL", "gpt-4.1-mini")
        self.max_retries = max_retries
        self.client = OpenAI(
            api_key=api_key or os.environ["OPENAI_API_KEY"],
            base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
        )

    def analyze_json(
        self,
        *,
        system_prompt: str,
        text: str,
        image_urls: Iterable[str] = (),
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Send text and remote images, asking the model for a JSON object only."""
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content.extend(
            {"type": "image_url", "image_url": {"url": url, "detail": "low"}}
            for url in image_urls
            if url
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    messages=cast(
                        Iterable[ChatCompletionMessageParam],
                        [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": content},
                        ],
                    ),
                )
                raw = response.choices[0].message.content or "{}"
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("模型返回的 JSON 顶层必须是对象")
                return result
            except Exception as exc:  # network failures and malformed model output
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(2**attempt)
        raise RuntimeError("LLM 请求失败") from last_error

    def continue_json(
        self,
        *,
        system_prompt: str,
        previous_user_text: str,
        previous_assistant_json: dict[str, Any],
        next_user_text: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Continue a two-turn analysis without re-sending the images.

        The image-stage result is deliberately kept as an assistant message. This
        lets the second stage inspect, qualify, or reject visual hypotheses while
        grounding its product judgement in the note text and comments.
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": previous_user_text},
            {
                "role": "assistant",
                "content": json.dumps(previous_assistant_json, ensure_ascii=False),
            },
            {"role": "user", "content": next_user_text},
        ]
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    messages=cast(Iterable[ChatCompletionMessageParam], messages),
                )
                raw = response.choices[0].message.content or "{}"
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError("模型返回的 JSON 顶层必须是对象")
                return result
            except Exception as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(2**attempt)
        raise RuntimeError("LLM 多轮请求失败") from last_error
