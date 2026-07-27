"""Local asynchronous connector for the Xiaohongshu crawler.

The browser extension only receives task state and desensitized collection
data.  Authentication cookies and browser profiles remain local to the
connector process and are never included in an API response.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from app.data.crawlers.xhs_client import (
    AuthRequiredError,
    PRIVATE_NOTE_OPEN_URL_FIELD,
    XiaohongshuScraper,
    classify_input,
    clean_text,
    translate_client_exception,
)
from app.services.analysis_pipeline import AnalysisPipelineService
from app.services.persistence_service import PersistenceService


router = APIRouter(prefix="/api/v1/xhs", tags=["xhs-connector"])

BrowserName = Literal["auto", "edge", "chrome", "chromium"]
JobKind = Literal["login", "collection"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]

SENSITIVE_FIELD_NAMES = {
    "a1",
    "cookie",
    "cookies",
    "cookie_path",
    "authorization",
    "request_headers",
    "headers",
    "web_session",
    "webid",
    "xsec_token",
    "xsec_source",
    "qr_code",
    "qr_code_credentials",
}
SENSITIVE_QUERY_NAMES = {
    "a1",
    "authorization",
    "cookie",
    "session",
    "token",
    "web_session",
    "webid",
    "xsec_token",
    "xsec_source",
}
NORMALIZED_SENSITIVE_FIELD_NAMES = {normalized for name in SENSITIVE_FIELD_NAMES if (normalized := re.sub(r"[^a-z0-9]", "", name.lower()))}
NORMALIZED_SENSITIVE_QUERY_NAMES = {normalized for name in SENSITIVE_QUERY_NAMES if (normalized := re.sub(r"[^a-z0-9]", "", name.lower()))}
PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCAL_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
NOTE_OPEN_LINK_TTL_SECONDS = 30 * 60
XHS_OPEN_HOSTS = {"xiaohongshu.com", "www.xiaohongshu.com"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalized_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def is_sensitive_field(value: str) -> bool:
    return value.lower() in SENSITIVE_FIELD_NAMES or normalized_field_name(value) in NORMALIZED_SENSITIVE_FIELD_NAMES


def sanitize_url(value: str) -> str:
    """Drop authentication-like query parameters while retaining public URLs."""

    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    safe_query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if normalized_field_name(key) not in NORMALIZED_SENSITIVE_QUERY_NAMES
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_query), ""))


def sanitize_value(value: Any, key: str | None = None) -> Any:
    """Defence in depth: prevent future crawler changes from leaking secrets."""

    if key == PRIVATE_NOTE_OPEN_URL_FIELD or (key is not None and is_sensitive_field(key)):
        return None
    if isinstance(value, dict):
        return {
            child_key: sanitized
            for child_key, child_value in value.items()
            if not is_sensitive_field(str(child_key))
            and (sanitized := sanitize_value(child_value, str(child_key))) is not None
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str) and key is not None and "url" in key.lower():
        return sanitize_url(value)
    return value


def normalize_collection_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    """Return the documented connector schema with only public XHS content."""

    safe_dataset = sanitize_value(dataset)
    raw_input = safe_dataset.get("input", {})
    input_type = raw_input.get("type")
    return {
        "schema_version": safe_dataset.get("schema_version", "1.1"),
        "collected_at": safe_dataset.get("collected_at"),
        "input": {
            "source": "keyword" if input_type == "keyword" else "taobao_or_tmall",
            "query": raw_input.get("resolved_query"),
        },
        "collection": safe_dataset.get("collection", {}),
        "notes": safe_dataset.get("notes", []),
        "errors": safe_dataset.get("errors", []),
    }


def frontend_llm_summary_fields(llm_response: dict[str, Any] | None) -> dict[str, Any]:
    """Expose the complete validated summary without raw per-post LLM data."""

    if not isinstance(llm_response, dict):
        return {}
    summary = llm_response.get("summary")
    if not isinstance(summary, dict):
        return {}

    allowed_summary_fields = (
        "pros",
        "cons",
        "purchase_reference",
        "sample_overview",
        "sentiment_scores",
        "platform",
        "aspects",
        "risk_overview",
        "recommended_sources",
        "evidence_details",
        "limitations",
    )
    return {
        field_name: sanitize_value(summary[field_name], field_name)
        for field_name in allowed_summary_fields
        if field_name in summary
    }


class LoginRequest(BaseModel):
    browser: BrowserName = "auto"
    force: bool = False


class CollectionRequest(BaseModel):
    source: str = Field(min_length=1, max_length=2_000)
    query_override: str | None = Field(default=None, max_length=300)
    max_notes: int = Field(default=10, ge=1, le=50)
    max_comments_per_note: int = Field(default=20, ge=0, le=100)

    @field_validator("source")
    @classmethod
    def source_must_be_product_keyword_or_url(cls, value: str) -> str:
        source = clean_text(value)
        if not source:
            raise ValueError("source 必须是商品名或淘宝/天猫商品链接")
        try:
            input_type = classify_input(source)
        except Exception as exc:
            raise ValueError("source 必须是商品名或淘宝/天猫商品链接") from exc
        if input_type not in {"keyword", "product_url"}:
            raise ValueError("source 必须是商品名或淘宝/天猫商品链接")
        return source

    @field_validator("query_override")
    @classmethod
    def normalize_query_override(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_text(value) or None


class ErrorDetail(BaseModel):
    code: str
    message: str


class JobResponse(BaseModel):
    job_id: str
    kind: JobKind
    status: JobStatus
    stage: str
    progress: float = Field(ge=0, le=1)
    created_at: str
    updated_at: str
    error: ErrorDetail | None = None


class AuthStatusResponse(BaseModel):
    authenticated: bool
    status: Literal["authenticated", "unauthenticated", "unavailable"]
    checked_at: str
    verification: Literal["live", "cached", "missing_cookie", "unavailable"]
    error: ErrorDetail | None = None


@dataclass(frozen=True)
class ConnectorSettings:
    profile_dir: Path = Path(os.getenv("XHS_PROFILE_DIR", str(PROJECT_ROOT / ".runtime/xhs-profile"))).resolve()
    max_candidates: int = 50
    max_notes: int = 10
    max_comments: int = 20
    min_note_likes: int = 10
    min_comment_likes: int = 2
    delay: float = 1.0


class JobStore:
    """Small, process-local store for long-running browser and crawler jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def create(self, kind: JobKind) -> dict[str, Any]:
        timestamp = utc_now()
        job = {
            "job_id": f"xhs_{kind}_{uuid4().hex}",
            "kind": kind,
            "status": "queued",
            "stage": "queued",
            "progress": 0.0,
            "created_at": timestamp,
            "updated_at": timestamp,
            "error": None,
            "result": None,
        }
        with self._lock:
            self._jobs[job["job_id"]] = job
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def active_job(self, kind: JobKind) -> dict[str, Any] | None:
        with self._lock:
            for job in self._jobs.values():
                if job["kind"] == kind and job["status"] in {"queued", "running"}:
                    return dict(job)
        return None

    def update(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(updates)
            job["updated_at"] = utc_now()

    @staticmethod
    def public(job: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in job.items() if key != "result"}


class XhsConnectorService:
    def __init__(
        self,
        settings: ConnectorSettings | None = None,
        job_store: JobStore | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.settings = settings or ConnectorSettings()
        self.jobs = job_store or JobStore()
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="xhs-job")
        self.analysis_pipeline = AnalysisPipelineService()
        self.raw_persistence = PersistenceService(PROJECT_ROOT / "data/raw")
        self.persistence = PersistenceService(PROJECT_ROOT / "data/processed")
        self.result_persistence = PersistenceService(PROJECT_ROOT / "data/result")
        self._futures: dict[str, Future[Any]] = {}
        self._auth_cache: dict[str, Any] | None = None
        self._auth_cache_at = 0.0
        self._auth_lock = RLock()
        self._note_open_links: dict[str, dict[str, tuple[str, datetime]]] = {}
        self._note_open_links_lock = RLock()

    def _build_scraper(
        self,
        browser: BrowserName = "auto",
        *,
        max_notes: int | None = None,
        max_comments: int | None = None,
    ) -> XiaohongshuScraper:
        return XiaohongshuScraper(
            profile_dir=self.settings.profile_dir,
            max_candidates=self.settings.max_candidates,
            max_notes=self.settings.max_notes if max_notes is None else max_notes,
            max_comments=self.settings.max_comments if max_comments is None else max_comments,
            min_note_likes=self.settings.min_note_likes,
            min_comment_likes=self.settings.min_comment_likes,
            delay=self.settings.delay,
            headless=False,
            browser=browser,
        )

    def start_login(self, browser: BrowserName, *, force: bool = False) -> dict[str, Any]:
        existing = self.jobs.active_job("login")
        if existing:
            raise ValueError(existing["job_id"])
        job = self.jobs.create("login")
        self._futures[job["job_id"]] = self.executor.submit(self._run_login, job["job_id"], browser, force)
        return job

    def _run_login(self, job_id: str, browser: BrowserName, force: bool) -> None:
        self.jobs.update(job_id, status="running", stage="waiting_for_login", progress=0.1)
        try:
            self._build_scraper(browser).login(force=force)
            self.auth_status(refresh=True, require_authenticated=True)
        except Exception as exc:
            error = translate_client_exception(exc)
            self.jobs.update(
                job_id,
                status="failed",
                stage="failed",
                progress=1.0,
                error={"code": error.code, "message": clean_text(error)[:500]},
            )
            return
        self.jobs.update(job_id, status="succeeded", stage="completed", progress=1.0)

    def start_collection(self, request: CollectionRequest) -> dict[str, Any]:
        existing = self.jobs.active_job("collection")
        if existing:
            raise ValueError(existing["job_id"])
        job = self.jobs.create("collection")
        self._futures[job["job_id"]] = self.executor.submit(
            self._run_collection, job["job_id"], request
        )
        return job

    def _run_collection(self, job_id: str, request: CollectionRequest) -> None:
        self.jobs.update(job_id, status="running", stage="collecting", progress=0.1)
        try:
            self.auth_status(refresh=True, require_authenticated=True)
            scraper = self._build_scraper(
                max_notes=request.max_notes,
                max_comments=request.max_comments_per_note,
            )
            dataset = scraper.collect(request.source, query_override=request.query_override)
            raw_storage_path = self.raw_persistence.save(job_id, dataset)
            note_open_links = self._extract_note_open_links(dataset)
            processed_dataset = normalize_collection_dataset(dataset)
            processed_storage_path = self.persistence.save(job_id, processed_dataset)
            self._store_note_open_links(job_id, note_open_links)
            result = {
                **processed_dataset,
                "job_id": job_id,
                "storage": {
                    "raw_path": raw_storage_path,
                    "processed_path": processed_storage_path,
                },
            }
        except Exception as exc:
            self._discard_note_open_links(job_id)
            error = translate_client_exception(exc)
            self.jobs.update(
                job_id,
                status="failed",
                stage="failed",
                progress=1.0,
                error={"code": error.code, "message": clean_text(error)[:500]},
            )
            return
        self.jobs.update(
            job_id,
            status="succeeded",
            stage="completed",
            progress=1.0,
            result=result,
        )

    def analyze_collection(self, job_id: str) -> dict[str, Any]:
        """Analyze precisely the dataset saved by one completed collection job."""

        job = self.jobs.get(job_id)
        if job is not None and job["kind"] != "collection":
            raise KeyError(job_id)
        if job is not None and job["status"] != "succeeded":
            raise RuntimeError("采集任务尚未完成")
        if job is not None and job.get("analysis_result") is not None:
            return job["analysis_result"]

        dataset = self.persistence.load(job_id)
        if dataset is None:
            if job is None:
                raise KeyError(job_id)
            raise RuntimeError("找不到该采集任务对应的数据文件")
        dataset["task_id"] = job_id
        analysis, llm_response = self.analysis_pipeline.run_with_llm_response(dataset)
        analysis_result = analysis.model_dump(mode="json")
        analysis_result.update(frontend_llm_summary_fields(llm_response))
        links = self._note_open_links.get(job_id, {})
        self._attach_note_open_urls(analysis_result, job_id, {key: value[0] for key, value in links.items()}, datetime.now(timezone.utc))
        result = {**analysis_result, "job_id": job_id}
        result_storage_path = self.result_persistence.save(
            job_id,
            {"job_id": job_id, "llm_response": llm_response, "analysis": result},
        )
        result["storage"] = {"result_path": result_storage_path}
        if job is not None:
            self.jobs.update(job_id, analysis_result=result)
        return result

    @staticmethod
    def _extract_note_open_links(dataset: dict[str, Any]) -> dict[str, str]:
        links: dict[str, str] = {}
        for note in dataset.get("notes", []):
            if not isinstance(note, dict):
                continue
            note_id = clean_text(note.get("note_id"))
            target = clean_text(note.get(PRIVATE_NOTE_OPEN_URL_FIELD))
            parsed = urlsplit(target)
            query_names = {normalized_field_name(key) for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
            path_note_id = clean_text(parsed.path.rstrip("/").rsplit("/", 1)[-1])
            if (
                note_id
                and parsed.scheme == "https"
                and (parsed.hostname or "").lower() in XHS_OPEN_HOSTS
                and parsed.path.startswith("/explore/")
                and path_note_id == note_id
                and "xsectoken" in query_names
            ):
                links[note_id] = target
        return links

    def _store_note_open_links(self, job_id: str, links: dict[str, str]) -> datetime:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=NOTE_OPEN_LINK_TTL_SECONDS)
        with self._note_open_links_lock:
            self._prune_note_open_links_locked()
            self._note_open_links[job_id] = {
                note_id: (target, expires_at)
                for note_id, target in links.items()
            }
        return expires_at

    def _prune_note_open_links_locked(self) -> None:
        now = datetime.now(timezone.utc)
        for job_id, links in list(self._note_open_links.items()):
            valid_links = {
                note_id: item
                for note_id, item in links.items()
                if item[1] > now
            }
            if valid_links:
                self._note_open_links[job_id] = valid_links
            else:
                self._note_open_links.pop(job_id, None)

    def _discard_note_open_links(self, job_id: str) -> None:
        with self._note_open_links_lock:
            self._note_open_links.pop(job_id, None)

    @staticmethod
    def _note_open_url(job_id: str, note_id: str) -> str:
        return f"{LOCAL_API_BASE_URL}/xhs/collections/{job_id}/notes/{note_id}/open"

    def _attach_note_open_urls(
        self,
        analysis: dict[str, Any],
        job_id: str,
        links: dict[str, str],
        expires_at: datetime,
    ) -> None:
        expires_at_value = expires_at.isoformat(timespec="seconds")
        for note in analysis.get("representative_notes", []):
            if not isinstance(note, dict):
                continue
            note_id = clean_text(note.get("note_id"))
            if not note_id:
                continue
            note["source_url"] = self._note_open_url(job_id, note_id)
            note["link_expires_at"] = expires_at_value if note_id in links else None

    def note_open_url(self, job_id: str, note_id: str) -> str | None:
        with self._note_open_links_lock:
            self._prune_note_open_links_locked()
            item = self._note_open_links.get(job_id, {}).get(note_id)
            return item[0] if item else None

    def auth_status(self, *, refresh: bool = False, require_authenticated: bool = False) -> dict[str, Any]:
        with self._auth_lock:
            if not refresh and self._auth_cache is not None and time.monotonic() - self._auth_cache_at < 60:
                cached = {**self._auth_cache, "verification": "cached"}
                if require_authenticated and not cached["authenticated"]:
                    raise AuthRequiredError((cached.get("error") or {}).get("message", "小红书登录状态不存在或已过期，请重新登录"))
                return cached

        try:
            self._build_scraper().validate_saved_login()
            result = {
                "authenticated": True,
                "status": "authenticated",
                "checked_at": utc_now(),
                "verification": "live",
            }
        except AuthRequiredError as exc:
            result = {
                "authenticated": False,
                "status": "unauthenticated",
                "checked_at": utc_now(),
                "verification": "missing_cookie" if "没有找到" in str(exc) else "live",
                "error": {"code": exc.code, "message": clean_text(exc)[:500]},
            }
        except Exception as exc:
            error = translate_client_exception(exc)
            result = {
                "authenticated": False,
                "status": "unavailable",
                "checked_at": utc_now(),
                "verification": "unavailable",
                "error": {"code": error.code, "message": clean_text(error)[:500]},
            }
        if result["status"] != "unavailable":
            with self._auth_lock:
                self._auth_cache = result
                self._auth_cache_at = time.monotonic()
        if require_authenticated and not result["authenticated"]:
            raise AuthRequiredError((result.get("error") or {}).get("message", "小红书登录状态不存在或已过期，请重新登录"))
        return result


service = XhsConnectorService()


def get_job_or_404(job_id: str, expected_kind: JobKind) -> dict[str, Any]:
    job = service.jobs.get(job_id)
    if job is None or job["kind"] != expected_kind:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return job


@router.post("/auth/login", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_login(request: LoginRequest) -> dict[str, Any]:
    try:
        return JobStore.public(service.start_login(request.browser, force=request.force))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "已有登录任务正在运行", "job_id": str(exc)},
        ) from exc


@router.get("/auth/login/{job_id}", response_model=JobResponse)
def get_login_job(job_id: str) -> dict[str, Any]:
    return JobStore.public(get_job_or_404(job_id, "login"))


@router.get("/auth/status", response_model=AuthStatusResponse)
def get_auth_status(refresh: bool = False) -> dict[str, Any]:
    return service.auth_status(refresh=refresh)


@router.post("/collections", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_collection(request: CollectionRequest) -> dict[str, Any]:
    try:
        return JobStore.public(service.start_collection(request))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "已有采集任务正在运行", "job_id": str(exc)},
        ) from exc


@router.get("/collections/{job_id}", response_model=JobResponse)
def get_collection_job(job_id: str) -> dict[str, Any]:
    return JobStore.public(get_job_or_404(job_id, "collection"))


@router.get("/collections/{job_id}/result")
def get_collection_result(job_id: str) -> dict[str, Any]:
    job = get_job_or_404(job_id, "collection")
    if job["status"] == "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=job["error"])
    if job["status"] != "succeeded":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="采集任务尚未完成")
    return job["result"]


@router.post("/collections/{job_id}/analysis")
def analyze_collection(job_id: str) -> dict[str, Any]:
    try:
        return service.analyze_collection(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/collections/{job_id}/notes/{note_id}/open", include_in_schema=False)
def open_collection_note(job_id: str, note_id: str) -> RedirectResponse:
    target = service.note_open_url(job_id, note_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="原文链接已过期，请重新采集")
    return RedirectResponse(target, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
