import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.LLM.client import LLMClient
from app.LLM.service import XiaohongshuInsightService
from app.schemas.llmoutput import (
    ImageAnalysisOutput,
    PostAnalysisModelOutput,
    XiaohongshuAnalysisOutput,
    XiaohongshuSummaryModelOutput,
    XiaohongshuSummaryOutput,
)


def completion(payload):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
            )
        ]
    )


class SequencedCompletions:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.messages = []

    def create(self, **kwargs):
        self.messages.append(kwargs["messages"])
        return completion(self.payloads.pop(0))


def make_client(payloads):
    client = LLMClient.__new__(LLMClient)
    client.model = "test-model"
    client.max_retries = len(payloads)
    client.timeout_seconds = 1
    completions = SequencedCompletions(payloads)
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    return client, completions


def valid_image_output():
    return {
        "note_id": "note-1",
        "image_observations": [],
        "visible_product_details": [],
        "visible_usage_or_result": [],
        "image_caveats": [],
    }


def valid_post_output():
    return {
        "post_id": "note-1",
        "source": {
            "platform": "xiaohongshu",
            "title": "测试笔记",
            "publish_time": "未提供",
            "url": "https://www.xiaohongshu.com/explore/note-1",
        },
        "post_sentiment": "positive",
        "post_summary": "整体反馈偏正面。",
        "product_mentions": [{"name": "测试耳机", "variant": "未提及"}],
        "aspects": [
            {
                "aspect": "质量",
                "sentiment": "positive",
                "opinion": "体验不错。",
                "evidence_ids": ["e1"],
            }
        ],
        "comment_overview": {
            "total": 0,
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "mixed": 0,
            "key_questions": [],
        },
        "image_observations": [],
        "content_risk": {"level": "low", "score": 0, "reasons": []},
        "evidence_items": [
            {
                "evidence_id": "e1",
                "aspect": "质量",
                "source_type": "post",
                "source_ref": "note",
                "quote": "测试耳机体验不错",
                "context": "正文",
                "sentiment": "positive",
                "risk_level": "low",
                "risk_score": 0,
                "risk_reasons": [],
            }
        ],
        "purchase_intent": "consider",
        "risks_or_caveats": [],
        "confidence": 0.8,
    }


def valid_summary_output():
    return {
        "purchase_reference": {
            "trust_aware_one_liner": "当前反馈偏正面，建议结合需求判断。",
            "raw_one_liner": "当前反馈偏正面。",
            "recommended_default_mode": "trust_aware",
            "reasons_for_difference": [],
            "evidence_ids": [],
        },
        "sample_overview": {
            "posts_analyzed": 1,
            "comment_count": 0,
            "coverage_note": "测试样本",
        },
        "sentiment_scores": {
            "raw": 80,
            "trust_aware": 75,
            "analysis_confidence": 80,
            "score_disclaimer": "分数反映评价情感倾向，不是商品客观质量分。",
        },
        "platform": {
            "name": "xiaohongshu",
            "content_count": 1,
            "raw_score": 80,
            "trust_aware_score": 75,
            "high_risk_content_ratio": 0,
        },
        "aspects": [],
        "risk_overview": {
            "high_risk_content_count": 0,
            "high_risk_content_ratio": 0,
            "reason_distribution": [],
            "caution": "风险分数表示内容需要谨慎参考，不代表评论一定虚假。",
        },
        "recommended_sources": [],
        "evidence_details": [],
        "limitations": [],
    }


def valid_summary_model_output():
    payload = valid_summary_output()
    payload.pop("evidence_details")
    return payload


def test_analyze_json_retries_after_schema_validation_failure(monkeypatch):
    client, completions = make_client([{"unexpected": True}, valid_image_output()])
    monkeypatch.setattr("app.LLM.client.time.sleep", lambda _seconds: None)

    result = client.analyze_json(
        system_prompt="system",
        text="user",
        response_model=ImageAnalysisOutput,
    )

    assert result["note_id"] == "note-1"
    assert len(completions.messages) == 2
    assert "ImageAnalysisOutput" in completions.messages[1][-1]["content"]


def test_continue_json_retries_after_schema_validation_failure(monkeypatch):
    invalid = {**valid_post_output(), "confidence": 2}
    client, completions = make_client([invalid, valid_post_output()])
    monkeypatch.setattr("app.LLM.client.time.sleep", lambda _seconds: None)

    result = client.continue_json(
        system_prompt="system",
        previous_user_text="image request",
        previous_assistant_json=valid_image_output(),
        next_user_text="post request",
        response_model=PostAnalysisModelOutput,
    )

    assert result["confidence"] == 0.8
    assert len(completions.messages) == 2
    assert "PostAnalysisModelOutput" in completions.messages[1][-1]["content"]


class SchemaAwareFakeLlm:
    def __init__(self):
        self.response_models = []

    def analyze_json(self, *, response_model, **kwargs):
        self.response_models.append(response_model)
        if response_model is ImageAnalysisOutput:
            return valid_image_output()
        if response_model is XiaohongshuSummaryModelOutput:
            payload = valid_summary_model_output()
            allowed_ids = sorted(kwargs["validation_context"]["allowed_evidence_ids"])
            payload["purchase_reference"]["evidence_ids"] = allowed_ids[:1]
            return payload
        raise AssertionError(f"unexpected response model: {response_model}")

    def continue_json(self, *, response_model, **_kwargs):
        self.response_models.append(response_model)
        assert response_model is PostAnalysisModelOutput
        return valid_post_output()


def test_service_validates_both_stages_and_complete_batch():
    llm = SchemaAwareFakeLlm()
    service = XiaohongshuInsightService(llm, max_workers=1, max_images_per_post=1)
    post = {
        "note_id": "note-1",
        "url": "https://www.xiaohongshu.com/explore/note-1",
        "title": "测试笔记",
        "text": "测试耳机体验不错。",
        "images": [{"position": 0, "url": "https://example.com/image.jpg"}],
        "comments": [],
    }

    result = service.analyze_batch("测试耳机", [post])

    validated = XiaohongshuAnalysisOutput.model_validate(result)
    assert validated.post_analyses[0].image_analysis.note_id == "note-1"
    assert validated.post_analyses[0].evidence_items[0].evidence_id.startswith(
        "p1::note-1::"
    )
    assert validated.summary.evidence_details[0].quote == "测试耳机体验不错"
    assert (
        validated.summary.evidence_details[0].url
        == "https://www.xiaohongshu.com/explore/note-1"
    )
    assert llm.response_models == [
        ImageAnalysisOutput,
        PostAnalysisModelOutput,
        XiaohongshuSummaryModelOutput,
    ]


def test_post_schema_rejects_duplicate_evidence_ids():
    payload = valid_post_output()
    payload["evidence_items"] = [
        {
            "evidence_id": "duplicate",
            "aspect": "功效",
            "source_type": "post",
            "source_ref": "note",
            "quote": "第一条证据",
            "context": "",
            "sentiment": "positive",
            "risk_level": "low",
            "risk_score": 0,
            "risk_reasons": [],
        },
        {
            "evidence_id": "duplicate",
            "aspect": "价格",
            "source_type": "post",
            "source_ref": "note",
            "quote": "第二条证据",
            "context": "",
            "sentiment": "negative",
            "risk_level": "low",
            "risk_score": 0,
            "risk_reasons": [],
        },
    ]

    with pytest.raises(ValidationError, match="must be unique"):
        PostAnalysisModelOutput.model_validate(payload)


def test_summary_schema_rejects_unknown_evidence_references():
    payload = valid_summary_output()
    payload["purchase_reference"]["evidence_ids"] = ["missing"]

    with pytest.raises(ValidationError, match="unknown summary evidence_ids"):
        XiaohongshuSummaryOutput.model_validate(payload)


def test_summary_model_retries_with_exact_allowed_evidence_ids(monkeypatch):
    invalid = valid_summary_model_output()
    invalid["purchase_reference"]["evidence_ids"] = ["e1_3"]
    client, completions = make_client([invalid, valid_summary_model_output()])
    monkeypatch.setattr("app.LLM.client.time.sleep", lambda _seconds: None)

    result = client.analyze_json(
        system_prompt="system",
        text="user",
        response_model=XiaohongshuSummaryModelOutput,
        validation_context={"allowed_evidence_ids": {"p3::note-3::e1"}},
    )

    assert result["purchase_reference"]["evidence_ids"] == []
    correction = completions.messages[1][-1]["content"]
    assert "unknown input evidence_ids" in correction
    assert "p3::note-3::e1" in correction
    assert "禁止新建、改名或添加后缀" in correction


def test_globalizes_same_local_evidence_id_across_posts():
    service = XiaohongshuInsightService.__new__(XiaohongshuInsightService)
    first = {
        **valid_post_output(),
        "image_analysis": valid_image_output(),
    }
    second = {
        **valid_post_output(),
        "post_id": "note-2",
        "image_analysis": {**valid_image_output(), "note_id": "note-2"},
    }

    first = service._globalize_post_evidence_ids(first, 1)
    second = service._globalize_post_evidence_ids(second, 2)
    catalog = service._build_evidence_catalog([first, second])

    first_id = first["evidence_items"][0]["evidence_id"]
    second_id = second["evidence_items"][0]["evidence_id"]
    assert first_id == "p1::note-1::e1"
    assert second_id == "p2::note-2::e1"
    assert set(catalog) == {first_id, second_id}
    assert first["aspects"][0]["evidence_ids"] == [first_id]
    assert second["aspects"][0]["evidence_ids"] == [second_id]
