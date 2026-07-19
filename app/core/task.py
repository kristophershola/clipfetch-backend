from __future__ import annotations

import hashlib
import time
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


class RestartableAction(str, Enum):
    FETCH_INFO = "fetch_info"
    DOWNLOAD = "download"


class DownloadState:
    class Idle:
        action: RestartableAction | None = None

    class FetchingInfo:
        def __init__(self, task_id: str):
            self.task_id = task_id
            self.action = RestartableAction.FETCH_INFO

    class ReadyWithInfo:
        action: RestartableAction | None = None

    class Running:
        def __init__(self, task_id: str, progress: float = -1.0, progress_text: str = ""):
            self.task_id = task_id
            self.progress = progress
            self.progress_text = progress_text
            self.action = RestartableAction.DOWNLOAD

    class Canceled:
        def __init__(self, action: RestartableAction, progress: float | None = None):
            self.action = action
            self.progress = progress

    class Error:
        def __init__(self, message: str, action: RestartableAction):
            self.message = message
            self.action = action

    class Completed:
        def __init__(self, file_path: str | None = None):
            self.file_path = file_path
            self.action: RestartableAction | None = None


class TaskType:
    class URL:
        pass

    class Playlist:
        def __init__(self, index: int = 0):
            self.index = index

    class CustomCommand:
        def __init__(self, template: dict):
            self.template = template


class FormatInfo(BaseModel):
    format_id: str = ""
    ext: str = ""
    resolution: str = ""
    file_size: float | None = None
    vcodec: str = ""
    acodec: str = ""
    tbr: float | None = None

    def contains_video(self) -> bool:
        return bool(self.vcodec) and self.vcodec != "none"

    def is_audio_only(self) -> bool:
        return (not self.vcodec or self.vcodec == "none") and bool(self.acodec) and self.acodec != "none"


class ViewState(BaseModel):
    url: str = ""
    title: str = ""
    uploader: str = ""
    extractor_key: str = ""
    duration: int = 0
    file_size_approx: float = 0.0
    thumbnail_url: str | None = None
    video_formats: list[FormatInfo] | None = None
    audio_only_formats: list[FormatInfo] | None = None


class Task:
    def __init__(
        self,
        url: str,
        preferences: dict | None = None,
        task_type: Any | None = None,
    ):
        self.url = url
        self.preferences = preferences or {}
        self.type = task_type or TaskType.URL()
        type_id = ""
        if isinstance(self.type, TaskType.CustomCommand):
            t = self.type.template
            type_id = f"{t.get('id', '')}_{t.get('name', '')}"
        elif isinstance(self.type, TaskType.Playlist):
            type_id = str(self.type.index)
        raw = f"{url}_{type_id}_{hashlib.md5(str(preferences).encode()).hexdigest()}"
        self.id = hashlib.sha256(raw.encode()).hexdigest()[:16]
        self.time_created = time.time()

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, Task) and self.id == other.id


class TaskState(BaseModel):
    download_state: str = "idle"
    video_info: dict | None = None
    view_state: ViewState = ViewState()
    progress: float = 0.0
    progress_text: str = ""
    error_message: str = ""
    file_path: str | None = None


class TaskEntry(BaseModel):
    id: str
    url: str
    state: TaskState
    time_created: float
    preferences: dict = Field(default_factory=dict)
    type: str = "url"
