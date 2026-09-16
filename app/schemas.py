from typing import Literal

from pydantic import BaseModel, Field

TaskStatus = Literal["pending", "transcribing", "summarizing", "done", "failed"]


class SummaryResult(BaseModel):
    summary: str
    key_points: list[str] = Field(default_factory=list)
    todos: list[str] = Field(default_factory=list)


class TaskOut(BaseModel):
    task_id: str
    recording_id: str
    status: TaskStatus
    attempt_count: int
    max_attempts: int
    error: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class RecordingListItem(BaseModel):
    recording_id: str
    filename: str
    size_bytes: int
    created_at: str
    latest_task: TaskOut | None = None


class RecordingDetail(RecordingListItem):
    transcript: str | None = None
    summary: SummaryResult | None = None


class RecordingListOut(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[RecordingListItem]


class UploadOut(BaseModel):
    recording_id: str
    task_id: str
    status: TaskStatus
