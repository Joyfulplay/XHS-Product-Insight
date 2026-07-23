"""Validated contract for raw Xiaohongshu crawler datasets.

The crawler writes this shape to disk.  Downstream services must validate it
before turning any collected content into LLM input.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CrawlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "keyword",
        "product_url",
        "xiaohongshu_url",
        "xiaohongshu_note",
        "xiaohongshu_search",
    ] | None = None
    value: str = Field(min_length=1)
    resolved_query: str | None = None


class CollectionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_limit: int = Field(ge=1)
    note_limit: int = Field(ge=1)
    comments_per_note_limit: int = Field(ge=0)
    min_note_likes: int = Field(ge=0)
    min_comment_likes: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    note_count: int = Field(ge=0)
    comment_count: int = Field(ge=0)


class Engagement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likes: int | None = Field(default=None, ge=0)
    favorites: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)


class CrawlImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=0)
    url: str = Field(min_length=1)


class CrawlComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    author_id_hash: str | None = None
    likes: int | None = Field(default=None, ge=0)
    publish_time: str | None = None


class CrawlNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    search_query: str | None = None
    search_rank: int | None = Field(default=None, ge=0)
    title: str = ""
    text: str = ""
    tags: list[str] = Field(default_factory=list)
    publish_time: str | None = None
    author_id_hash: str | None = None
    engagement: Engagement
    images: list[CrawlImage] = Field(default_factory=list)
    comments: list[CrawlComment] = Field(default_factory=list)

    @model_validator(mode="after")
    def must_include_content(self) -> "CrawlNote":
        if not self.title.strip() and not self.text.strip():
            raise ValueError("a crawled note must include a title or body text")
        if len({comment.comment_id for comment in self.comments}) != len(self.comments):
            raise ValueError("comment_id values must be unique within a note")
        return self


class CrawlError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1)
    code: str = Field(min_length=1)
    url: str | None = None
    message: str = Field(min_length=1)


class CrawlDataset(BaseModel):
    """Raw crawler output accepted by the backend analysis pipeline."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"]
    input: CrawlInput
    collected_at: str | None = None
    collection: CollectionSummary
    notes: list[CrawlNote] = Field(default_factory=list)
    errors: list[CrawlError] = Field(default_factory=list)

    @model_validator(mode="after")
    def counts_must_match_payload(self) -> "CrawlDataset":
        if len({note.note_id for note in self.notes}) != len(self.notes):
            raise ValueError("note_id values must be unique")
        if self.collection.note_count != len(self.notes):
            raise ValueError("collection.note_count must equal the number of notes")
        comment_count = sum(len(note.comments) for note in self.notes)
        if self.collection.comment_count != comment_count:
            raise ValueError("collection.comment_count must equal the collected comments")
        if self.collection.candidate_count > self.collection.candidate_limit:
            raise ValueError("collection.candidate_count cannot exceed candidate_limit")
        if self.collection.note_count > self.collection.note_limit:
            raise ValueError("collection.note_count cannot exceed note_limit")
        return self
