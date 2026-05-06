from __future__ import annotations

import asyncio
import html as _html
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

import database.db as db
from services.drive import (
    download_url, download_telegram_file, download_youtube, upload_file,
    is_youtube_url, FileTooLargeError, UploadCancelled,
)

_DEFAULT_YT_FORMAT = "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
from config import MAX_CONCURRENT_UPLOADS, MAX_QUEUE_SIZE, DAILY_UPLOAD_LIMIT

logger = logging.getLogger(__name__)

_CANCEL_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ لغو آپلود", callback_data="cancel_upload")]]
)


@dataclass
class UploadTask:
    user_id: int
    chat_id: int
    status_msg_id: int
    upload_type: str          # "link" | "file"
    source: str
    filename: str = ""
    mime_type: str = "application/octet-stream"
    file_size: int = 0
    tokens: dict = field(default_factory=dict)
    cancelled: bool = False
    yt_format: str = ""          # yt-dlp format selector (empty = default)


class QueueFullError(Exception):
    pass


class UploadQueue:
    def __init__(self):
        self._q: asyncio.Queue[UploadTask] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._workers: list[asyncio.Task] = []
        self._uploading: dict[int, UploadTask] = {}

    @property
    def pending(self) -> int:
        return self._q.qsize()

    def is_uploading(self, user_id: int) -> bool:
        return user_id in self._uploading

    def cancel_upload(self, user_id: int) -> bool:
        task = self._uploading.get(user_id)
        if task:
            task.cancelled = True
            return True
        return False

    async def start(self, bot: Bot):
        for _ in range(MAX_CONCURRENT_UPLOADS):
            t = asyncio.create_task(self._worker(bot))
            self._workers.append(t)
        logger.info("Upload queue started (%d workers)", MAX_CONCURRENT_UPLOADS)

    async def enqueue(self, task: UploadTask) -> int:
        if self._q.full():
            raise QueueFullError()
        await self._q.put(task)
        return self._q.qsize()

    async def _worker(self, bot: Bot):
        while True:
            task = await self._q.get()
            self._uploading[task.user_id] = task
            try:
                await self._process(task, bot)
            except Exception as exc:
                logger.exception("Worker uncaught error for user %s", task.user_id)
                try:
                    await bot.edit_message_text(
                        f"❌ خطای غیرمنتظره:\n{_html.escape(str(exc))}",
                        chat_id=task.chat_id,
                        message_id=task.status_msg_id,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            finally:
                self._uploading.pop(task.user_id, None)
                self._q.task_done()

    async def _process(self, task: UploadTask, bot: Bot):
        loop = asyncio.get_running_loop()

        _last_edit = [0.0]
        _last_pct = [-1]

        async def status(text: str, markup=None, parse_mode: str | None = None):
            try:
                await bot.edit_message_text(
                    text,
                    chat_id=task.chat_id,
                    message_id=task.status_msg_id,
                    reply_markup=markup,
                    parse_mode=parse_mode,
                )
            except Exception:
                pass

        async def progress(downloaded: int, total: int, stage: str):
            if total <= 0:
                return
            pct = min(99, int(downloaded / total * 100))
            now = time.monotonic()
            if pct - _last_pct[0] < 4 and now - _last_edit[0] < 2.5:
                return
            _last_pct[0] = pct
            _last_edit[0] = now
            filled = pct // 5
            bar = "▓" * filled + "░" * (20 - filled)
            await status(f"{stage}\n[{bar}] {pct}%", markup=_CANCEL_KB)

        # Re-check daily limit
        can, used = await db.check_daily_limit(task.user_id, DAILY_UPLOAD_LIMIT)
        if not can:
            await status(f"❌ محدودیت روزانه ({DAILY_UPLOAD_LIMIT} فایل) پر شده است.\nفردا دوباره امتحان کنید.")
            return

        tokens = await db.get_tokens(task.user_id)
        if not tokens:
            await status("❌ اتصال به گوگل درایو قطع شده. لطفاً /start بزنید و دوباره وصل شوید.")
            return

        tmp_path: Path | None = None
        try:
            # ── Download ──────────────────────────────────────
            if task.upload_type == "link":
                if is_youtube_url(task.source):
                    await status("⏬ در حال دانلود ویدیو از یوتیوب...", markup=_CANCEL_KB)
                    fmt = task.yt_format or _DEFAULT_YT_FORMAT
                    tmp_path, filename, mime_type, size = await download_youtube(
                        task.source,
                        format_str=fmt,
                        progress_cb=lambda d, t: progress(d, t, "⏬ در حال دانلود از یوتیوب..."),
                        cancelled_check=lambda: task.cancelled,
                    )
                else:
                    await status("⏬ در حال دانلود از لینک...", markup=_CANCEL_KB)
                    tmp_path, filename, mime_type, size = await download_url(
                        task.source,
                        progress_cb=lambda d, t: progress(d, t, "⏬ در حال دانلود از لینک..."),
                        cancelled_check=lambda: task.cancelled,
                    )
            else:
                await status("⏬ در حال دریافت فایل از تلگرام...", markup=_CANCEL_KB)
                tmp_path, filename, size = await download_telegram_file(
                    task.source, task.filename, task.file_size,
                    progress_cb=lambda d, t: progress(d, t, "⏬ در حال دریافت از تلگرام..."),
                    cancelled_check=lambda: task.cancelled,
                )
                mime_type = task.mime_type

            if task.cancelled:
                raise UploadCancelled()

            # ── Upload — async monitor reads sync progress ────
            _upload_pct = [0]

            def _sync_progress(uploaded: int, total: int):
                if total > 0:
                    _upload_pct[0] = min(99, int(uploaded / total * 100))

            size_mb = size / (1024 * 1024)
            await status(
                f"⬆️ در حال آپلود به گوگل درایو...\n📁 {filename} ({size_mb:.1f} MB)",
                markup=_CANCEL_KB,
            )

            async def _monitor():
                last = -1
                while True:
                    await asyncio.sleep(2.5)
                    pct = _upload_pct[0]
                    if pct == last or pct <= 0:
                        continue
                    last = pct
                    filled = pct // 5
                    bar = "▓" * filled + "░" * (20 - filled)
                    await status(
                        f"⬆️ در حال آپلود به گوگل درایو...\n[{bar}] {pct}%",
                        markup=_CANCEL_KB,
                    )

            monitor = asyncio.create_task(_monitor())
            try:
                file_meta, updated_tokens = await loop.run_in_executor(
                    None,
                    lambda: upload_file(
                        tokens, tmp_path, filename, mime_type,
                        sync_progress_cb=_sync_progress,
                        cancelled_check=lambda: task.cancelled,
                    ),
                )
            finally:
                monitor.cancel()
                try:
                    await monitor
                except asyncio.CancelledError:
                    pass

            if updated_tokens.get("token") != tokens.get("token"):
                await db.save_tokens(task.user_id, updated_tokens)

            await db.increment_daily(task.user_id)
            await db.record_upload(
                task.user_id, filename, size, task.upload_type,
                file_meta["id"], file_meta["webViewLink"], file_meta["webContentLink"],
            )

            uploaded_mb = int(file_meta.get("size", size)) / (1024 * 1024)
            remaining = DAILY_UPLOAD_LIMIT - used - 1

            view_link = file_meta["webViewLink"]
            dl_link = file_meta["webContentLink"]
            await status(
                f"✅ <b>آپلود موفق!</b>\n\n"
                f"📁 نام: <code>{_html.escape(filename)}</code>\n"
                f"📦 حجم: {uploaded_mb:.2f} MB\n\n"
                f'🔗 <a href="{view_link}">مشاهده در گوگل درایو</a>\n'
                f'⬇️ <a href="{dl_link}">دانلود مستقیم</a>\n\n'
                f"📊 آپلودهای باقی‌مانده امروز: {remaining}",
                parse_mode="HTML",
            )

        except UploadCancelled:
            await status("⏹ آپلود لغو شد.")
        except FileTooLargeError as e:
            await status(str(e))
        except Exception as e:
            logger.exception("Upload failed for user %s", task.user_id)
            await status(f"❌ خطا در آپلود:\n{_html.escape(str(e))}", parse_mode="HTML")
        finally:
            if tmp_path and tmp_path.exists():
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass