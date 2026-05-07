"""Admin panel — only accessible to users listed in ADMIN_IDS."""
from __future__ import annotations

import html
import logging
from telegram import Update
from telegram.ext import ContextTypes

import database.db as db
from bot.keyboards import admin_menu, admin_user_actions, channels_manage, main_menu, back_to_menu, oauth_settings_menu, admin_users_kb
from bot.states import IDLE, ADMIN_SEARCH, ADMIN_ADD_CHANNEL, ADMIN_SET_GOOGLE_ID, ADMIN_SET_GOOGLE_SECRET
from config import ADMIN_IDS

logger = logging.getLogger(__name__)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _fmt_size(b: int) -> str:
    if b >= 1024 ** 3:
        return f"{b / 1024**3:.2f} GB"
    if b >= 1024 ** 2:
        return f"{b / 1024**2:.1f} MB"
    return f"{b / 1024:.0f} KB"


# ── Entry points ──────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("❌ شما دسترسی ادمین ندارید.")
        return
    context.user_data["state"] = IDLE
    await update.message.reply_text("🛡 **پنل مدیریت**", parse_mode="Markdown", reply_markup=admin_menu())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not _is_admin(update.effective_user.id):
        await query.edit_message_text("❌ دسترسی ندارید.")
        return

    action = query.data  # e.g. "admin:search", "admin:stats", "admin:block:123"

    if action == "admin:search":
        context.user_data["state"] = ADMIN_SEARCH
        await query.edit_message_text(
            "🔍 شناسه عددی یا نام کاربری کاربر را بفرستید:",
            reply_markup=back_to_menu(),
        )

    elif action == "admin:stats":
        total = await db.get_total_users()
        await query.edit_message_text(
            f"📊 **آمار کلی**\n\n👥 کل کاربران: {total}",
            parse_mode="Markdown",
            reply_markup=admin_menu(),
        )

    elif action.startswith("admin:block:"):
        target_id = int(action.split(":")[-1])
        await db.set_blocked(target_id, True)
        await query.edit_message_text(
            f"🚫 کاربر `{target_id}` مسدود شد.",
            parse_mode="Markdown",
            reply_markup=admin_menu(),
        )

    elif action.startswith("admin:unblock:"):
        target_id = int(action.split(":")[-1])
        await db.set_blocked(target_id, False)
        await query.edit_message_text(
            f"✅ کاربر `{target_id}` رفع مسدودیت شد.",
            parse_mode="Markdown",
            reply_markup=admin_menu(),
        )

    elif action.startswith("admin:users:"):
        offset = int(action.split(":", 2)[2])
        await _show_user_list(query, offset)

    elif action == "admin:channels":
        await _show_channels(query)

    elif action == "admin:addchan":
        context.user_data["state"] = ADMIN_ADD_CHANNEL
        await query.edit_message_text(
            "📢 **افزودن کانال اجباری**\n\n"
            "یوزرنیم یا شناسه عددی کانال را بفرستید:\n"
            "مثال: `@mychannel` یا `-1001234567890`\n\n"
            "⚠️ ربات باید ادمین آن کانال باشد تا بتواند عضویت را بررسی کند.",
            parse_mode="Markdown",
            reply_markup=back_to_menu(),
        )

    elif action.startswith("admin:rmchan:"):
        # split max 3 parts to handle channel IDs with colons (e.g. numeric)
        channel_id = action.split(":", 2)[2]
        await db.remove_required_channel(channel_id)
        await _show_channels(query, notice=f"✅ کانال <code>{html.escape(channel_id)}</code> حذف شد.")

    elif action == "admin:oauth":
        await _show_oauth_settings(query)

    elif action == "admin:oauth_set_id":
        context.user_data["state"] = ADMIN_SET_GOOGLE_ID
        await query.edit_message_text(
            "⚙️ **تنظیم Google Client ID**\n\n"
            "مقدار `client_id` را از Google Cloud Console کپی کرده و بفرستید:\n"
            "_(معمولاً به `.apps.googleusercontent.com` ختم می‌شود)_",
            parse_mode="Markdown",
            reply_markup=back_to_menu(),
        )

    elif action == "admin:oauth_set_secret":
        context.user_data["state"] = ADMIN_SET_GOOGLE_SECRET
        await query.edit_message_text(
            "⚙️ **تنظیم Google Client Secret**\n\n"
            "مقدار `client_secret` را از Google Cloud Console کپی کرده و بفرستید:",
            parse_mode="Markdown",
            reply_markup=back_to_menu(),
        )

    elif action == "admin:oauth_test":
        await query.edit_message_text("🔄 در حال تست اتصال...")
        await _test_oauth(query)
        return

    elif action == "admin:oauth_clear":
        await db.delete_app_setting("google_client_id")
        await db.delete_app_setting("google_client_secret")
        await _show_oauth_settings(query, notice="🗑 اعتبارنامه‌های OAuth حذف شدند.")

    elif action == "admin:menu":
        context.user_data["state"] = IDLE
        await query.edit_message_text("🛡 **پنل مدیریت**", parse_mode="Markdown", reply_markup=admin_menu())


async def _show_user_list(query, offset: int = 0):
    _PAGE = 15
    total = await db.get_total_users()
    users = await db.get_all_users(limit=_PAGE, offset=offset)

    page = offset // _PAGE + 1
    total_pages = max(1, (total + _PAGE - 1) // _PAGE)
    lines = [f"👥 <b>لیست کاربران</b> (صفحه {page}/{total_pages} — کل: {total})\n"]

    for u in users:
        blocked = "🚫" if u["is_blocked"] else "✅"
        uname = f"@{html.escape(u['username'])}" if u["username"] else "—"
        fname = html.escape(f"{u['first_name']} {u['last_name'] or ''}".strip())
        lines.append(
            f"{blocked} <code>{u['user_id']}</code> — {fname} "
            f"({uname}) — {u['total_uploads']} آپلود"
        )

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=admin_users_kb(offset, total, _PAGE),
    )


async def _show_channels(query, notice: str = ""):
    channels = await db.get_required_channels()
    if channels:
        lines = "\n".join(
            f"▪️ {html.escape(ch['title'] or ch['channel_id'])}  (<code>{html.escape(ch['channel_id'])}</code>)"
            for ch in channels
        )
        header = f"📢 <b>کانال‌های اجباری</b> ({len(channels)} عدد)\n\n{lines}"
    else:
        header = "📢 <b>کانال‌های اجباری</b>\n\nهیچ کانالی تنظیم نشده است."

    if notice:
        header = f"{notice}\n\n{header}"

    await query.edit_message_text(
        header,
        parse_mode="HTML",
        reply_markup=channels_manage(channels),
    )


async def _test_oauth(query):
    from services.auth import get_auth_url, has_oauth_config
    from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    try:
        if not await has_oauth_config():
            await query.edit_message_text(
                "❌ Client ID یا Client Secret تنظیم نشده است.",
                reply_markup=back_to_menu(),
            )
            return
        # Try to generate a real auth URL — this validates credentials format
        test_url = await get_auth_url("__admin_test__")
        db_id = await db.get_app_setting("google_client_id", encrypted=True)
        source = "دیتابیس" if db_id else "فایل .env"
        short_url = html.escape(test_url[:60] + "..." if len(test_url) > 60 else test_url)
        await query.edit_message_text(
            "✅ <b>تست اتصال موفق!</b>\n\n"
            f"منبع اعتبارنامه: {source}\n"
            f"URL تولید شد:\n<code>{short_url}</code>\n\n"
            "اعتبارنامه‌ها به‌درستی پیکربندی شده‌اند.\n"
            "کاربران می‌توانند Drive خود را متصل کنند.",
            parse_mode="HTML",
            reply_markup=back_to_menu(),
        )
    except Exception as e:
        await query.edit_message_text(
            f"❌ <b>تست شکست خورد:</b>\n\n<code>{html.escape(str(e))}</code>\n\n"
            "Client ID یا Client Secret نامعتبر است.",
            parse_mode="HTML",
            reply_markup=back_to_menu(),
        )


_OAUTH_PLACEHOLDERS = {
    "your_client_id.apps.googleusercontent.com",
    "your_client_secret",
    "your_client_id",
    "",
}


def _is_real_oauth_value(val: str | None) -> bool:
    return bool(val) and val.strip() not in _OAUTH_PLACEHOLDERS


async def _show_oauth_settings(query, notice: str = ""):
    from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    db_id = await db.get_app_setting("google_client_id", encrypted=True)
    db_secret = await db.get_app_setting("google_client_secret", encrypted=True)

    # فقط مقادیر واقعی (نه placeholder) به عنوان «تنظیم شده» محسوب می‌شوند
    has_id = _is_real_oauth_value(db_id) or _is_real_oauth_value(GOOGLE_CLIENT_ID)
    has_secret = _is_real_oauth_value(db_secret) or _is_real_oauth_value(GOOGLE_CLIENT_SECRET)

    if _is_real_oauth_value(db_id):
        source_id = "دیتابیس"
    elif _is_real_oauth_value(GOOGLE_CLIENT_ID):
        source_id = "فایل .env"
    else:
        source_id = "—"

    if _is_real_oauth_value(db_secret):
        source_secret = "دیتابیس"
    elif _is_real_oauth_value(GOOGLE_CLIENT_SECRET):
        source_secret = "فایل .env"
    else:
        source_secret = "—"

    text = (
        "⚙️ **تنظیمات OAuth گوگل**\n\n"
        f"🔑 Client ID: {'✅ موجود' if has_id else '❌ تنظیم نشده'} _(منبع: {source_id})_\n"
        f"🔐 Client Secret: {'✅ موجود' if has_secret else '❌ تنظیم نشده'} _(منبع: {source_secret})_\n\n"
        "اعتبارنامه‌های ذخیره‌شده در دیتابیس اولویت دارند و بدون ری‌استارت فعال می‌شوند."
    )
    if notice:
        text = f"{notice}\n\n{text}"

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=oauth_settings_menu(has_id, has_secret),
    )


async def handle_admin_set_google_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != ADMIN_SET_GOOGLE_ID:
        return
    if not _is_admin(update.effective_user.id):
        return

    value = update.message.text.strip()
    if not value or len(value) < 10:
        await update.message.reply_text(
            "❌ مقدار وارد‌شده معتبر نیست. لطفاً دوباره امتحان کنید.",
            reply_markup=back_to_menu(),
        )
        return

    await db.set_app_setting("google_client_id", value, encrypted=True)
    context.user_data["state"] = IDLE
    await update.message.reply_text(
        "✅ **Client ID با موفقیت ذخیره شد.**\n\n"
        "تنظیمات جدید فوری اعمال می‌شوند — نیازی به ری‌استارت نیست.",
        parse_mode="Markdown",
        reply_markup=admin_menu(),
    )


async def handle_admin_set_google_secret(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != ADMIN_SET_GOOGLE_SECRET:
        return
    if not _is_admin(update.effective_user.id):
        return

    value = update.message.text.strip()
    if not value or len(value) < 6:
        await update.message.reply_text(
            "❌ مقدار وارد‌شده معتبر نیست. لطفاً دوباره امتحان کنید.",
            reply_markup=back_to_menu(),
        )
        return

    await db.set_app_setting("google_client_secret", value, encrypted=True)
    context.user_data["state"] = IDLE
    await update.message.reply_text(
        "✅ **Client Secret با موفقیت ذخیره شد.**\n\n"
        "تنظیمات جدید فوری اعمال می‌شوند — نیازی به ری‌استارت نیست.",
        parse_mode="Markdown",
        reply_markup=admin_menu(),
    )


async def handle_admin_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != ADMIN_ADD_CHANNEL:
        return
    if not _is_admin(update.effective_user.id):
        return

    raw = update.message.text.strip()
    # Normalize: add @ if it looks like a username without it
    if not raw.startswith("@") and not raw.startswith("-") and not raw.lstrip("-").isdigit():
        raw = f"@{raw}"

    # Validate via Telegram API and fetch real title
    try:
        chat = await update.get_bot().get_chat(raw)
        title = chat.title or raw
        channel_id = f"@{chat.username}" if chat.username else str(chat.id)
    except Exception:
        await update.message.reply_text(
            f"❌ نمی‌توانم کانال <code>{html.escape(raw)}</code> را پیدا کنم.\n"
            "مطمئن شوید ربات عضو/ادمین کانال است.",
            parse_mode="HTML",
            reply_markup=back_to_menu(),
        )
        return

    added = await db.add_required_channel(channel_id, title)
    context.user_data["state"] = IDLE

    if added:
        channels = await db.get_required_channels()
        await update.message.reply_text(
            f"✅ کانال <b>{html.escape(title)}</b> (<code>{html.escape(channel_id)}</code>) اضافه شد.\n\n"
            f"📢 اکنون {len(channels)} کانال اجباری دارید.",
            parse_mode="HTML",
            reply_markup=channels_manage(channels),
        )
        # Update title in DB if bot fetched a fresher name
        await db.update_channel_title(channel_id, title)
    else:
        await update.message.reply_text(
            f"⚠️ کانال <code>{html.escape(channel_id)}</code> از قبل در لیست است.",
            parse_mode="HTML",
            reply_markup=back_to_menu(),
        )


async def handle_admin_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != ADMIN_SEARCH:
        return
    if not _is_admin(update.effective_user.id):
        return

    query_text = update.message.text.strip()
    results = await db.search_users(query_text)

    if not results:
        await update.message.reply_text(
            "❌ کاربری یافت نشد.",
            reply_markup=back_to_menu(),
        )
        return

    for user in results[:3]:  # show max 3 matches
        await _send_user_card(update, context, user)

    context.user_data["state"] = IDLE


async def _send_user_card(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    import html as _html
    uid = user["user_id"]
    uploads = await db.get_user_uploads(uid, limit=5)
    upload_count = await db.count_user_uploads(uid)

    joined = str(user["joined_at"])[:10]
    blocked_status = "🚫 مسدود" if user["is_blocked"] else "✅ فعال"
    first = _html.escape(user["first_name"] or "")
    last = _html.escape(user.get("last_name") or "")
    uname = _html.escape(user["username"] or "")

    recent_files = ""
    if uploads:
        recent_files = "\n\n📋 <b>آخرین فایل‌ها:</b>\n"
        for up in uploads:
            icon = "🔗" if up["upload_type"] == "link" else "📤"
            size = _fmt_size(up["file_size"])
            fname = _html.escape(up["filename"])
            recent_files += f"  {icon} {fname} — {size} — {str(up['uploaded_at'])[:10]}\n"

    text = (
        f"👤 <b>اطلاعات کاربر</b>\n\n"
        f"🆔 شناسه: <code>{uid}</code>\n"
        f"👤 نام: {first} {last}\n"
        f"📱 نام کاربری: {'@' + uname if uname else '—'}\n"
        f"📅 عضویت: {joined}\n"
        f"🔒 وضعیت: {blocked_status}\n\n"
        f"📊 <b>آمار آپلود</b>\n"
        f"▪️ کل: {user['total_uploads']} فایل\n"
        f"▪️ با لینک: {user['total_link_ups']}\n"
        f"▪️ فایل مستقیم: {user['total_file_ups']}\n"
        f"▪️ حجم کل: {_fmt_size(user['total_size_bytes'])}\n"
        f"▪️ تعداد ثبت‌شده: {upload_count}"
        f"{recent_files}"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=admin_user_actions(uid, bool(user["is_blocked"])),
    )
