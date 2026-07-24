"""Local asynchronous connector for the Xiaohongshu crawler.

The browser extension only receives task state and desensitized collection
data.  Authentication cookies and browser profiles remain local to the
connector process and are never included in an API response.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.data.crawlers.xhs_client import (
    XiaohongshuScraper,
    classify_input,
    clean_text,
    translate_client_exception,
)
from app.services.analysis_pipeline import AnalysisPipelineService
from app.services.persistence_service import PersistenceService


router = APIRouter(prefix="/api/v1/xhs", tags=["xhs-connector"])

BrowserName = Literal["auto", "edge", "chrome"]
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

    if key is not None and is_sensitive_field(key):
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


class LoginRequest(BaseModel):
    browser: BrowserName = "auto"


class CollectionRequest(BaseModel):
    source: str = Field(min_length=1, max_length=2_000)
    query_override: str | None = Field(default=None, max_length=300)

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
    verification: Literal["local_cookie_presence"]
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
        self.persistence = PersistenceService(PROJECT_ROOT / "data/processed/collection_results")
        self._futures: dict[str, Future[Any]] = {}

    def _build_scraper(self, browser: BrowserName = "auto") -> XiaohongshuScraper:
        return XiaohongshuScraper(
            profile_dir=self.settings.profile_dir,
            max_candidates=self.settings.max_candidates,
            max_notes=self.settings.max_notes,
            max_comments=self.settings.max_comments,
            min_note_likes=self.settings.min_note_likes,
            min_comment_likes=self.settings.min_comment_likes,
            delay=self.settings.delay,
            headless=False,
            browser=browser,
        )

    def start_login(self, browser: BrowserName) -> dict[str, Any]:
        existing = self.jobs.active_job("login")
        if existing:
            raise ValueError(existing["job_id"])
        job = self.jobs.create("login")
        self._futures[job["job_id"]] = self.executor.submit(self._run_login, job["job_id"], browser)
        return job

    def _run_login(self, job_id: str, browser: BrowserName) -> None:
        self.jobs.update(job_id, status="running", stage="waiting_for_login", progress=0.1)
        try:
            self._build_scraper(browser).login()
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
            self._run_collection, job["job_id"], request.source, request.query_override
        )
        return job

    def _run_collection(self, job_id: str, source: str, query_override: str | None) -> None:
        self.jobs.update(job_id, status="running", stage="collecting", progress=0.1)
        try:
            dataset = self._build_scraper().collect(source, query_override=query_override)
            result = normalize_collection_dataset(dataset)
            self.jobs.update(job_id, stage="cleaning", progress=0.55)
            analysis_result = self.analysis_pipeline.run(result).model_dump(mode="json")
            self.jobs.update(job_id, stage="statistical_analysis", progress=0.85)
            result = {**result, **analysis_result}
            self.jobs.update(job_id, stage="persisting", progress=0.95)
            storage_path = self.persistence.save(job_id, result)
            result = {**result, "storage": {"path": storage_path}}
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
        self.jobs.update(
            job_id,
            status="succeeded",
            stage="completed",
            progress=1.0,
            result=result,
        )

    def auth_status(self) -> dict[str, Any]:
        try:
            _, load_saved_cookies, _ = XiaohongshuScraper._import_client_components()
            cookies = load_saved_cookies()
            valid = XiaohongshuScraper._has_required_login_cookies(cookies)
        except Exception as exc:
            error = translate_client_exception(exc)
            return {
                "authenticated": False,
                "status": "unavailable",
                "checked_at": utc_now(),
                "verification": "local_cookie_presence",
                "error": {"code": error.code, "message": clean_text(error)[:500]},
            }
        return {
            "authenticated": valid,
            "status": "authenticated" if valid else "unauthenticated",
            "checked_at": utc_now(),
            "verification": "local_cookie_presence",
        }


service = XhsConnectorService()


def get_job_or_404(job_id: str, expected_kind: JobKind) -> dict[str, Any]:
    job = service.jobs.get(job_id)
    if job is None or job["kind"] != expected_kind:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return job


@router.post("/auth/login", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_login(request: LoginRequest) -> dict[str, Any]:
    try:
        return JobStore.public(service.start_login(request.browser))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "已有登录任务正在运行", "job_id": str(exc)},
        ) from exc


@router.get("/auth/login/{job_id}", response_model=JobResponse)
def get_login_job(job_id: str) -> dict[str, Any]:
    return JobStore.public(get_job_or_404(job_id, "login"))


@router.get("/auth/status", response_model=AuthStatusResponse)
def get_auth_status() -> dict[str, Any]:
    return service.auth_status()


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
