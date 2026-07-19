from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.core.task import (
    DownloadState,
    RestartableAction,
    Task,
    TaskEntry,
    TaskState,
    TaskType,
    ViewState,
)
from app.services.ytdlp_service import (
    download_video,
    fetch_video_info,
    info_to_view_state,
)

logger = logging.getLogger(__name__)

MAX_CONCURRENCY = 3

_progress_callbacks: dict[str, list[Callable]] = {}


def subscribe_progress(task_id: str, callback: Callable):
    if task_id not in _progress_callbacks:
        _progress_callbacks[task_id] = []
    _progress_callbacks[task_id].append(callback)


def unsubscribe_progress(task_id: str, callback: Callable):
    if task_id in _progress_callbacks:
        _progress_callbacks[task_id] = [c for c in _progress_callbacks[task_id] if c is not callback]
        if not _progress_callbacks[task_id]:
            del _progress_callbacks[task_id]


def _notify_progress(task_id: str, progress: float, text: str):
    if task_id in _progress_callbacks:
        for cb in _progress_callbacks[task_id]:
            try:
                cb(progress, text)
            except Exception:
                pass


_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY + 1)

_task_store: dict[str, TaskEntry] = {}
_task_lock = threading.Lock()
_semaphore = threading.Semaphore(MAX_CONCURRENCY)


def get_all_tasks() -> list[TaskEntry]:
    with _task_lock:
        return sorted(
            list(_task_store.values()),
            key=lambda t: t.time_created,
            reverse=True,
        )


def get_task(task_id: str) -> TaskEntry | None:
    with _task_lock:
        return _task_store.get(task_id)


def delete_task(task_id: str) -> bool:
    with _task_lock:
        if task_id in _task_store:
            del _task_store[task_id]
            return True
        return False


def create_task(url: str, preferences: dict | None = None) -> TaskEntry:
    task = Task(url=url, preferences=preferences)
    state = TaskState(download_state="idle", view_state=ViewState(url=url, title=url))
    entry = TaskEntry(
        id=task.id,
        url=task.url,
        state=state,
        time_created=task.time_created,
        preferences=preferences or {},
    )
    with _task_lock:
        _task_store[task.id] = entry
    return entry


def _update_state(task_id: str, **kwargs):
    with _task_lock:
        entry = _task_store.get(task_id)
        if entry:
            for k, v in kwargs.items():
                setattr(entry.state, k, v)


def enqueue_task(task_id: str):
    _executor.submit(_process_task, task_id)


def cancel_task(task_id: str) -> bool:
    with _task_lock:
        entry = _task_store.get(task_id)
        if not entry:
            return False
        ds = entry.state.download_state
        if ds in ("fetching_info", "running"):
            entry.state.download_state = "canceled"
            entry.state.progress_text = "Canceled"
            _notify_progress(task_id, 0.0, "Canceled")
            return True
        elif ds in ("idle", "ready_with_info"):
            entry.state.download_state = "canceled"
            return True
        return False


def restart_task(task_id: str) -> bool:
    with _task_lock:
        entry = _task_store.get(task_id)
        if not entry:
            return False
        ds = entry.state.download_state
        if ds in ("error", "canceled", "completed"):
            entry.state.download_state = "idle"
            entry.state.progress = 0.0
            entry.state.progress_text = ""
            entry.state.error_message = ""
            entry.state.file_path = None
            enqueue_task(task_id)
            return True
        return False


def _process_task(task_id: str):
    entry = get_task(task_id)
    if not entry:
        return

    _acquired = _semaphore.acquire(blocking=True)
    if not _acquired:
        return

    try:
        entry = get_task(task_id)
        if not entry or entry.state.download_state != "idle":
            return

        _update_state(task_id, download_state="fetching_info", progress_text="Fetching video info...")
        _notify_progress(task_id, 0.0, "Fetching video info...")

        try:
            info = fetch_video_info(entry.url)
            view_state = info_to_view_state(info)
            _update_state(
                task_id,
                download_state="ready_with_info",
                video_info=info,
                view_state=view_state,
                progress_text="Ready - starting download",
            )
        except Exception as e:
            logger.error(f"Failed to fetch info for {entry.url}: {e}")
            _update_state(
                task_id,
                download_state="error",
                error_message=str(e),
                progress_text=f"Error: {str(e)[:100]}",
            )
            _notify_progress(task_id, 0.0, f"Error: {str(e)[:100]}")
            return

        entry = get_task(task_id)
        if not entry or entry.state.download_state == "canceled":
            return

        _update_state(task_id, download_state="running")
        _notify_progress(task_id, 0.0, "Downloading...")

        def progress_cb(pct: float, _bytes: int, text: str):
            _update_state(task_id, progress=pct, progress_text=text)
            _notify_progress(task_id, pct, text)

        try:
            paths = download_video(
                url=entry.url,
                task_id=task_id,
                preferences=entry.preferences,
                progress_callback=progress_cb,
            )
            file_path = paths[0] if paths else None
            _update_state(
                task_id,
                download_state="completed",
                progress=100.0,
                progress_text="Completed",
                file_path=file_path,
            )
            _notify_progress(task_id, 100.0, "Completed")
        except Exception as e:
            logger.error(f"Download failed for {entry.url}: {e}")
            _update_state(
                task_id,
                download_state="error",
                error_message=str(e),
                progress_text=f"Error: {str(e)[:100]}",
            )
            _notify_progress(task_id, 0.0, f"Error: {str(e)[:100]}")
    finally:
        _semaphore.release()
