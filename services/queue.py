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
    get_drive_quota, generate_zip_password, zip_with_password,
)

_DEFAULT_YT_FORMAT = "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"
from config import MAX_CONCURRENT_UPLOADS, MAX_QUEUE_SIZE, DAILY_UPLOAD_LIMIT, PUBLIC_DRIVE_MAX_MB

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
    yt_format: str = ""
    use_public_drive: bool = False


class QueueFullError(Exception):
    pass


class AlreadyQueuedError(Exception):
    pass


class UploadQueue:
    def __init__(self):
        self._q: asyncio.Queue[UploadTask] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._workers: list[asyncio.Task] = []
        self._uploading: dict[int, UploadTask] = {}
        self._queued: set[int] = set()      # user_ids waiting in queue (not yet picked)

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

    def is_queued_or_uploading(self, user_id: int) -> bool:
        return user_id in self._queued or user_id in self._uploading

    async def enqueue(self, task: UploadTask) -> int:
        if task.user_id in self._queued or task.user_id in self._uploading:
            raise AlreadyQueuedError()
        if self._q.full():
            raise QueueFullError()
        self._queued.add(task.user_id)
        await self._q.put(task)
        return self._q.qsize()

    async def _worker(self, bot: Bot):
        while True:
            task = await self._q.get()
            self._queued.discard(task.user_id)
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

        # For personal drive, verify token still exists
        if not task.use_public_drive:
            tokens = await db.get_tokens(task.user_id)
            if not tokens:
                await status("❌ اتصال به گوگل درایو قطع شده. لطفاً /start بزنید و دوباره وصل شوید.")
                return
        else:
            tokens = None

        tmp_path: Path | None = None
        zip_path: Path | None = None
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

            # ── Public drive path ─────────────────────────────
            if task.use_public_drive:
                max_pub = PUBLIC_DRIVE_MAX_MB * 1024 * 1024
                if size > max_pub:
                    await status(
                        f"❌ حجم فایل ({size / 1024**2:.0f} MB) از سقف درایو عمومی "
                        f"({PUBLIC_DRIVE_MAX_MB // 1024} GB) بیشتر است."
                    )
                    return

                await status("🔒 در حال رمزنگاری فایل...", markup=_CANCEL_KB)
                password = generate_zip_password()
                zip_path = tmp_path.with_suffix(tmp_path.suffix + ".zip")
                await loop.run_in_executor(None, zip_with_password, tmp_path, zip_path, password)

                # Clean original now — only zip needed from here
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                tmp_path = None

                drives = await db.get_active_public_drives()
                if not drives:
                    await status("❌ هیچ درایو عمومی فعالی موجود نیست. با ادمین تماس بگیرید.")
                    return

                # Sort by free space (most free first)
                drive_spaces: list[tuple[int, dict]] = []
                for d in drives:
                    try:
                        quota = await loop.run_in_executor(None, get_drive_quota, d["tokens"])
                        limit = int(quota.get("limit", 0))
                        used_bytes = int(quota.get("usageInDrive", 0))
                        free = limit - used_bytes if limit > 0 else 10 ** 18
                    except Exception:
                        free = 0
                    drive_spaces.append((free, d))
                drive_spaces.sort(key=lambda x: x[0], reverse=True)

                zip_filename = filename + ".zip"
                await status(f"⬆️ در حال آپلود به درایو عمومی...\n📁 {zip_filename}", markup=_CANCEL_KB)

                file_meta = None
                for _, drive in drive_spaces:
                    try:
                        file_meta, upd_tok = await loop.run_in_executor(
                            None,
                            lambda t=drive["tokens"]: upload_file(
                                t, zip_path, zip_filename, "application/zip",
                                cancelled_check=lambda: task.cancelled,
                            ),
                        )
                        if upd_tok.get("token") != drive["tokens"].get("token"):
                            await db.update_public_drive_tokens(drive["id"], upd_tok)
                        break
                    except UploadCancelled:
                        raise
                    except Exception as e:
                        logger.warning("Public drive %d failed: %s", drive["id"], e)
                        continue

                if not file_meta:
                    raise RuntimeError("همه درایوهای عمومی ناموفق بودند. لطفاً بعداً امتحان کنید.")

                await db.increment_daily(task.user_id)
                await db.record_upload(
                    task.user_id, zip_filename, size, task.upload_type,
                    file_meta["id"], file_meta["webViewLink"], file_meta["webContentLink"],
                )

                remaining = DAILY_UPLOAD_LIMIT - used - 1
                view_link = file_meta["webViewLink"]
                dl_link = file_meta["webContentLink"]
                await status(
                    f"✅ <b>آپلود موفق!</b> (درایو عمومی)\n\n"
                    f"📁 نام فایل: <code>{_html.escape(filename)}</code>\n"
                    f"📦 حجم: {size / 1024 / 1024:.2f} MB\n\n"
                    f'🔗 <a href="{view_link}">مشاهده در گوگل درایو</a>\n'
                    f'⬇️ <a href="{dl_link}">دانلود مستقیم</a>\n\n'
                    f"🔐 <b>رمز عبور فایل زیپ:</b>\n<code>{_html.escape(password)}</code>\n\n"
                    "📦 <b>نحوه استخراج:</b>\n"
                    "• <b>ویندوز:</b> راست‌کلیک ← Extract with 7-Zip یا WinRAR\n"
                    "• <b>مک / لینوکس:</b>\n"
                    f"  <code>unzip -P {_html.escape(password)} «نام‌فایل».zip</code>\n"
                    "• <b>اندروید:</b> اپ ZArchiver یا WinZip\n\n"
                    "⚠️ <i>فایل به دلیل امنیت درایو عمومی به‌صورت زیپ رمزدار تحویل داده شد.</i>\n"
                    f"📊 آپلودهای باقی‌مانده امروز: {remaining}",
                    parse_mode="HTML",
                )
                return

            # ── Personal drive path ───────────────────────────
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
            for p in (tmp_path, zip_path):
                if p and p.exists():
                    try:
                        os.unlink(p)
                    except Exception:
                        pass