from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup


def main_menu() -> Markup:
    return Markup([
        [Btn("👤 حساب کاربری من", callback_data="account")],
        [
            Btn("🔗 آپلود با لینک", callback_data="upload_link"),
            Btn("📤 آپلود فایل", callback_data="upload_file"),
        ],
        [Btn("📁 مدیریت فایل‌های آپلود‌شده", callback_data="files:0")],
    ])


def check_membership(channels: list[dict]) -> Markup:
    """channels: list of {"title": str, "url": str}"""
    buttons = [[Btn(f"📢 {ch['title']}", url=ch["url"])] for ch in channels]
    buttons.append([Btn("✅ عضو شدم، بررسی کن", callback_data="check_join")])
    return Markup(buttons)


def back_to_menu() -> Markup:
    return Markup([[Btn("🏠 منوی اصلی", callback_data="main_menu")]])


def cancel_and_menu() -> Markup:
    return Markup([[Btn("❌ انصراف", callback_data="main_menu")]])


def account_menu(has_drive: bool) -> Markup:
    rows = []
    if has_drive:
        rows.append([Btn("🔌 قطع اتصال گوگل درایو", callback_data="disconnect_drive")])
    rows.append([Btn("🏠 منوی اصلی", callback_data="main_menu")])
    return Markup(rows)


def files_nav(offset: int, total: int, page_size: int = 10) -> Markup:
    rows = []
    nav = []
    if offset > 0:
        nav.append(Btn("◀️ قبلی", callback_data=f"files:{offset - page_size}"))
    if offset + page_size < total:
        nav.append(Btn("▶️ بعدی", callback_data=f"files:{offset + page_size}"))
    if nav:
        rows.append(nav)
    rows.append([Btn("🏠 منوی اصلی", callback_data="main_menu")])
    return Markup(rows)


def files_manage_kb(uploads: list[dict], offset: int, total: int, page_size: int = 5) -> Markup:
    """File list with delete buttons per file + pagination."""
    rows = []
    for up in uploads:
        fname = up["filename"]
        label = (fname[:28] + "…") if len(fname) > 28 else fname
        rows.append([Btn(f"🗑 {label}", callback_data=f"file:del:{up['id']}")])
    nav = []
    if offset > 0:
        nav.append(Btn("◀️ قبلی", callback_data=f"files:{offset - page_size}"))
    if offset + page_size < total:
        nav.append(Btn("▶️ بعدی", callback_data=f"files:{offset + page_size}"))
    if nav:
        rows.append(nav)
    rows.append([Btn("🏠 منوی اصلی", callback_data="main_menu")])
    return Markup(rows)


def admin_users_kb(offset: int, total: int, page_size: int = 15) -> Markup:
    rows = []
    nav = []
    if offset > 0:
        nav.append(Btn("◀️ قبلی", callback_data=f"admin:users:{offset - page_size}"))
    if offset + page_size < total:
        nav.append(Btn("▶️ بعدی", callback_data=f"admin:users:{offset + page_size}"))
    if nav:
        rows.append(nav)
    rows.append([Btn("🔙 بازگشت به پنل ادمین", callback_data="admin:menu")])
    return Markup(rows)


def admin_menu() -> Markup:
    return Markup([
        [Btn("🔍 جستجوی کاربر", callback_data="admin:search")],
        [Btn("👥 لیست کاربران", callback_data="admin:users:0")],
        [Btn("📢 مدیریت کانال‌های اجباری", callback_data="admin:channels")],
        [Btn("⚙️ تنظیمات OAuth گوگل", callback_data="admin:oauth")],
        [Btn("📊 آمار کلی", callback_data="admin:stats")],
        [Btn("🏠 منوی اصلی", callback_data="main_menu")],
    ])


def oauth_settings_menu(has_id: bool, has_secret: bool) -> Markup:
    id_label = "✅ Client ID تنظیم‌شده" if has_id else "➕ تنظیم Client ID"
    secret_label = "✅ Client Secret تنظیم‌شده" if has_secret else "➕ تنظیم Client Secret"
    rows = [
        [Btn(id_label, callback_data="admin:oauth_set_id")],
        [Btn(secret_label, callback_data="admin:oauth_set_secret")],
    ]
    if has_id and has_secret:
        rows.append([Btn("🧪 تست اتصال", callback_data="admin:oauth_test")])
    if has_id or has_secret:
        rows.append([Btn("🗑 حذف اعتبارنامه‌ها", callback_data="admin:oauth_clear")])
    rows.append([Btn("🔙 بازگشت به پنل ادمین", callback_data="admin:menu")])
    return Markup(rows)


def channels_manage(channels: list[dict]) -> Markup:
    """List of required channels with remove buttons + add button."""
    rows = []
    for ch in channels:
        label = ch["title"] or ch["channel_id"]
        rows.append([Btn(f"❌ {label}", callback_data=f"admin:rmchan:{ch['channel_id']}")])
    rows.append([Btn("➕ افزودن کانال جدید", callback_data="admin:addchan")])
    rows.append([Btn("🔙 بازگشت به پنل ادمین", callback_data="admin:menu")])
    return Markup(rows)


def admin_user_actions(user_id: int, is_blocked: bool) -> Markup:
    block_label = "✅ رفع مسدودیت" if is_blocked else "🚫 مسدود کردن"
    block_cb = f"admin:unblock:{user_id}" if is_blocked else f"admin:block:{user_id}"
    return Markup([
        [Btn(block_label, callback_data=block_cb)],
        [Btn("🔙 جستجوی دیگر", callback_data="admin:search")],
        [Btn("🏠 منوی اصلی", callback_data="main_menu")],
    ])


def quality_kb(qualities: list[dict]) -> Markup:
    """Inline buttons for YouTube quality selection."""
    rows = [[Btn(q["label"], callback_data=f"yt_q:{i}")] for i, q in enumerate(qualities)]
    rows.append([Btn("❌ انصراف", callback_data="main_menu")])
    return Markup(rows)


def connect_drive(auth_url: str) -> Markup:
    return Markup([
        [Btn("🔗 اتصال به گوگل درایو", url=auth_url)],
        [Btn("❌ انصراف", callback_data="main_menu")],
    ])
