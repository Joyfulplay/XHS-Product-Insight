from concurrent.futures import Future

import pytest
from fastapi.testclient import TestClient

import app.api.xhs_connector as xhs_connector
from app.api.xhs_connector import (
    CollectionRequest,
    JobStore,
    XhsConnectorService,
    normalize_collection_dataset,
)


class ImmediateExecutor:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:  # pragma: no cover - matches Executor behavior
            future.set_exception(exc)
        return future


class FakeScraper:
    def __init__(self, dataset=None, error=None):
        self.dataset = dataset
        self.error = error

    def login(self):
        if self.error:
            raise self.error

    def collect(self, source, query_override=None):
        if self.error:
            raise self.error
        return self.dataset


class FakeConnectorService(XhsConnectorService):
    def __init__(self, scraper):
        super().__init__(job_store=JobStore(), executor=ImmediateExecutor())
        self.scraper = scraper

    def _build_scraper(self, browser="auto"):
        return self.scraper


def test_collection_request_accepts_a_product_keyword():
    request = CollectionRequest(source="索尼 XM5")

    assert request.source == "索尼 XM5"


def test_collection_request_rejects_an_xiaohongshu_url():
    with pytest.raises(ValueError, match="商品名或淘宝/天猫"):
        CollectionRequest(source="https://www.xiaohongshu.com/explore/example")


def test_normalize_collection_dataset_removes_authentication_fields():
    result = normalize_collection_dataset(
        {
            "schema_version": "1.1",
            "input": {"type": "keyword", "resolved_query": "耳机", "value": "https://detail.tmall.com/?session=secret"},
            "collection": {"note_count": 1, "comment_count": 0},
            "notes": [
                {
                    "title": "公开笔记",
                    "author_id_hash": "sha256:abc",
                    "url": "https://www.xiaohongshu.com/explore/note?xsec_token=secret&public=1",
                    "web_session": "secret",
                    "comments": [],
                }
            ],
            "errors": [],
            "a1": "secret",
        }
    )

    assert result["input"] == {"source": "keyword", "query": "耳机"}
    assert result["notes"][0]["url"] == "https://www.xiaohongshu.com/explore/note?public=1"
    assert "web_session" not in result["notes"][0]
    assert "a1" not in str(result)


def test_collection_job_returns_desensitized_result():
    scraper = FakeScraper(
        {
            "schema_version": "1.1",
            "input": {"type": "product_url", "resolved_query": "耳机"},
            "collection": {"note_count": 0, "comment_count": 0},
            "notes": [],
            "errors": [],
        }
    )
    service = FakeConnectorService(scraper)

    job = service.start_collection(CollectionRequest(source="https://detail.tmall.com/item.htm?id=1"))

    completed = service.jobs.get(job["job_id"])
    assert completed["status"] == "succeeded"
    assert completed["result"]["input"] == {"source": "taobao_or_tmall", "query": "耳机"}


def test_collection_endpoints_return_a_finished_desensitized_job(monkeypatch):
    scraper = FakeScraper(
        {
            "schema_version": "1.1",
            "input": {"type": "keyword", "resolved_query": "耳机"},
            "collection": {"note_count": 0, "comment_count": 0},
            "notes": [],
            "errors": [],
        }
    )
    monkeypatch.setattr(xhs_connector, "service", FakeConnectorService(scraper))

    from main import app

    client = TestClient(app)
    created = client.post(
        "/api/v1/xhs/collections",
        json={"source": "索尼 XM5"},
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    progress = client.get(f"/api/v1/xhs/collections/{job_id}")
    result = client.get(f"/api/v1/xhs/collections/{job_id}/result")
    assert progress.json()["status"] == "succeeded"
    assert result.status_code == 200
    assert result.json()["input"] == {"source": "keyword", "query": "耳机"}
