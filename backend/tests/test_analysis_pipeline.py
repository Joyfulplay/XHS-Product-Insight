from app.services.analysis_pipeline import AnalysisPipelineService


class FakeLlmClient:
    def analyze_json(self, **_kwargs):
        return {
            "overall_summary": "LLM ???????",
            "product_attributes": ["??", "??"],
            "usage_scenarios": ["??"],
            "user_types": ["???"],
            "unsuitable_users": ["???????"],
            "pros": ["??????"],
            "cons": ["????????????"],
            "purchase_advice": "??????????????",
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


def test_analysis_pipeline_uses_llm_insights_when_available(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    service = AnalysisPipelineService(llm_client_factory=FakeLlmClient)

    result = service.run(sample_dataset())

    assert result.llm_insights.overall_summary == "LLM ???????"
    assert result.llm_insights.usage_scenarios == ["??"]


def test_sentiment_distribution_rounding_does_not_exceed_one():
    service = AnalysisPipelineService()
    texts = ["good"] * 8 + ["ordinary"] * 26 + ["bad"]

    distribution = service._sentiment_distribution(texts)

    assert distribution is not None
    assert distribution.positive == 0.2286
    assert distribution.neutral == 0.7429
    assert distribution.negative == 0.0285
    assert distribution.positive + distribution.neutral + distribution.negative <= 1
