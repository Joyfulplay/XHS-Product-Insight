from app.services.analysis_pipeline import AnalysisPipelineService


def test_analysis_pipeline_builds_frontend_contract():
    dataset = {
        "schema_version": "1.1",
        "collection": {"note_count": 1, "comment_count": 2},
        "notes": [
            {
                "note_id": "note-1",
                "url": "https://www.xiaohongshu.com/explore/note-1",
                "title": "降噪耳机通勤体验",
                "text": "音质不错，通勤很舒服，但是价格有点贵。",
                "engagement": {"likes": 12},
                "comments": [
                    {"comment_id": "comment-1", "text": "降噪真的好用，推荐。", "likes": 5},
                    {"comment_id": "comment-2", "text": "价格贵，有点闷。", "likes": 3},
                ],
            }
        ],
        "errors": [],
    }

    result = AnalysisPipelineService().run(dataset)

    assert result.collection.valid_comment_count == 2
    assert "降噪" in result.llm_insights.product_attributes
    assert result.statistics.sentiment_distribution is not None
    assert result.representative_notes[0].url == "https://www.xiaohongshu.com/explore/note-1"
