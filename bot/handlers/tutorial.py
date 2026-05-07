"""Tutorial content: users view, admin manages."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

import database.db as db
from bot.keyboards import tutorial_admin_kb, tutorial_list_kb, back_to_menu, cancel_and_menu
from bot.states import IDLE, ADMIN_TUTORIAL_ADD
from config import ADMIN_IDS


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

logger = logging.getLogger(__name__)

_TYPE_ICON = {"photo": "🖼", "video": "🎬", "animation": "🎞", "document": "📎"}


async def _send_item(bot, chat_id: int, item: dict):
    fid = item["file_id"]
    caption = item.get("caption") or None
    ft = item["file_type"]
    if ft == "photo":
        await bot.send_photo(chat_id, fid, caption=caption)
    elif ft == "video":
        await bot.send_video(chat_id, fid, caption=caption)
    elif ft == "animation":
        await bot.send_animation(chat_id, fid, caption=caption)
    else:
        await bot.send_document(chat_id, fid, caption=caption)


# ── User: view tutorial ───────────────────────────────────────

async def tutorial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    items = await db.get_tutorial_media()
    if not items:
        await query.edit_message_text(
            "📚 آموزش استفاده\n\nهنوز محتوای آموزشی تنظیم نشده است.",
            reply_markup=back_to_menu(),
        )
        return

    await query.edit_message_text("📚 در حال ارسال آموزش...")
    chat_id = update.effective_chat.id
    for item in items:
        await _send_item(context.bot, chat_id, item)
    await context.bot.send_message(chat_id, "✅ پایان آموزش.", reply_markup=back_to_menu())


# ── Admin: management ─────────────────────────────────────────

async def tutorial_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    count = await db.count_tutorial_media()
    await query.edit_message_text(
        f"📚 مدیریت آموزش\n\nتعداد محتواها: {count}",
        reply_markup=tutorial_admin_kb(count > 0),
    )


async def tutorial_admin_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    context.user_data["state"] = ADMIN_TUTORIAL_ADD
    await query.edit_message_text(
        "📚 افزودن محتوای آموزشی\n\n"
        "عکس، ویدیو، انیمیشن یا فایل ارسال کنید.\n"
        "کپشن پیام به عنوان توضیح ذخیره می‌شود.",
        reply_markup=cancel_and_menu(),
    )


async def tutorial_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    items = await db.get_tutorial_media()
    if not items:
        await query.edit_message_text(
            "📋 لیست خالی است.", reply_markup=tutorial_admin_kb(False)
        )
        return
    await query.edit_message_text(
        f"📋 لیست محتوای آموزشی ({len(items)} مورد)\nبرای حذف روی هر آیتم بزنید:",
        reply_markup=tutorial_list_kb(items),
    )


async def tutorial_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    item_id = int(query.data.split(":")[-1])
    await db.delete_tutorial_media(item_id)

    items = await db.get_tutorial_media()
    if not items:
        await query.edit_message_text("🗑 حذف شد. لیست خالی است.", reply_markup=tutorial_admin_kb(False))
        return
    await query.edit_message_text(
        f"🗑 حذف شد. {len(items)} مورد باقی‌مانده:",
        reply_markup=tutorial_list_kb(items),
    )


# ── Admin: receive media ──────────────────────────────────────

async def handle_admin_tutorial_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != ADMIN_TUTORIAL_ADD:
        return
    if not _is_admin(update.effective_user.id):
        return

    msg = update.message
    file_id = file_type = None

    if msg.photo:
        file_id, file_type = msg.photo[-1].file_id, "photo"
    elif msg.video:
        file_id, file_type = msg.video.file_id, "video"
    elif msg.animation:
        file_id, file_type = msg.animation.file_id, "animation"
    elif msg.document:
        file_id, file_type = msg.document.file_id, "document"

    if not file_id:
        await msg.reply_text("❌ لطفاً عکس، ویدیو یا فایل ارسال کنید.")
        return

    caption = msg.caption or ""
    await db.add_tutorial_media(file_id, file_type, caption)
    context.user_data["state"] = IDLE

    count = await db.count_tutorial_media()
    icon = _TYPE_ICON.get(file_type, "📎")
    await msg.reply_text(
        f"✅ {icon} محتوا ذخیره شد. (تعداد کل: {count})",
        reply_markup=tutorial_admin_kb(True),
    )