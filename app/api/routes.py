from __future__ import annotations

import asyncio
import logging

import os

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.models.database import (
    DownloadedVideoInfo,
    SessionLocal,
)
from app.services.downloader import (
    cancel_task,
    create_task,
    delete_task,
    enqueue_task,
    get_all_tasks,
    get_task,
    restart_task,
    subscribe_progress,
    unsubscribe_progress,
)
from app.services.ytdlp_service import (
    fetch_playlist_info,
    get_available_formats,
    info_to_view_state,
    read_cookies,
    save_cookies,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SubmitURLRequest(BaseModel):
    url: str
    preferences: dict | None = None


class FormatQuery(BaseModel):
    url: str


class PlaylistQuery(BaseModel):
    url: str


@router.post("/api/submit")
def submit_url(req: SubmitURLRequest):
    task = create_task(url=req.url, preferences=req.preferences)
    enqueue_task(task.id)
    return {"task_id": task.id, "url": task.url, "status": "queued"}


@router.get("/api/tasks")
def list_tasks():
    tasks = get_all_tasks()
    return {
        "tasks": [
            {
                "id": t.id,
                "url": t.url,
                "state": t.state.download_state,
                "progress": t.state.progress,
                "progress_text": t.state.progress_text,
                "title": t.state.view_state.title or t.url,
                "thumbnail": t.state.view_state.thumbnail_url,
                "uploader": t.state.view_state.uploader,
                "duration": t.state.view_state.duration,
                "file_path": t.state.file_path,
                "error_message": t.state.error_message,
            }
            for t in tasks
        ]
    }


@router.get("/api/tasks/{task_id}")
def get_task_info(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "id": task.id,
        "url": task.url,
        "state": task.state.download_state,
        "progress": task.state.progress,
        "progress_text": task.state.progress_text,
        "title": task.state.view_state.title or task.url,
        "thumbnail": task.state.view_state.thumbnail_url,
        "uploader": task.state.view_state.uploader,
        "duration": task.state.view_state.duration,
        "video_formats": (
            [f.model_dump() for f in (task.state.view_state.video_formats or [])]
        ),
        "audio_only_formats": (
            [f.model_dump() for f in (task.state.view_state.audio_only_formats or [])]
        ),
        "file_path": task.state.file_path,
        "error_message": task.state.error_message,
        "time_created": task.time_created,
    }


@router.post("/api/tasks/{task_id}/cancel")
def cancel_task_endpoint(task_id: str):
    if cancel_task(task_id):
        return {"status": "canceled"}
    raise HTTPException(status_code=404, detail="Task not found or cannot be canceled")


@router.post("/api/tasks/{task_id}/restart")
def restart_task_endpoint(task_id: str):
    if restart_task(task_id):
        return {"status": "restarted"}
    raise HTTPException(status_code=404, detail="Task not found or cannot be restarted")


@router.get("/api/tasks/{task_id}/file")
def download_task_file(task_id: str):
    task = get_task(task_id)
    if not task or not task.state.file_path:
        raise HTTPException(status_code=404, detail="File not found")
    fp = task.state.file_path
    if not os.path.exists(fp):
        raise HTTPException(status_code=404, detail="File no longer exists on server")
    filename = os.path.basename(fp)
    return FileResponse(fp, media_type="application/octet-stream", filename=filename)


@router.delete("/api/tasks/{task_id}")
def delete_task_endpoint(task_id: str):
    if delete_task(task_id):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Task not found")


@router.post("/api/formats")
def get_formats(req: FormatQuery):
    try:
        formats = get_available_formats(req.url)
        return {"formats": formats}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/playlist")
def get_playlist(req: PlaylistQuery):
    try:
        info = fetch_playlist_info(req.url)
        if info.get("_type") == "playlist":
            entries = info.get("entries", [])
            return {
                "type": "playlist",
                "title": info.get("title", ""),
                "channel": info.get("channel", ""),
                "entries": [
                    {
                        "url": e.get("url") or e.get("webpage_url", ""),
                        "title": e.get("title", ""),
                        "duration": e.get("duration"),
                        "uploader": e.get("uploader") or e.get("channel", ""),
                    }
                    for e in (entries or [])
                    if e
                ],
            }
        view = info_to_view_state(info)
        return {
            "type": "video",
            "title": view.title,
            "uploader": view.uploader,
            "duration": view.duration,
            "thumbnail": view.thumbnail_url,
            "formats": [f.model_dump() for f in (view.video_formats or [])],
            "audio_formats": [f.model_dump() for f in (view.audio_only_formats or [])],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/history")
def get_history(limit: int = 50):
    db = SessionLocal()
    try:
        items = (
            db.query(DownloadedVideoInfo)
            .order_by(DownloadedVideoInfo.created_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "history": [
                {
                    "id": item.id,
                    "title": item.video_title,
                    "author": item.video_author,
                    "url": item.video_url,
                    "path": item.video_path,
                    "extractor": item.extractor,
                    "file_size": item.file_size,
                    "duration": item.duration,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in items
            ]
        }
    finally:
        db.close()


@router.get("/api/cookies")
def get_cookies():
    return {"cookies": read_cookies()}


@router.put("/api/cookies")
def update_cookies(body: dict):
    content = body.get("cookies", "")
    path = save_cookies(content)
    return {"status": "saved", "path": path, "size": len(content)}


@router.websocket("/ws/progress/{task_id}")
async def ws_progress(websocket: WebSocket, task_id: str):
    await websocket.accept()

    async def send_progress(progress: float, text: str):
        try:
            await websocket.send_json({"progress": progress, "text": text})
        except Exception:
            pass

    loop = asyncio.get_event_loop()

    def callback(pct: float, txt: str):
        asyncio.run_coroutine_threadsafe(send_progress(pct, txt), loop)

    subscribe_progress(task_id, callback)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe_progress(task_id, callback)
