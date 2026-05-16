"""Admin panel for managing shared/public Google Drive accounts."""
from __future__ import annotations

import html
import json
import logging
import secrets

from telegram import Update
from telegram.ext import ContextTypes

import database.db as db
from bot.keyboards import public_drives_admin_kb, back_to_menu
from bot.states import IDLE, ADMIN_PUBLIC_DRIVE_LABEL
from config import ADMIN_IDS
from services.drive import get_drive_quota

logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _fmt_size(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024**3:.2f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024**2:.1f} MB"
    return f"{b / 1024:.0f} KB"


async def _show_public_drives(query, notice: str = ""):
    drives = await db.get_public_drives()
    enabled = await db.is_public_drive_enabled()

    status_line = "🟢 فعال" if enabled else "🔴 غیرفعال"
    lines = [f"🌐 <b>درایوهای عمومی</b> — وضعیت: {status_line}\n"]

    if drives:
        lines.append(f"تعداد: {len(drives)} درایو متصل\n")
        for d in drives:
            state = "✅ فعال" if d["is_active"] else "⏸ غیرفعال"
            label = html.escape(d["label"] or f"Drive #{d['id']}")
            lines.append(f"• <b>{label}</b> — {state}")
    else:
        lines.append("هیچ درایو عمومی متصل نشده است.")

    lines.append(
        "\n<i>برای اضافه کردن درایو جدید، روی دکمه «اتصال» بزنید.\n"
        "ادمین باید با حساب گوگل مورد نظر وارد شود.</i>"
    )

    text = "\n".join(lines)
    if notice:
        text = f"{notice}\n\n{text}"

    await query.edit_message_text(
        text, parse_mode="HTML", reply_markup=public_drives_admin_kb(drives, enabled)
    )


async def public_drive_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return
    await _show_public_drives(query)


async def public_drive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    action = query.data  # pubdrv:toggle | pubdrv:add | pubdrv:del:ID | pubdrv:toggle_drive:ID

    if action == "pubdrv:toggle":
        enabled = await db.is_public_drive_enabled()
        new_val = "0" if enabled else "1"
        await db.set_app_setting("public_drive_enabled", new_val)
        status = "فعال" if new_val == "1" else "غیرفعال"
        await _show_public_drives(query, notice=f"✅ ویژگی درایو عمومی <b>{status}</b> شد.")

    elif action == "pubdrv:add":
        context.user_data["state"] = ADMIN_PUBLIC_DRIVE_LABEL
        await query.edit_message_text(
            "🌐 <b>اتصال درایو عمومی جدید</b>\n\n"
            "ابتدا یک نام برای این درایو بفرستید:\n"
            "<i>مثال: درایو ۱ — یا هر نام دلخواه</i>",
            parse_mode="HTML",
            reply_markup=back_to_menu(),
        )

    elif action.startswith("pubdrv:del:"):
        drive_id = int(action.split(":")[-1])
        await db.delete_public_drive(drive_id)
        await _show_public_drives(query, notice="🗑 درایو حذف شد.")

    elif action.startswith("pubdrv:toggle_drive:"):
        drive_id = int(action.split(":")[-1])
        drives = await db.get_public_drives()
        drive = next((d for d in drives if d["id"] == drive_id), None)
        if drive:
            await db.toggle_public_drive(drive_id, not drive["is_active"])
            status = "فعال" if not drive["is_active"] else "غیرفعال"
            await _show_public_drives(query, notice=f"✅ درایو <b>{html.escape(drive['label'] or str(drive_id))}</b> {status} شد.")
        else:
            await _show_public_drives(query)


async def handle_admin_public_drive_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sent the label for a new public drive — generate OAuth URL."""
    if context.user_data.get("state") != ADMIN_PUBLIC_DRIVE_LABEL:
        return
    if not _is_admin(update.effective_user.id):
        return

    label = update.message.text.strip()
    if not label:
        await update.message.reply_text(
            "❌ نام معتبری وارد نشد.", reply_markup=back_to_menu()
        )
        return

    from services.auth import get_auth_url, has_oauth_config
    if not await has_oauth_config():
        await update.message.reply_text(
            "❌ ابتدا OAuth (Client ID و Secret) را از پنل ادمین تنظیم کنید.",
            reply_markup=back_to_menu(),
        )
        context.user_data["state"] = IDLE
        return

    state = secrets.token_urlsafe(32)
    extra = json.dumps({"is_public_drive": True, "label": label})
    await db.save_oauth_state(state, update.effective_user.id, extra)
    auth_url = await get_auth_url(state)

    context.user_data["state"] = IDLE
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 ورود با گوگل برای درایو عمومی", url=auth_url)],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="pubdrv:menu")],
    ])
    await update.message.reply_text(
        f"🌐 <b>اتصال درایو عمومی: «{html.escape(label)}»</b>\n\n"
        "روی دکمه زیر کلیک کنید و با حساب گوگلی که می‌خواهید به عنوان درایو عمومی استفاده شود وارد شوید.\n\n"
        "⚠️ <i>این حساب برای همه کاربران بدون اتصال شخصی استفاده خواهد شد.</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )
