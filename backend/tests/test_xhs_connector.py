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
from app.data.crawlers.xhs_client import AuthRequiredError


class ImmediateExecutor:
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:  # pragma: no cover - matches Executor behavior
            future.set_exception(exc)
        return future


class FakeScraper:
    def __init__(self, dataset=None, error=None, auth_error=None):
        self.dataset = dataset
        self.error = error
        self.auth_error = auth_error
        self.login_force = None
        self.auth_checks = 0
        self.collection_calls = 0

    def login(self, *, force=False):
        self.login_force = force
        if self.error:
            raise self.error

    def validate_saved_login(self):
        self.auth_checks += 1
        if self.auth_error:
            raise self.auth_error

    def collect(self, source, query_override=None):
        self.collection_calls += 1
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


def test_auth_status_rejects_guest_or_expired_sessions_and_caches_live_result():
    scraper = FakeScraper(auth_error=AuthRequiredError("当前保存的是游客会话或登录已失效，请重新登录"))
    service = FakeConnectorService(scraper)

    first = service.auth_status(refresh=True)
    cached = service.auth_status()
    refreshed = service.auth_status(refresh=True)

    assert first["authenticated"] is False
    assert first["status"] == "unauthenticated"
    assert first["verification"] == "live"
    assert cached["verification"] == "cached"
    assert refreshed["verification"] == "live"
    assert scraper.auth_checks == 2


def test_forced_login_uses_a_fresh_login_task_and_rechecks_authentication():
    scraper = FakeScraper()
    service = FakeConnectorService(scraper)

    job = service.start_login("auto", force=True)
    completed = service.jobs.get(job["job_id"])

    assert completed["status"] == "succeeded"
    assert scraper.login_force is True
    assert scraper.auth_checks == 1


def test_login_job_fails_when_the_new_session_cannot_pass_live_authentication():
    scraper = FakeScraper(auth_error=AuthRequiredError("当前保存的是游客会话或登录已失效，请重新登录"))
    service = FakeConnectorService(scraper)

    job = service.start_login("auto", force=True)
    completed = service.jobs.get(job["job_id"])

    assert completed["status"] == "failed"
    assert completed["error"]["code"] == "AUTH_REQUIRED"
    assert scraper.login_force is True


def test_collection_stops_before_crawler_when_live_authentication_fails():
    scraper = FakeScraper(auth_error=AuthRequiredError("小红书登录状态不存在或已过期，请重新登录"))
    service = FakeConnectorService(scraper)

    job = service.start_collection(CollectionRequest(source="索尼 XM5"))
    completed = service.jobs.get(job["job_id"])

    assert completed["status"] == "failed"
    assert completed["error"]["code"] == "AUTH_REQUIRED"
    assert scraper.collection_calls == 0


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
