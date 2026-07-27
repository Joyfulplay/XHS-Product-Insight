"""Opt-in integration test for the configured OpenAI-compatible LLM.

Run from the project root:

    RUN_LLM_CONNECTIVITY_TEST=1 PYTHONPATH=backend \
        python3 -m pytest -q -s backend/tests/test_llm_connectivity.py

The test loads OPENAI_API_KEY, OPENAI_BASE_URL, and LLM_MODEL from the
project's .env file without overriding values already exported by the shell.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.LLM.client import LLMClient


def _load_local_env(path: Path) -> None:
    """Load simple KEY=VALUE entries without printing secrets."""
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("export "):
            entry = entry[7:].lstrip()
        if "=" not in entry:
            continue

        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def test_llm_connectivity() -> None:
    """Send one real request and verify that the model returns a JSON object."""
    if os.getenv("RUN_LLM_CONNECTIVITY_TEST") != "1":
        pytest.skip("设置 RUN_LLM_CONNECTIVITY_TEST=1 后才会调用真实大模型")

    _load_local_env(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.fail("未配置 OPENAI_API_KEY，请在项目根目录的 .env 中设置")

    model = os.getenv("LLM_MODEL", "gpt-4.1-mini")

    try:
        response = LLMClient(max_retries=1).analyze_json(
            system_prompt="你是连通性测试助手，只返回 JSON 对象。",
            text='请只返回 {"status":"ok"}，不要添加其他内容。',
            temperature=0,
        )
    except Exception as exc:
        cause = exc.__cause__ or exc
        pytest.fail(
            f"大模型连通性测试失败（model={model}）："
            f"{type(cause).__name__}: {cause}",
            pytrace=True,
        )

    assert isinstance(response, dict)
    assert response, f"模型 {model} 已响应，但返回了空 JSON 对象"
    print(f"大模型连通正常：model={model}, response={response}")
