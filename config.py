import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
# Comma-separated channel usernames or IDs, e.g. "@mychannel,-1001234567890"
REQUIRED_CHANNELS = [x.strip() for x in os.getenv("REQUIRED_CHANNELS", "").split(",") if x.strip()]

# ── Google OAuth ──────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8080/oauth/callback")

# ── Database ──────────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
# Generate with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

# ── Upload limits ─────────────────────────────────────────────
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "4096"))         # 4 GB
PUBLIC_DRIVE_MAX_MB = int(os.getenv("PUBLIC_DRIVE_MAX_MB", "1024"))   # 1 GB cap for public drives
DAILY_UPLOAD_LIMIT = int(os.getenv("DAILY_UPLOAD_LIMIT", "5"))
MAX_CONCURRENT_UPLOADS = int(os.getenv("MAX_CONCURRENT_UPLOADS", "3"))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "50"))

# ── Anti-spam ─────────────────────────────────────────────────
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "5"))   # max requests
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "10"))       # per N seconds

# ── Webhook (set by install.sh when a domain is configured) ──
# Leave empty to use polling mode (development / no domain)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")           # e.g. https://example.com
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")     # random hex, auto-generated

# ── Web server (OAuth callback + webhook receiver) ────────────
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")  # behind Nginx: bind only loopback
SERVER_PORT = int(os.getenv("SERVER_PORT", "8080"))
