import pytest
from pydantic import ValidationError

from app.data.crawlers.xhs_client import DEFAULT_RAW_DATA_DIR, default_output_path
from app.schemas.crawler import CrawlDataset


def raw_dataset():
    return {
        "schema_version": "1.1",
        "input": {
            "type": "keyword",
            "value": "耳机",
            "resolved_query": "耳机",
        },
        "collected_at": "2026-07-23T10:00:00+08:00",
        "collection": {
            "candidate_limit": 50,
            "note_limit": 10,
            "comments_per_note_limit": 20,
            "min_note_likes": 10,
            "min_comment_likes": 2,
            "candidate_count": 2,
            "note_count": 1,
            "comment_count": 1,
        },
        "notes": [
            {
                "note_id": "note-1",
                "url": "https://www.xiaohongshu.com/explore/note-1",
                "search_query": "耳机",
                "search_rank": 1,
                "title": "耳机使用体验",
                "text": "降噪表现不错。",
                "tags": ["耳机"],
                "publish_time": "2026-07-22T10:00:00+08:00",
                "author_id_hash": "sha256:abc",
                "engagement": {
                    "likes": 12,
                    "favorites": 3,
                    "comments": 1,
                    "shares": 0,
                },
                "images": [],
                "comments": [
                    {
                        "comment_id": "comment-1",
                        "text": "我也有同感。",
                        "author_id_hash": "sha256:def",
                        "likes": 2,
                        "publish_time": "2026-07-22T11:00:00+08:00",
                    }
                ],
            }
        ],
        "errors": [],
    }


def test_crawl_dataset_accepts_complete_payload():
    dataset = CrawlDataset.model_validate(raw_dataset())

    assert dataset.collection.note_count == 1


def test_crawl_dataset_rejects_inconsistent_summary_counts():
    payload = raw_dataset()
    payload["collection"]["comment_count"] = 2

    with pytest.raises(ValidationError, match="comment_count"):
        CrawlDataset.model_validate(payload)


def test_default_crawler_output_uses_project_raw_data_directory():
    output = default_output_path()

    assert output.parent == DEFAULT_RAW_DATA_DIR
    assert output.suffix == ".json"
