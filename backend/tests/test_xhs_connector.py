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
from app.services.persistence_service import PersistenceService
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
        self.build_calls = []

    def _build_scraper(self, browser="auto", *, max_notes=None, max_comments=None):
        self.build_calls.append(
            {"browser": browser, "max_notes": max_notes, "max_comments": max_comments}
        )
        return self.scraper


def test_collection_request_defaults_and_custom_limits_reach_the_scraper():
    dataset = {
        "schema_version": "1.1",
        "input": {"type": "keyword", "resolved_query": "example headphones"},
        "collection": {"note_count": 0, "comment_count": 0},
        "notes": [],
        "errors": [],
    }
    scraper = FakeScraper(dataset)
    service = FakeConnectorService(scraper)

    default_request = CollectionRequest(source="example headphones")
    assert default_request.max_notes == 10
    assert default_request.max_comments_per_note == 20

    default_job = service.start_collection(default_request)
    assert service.jobs.get(default_job["job_id"])["status"] == "succeeded"
    assert service.build_calls[-1] == {"browser": "auto", "max_notes": 10, "max_comments": 20}

    job = service.start_collection(
        CollectionRequest(source="example headphones", max_notes=15, max_comments_per_note=20)
    )

    assert service.jobs.get(job["job_id"])["status"] == "succeeded"
    assert service.build_calls[-1] == {"browser": "auto", "max_notes": 15, "max_comments": 20}


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "example headphones", "max_notes": 0},
        {"source": "example headphones", "max_notes": 51},
        {"source": "example headphones", "max_comments_per_note": -1},
        {"source": "example headphones", "max_comments_per_note": 101},
    ],
)
def test_collection_endpoint_rejects_out_of_range_limits(payload):
    from main import app

    response = TestClient(app).post("/api/v1/xhs/collections", json=payload)

    assert response.status_code == 422


class FailingPersistence:
    def save(self, key, payload):
        raise OSError("persistence failed")


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


def test_collection_keeps_full_note_link_only_in_memory(tmp_path):
    full_note_url = "https://www.xiaohongshu.com/explore/note-1?xsec_token=private-token&xsec_source=pc_search"
    scraper = FakeScraper(
        {
            "schema_version": "1.1",
            "input": {"type": "keyword", "resolved_query": "耳机"},
            "collection": {"note_count": 1, "comment_count": 0},
            "notes": [
                {
                    "note_id": "note-1",
                    "url": "https://www.xiaohongshu.com/explore/note-1",
                    "_xhs_open_url": full_note_url,
                    "title": "公开笔记",
                    "text": "公开内容",
                    "comments": [],
                    "engagement": {"likes": 1},
                }
            ],
            "errors": [],
        }
    )
    service = FakeConnectorService(scraper)
    service.persistence = PersistenceService(tmp_path)

    job = service.start_collection(CollectionRequest(source="耳机"))
    completed = service.jobs.get(job["job_id"])
    representative = completed["result"]["representative_notes"][0]
    persisted = (tmp_path / f"{job['job_id']}.json").read_text(encoding="utf-8")

    assert representative["source_url"].endswith(f"/collections/{job['job_id']}/notes/note-1/open")
    assert representative["link_expires_at"] is not None
    assert "private-token" not in str(completed["result"])
    assert "xsec_token" not in str(completed["result"])
    assert "private-token" not in persisted
    assert "xsec_token" not in persisted
    assert service.note_open_url(job["job_id"], "note-1") == full_note_url


def test_collection_does_not_fallback_to_a_canonical_note_url_without_a_full_link():
    scraper = FakeScraper(
        {
            "schema_version": "1.1",
            "input": {"type": "keyword", "resolved_query": "耳机"},
            "collection": {"note_count": 1, "comment_count": 0},
            "notes": [
                {
                    "note_id": "note-1",
                    "url": "https://www.xiaohongshu.com/explore/note-1",
                    "_xhs_open_url": "https://www.xiaohongshu.com/explore/note-1",
                    "title": "公开笔记",
                    "text": "公开内容",
                    "comments": [],
                    "engagement": {"likes": 1},
                }
            ],
            "errors": [],
        }
    )
    service = FakeConnectorService(scraper)

    job = service.start_collection(CollectionRequest(source="耳机"))
    completed = service.jobs.get(job["job_id"])
    representative = completed["result"]["representative_notes"][0]

    assert representative["source_url"].endswith(f"/collections/{job['job_id']}/notes/note-1/open")
    assert representative["link_expires_at"] is None
    assert service.note_open_url(job["job_id"], "note-1") is None


def test_collection_failure_discards_temporary_note_links():
    scraper = FakeScraper(
        {
            "schema_version": "1.1",
            "input": {"type": "keyword", "resolved_query": "耳机"},
            "collection": {"note_count": 1, "comment_count": 0},
            "notes": [
                {
                    "note_id": "note-1",
                    "url": "https://www.xiaohongshu.com/explore/note-1",
                    "_xhs_open_url": "https://www.xiaohongshu.com/explore/note-1?xsec_token=private-token&xsec_source=pc_search",
                    "title": "公开笔记",
                    "text": "公开内容",
                    "comments": [],
                    "engagement": {"likes": 1},
                }
            ],
            "errors": [],
        }
    )
    service = FakeConnectorService(scraper)
    service.persistence = FailingPersistence()

    job = service.start_collection(CollectionRequest(source="耳机"))
    completed = service.jobs.get(job["job_id"])

    assert completed["status"] == "failed"
    assert service.note_open_url(job["job_id"], "note-1") is None


def test_note_open_endpoint_redirects_and_expires(monkeypatch):
    service = XhsConnectorService(job_store=JobStore(), executor=ImmediateExecutor())
    job = service.jobs.create("collection")
    target = "https://www.xiaohongshu.com/explore/note-1?xsec_token=private-token&xsec_source=pc_search"
    service._store_note_open_links(job["job_id"], {"note-1": target})
    monkeypatch.setattr(xhs_connector, "service", service)

    from main import app

    client = TestClient(app)
    response = client.get(
        f"/api/v1/xhs/collections/{job['job_id']}/notes/note-1/open",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == target

    monkeypatch.setattr(xhs_connector, "NOTE_OPEN_LINK_TTL_SECONDS", -1)
    service._store_note_open_links(job["job_id"], {"note-1": target})
    expired = client.get(
        f"/api/v1/xhs/collections/{job['job_id']}/notes/note-1/open",
        follow_redirects=False,
    )

    assert expired.status_code == 410
    assert "链接已过期" in expired.json()["detail"]


def test_note_open_links_do_not_cross_collection_jobs():
    service = XhsConnectorService(job_store=JobStore(), executor=ImmediateExecutor())
    first = service.jobs.create("collection")
    second = service.jobs.create("collection")
    first_target = "https://www.xiaohongshu.com/explore/note-1?xsec_token=first&xsec_source=pc_search"
    second_target = "https://www.xiaohongshu.com/explore/note-1?xsec_token=second&xsec_source=pc_search"

    service._store_note_open_links(first["job_id"], {"note-1": first_target})
    service._store_note_open_links(second["job_id"], {"note-1": second_target})

    assert service.note_open_url(first["job_id"], "note-1") == first_target
    assert service.note_open_url(second["job_id"], "note-1") == second_target


def test_note_open_endpoint_returns_gone_after_restart(monkeypatch):
    service = XhsConnectorService(job_store=JobStore(), executor=ImmediateExecutor())
    monkeypatch.setattr(xhs_connector, "service", service)

    from main import app

    response = TestClient(app).get(
        "/api/v1/xhs/collections/xhs_collection_missing/notes/note-1/open",
        follow_redirects=False,
    )

    assert response.status_code == 410


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
