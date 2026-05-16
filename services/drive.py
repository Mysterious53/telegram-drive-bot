from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import secrets
import shutil
import socket
import string as _string
import tempfile
import logging
from pathlib import Path
from typing import Callable, Awaitable, Optional
from urllib.parse import urlparse, urljoin

import aiohttp
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from services.auth import get_credentials, creds_to_dict
from config import MAX_FILE_SIZE_MB

logger = logging.getLogger(__name__)

_MAX_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
_CHUNK = 512 * 1024
_DRIVE_CHUNK = 5 * 1024 * 1024

_YT_RE = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?v=|shorts/|embed/|live/)|youtu\.be/)[\w\-]+"
)

# IP ranges that must never be fetched (SSRF protection)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),    # carrier-grade NAT
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _host_is_public(hostname: str) -> bool:
    """Resolve hostname and confirm every returned IP is non-private."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        if not infos:
            return False
        for (_, _, _, _, sockaddr) in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_loopback or ip.is_link_local or ip.is_private:
                return False
            for net in _BLOCKED_NETWORKS:
                try:
                    if ip in net:
                        return False
                except TypeError:
                    pass
        return True
    except Exception:
        return False


async def _validate_download_url(url: str):
    """Raise ValueError for non-HTTP or internal-IP URLs (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"طرح URL نامعتبر است: {parsed.scheme}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("هاست URL نامعتبر است.")
    loop = asyncio.get_running_loop()
    safe = await loop.run_in_executor(None, _host_is_public, hostname)
    if not safe:
        raise ValueError("لینک به آدرس شبکه داخلی اشاره دارد و مجاز نیست.")


class FileTooLargeError(Exception):
    pass


class UploadCancelled(Exception):
    pass


def is_youtube_url(url: str) -> bool:
    return bool(_YT_RE.search(url))


_MAX_REDIRECTS = 5


async def _resolve_redirects(url: str) -> str:
    """Follow redirects while validating each hop for SSRF. Returns final URL."""
    async with aiohttp.ClientSession() as session:
        current = url
        for _ in range(_MAX_REDIRECTS):
            async with session.get(current, allow_redirects=False) as resp:
                if resp.status not in (301, 302, 303, 307, 308):
                    return current
                location = resp.headers.get("Location", "").strip()
                if not location:
                    return current
                location = urljoin(current, location)
                await _validate_download_url(location)
                current = location
        return current


def _safe_filename(raw: str) -> str:
    """Sanitize a filename to prevent path traversal and invalid characters."""
    name = os.path.basename(raw.replace("\\", "/"))
    name = re.sub(r"[^\w\-. ]", "_", name).strip()[:200]
    return name or "downloaded_file"


async def download_url(
    url: str,
    progress_cb: Optional[Callable[[int, int], Awaitable[None]]] = None,
    cancelled_check: Optional[Callable[[], bool]] = None,
) -> tuple[Path, str, str, int]:
    await _validate_download_url(url)
    url = await _resolve_redirects(url)   # validate every redirect hop
    async with aiohttp.ClientSession() as session:
        async with session.get(url, allow_redirects=False) as resp:
            resp.raise_for_status()

            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > _MAX_BYTES:
                raise FileTooLargeError(f"حجم فایل بیشتر از {MAX_FILE_SIZE_MB} مگابایت است.")

            cd = resp.headers.get("Content-Disposition", "")
            filename = None
            if "filename=" in cd:
                filename = _safe_filename(cd.split("filename=")[-1].strip("\"' "))
            if not filename:
                raw = str(resp.url).split("?")[0].rstrip("/").split("/")[-1]
                filename = _safe_filename(raw) if raw else "downloaded_file"

            mime_type = resp.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
            total_size = int(cl) if cl else 0

            tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_drivebot")
            total = 0
            try:
                async for chunk in resp.content.iter_chunked(_CHUNK):
                    if cancelled_check and cancelled_check():
                        raise UploadCancelled()
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        raise FileTooLargeError(f"حجم فایل بیشتر از {MAX_FILE_SIZE_MB} مگابایت است.")
                    tmp.write(chunk)
                    if progress_cb and total_size > 0:
                        await progress_cb(total, total_size)
                tmp.flush()
            except Exception:
                tmp.close()
                os.unlink(tmp.name)
                raise
            finally:
                tmp.close()

            return Path(tmp.name), filename, mime_type, total


async def get_youtube_info(url: str) -> dict:
    """Fetch video metadata and available quality options without downloading."""
    try:
        import yt_dlp
    except ImportError:
        raise Exception("yt-dlp نصب نیست.")

    loop = asyncio.get_running_loop()
    _result: list[dict | None] = [None]
    _error: list[Exception | None] = [None]

    def _fetch():
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
                _result[0] = ydl.extract_info(url, download=False)
        except Exception as exc:
            _error[0] = exc

    await loop.run_in_executor(None, _fetch)

    if _error[0]:
        raise _error[0]

    info = _result[0] or {}
    formats = info.get("formats", [])

    # Collect unique heights that have a real video stream
    heights: set[int] = set()
    for f in formats:
        h = f.get("height")
        if h and f.get("vcodec") not in (None, "none"):
            heights.add(h)

    _label_map = {
        2160: "4K (2160p)", 1440: "2K (1440p)", 1080: "1080p HD",
        720: "720p HD", 480: "480p", 360: "360p", 240: "240p", 144: "144p",
    }

    qualities = []
    for h in sorted(heights, reverse=True)[:7]:          # max 7 video qualities
        label = _label_map.get(h, f"{h}p")
        fmt = (
            f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
            f"/bestvideo[height<={h}]+bestaudio"
            f"/best[height<={h}]"
        )
        qualities.append({"label": label, "format": fmt, "height": h})

    qualities.append({"label": "🎵 فقط صدا", "format": "bestaudio[ext=m4a]/bestaudio", "height": 0})

    dur = info.get("duration", 0) or 0
    return {
        "title": info.get("title", "ویدیوی ناشناس"),
        "duration": f"{dur // 60}:{dur % 60:02d}" if dur else "نامشخص",
        "qualities": qualities,
    }


async def download_youtube(
    url: str,
    format_str: str = "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
    progress_cb: Optional[Callable[[int, int], Awaitable[None]]] = None,
    cancelled_check: Optional[Callable[[], bool]] = None,
) -> tuple[Path, str, str, int]:
    try:
        import yt_dlp
    except ImportError:
        raise Exception("yt-dlp نصب نیست. دستور زیر را اجرا کنید:\npip install yt-dlp")

    tmp_dir = tempfile.mkdtemp(prefix="ytdl_")
    _prog = [0, 0]        # [downloaded_bytes, total_bytes]
    _done_event = asyncio.Event()
    _error: list[Exception | None] = [None]
    _info: list[dict | None] = [None]

    def _hook(d: dict):
        if d["status"] == "downloading":
            _prog[0] = d.get("downloaded_bytes", 0)
            _prog[1] = d.get("total_bytes") or d.get("total_bytes_estimate", 0)

    ydl_opts = {
        "format": format_str,
        "outtmpl": os.path.join(tmp_dir, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "progress_hooks": [_hook],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    loop = asyncio.get_running_loop()

    async def _monitor():
        while not _done_event.is_set():
            if progress_cb and _prog[1] > 0:
                await progress_cb(_prog[0], _prog[1])
            await asyncio.sleep(1.5)

    mon = asyncio.create_task(_monitor())

    def _dl():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                _info[0] = ydl.extract_info(url, download=True)
        except Exception as exc:
            _error[0] = exc

    await loop.run_in_executor(None, _dl)
    _done_event.set()
    mon.cancel()
    try:
        await mon
    except asyncio.CancelledError:
        pass

    if _error[0]:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise _error[0]

    if cancelled_check and cancelled_check():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise UploadCancelled()

    files = [f for f in Path(tmp_dir).iterdir() if f.is_file()]
    if not files:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise Exception("yt-dlp: فایلی دانلود نشد.")

    dl_file = sorted(files, key=lambda f: f.stat().st_size, reverse=True)[0]
    size = dl_file.stat().st_size

    if size > _MAX_BYTES:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise FileTooLargeError(f"حجم ویدیو بیشتر از {MAX_FILE_SIZE_MB // 1024} گیگابایت است.")

    filename = dl_file.name
    ext = dl_file.suffix.lstrip(".").lower()
    _mime_map = {
        "mp4": "video/mp4", "webm": "video/webm", "mkv": "video/x-matroska",
        "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg",
    }
    mime_type = _mime_map.get(ext, "video/mp4")

    # Move out of tmp_dir so we can clean it up
    out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_ytdl{dl_file.suffix}")
    out_tmp.close()
    shutil.move(str(dl_file), out_tmp.name)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return Path(out_tmp.name), filename, mime_type, size


async def download_telegram_file(
    file_path_url: str,
    filename: str,
    file_size: int,
    progress_cb: Optional[Callable[[int, int], Awaitable[None]]] = None,
    cancelled_check: Optional[Callable[[], bool]] = None,
) -> tuple[Path, str, int]:
    if file_size and file_size > _MAX_BYTES:
        raise FileTooLargeError(f"حجم فایل بیشتر از {MAX_FILE_SIZE_MB} مگابایت است.")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_drivebot")
    total = 0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_path_url) as resp:
                resp.raise_for_status()
                async for chunk in resp.content.iter_chunked(_CHUNK):
                    if cancelled_check and cancelled_check():
                        raise UploadCancelled()
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        raise FileTooLargeError(f"حجم فایل بیشتر از {MAX_FILE_SIZE_MB} مگابایت است.")
                    tmp.write(chunk)
                    if progress_cb and file_size > 0:
                        await progress_cb(total, file_size)
        tmp.flush()
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise
    finally:
        tmp.close()

    return Path(tmp.name), filename, total


def upload_file(
    tokens: dict,
    file_path: Path,
    filename: str,
    mime_type: str,
    sync_progress_cb: Optional[Callable[[int, int], None]] = None,
    cancelled_check: Optional[Callable[[], bool]] = None,
) -> tuple[dict, dict]:
    creds = get_credentials(tokens)
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    file_size = file_path.stat().st_size

    with open(file_path, "rb") as fh:
        media = MediaIoBaseUpload(fh, mimetype=mime_type, resumable=True, chunksize=_DRIVE_CHUNK)
        request = svc.files().create(
            body={"name": filename},
            media_body=media,
            fields="id,name,webViewLink,webContentLink,size",
        )

        response = None
        while response is None:
            if cancelled_check and cancelled_check():
                raise UploadCancelled()
            status, response = request.next_chunk()
            if status and sync_progress_cb and file_size > 0:
                sync_progress_cb(status.resumable_progress, file_size)

        file_meta = response

    svc.permissions().create(
        fileId=file_meta["id"],
        body={"role": "reader", "type": "anyone"},
    ).execute()

    return file_meta, creds_to_dict(creds)


def delete_file(tokens: dict, drive_file_id: str):
    creds = get_credentials(tokens)
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    svc.files().delete(fileId=drive_file_id).execute()


def get_drive_quota(tokens: dict) -> dict:
    """Returns storageQuota dict: limit, usage, usageInDrive (bytes as strings)."""
    creds = get_credentials(tokens)
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    result = svc.about().get(fields="storageQuota").execute()
    return result.get("storageQuota", {})


# ── Public drive helpers ──────────────────────────────────────

def generate_zip_password(length: int = 12) -> str:
    alphabet = _string.ascii_letters + _string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def zip_with_password(src_path: Path, dst_path: Path, password: str) -> None:
    """Create AES-256 encrypted ZIP using pyzipper."""
    import pyzipper
    with pyzipper.AESZipFile(
        dst_path, "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(password.encode())
        zf.write(src_path, src_path.name)