"""Validated contract for cleaned Xiaohongshu datasets.

Pre-processing pipeline must output this schema (.json or .jsonl) after:
1. De-duplicating notes & filtering low-quality noise/spam.
2. Truncating comments to Top-K (sorted by likes/relevance).
3. Truncating & filtering images to Top-K (removing avatars, ads, low-res).
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CleanedImage(BaseModel):
    """Cleaned and validated image optimized for Multimodal LLM processing."""

    model_config = ConfigDict(extra="ignore")

    position: int = Field(ge=0, description="Original position index in note")
    url: str = Field(min_length=1, description="Accessible or stored CDN image URL")


class CleanedComment(BaseModel):
    """Cleaned comment filtered from spam/noise, used in Map-stage processing."""

    model_config = ConfigDict(extra="ignore")

    comment_id: str = Field(min_length=1)
    text: str = Field(min_length=1, description="Purified comment text with clean semantics")
    likes: int = Field(default=0, ge=0)
    is_author: bool = Field(default=False, description="Whether the comment is posted by the note author")


class CleanedNote(BaseModel):
    """Single note object passed into the Map stage (LLM inference)."""

    model_config = ConfigDict(extra="ignore")

    note_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    title: str = Field(default="")
    text: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    publish_time: str | None = None

    # Key Engagement Summary (Flattens complexity for direct LLM context weighting)
    likes: int = Field(default=0, ge=0)
    comments_count: int = Field(default=0, ge=0)

    # Top-K truncated lists
    images: list[CleanedImage] = Field(default_factory=list, description="Top-K filtered images")
    comments: list[CleanedComment] = Field(default_factory=list, description="Top-K filtered comments")

    @model_validator(mode="after")
    def validate_content_and_uniqueness(self) -> "CleanedNote":
        if not self.title.strip() and not self.text.strip():
            raise ValueError("a cleaned note must include at least title or text content")
        if len({comment.comment_id for comment in self.comments}) != len(self.comments):
            raise ValueError("comment_id values must be unique within a note")
        return self


class CleanedDataset(BaseModel):
    """Top-level schema for cleaned datasets exported to .json or .jsonl lines."""

    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["1.1_cleaned"] = "1.1_cleaned"
    query_context: str | None = Field(default=None, description="Original query or target topic")
    cleaned_at: str | None = Field(default=None, description="ISO timestamp of preprocessing execution")
    notes: list[CleanedNote] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_global_uniqueness(self) -> "CleanedDataset":
        if len({note.note_id for note in self.notes}) != len(self.notes):
            raise ValueError("note_id values must be unique across the cleaned dataset")
        return self