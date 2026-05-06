"""Handles both link-upload and file-upload flows."""
from __future__ import annotations

import secrets
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

import database.db as db
from bot.keyboards import main_menu, cancel_and_menu, connect_drive, quality_kb
from bot.states import IDLE, WAIT_URL, WAIT_FILE
from bot.rate_limiter import limiter
from services.auth import get_auth_url, has_oauth_config
from services.drive import get_youtube_info, is_youtube_url
from services.queue import UploadTask, QueueFullError
from config import DAILY_UPLOAD_LIMIT, MAX_FILE_SIZE_MB

logger = logging.getLogger(__name__)
_URL_RE = re.compile(r"https?://[^\s<>\"{}|\\^`\[\]]+")


# ── Shared pre-upload checks ──────────────────────────────────

async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if user can proceed. Handles blocks, rate-limit, daily-limit, OAuth."""
    query = update.callback_query
    user_id = update.effective_user.id

    if await db.is_blocked(user_id):
        txt = "⛔ حساب شما مسدود است."
        if query:
            await query.edit_message_text(txt)
        else:
            await update.message.reply_text(txt)
        return False

    if not limiter.is_allowed(user_id):
        txt = (
            "⚠️ لطفاً اسپم نکنید!\n"
            "عملیات قبلی هنوز در حال انجام است یا درخواست‌های زیادی فرستادید.\n"
            "چند ثانیه صبر کنید."
        )
        if query:
            await query.answer(txt, show_alert=True)
        else:
            await update.message.reply_text(txt)
        return False

    can, used = await db.check_daily_limit(user_id, DAILY_UPLOAD_LIMIT)
    if not can:
        txt = f"❌ محدودیت روزانه ({DAILY_UPLOAD_LIMIT} فایل) پر شده است. فردا دوباره امتحان کنید."
        if query:
            await query.edit_message_text(txt, reply_markup=main_menu())
        else:
            await update.message.reply_text(txt, reply_markup=main_menu())
        return False

    return True


async def _ensure_oauth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """If user has no Drive token, send auth link and return False."""
    user_id = update.effective_user.id
    if await db.has_tokens(user_id):
        return True

    if not await has_oauth_config():
        query = update.callback_query
        txt = (
            "⚠️ اتصال به گوگل درایو هنوز تنظیم نشده است.\n\n"
            "ادمین باید ابتدا Client ID و Client Secret گوگل را از پنل ادمین وارد کند."
        )
        if query:
            await query.edit_message_text(txt, reply_markup=main_menu())
        else:
            await update.message.reply_text(txt, reply_markup=main_menu())
        return False

    state = secrets.token_urlsafe(32)
    await db.save_oauth_state(state, user_id)
    auth_url = await get_auth_url(state)

    query = update.callback_query
    text = (
        "☁️ اتصال به گوگل درایو\n\n"
        "برای آپلود، ابتدا حساب گوگل خود را متصل کنید.\n"
        "روی دکمه زیر کلیک کنید و پس از تأیید به ربات برگردید:"
    )
    if query:
        await query.edit_message_text(text, reply_markup=connect_drive(auth_url))
    else:
        await update.message.reply_text(text, reply_markup=connect_drive(auth_url))
    return False


# ── Upload via link ───────────────────────────────────────────

async def upload_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await _guard(update, context):
        return
    if not await _ensure_oauth(update, context):
        return

    context.user_data["state"] = WAIT_URL
    await query.edit_message_text(
        f"🔗 آپلود با لینک\n\n"
        f"لینک فایل یا ویدیو یوتیوب را ارسال کنید:\n"
        f"(حداکثر حجم: {MAX_FILE_SIZE_MB // 1024} گیگابایت)\n\n"
        f"پشتیبانی از:\n"
        f"• لینک مستقیم فایل\n"
        f"• لینک یوتیوب (youtube.com / youtu.be)",
        reply_markup=cancel_and_menu(),
    )


async def handle_url_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAIT_URL:
        return

    urls = _URL_RE.findall(update.message.text or "")
    if not urls:
        await update.message.reply_text(
            "❌ لینک معتبری یافت نشد. لطفاً یک URL کامل ارسال کنید.",
            reply_markup=cancel_and_menu(),
        )
        return

    if not await _guard(update, context):
        context.user_data["state"] = IDLE
        return

    user_id = update.effective_user.id
    tokens = await db.get_tokens(user_id)
    if not tokens:
        await _ensure_oauth(update, context)
        context.user_data["state"] = IDLE
        return

    context.user_data["state"] = IDLE
    url = urls[0]

    # ── YouTube: show quality selector ───────────────────────
    if is_youtube_url(url):
        msg = await update.message.reply_text("🔍 در حال دریافت اطلاعات ویدیو...")
        try:
            info = await get_youtube_info(url)
        except Exception as e:
            await msg.edit_text(
                f"❌ خطا در دریافت اطلاعات ویدیو:\n{e}",
                reply_markup=main_menu(),
            )
            return

        # Store pending data server-side (user_data is per-user in-memory)
        context.user_data["yt_url"] = url
        context.user_data["yt_qualities"] = info["qualities"]
        context.user_data["yt_tokens"] = tokens

        title = info["title"][:60] + ("..." if len(info["title"]) > 60 else "")
        await msg.edit_text(
            f"🎬 ویدیو یافت شد!\n\n"
            f"📌 {title}\n"
            f"⏱ مدت: {info['duration']}\n\n"
            "کیفیت دانلود را انتخاب کنید:",
            reply_markup=quality_kb(info["qualities"]),
        )
        return

    # ── Regular link: enqueue directly ───────────────────────
    queue = context.application.bot_data["upload_queue"]
    status_msg = await update.message.reply_text("⏳ در حال افزودن به صف آپلود...")

    task = UploadTask(
        user_id=user_id,
        chat_id=update.effective_chat.id,
        status_msg_id=status_msg.message_id,
        upload_type="link",
        source=url,
        tokens=tokens,
    )

    try:
        pos = await queue.enqueue(task)
        if pos > 1:
            await status_msg.edit_text(
                f"📋 در صف آپلود هستید.\n"
                f"موقعیت شما: {pos}\n"
                "به محض رسیدن نوبت شروع می‌شود.",
            )
    except QueueFullError:
        await status_msg.edit_text(
            "⚠️ سرور در حال حاضر پر است.\n"
            "لطفاً چند دقیقه دیگر امتحان کنید.",
        )


async def quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected a YouTube quality from the inline keyboard."""
    query = update.callback_query
    await query.answer()

    qualities: list | None = context.user_data.get("yt_qualities")
    url: str | None = context.user_data.get("yt_url")
    tokens: dict | None = context.user_data.get("yt_tokens")

    if not qualities or not url or not tokens:
        await query.edit_message_text(
            "❌ اطلاعات منقضی شده. لطفاً لینک را دوباره ارسال کنید.",
            reply_markup=main_menu(),
        )
        return

    try:
        idx = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("❌ کیفیت نامعتبر", show_alert=True)
        return

    if idx < 0 or idx >= len(qualities):
        await query.answer("❌ کیفیت نامعتبر", show_alert=True)
        return

    selected = qualities[idx]

    # Clear pending data
    context.user_data.pop("yt_qualities", None)
    context.user_data.pop("yt_url", None)
    context.user_data.pop("yt_tokens", None)

    if not await _guard(update, context):
        return

    queue = context.application.bot_data["upload_queue"]
    await query.edit_message_text(f"⏳ در حال افزودن به صف...\nکیفیت: {selected['label']}")

    task = UploadTask(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        status_msg_id=query.message.message_id,
        upload_type="link",
        source=url,
        tokens=tokens,
        yt_format=selected["format"],
    )

    try:
        pos = await queue.enqueue(task)
        if pos > 1:
            await query.edit_message_text(
                f"📋 در صف آپلود هستید.\nموقعیت: {pos}\nکیفیت: {selected['label']}",
            )
    except QueueFullError:
        await query.edit_message_text(
            "⚠️ سرور پر است. چند دقیقه دیگر امتحان کنید.",
            reply_markup=main_menu(),
        )


# ── Upload via Telegram file ──────────────────────────────────

async def upload_file_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not await _guard(update, context):
        return
    if not await _ensure_oauth(update, context):
        return

    context.user_data["state"] = WAIT_FILE
    await query.edit_message_text(
        f"📤 آپلود فایل\n\n"
        f"فایل، عکس یا ویدیو خود را ارسال کنید.\n"
        f"(حداکثر حجم: {MAX_FILE_SIZE_MB // 1024} گیگابایت)\n\n"
        f"انواع پشتیبانی‌شده: هر نوع فایل، عکس، ویدیو، صدا",
        reply_markup=cancel_and_menu(),
    )


async def handle_file_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAIT_FILE:
        return

    msg = update.message

    # Determine file object and metadata
    if msg.photo:
        # photos come as a list of PhotoSize; take the largest
        photo = msg.photo[-1]
        file_obj = photo
        filename = f"photo_{photo.file_unique_id}.jpg"
        file_size = photo.file_size or 0
        mime_type = "image/jpeg"
    elif msg.document:
        file_obj = msg.document
        filename = file_obj.file_name or "file"
        file_size = file_obj.file_size or 0
        mime_type = file_obj.mime_type or "application/octet-stream"
    elif msg.video:
        file_obj = msg.video
        filename = file_obj.file_name or f"video_{file_obj.file_unique_id}.mp4"
        file_size = file_obj.file_size or 0
        mime_type = file_obj.mime_type or "video/mp4"
    elif msg.audio:
        file_obj = msg.audio
        filename = file_obj.file_name or f"audio_{file_obj.file_unique_id}.mp3"
        file_size = file_obj.file_size or 0
        mime_type = file_obj.mime_type or "audio/mpeg"
    elif msg.voice:
        file_obj = msg.voice
        filename = f"voice_{file_obj.file_unique_id}.ogg"
        file_size = file_obj.file_size or 0
        mime_type = "audio/ogg"
    elif msg.video_note:
        file_obj = msg.video_note
        filename = f"video_note_{file_obj.file_unique_id}.mp4"
        file_size = file_obj.file_size or 0
        mime_type = "video/mp4"
    else:
        file_obj = None

    if not file_obj:
        await msg.reply_text(
            "❌ فایل معتبری دریافت نشد. لطفاً یک فایل، عکس یا ویدیو ارسال کنید.",
            reply_markup=cancel_and_menu(),
        )
        return

    if not await _guard(update, context):
        context.user_data["state"] = IDLE
        return

    user_id = update.effective_user.id
    tokens = await db.get_tokens(user_id)
    if not tokens:
        await _ensure_oauth(update, context)
        context.user_data["state"] = IDLE
        return

    # Check size (Telegram gives us file_size for files < 20 MB; for larger it may be 0)
    max_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size and file_size > max_bytes:
        await msg.reply_text(
            f"❌ حجم فایل ({file_size / 1024**3:.2f} GB) بیشتر از حداکثر مجاز است.\n"
            "برای فایل‌های بزرگ از گزینه «آپلود با لینک» استفاده کنید.",
            reply_markup=main_menu(),
        )
        context.user_data["state"] = IDLE
        return

    # Get Telegram download URL
    tg_file = await context.bot.get_file(file_obj.file_id)
    file_path_url = tg_file.file_path

    context.user_data["state"] = IDLE
    queue = context.application.bot_data["upload_queue"]
    status_msg = await msg.reply_text("⏳ در حال افزودن به صف آپلود...")

    task = UploadTask(
        user_id=user_id,
        chat_id=update.effective_chat.id,
        status_msg_id=status_msg.message_id,
        upload_type="file",
        source=file_path_url,
        filename=filename,
        mime_type=mime_type,
        file_size=file_size,
        tokens=tokens,
    )

    try:
        pos = await queue.enqueue(task)
        if pos > 1:
            await status_msg.edit_text(
                f"📋 در صف آپلود هستید.\nموقعیت: {pos}",
            )
    except QueueFullError:
        await status_msg.edit_text(
            "⚠️ سرور در حال حاضر پر است. چند دقیقه دیگر امتحان کنید."
        )