"""Software download: users pick OS, admin manages files per platform."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

import database.db as db
from bot.keyboards import (
    software_os_kb, software_admin_menu_kb,
    software_admin_platform_kb, back_to_menu, cancel_and_menu,
)
from bot.states import IDLE, ADMIN_SW_ADD
from config import ADMIN_IDS


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

logger = logging.getLogger(__name__)

_PLATFORM_NAME = {
    "android": "🤖 اندروید",
    "windows": "🪟 ویندوز",
    "mac":     "🍎 مک",
    "ios":     "📱 iOS",
    "linux":   "🐧 لینوکس",
}


async def _send_sw_file(bot, chat_id: int, f: dict):
    fid = f["file_id"]
    caption = f.get("caption") or f.get("name") or None
    ft = f["file_type"]
    if ft == "photo":
        await bot.send_photo(chat_id, fid, caption=caption)
    elif ft == "video":
        await bot.send_video(chat_id, fid, caption=caption)
    else:
        await bot.send_document(chat_id, fid, caption=caption)


# ── User: OS selection ────────────────────────────────────────

async def software_os_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📥 دانلود نرم‌افزار\n\nسیستم‌عامل خود را انتخاب کنید:",
        reply_markup=software_os_kb(),
    )


async def software_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected a platform — send all its files."""
    query = update.callback_query
    await query.answer()

    platform = query.data.split(":")[-1]
    pname = _PLATFORM_NAME.get(platform, platform)
    files = await db.get_software_files(platform)

    if not files:
        await query.edit_message_text(
            f"📥 {pname}\n\nهنوز نرم‌افزاری برای این سیستم‌عامل اضافه نشده.",
            reply_markup=back_to_menu(),
        )
        return

    await query.edit_message_text(f"📥 در حال ارسال {len(files)} فایل برای {pname}...")
    chat_id = update.effective_chat.id
    for f in files:
        await _send_sw_file(context.bot, chat_id, f)
    await context.bot.send_message(
        chat_id,
        f"✅ ارسال نرم‌افزارهای {pname} تمام شد.",
        reply_markup=back_to_menu(),
    )


# ── Admin: management ─────────────────────────────────────────

async def software_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return
    await query.edit_message_text(
        "📥 مدیریت نرم‌افزار\n\nسیستم‌عامل را انتخاب کنید:",
        reply_markup=software_admin_menu_kb(),
    )


async def software_admin_platform_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    platform = query.data.split(":")[-1]
    pname = _PLATFORM_NAME.get(platform, platform)
    files = await db.get_software_files(platform)

    await query.edit_message_text(
        f"📥 {pname}\nتعداد فایل‌ها: {len(files)}",
        reply_markup=software_admin_platform_kb(platform, files),
    )


async def software_admin_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    platform = query.data.split(":")[-1]
    pname = _PLATFORM_NAME.get(platform, platform)

    context.user_data["sw_platform"] = platform
    context.user_data["state"] = ADMIN_SW_ADD

    await query.edit_message_text(
        f"📥 افزودن نرم‌افزار برای {pname}\n\n"
        "فایل نرم‌افزار را ارسال کنید.\n"
        "کپشن پیام به عنوان نام نمایش داده می‌شود.",
        reply_markup=cancel_and_menu(),
    )


async def software_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    db_id = int(query.data.split(":")[-1])
    f = await db.get_software_file(db_id)
    if not f:
        await query.answer("❌ فایل یافت نشد.", show_alert=True)
        return

    platform = f["platform"]
    pname = _PLATFORM_NAME.get(platform, platform)
    await db.delete_software_file(db_id)

    files = await db.get_software_files(platform)
    await query.edit_message_text(
        f"🗑 حذف شد.\n{pname}: {len(files)} فایل باقی‌مانده",
        reply_markup=software_admin_platform_kb(platform, files),
    )


# ── Admin: receive file ───────────────────────────────────────

async def handle_admin_sw_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != ADMIN_SW_ADD:
        return
    if not _is_admin(update.effective_user.id):
        return

    platform = context.user_data.get("sw_platform", "android")
    pname = _PLATFORM_NAME.get(platform, platform)
    msg = update.message

    file_id = file_type = filename = None

    if msg.document:
        file_id = msg.document.file_id
        file_type = "document"
        filename = msg.document.file_name or "file"
    elif msg.video:
        file_id = msg.video.file_id
        file_type = "video"
        filename = msg.video.file_name or "video.mp4"
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        file_type = "photo"
        filename = "image.jpg"

    if not file_id:
        await msg.reply_text("❌ لطفاً فایل، ویدیو یا عکس ارسال کنید.")
        return

    name = msg.caption or filename or "نرم‌افزار"
    caption = msg.caption or ""

    await db.add_software_file(platform, file_id, file_type, name, filename or "", caption)
    context.user_data["state"] = IDLE
    context.user_data.pop("sw_platform", None)

    files = await db.get_software_files(platform)
    await msg.reply_text(
        f"✅ فایل «{name}» برای {pname} ذخیره شد.\nتعداد کل: {len(files)}",
        reply_markup=software_admin_platform_kb(platform, files),
    )