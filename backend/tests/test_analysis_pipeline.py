import logging

from app.services.analysis_pipeline import AnalysisPipelineService


class FakeInsightService:
    def analyze_batch(self, _product_name, _notes):
        return {
            "summary": {
                "purchase_reference": {
                    "trust_aware_one_liner": "LLM 可信购买建议",
                    "raw_one_liner": "LLM 原始购买建议",
                    "recommended_default_mode": "trust_aware",
                    "reasons_for_difference": [],
                    "evidence_ids": [],
                },
                "sample_overview": {
                    "posts_analyzed": 1,
                    "comment_count": 2,
                    "coverage_note": "测试样本",
                },
                "sentiment_scores": {
                    "raw": 82,
                    "trust_aware": 76,
                    "analysis_confidence": 88,
                    "score_disclaimer": "分数反映评价情感倾向，不是商品客观质量分。",
                },
                "platform": {
                    "name": "xiaohongshu",
                    "content_count": 1,
                    "raw_score": 82,
                    "trust_aware_score": 76,
                    "high_risk_content_ratio": 0,
                },
                "aspects": [
                    {
                        "name": "降噪",
                        "trust_aware_score": 80,
                        "mention_count": 2,
                        "positive_ratio": 0.5,
                        "neutral_ratio": 0.5,
                        "negative_ratio": 0,
                        "evidence_ids": [],
                    }
                ],
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
        }


def sample_dataset():
    return {
        "schema_version": "1.1",
        "input": {"source": "keyword", "query": "?? XM5"},
        "collection": {"note_count": 1, "comment_count": 2},
        "notes": [
            {
                "note_id": "note-1",
                "url": "https://www.xiaohongshu.com/explore/note-1",
                "title": "????????",
                "text": "???????????????????",
                "tags": ["??", "??"],
                "publish_time": "2026-07-23T10:00:00+08:00",
                "engagement": {"likes": 12},
                "comments": [
                    {"comment_id": "comment-1", "text": "??????????", "likes": 5},
                    {"comment_id": "comment-2", "text": "????????", "likes": 3},
                ],
            }
        ],
        "errors": [],
    }


def test_analysis_pipeline_builds_frontend_contract(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = AnalysisPipelineService().run(sample_dataset())

    assert result.collection.valid_comment_count == 2
    assert result.llm_insights.overall_summary is not None
    assert result.statistics.sentiment_distribution is not None
    assert result.representative_notes[0].url == "https://www.xiaohongshu.com/explore/note-1"


def test_analysis_pipeline_has_no_filesystem_side_effects(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    result = AnalysisPipelineService().run(
        {
            "task_id": "analysis-only",
            "collection": {"note_count": 0, "comment_count": 0},
            "notes": [],
        }
    )

    assert result.collection.note_count == 0
    assert not (tmp_path / "data").exists()


def test_analysis_pipeline_uses_llm_insights_when_available():
    service = AnalysisPipelineService(insight_service_factory=FakeInsightService)

    result, llm_response = service.run_with_llm_response(sample_dataset())

    assert result.llm_insights.overall_summary == "LLM 可信购买建议"
    assert result.llm_insights.purchase_advice == "LLM 可信购买建议"
    assert result.llm_insights.product_attributes == ["降噪"]
    assert llm_response is not None
    assert llm_response["summary"]["sentiment_scores"]["trust_aware"] == 76


def test_analysis_pipeline_emits_start_command_before_llm_analysis(caplog):
    service = AnalysisPipelineService(insight_service_factory=FakeInsightService)

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        service.run(sample_dataset())

    assert "[LLM_ANALYSIS_STARTED]" in caplog.text
    assert "note_count=1" in caplog.text


def test_sentiment_distribution_rounding_does_not_exceed_one():
    service = AnalysisPipelineService()
    texts = ["good"] * 8 + ["ordinary"] * 26 + ["bad"]

    distribution = service._sentiment_distribution(texts)

    assert distribution is not None
    assert distribution.positive == 0.2286
    assert distribution.neutral == 0.7429
    assert distribution.negative == 0.0285
    assert distribution.positive + distribution.neutral + distribution.negative <= 1
