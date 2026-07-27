"""OpenAI-compatible client used by the Xiaohongshu analysis service."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable, cast

from openai import APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError


class LLMClient:
    """Small wrapper that returns validated JSON dictionaries from an LLM."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model = model or os.getenv("LLM_MODEL", "gpt-4.1-mini")
        if max_retries < 1:
            raise ValueError("max_retries 必须大于等于 1")
        self.max_retries = max_retries
        raw_timeout: float | str = (
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("LLM_TIMEOUT_SECONDS", "120")
        )
        try:
            self.timeout_seconds = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("LLM_TIMEOUT_SECONDS 必须是正数") from exc
        if self.timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS 必须是正数")
        self.client = OpenAI(
            api_key=api_key or os.environ["OPENAI_API_KEY"],
            base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
            timeout=self.timeout_seconds,
            # This wrapper owns retry reporting and backoff. Disabling the SDK's
            # inner retries prevents one logical attempt from multiplying.
            max_retries=0,
        )

    @staticmethod
    def _is_timeout_error(exc: BaseException) -> bool:
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            if isinstance(current, (APITimeoutError, TimeoutError)):
                return True
            current = current.__cause__ or current.__context__
        return False

    def _report_timeout(self, *, operation: str, attempt: int) -> None:
        print(
            "[LLM_TIMEOUT] 大模型请求超时："
            f"operation={operation}, model={self.model}, "
            f"attempt={attempt}/{self.max_retries}, "
            f"timeout_seconds={self.timeout_seconds:g}",
            flush=True,
        )

    def _report_validation_error(
        self,
        *,
        operation: str,
        attempt: int,
        schema: type[BaseModel],
        exc: ValidationError,
        will_retry: bool,
    ) -> None:
        action = "准备重新请求" if will_retry else "重试次数已用尽"
        print(
            f"[LLM_SCHEMA_VALIDATION_FAILED] 大模型 JSON 不符合 Schema，{action}："
            f"operation={operation}, model={self.model}, "
            f"schema={schema.__name__}, attempt={attempt}/{self.max_retries}, "
            f"error_count={exc.error_count()}",
            flush=True,
        )

    @staticmethod
    def _validated_json(
        raw: str,
        response_model: type[BaseModel] | None,
        validation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("模型返回的 JSON 顶层必须是对象")
        if response_model is None:
            return result
        return response_model.model_validate(
            result,
            context=validation_context,
        ).model_dump(mode="json")

    @staticmethod
    def _schema_correction_message(
        response_model: type[BaseModel],
        exc: ValidationError,
        validation_context: dict[str, Any] | None = None,
    ) -> str:
        errors = [
            {
                "location": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in exc.errors(include_url=False)[:20]
        ]
        correction = (
            f"上一份 JSON 未通过 {response_model.__name__} 校验。"
            "请重新生成完整 JSON，严格保持既定返回结构，不要添加 Markdown 或额外字段。"
            f"校验错误：{json.dumps(errors, ensure_ascii=False)}"
        )
        if validation_context and "allowed_evidence_ids" in validation_context:
            allowed_ids = sorted(validation_context["allowed_evidence_ids"])
            correction += (
                "所有 evidence_ids 只能逐字符复制以下合法 ID，禁止新建、改名或添加后缀："
                f"{json.dumps(allowed_ids, ensure_ascii=False)}"
            )
        return correction

    def analyze_json(
        self,
        *,
        system_prompt: str,
        text: str,
        image_urls: Iterable[str] = (),
        temperature: float = 0.2,
        response_model: type[BaseModel] | None = None,
        validation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Request JSON and retry when parsing or Pydantic validation fails."""
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content.extend(
            {"type": "image_url", "image_url": {"url": url, "detail": "low"}}
            for url in image_urls
            if url
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
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
                try:
                    return self._validated_json(raw, response_model, validation_context)
                except ValidationError as exc:
                    if response_model is None:
                        raise
                    self._report_validation_error(
                        operation="analyze_json",
                        attempt=attempt + 1,
                        schema=response_model,
                        exc=exc,
                        will_retry=attempt < self.max_retries - 1,
                    )
                    messages.extend(
                        [
                            {"role": "assistant", "content": raw},
                            {
                                "role": "user",
                                "content": self._schema_correction_message(
                                    response_model,
                                    exc,
                                    validation_context,
                                ),
                            },
                        ]
                    )
                    raise
            except Exception as exc:  # network failures and malformed model output
                last_error = exc
                if self._is_timeout_error(exc):
                    self._report_timeout(operation="analyze_json", attempt=attempt + 1)
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
        response_model: type[BaseModel] | None = None,
        validation_context: dict[str, Any] | None = None,
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
                try:
                    return self._validated_json(raw, response_model, validation_context)
                except ValidationError as exc:
                    if response_model is None:
                        raise
                    self._report_validation_error(
                        operation="continue_json",
                        attempt=attempt + 1,
                        schema=response_model,
                        exc=exc,
                        will_retry=attempt < self.max_retries - 1,
                    )
                    messages.extend(
                        [
                            {"role": "assistant", "content": raw},
                            {
                                "role": "user",
                                "content": self._schema_correction_message(
                                    response_model,
                                    exc,
                                    validation_context,
                                ),
                            },
                        ]
                    )
                    raise
            except Exception as exc:
                last_error = exc
                if self._is_timeout_error(exc):
                    self._report_timeout(operation="continue_json", attempt=attempt + 1)
                if attempt == self.max_retries - 1:
                    break
                time.sleep(2**attempt)
        raise RuntimeError("LLM 多轮请求失败") from last_error
