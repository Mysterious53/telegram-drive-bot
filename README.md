# Telegram Drive Bot

ربات تلگرامی برای آپلود فایل به **گوگل درایو شخصی** هر کاربر.
هر کاربر با حساب Google خودش وارد می‌شود — هیچ فایلی روی سرور ذخیره نمی‌ماند.

---

## قابلیت‌ها

| | ویژگی | توضیح |
|---|---|---|
| 📤 | آپلود فایل | ارسال هر نوع فایل، عکس، ویدیو یا صدا مستقیم به Drive |
| 🔗 | آپلود با لینک | دادن URL → دانلود و آپلود خودکار |
| 🎬 | آپلود یوتیوب | انتخاب کیفیت (4K تا 144p یا فقط صدا) |
| ☁️ | درایو شخصی | هر کاربر به حساب Google خودش متصل می‌شود |
| 📁 | مدیریت فایل‌ها | مشاهده، باز کردن و حذف فایل‌های آپلودشده |
| 📊 | فضای درایو | مصرف و ظرفیت کل نمایش داده می‌شود |
| 📈 | نوار پیشرفت | درصد دانلود و آپلود لحظه‌به‌لحظه |
| ❌ | لغو آپلود | لغو عملیات در حال انجام |
| 📋 | صف آپلود | چند آپلود همزمان با مدیریت صف |
| 🔒 | قفل آپلود | در حین آپلود، دستورات دیگر بلاک می‌شوند |
| 📢 | کانال اجباری | محدود کردن دسترسی به اعضای کانال خاص |
| 🚦 | ضد اسپم | محدودیت درخواست و سقف روزانه آپلود |
| 📚 | آموزش | ادمین محتوای آموزشی آپلود می‌کند، کاربران مشاهده می‌کنند |
| 💾 | دانلود نرم‌افزار | ادمین فایل‌ها را برای هر OS آپلود می‌کند |
| 🛡 | پنل ادمین | مدیریت کاربران، کانال‌ها، OAuth، آموزش و نرم‌افزار |

---

## پیش‌نیازها

- سرور لینوکسی (Ubuntu 20.04+ / Debian 11+ / CentOS 8+)
- یک **دامنه** که DNS آن به IP سرور اشاره کند
- Python 3.10+
- حساب Google Cloud با Drive API فعال

---

## نصب سریع

```bash
curl -fsSL https://raw.githubusercontent.com/Mysterious53/telegram-drive-bot/main/install.sh | sudo bash
```

اسکریپت به‌صورت تعاملی می‌پرسد:
1. **Bot Token** — از [@BotFather](https://t.me/BotFather) بگیرید
2. **Admin ID** — از [@userinfobot](https://t.me/userinfobot) بگیرید
3. **دامنه** — مثال: `bot.example.com`

سپس به‌صورت خودکار:
- Python venv و وابستگی‌ها نصب می‌شود
- Nginx پیکربندی می‌شود
- SSL رایگان از Let's Encrypt دریافت می‌شود
- Webhook تلگرام ثبت می‌شود
- سرویس systemd ساخته و فعال می‌شود

---

## تنظیم Google Drive API

بعد از نصب، برای فعال‌سازی آپلود:

**۱. ساخت پروژه در Google Cloud**

1. به [console.cloud.google.com](https://console.cloud.google.com) بروید
2. پروژه جدید بسازید
3. **APIs & Services → Library** → `Google Drive API` → **Enable**

**۲. ساخت OAuth Credentials**

1. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
2. نوع: **Web application**
3. در **Authorized redirect URIs** اضافه کنید:
   ```
   https://YOUR_DOMAIN/oauth/callback
   ```
4. **Client ID** و **Client Secret** را کپی کنید

**۳. وارد کردن در پنل ادمین**

```
/admin → ⚙️ تنظیمات OAuth گوگل → تنظیم Client ID → تنظیم Client Secret → 🧪 تست اتصال
```

> **نکته:** اگر اپ هنوز تأیید نشده (Unverified)، در **OAuth consent screen → Test users** ایمیل کاربران را اضافه کنید.

---

## پنل ادمین

دستور `/admin` پنل مدیریت را باز می‌کند:

| گزینه | توضیح |
|---|---|
| 🔍 جستجوی کاربر | جستجو با ID یا یوزرنیم |
| 👥 لیست کاربران | نمایش همه کاربران با صفحه‌بندی |
| 📢 مدیریت کانال‌ها | اضافه/حذف کانال اجباری |
| ⚙️ تنظیمات OAuth | تنظیم و تست Google Credentials |
| 📚 مدیریت آموزش | آپلود محتوای آموزشی (عکس، ویدیو، فایل) |
| 📥 مدیریت نرم‌افزار | آپلود نرم‌افزار برای هر سیستم‌عامل |
| 📊 آمار کلی | تعداد کاربران ثبت‌شده |

### مدیریت آموزش

ادمین می‌تواند عکس، ویدیو، انیمیشن یا هر فایلی را به عنوان محتوای آموزشی آپلود کند.
کاربران با زدن دکمه **«📚 آموزش استفاده»** همه محتواها را به ترتیب دریافت می‌کنند.

### مدیریت نرم‌افزار

ادمین برای هر سیستم‌عامل فایل آپلود می‌کند (کپشن = نام نمایشی):

| | | |
|---|---|---|
| 🤖 اندروید | 📱 iOS | 🪟 ویندوز |
| 🍎 مک | 🐧 لینوکس | |

کاربران با زدن **«📥 دانلود نرم‌افزار»** سیستم‌عامل خود را انتخاب کرده و فایل‌ها را دریافت می‌کنند.

---

## دستورات

| دستور | توضیح |
|---|---|
| `/start` | شروع و منوی اصلی |
| `/admin` | پنل مدیریت (فقط ادمین) |

---

## به‌روزرسانی

```bash
sudo bash /opt/telegram-drive-bot/install.sh
```

---

## مدیریت سرویس

```bash
# وضعیت
sudo systemctl status telegram-drive-bot

# ری‌استارت
sudo systemctl restart telegram-drive-bot

# لاگ زنده
sudo journalctl -u telegram-drive-bot -f

# بررسی سلامت
curl https://YOUR_DOMAIN/health

# تست تمدید SSL
certbot renew --dry-run
```

---

## ساختار پروژه

```
telegram-drive-bot/
├── main.py                  # نقطه ورود — FastAPI + webhook
├── config.py                # تنظیمات از .env
├── install.sh               # نصب‌کننده خودکار
├── requirements.txt
├── bot/
│   ├── handlers/
│   │   ├── __init__.py      # ثبت handlers و routing
│   │   ├── start.py         # /start و بررسی عضویت کانال
│   │   ├── upload.py        # آپلود فایل و لینک (با یوتیوب)
│   │   ├── files.py         # مدیریت فایل‌های آپلودشده
│   │   ├── account.py       # حساب کاربری و قطع Drive
│   │   ├── admin.py         # پنل ادمین
│   │   ├── tutorial.py      # مدیریت آموزش
│   │   └── software.py      # مدیریت نرم‌افزار
│   ├── keyboards.py         # کیبردهای inline
│   ├── states.py            # وضعیت‌های مکالمه
│   └── rate_limiter.py      # ضد اسپم
├── database/
│   ├── db.py                # عملیات SQLite
│   └── encryption.py        # رمزنگاری Fernet
├── services/
│   ├── auth.py              # Google OAuth
│   ├── drive.py             # آپلود/دانلود/حذف Drive + یوتیوب
│   └── queue.py             # صف آپلود
└── oauth/
    └── server.py            # روت‌های FastAPI (webhook + OAuth callback)
```

---

## امنیت

- توکن‌های Google OAuth هر کاربر با **Fernet** رمزنگاری می‌شوند
- Webhook با `X-Telegram-Bot-Api-Secret-Token` تأیید می‌شود
- سرور روی `127.0.0.1` باند است — فقط Nginx دسترسی دارد
- HSTS و TLS 1.2/1.3 فعال است
- دانلود URL ها از نظر SSRF (IP داخلی) بررسی می‌شوند
- ورودی‌های کاربر در HTML با `html.escape` فیلتر می‌شوند

---

## لایسنس

MIT License