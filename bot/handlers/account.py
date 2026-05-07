import html
from telegram import Update
from telegram.ext import ContextTypes

import database.db as db
from bot.keyboards import account_menu, main_menu


def _fmt_size(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024**3:.2f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024**2:.2f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


async def account_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    if not user:
        await query.edit_message_text("خطا: کاربر یافت نشد.")
        return

    has_drive = await db.has_tokens(user_id)
    can_upload, used_today = await db.check_daily_limit(user_id, 5)
    from config import DAILY_UPLOAD_LIMIT
    remaining = DAILY_UPLOAD_LIMIT - used_today

    drive_status = "✅ متصل" if has_drive else "❌ متصل نیست"
    joined = user["joined_at"].split("T")[0] if "T" in str(user["joined_at"]) else str(user["joined_at"])[:10]
    full_name = html.escape(f"{user['first_name']} {user['last_name'] or ''}".strip())

    text = (
        f"👤 <b>حساب کاربری</b>\n\n"
        f"🆔 شناسه: <code>{user_id}</code>\n"
        f"👤 نام: {full_name}\n"
        f"📅 تاریخ عضویت: {joined}\n\n"
        f"📊 <b>آمار آپلود</b>\n"
        f"▪️ کل آپلودها: {user['total_uploads']}\n"
        f"▪️ آپلود با لینک: {user['total_link_ups']}\n"
        f"▪️ آپلود فایل: {user['total_file_ups']}\n"
        f"▪️ حجم کل: {_fmt_size(user['total_size_bytes'])}\n\n"
        f"📅 <b>امروز</b>\n"
        f"▪️ آپلودهای باقی‌مانده: {remaining} از {DAILY_UPLOAD_LIMIT}\n\n"
        f"☁️ <b>گوگل درایو</b>: {drive_status}"
    )

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=account_menu(has_drive))


async def disconnect_drive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await db.delete_tokens(update.effective_user.id)
    await query.edit_message_text(
        "✅ اتصال به گوگل درایو قطع شد.\n\nدفعه بعد که آپلود کنید، دوباره از شما می‌خواهیم.",
        reply_markup=main_menu(),
    )
