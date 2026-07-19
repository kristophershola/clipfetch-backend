from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from yt_dlp import YoutubeDL

from app.core.task import FormatInfo, ViewState

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

COOKIES_FILE = os.environ.get("COOKIES_FILE", "") or os.path.join(DATA_DIR, "cookies.txt")
FFMPEG_LOCATION = os.environ.get("FFMPEG_LOCATION", "")


def init_cookies():
    content = os.environ.get("COOKIES_CONTENT", "")
    if content:
        clean = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                clean.append(line)
            elif "\t" in line and len(line.split("\t")) >= 6:
                clean.append(line)
        with open(COOKIES_FILE, "w") as f:
            f.write("\n".join(clean))
        written = "\n".join(clean)
        logger.info("Injected cookies from COOKIES_CONTENT (%d raw -> %d clean bytes)", len(content), len(written))
    elif os.path.exists(COOKIES_FILE):
        logger.info("Cookies file already exists at %s", COOKIES_FILE)


def _apply_cookies(opts: dict) -> dict:
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


def save_cookies(content: str) -> str:
    with open(COOKIES_FILE, "w") as f:
        f.write(content)
    return COOKIES_FILE


def read_cookies() -> str:
    if os.path.exists(COOKIES_FILE):
        with open(COOKIES_FILE) as f:
            return f.read()
    return ""


def _build_info_opts() -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "no_playlist": True,
        "socket_timeout": 30,
    }
    _apply_cookies(opts)
    return opts


def fetch_video_info(url: str) -> dict:
    """Mirrors DownloadUtil.fetchVideoInfoFromUrl"""
    opts = _build_info_opts()
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise ValueError(f"Could not extract info for {url}")
        if info.get("_type") == "playlist":
            entries = info.get("entries", [])
            if entries:
                return entries[0]
        return info


def fetch_playlist_info(url: str) -> dict:
    """Mirrors DownloadUtil.getPlaylistOrVideoInfo"""
    opts = _build_info_opts()
    opts["extract_flat"] = True
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise ValueError(f"Could not extract playlist info for {url}")
        return info


def info_to_view_state(info: dict) -> ViewState:
    formats = info.get("requested_formats") or info.get("formats") or []
    video_formats = []
    audio_only_formats = []
    for f in formats:
        fmt = FormatInfo(
            format_id=str(f.get("format_id", "")),
            ext=f.get("ext", ""),
            resolution=f.get("resolution", "") or (f.get("width") and f"{f['width']}x{f['height']}") or "",
            file_size=f.get("filesize") or f.get("filesize_approx"),
            vcodec=f.get("vcodec", ""),
            acodec=f.get("acodec", ""),
            tbr=f.get("tbr"),
        )
        if fmt.contains_video():
            video_formats.append(fmt)
        elif fmt.is_audio_only():
            audio_only_formats.append(fmt)
    if not video_formats and not audio_only_formats:
        for f in formats:
            video_formats.append(FormatInfo(
                format_id=str(f.get("format_id", "")),
                ext=f.get("ext", ""),
                resolution=f.get("resolution", "") or "",
                file_size=f.get("filesize") or f.get("filesize_approx"),
                vcodec=f.get("vcodec", ""),
                acodec=f.get("acodec", ""),
                tbr=f.get("tbr"),
            ))

    return ViewState(
        url=info.get("original_url") or info.get("webpage_url") or "",
        title=info.get("title", ""),
        uploader=info.get("uploader") or info.get("channel") or info.get("uploader_id", ""),
        extractor_key=info.get("extractor_key", ""),
        duration=info.get("duration") and int(info.get("duration", 0)) or 0,
        thumbnail_url=info.get("thumbnail"),
        file_size_approx=info.get("filesize") or info.get("filesize_approx") or 0.0,
        video_formats=video_formats or None,
        audio_only_formats=audio_only_formats or None,
    )


def download_video(
    url: str,
    task_id: str,
    preferences: dict | None = None,
    progress_callback: Callable | None = None,
) -> list[str]:
    prefs = preferences or {}

    def progress_hook(d: dict):
        status = d.get("status", "")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total > 0 else 0
            text = d.get("_percent_str", "").strip() or f"{pct:.1f}%"
            if progress_callback:
                progress_callback(pct, downloaded, text)
        elif status == "finished":
            if progress_callback:
                progress_callback(100.0, 0, "Processing...")

    outtmpl = prefs.get("output_template") or "%(title).200S.%(ext)s"

    opts: dict = {
        "outtmpl": os.path.join(DOWNLOAD_DIR, outtmpl),
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "restrictfilenames": prefs.get("restrict_filenames", False),
        "socket_timeout": 15,
        "retries": 3,
    }
    _apply_cookies(opts)

    if FFMPEG_LOCATION:
        opts["ffmpeg_location"] = FFMPEG_LOCATION

    format_id = prefs.get("format_id", "")
    extract_audio = prefs.get("extract_audio", False)

    if extract_audio:
        opts["extract_audio"] = True
        opts["audio_format"] = prefs.get("audio_format", "mp3")
        opts["audio_quality"] = prefs.get("audio_quality", 5)
    elif format_id:
        opts["format"] = format_id

    if prefs.get("proxy"):
        opts["proxy"] = prefs.get("proxy_url", "")

    if prefs.get("embed_thumbnail"):
        opts["embedthumbnail"] = True
        opts["writethumbnail"] = True

    if prefs.get("embed_metadata"):
        opts["embedmetadata"] = True

    if prefs.get("subtitles"):
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = [prefs.get("subtitle_language", "en")]

    if prefs.get("sponsorblock"):
        opts["sponsorblock_remove"] = prefs.get("sponsorblock_categories", "all")

    if prefs.get("download_archive"):
        opts["download_archive"] = os.path.join(DOWNLOAD_DIR, "archive.txt")

    if prefs.get("rate_limit"):
        opts["ratelimit"] = f"{prefs.get('max_download_rate', '5000')}K"

    if prefs.get("concurrent_fragments", 0) > 1:
        opts["concurrent_fragments"] = prefs["concurrent_fragments"]

    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return []
            entries = info.get("entries", [info])
            paths = []
            for entry in entries:
                if entry and entry.get("requested_downloads"):
                    for dl in entry["requested_downloads"]:
                        fp = dl.get("filepath")
                        if fp and os.path.exists(fp):
                            paths.append(fp)
                elif entry:
                    fp = ydl.prepare_filename(entry)
                    if fp and os.path.exists(fp):
                        paths.append(fp)
            return paths
        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            raise


def get_available_formats(url: str) -> list[dict]:
    info = fetch_video_info(url)
    formats = info.get("formats", [])
    result = []
    for f in formats:
        result.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution") or (f"{f.get('width', '')}x{f.get('height', '')}" if f.get('width') else ""),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "vcodec": f.get("vcodec", ""),
            "acodec": f.get("acodec", ""),
            "tbr": f.get("tbr"),
            "fps": f.get("fps"),
        })
    return result
