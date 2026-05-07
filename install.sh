#!/usr/bin/env bash
# ============================================================
#  Telegram Drive Bot — نصب‌کننده یک‌خطی برای سرورهای لینوکس
#
#  ⚠️  این ربات فقط با دامنه + SSL کار می‌کند (webhook-only)
#
#  نصب تازه:
#    curl -fsSL https://raw.githubusercontent.com/rostami36285-create/telegram-drive-bot/main/install.sh | sudo bash
#
#  به‌روزرسانی:
#    sudo bash /opt/telegram-drive-bot/install.sh
# ============================================================
#
# نکته: عمداً از set -e استفاده نمی‌کنیم — pipefail + grep/crontab
# در محیط‌های مختلف کدهای خروجی متفاوت برمی‌گردانند و باعث خروج
# زودهنگام اسکریپت می‌شوند. خطاها را صریح بررسی می‌کنیم.
#
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[•]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
die()     { echo -e "${RED}[✗] $*${NC}" >&2; exit 1; }
hr()      { echo -e "${CYAN}──────────────────────────────────────────────${NC}"; }

INSTALL_DIR="${INSTALL_DIR:-/opt/telegram-drive-bot}"
SERVICE="telegram-drive-bot"
REPO_URL="https://github.com/rostami36285-create/telegram-drive-bot.git"
BOT_USER="drivebot"

# ── Root check ────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "با sudo اجرا کنید."

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   🤖 Telegram Drive Bot — Installer          ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── تضمین دسترسی به ترمینال — حتی در curl | bash ─────────────
# وقتی اسکریپت از پایپ اجرا می‌شه stdin = لوله curl نه ترمینال
if [[ -t 0 ]]; then
    exec 3<&0
elif [[ -e /dev/tty ]]; then
    exec 3</dev/tty
else
    die "ترمینال تعاملی یافت نشد. اسکریپت را مستقیماً اجرا کنید: sudo bash install.sh"
fi

# ── شناسایی توزیع ────────────────────────────────────────────
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
else
    die "توزیع شناخته نشد."
fi
info "سیستم‌عامل: ${PRETTY_NAME:-$ID}"

# ── تابع نصب پکیج ───────────────────────────────────────────
pkg_install() {
  case "${ID:-}" in
    ubuntu|debian)
      apt-get install -y -qq "$@" >/dev/null 2>&1 || \
        apt-get install -y "$@" ;;
    centos|rhel|rocky|almalinux|fedora)
      if command -v dnf &>/dev/null; then
        dnf install -y "$@" >/dev/null 2>&1 || dnf install -y "$@"
      else
        yum install -y "$@" >/dev/null 2>&1 || yum install -y "$@"
      fi ;;
    arch)
      pacman -Sy --noconfirm "$@" >/dev/null 2>&1 || pacman -Sy --noconfirm "$@" ;;
    *)
      warn "توزیع ناشناخته — پکیج‌ها را دستی نصب کنید."
      return 0 ;;
  esac
}

# ── به‌روزرسانی امن فایل .env (بدون sed — از مشکل کاراکتر خاص جلوگیری می‌کند) ──
_env_set() {
  local key="$1" val="$2" tmp
  tmp=$(mktemp) || die "نمی‌توان فایل موقت ساخت."
  grep -v "^${key}=" "${ENV}" > "${tmp}" 2>/dev/null || true
  echo "${key}=${val}" >> "${tmp}"
  mv "${tmp}" "${ENV}"
}

# ── پیش‌نیازهای پایه ─────────────────────────────────────────
info "نصب پیش‌نیازها..."
case "${ID:-}" in ubuntu|debian) apt-get update -qq >/dev/null 2>&1 || true ;; esac
pkg_install python3 python3-pip python3-venv git curl openssl || \
  die "نصب پیش‌نیازها شکست خورد."
# ffmpeg برای ترکیب ویدیو+صدا در آپلود یوتیوب
pkg_install ffmpeg 2>/dev/null || warn "ffmpeg نصب نشد — دانلود یوتیوب ممکن است محدود باشد."
success "پیش‌نیازها نصب شد."

# ── بررسی Python 3.10+ ───────────────────────────────────────
PY=$(command -v python3) || die "Python یافت نشد."
if ! "$PY" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>/dev/null; then
  die "Python 3.10+ لازم است. نسخه فعلی: $($PY --version)"
fi
success "Python: $($PY --version)"

# ── Clone / آپدیت کد ─────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "به‌روزرسانی کد در $INSTALL_DIR ..."
  # git 2.35.2+: اگر پوشه به drivebot تعلق دارد و root اجرا می‌کند،
  # مالکیت را موقتاً به root می‌دهیم، pull می‌کنیم و برمی‌گردانیم
  chown -R root:root "$INSTALL_DIR" 2>/dev/null || true
  git -C "$INSTALL_DIR" pull --ff-only || die "آپدیت کد شکست خورد."
else
  info "دریافت کد از GitHub..."
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" || die "دانلود کد شکست خورد."
fi
success "کد آماده است."

# ── محیط مجازی + وابستگی‌ها ──────────────────────────────────
VENV="$INSTALL_DIR/venv"
info "ساخت محیط مجازی Python..."
"$PY" -m venv "$VENV" || die "ساخت venv شکست خورد."
"$VENV/bin/pip" install --upgrade pip -q || true
"$VENV/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q || \
  die "نصب وابستگی‌های Python شکست خورد."
success "وابستگی‌های Python نصب شد."

# ── فایل .env ─────────────────────────────────────────────────
ENV="$INSTALL_DIR/.env"
[[ -f "$ENV" ]] || cp "$INSTALL_DIR/.env.example" "$ENV"

# ══════════════════════════════════════════════════════════════
#  پیکربندی تعاملی — فقط در نصب اول (وقتی token هنوز placeholder است)
# ══════════════════════════════════════════════════════════════
if grep -q "your_telegram_bot_token_here" "$ENV" 2>/dev/null; then
  hr
  echo -e "${BOLD}  پیکربندی ربات (نصب اول)${NC}"
  hr

  echo -en "${BOLD}  📱 Telegram Bot Token: ${NC}"
  read -r TG_TOKEN <&3
  [[ -n "$TG_TOKEN" ]] && _env_set "TELEGRAM_BOT_TOKEN" "$TG_TOKEN"

  echo -en "${BOLD}  👤 Admin Telegram ID(s) (با کاما — از @userinfobot بگیرید): ${NC}"
  read -r ADMINS <&3
  [[ -n "$ADMINS" ]] && _env_set "ADMIN_IDS" "$ADMINS"

  echo -en "${BOLD}  📢 کانال‌های اجباری (اختیاری، مثال: @ch1,@ch2): ${NC}"
  read -r CHANNELS <&3
  [[ -n "$CHANNELS" ]] && _env_set "REQUIRED_CHANNELS" "$CHANNELS"
fi

# ── کلید رمزنگاری ────────────────────────────────────────────
if grep -q "your_fernet_key_here" "$ENV" 2>/dev/null; then
  ENC_KEY=$("$VENV/bin/python3" -c \
    "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") || \
    die "تولید کلید رمزنگاری شکست خورد."
  _env_set "ENCRYPTION_KEY" "$ENC_KEY"
  success "کلید رمزنگاری ایجاد شد."
fi

# ══════════════════════════════════════════════════════════════
#  دامنه — همیشه می‌پرسیم
# ══════════════════════════════════════════════════════════════
DOMAIN=""
_current_domain=$(grep "^WEBHOOK_URL=https://" "$ENV" 2>/dev/null \
  | sed 's|WEBHOOK_URL=https://||' || true)

hr
echo -e "${BOLD}  دامنه سرور — الزامی${NC}"
echo "  ربات فقط با HTTPS/webhook کار می‌کند."
echo "  مطمئن شوید DNS دامنه به IP این سرور اشاره می‌کند."
[[ -n "$_current_domain" ]] && \
  echo -e "  دامنه فعلی: ${CYAN}$_current_domain${NC}"
hr

while [[ -z "$DOMAIN" ]]; do
  if [[ -n "$_current_domain" ]]; then
    echo -en "${BOLD}  🌐 دامنه [Enter برای نگه‌داشتن «${_current_domain}»]: ${NC}"
    read -r _inp <&3
    DOMAIN="${_inp:-$_current_domain}"
  else
    echo -en "${BOLD}  🌐 دامنه (مثال: bot.example.com): ${NC}"
    read -r DOMAIN <&3
    [[ -z "$DOMAIN" ]] && warn "دامنه اجباری است — بدون دامنه نصب ممکن نیست."
  fi
done

info "دامنه: $DOMAIN"

# ══════════════════════════════════════════════════════════════
#  Nginx + SSL
# ══════════════════════════════════════════════════════════════
info "نصب Nginx و Certbot..."
case "${ID:-}" in
  ubuntu|debian)
    pkg_install nginx certbot python3-certbot-nginx || die "نصب Nginx/Certbot شکست خورد." ;;
  centos|rhel|rocky|almalinux|fedora)
    pkg_install epel-release nginx certbot python3-certbot-nginx || \
      die "نصب Nginx/Certbot شکست خورد." ;;
  arch)
    pkg_install nginx certbot certbot-nginx || die "نصب Nginx/Certbot شکست خورد." ;;
esac

systemctl enable nginx >/dev/null 2>&1 || true
systemctl start nginx  >/dev/null 2>&1 || true
systemctl reload nginx >/dev/null 2>&1 || true
success "Nginx راه‌اندازی شد."

rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

# ── تعیین مسیر کانفیگ Nginx ──────────────────────────────────
if [[ -d /etc/nginx/sites-available ]]; then
  NGINX_CONF="/etc/nginx/sites-available/${SERVICE}"
  NGINX_LINK="/etc/nginx/sites-enabled/${SERVICE}"
else
  NGINX_CONF="/etc/nginx/conf.d/${SERVICE}.conf"
  NGINX_LINK=""
fi

# ── کانفیگ HTTP موقت برای ACME ───────────────────────────────
cat > "$NGINX_CONF" <<NGINXEOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    root /var/www/html;
    location /.well-known/acme-challenge/ { try_files \$uri =404; }
    location / { return 301 https://\$host\$request_uri; }
}
NGINXEOF

[[ -n "$NGINX_LINK" ]] && ln -sf "$NGINX_CONF" "$NGINX_LINK" 2>/dev/null || true
nginx -t >/dev/null 2>&1 && systemctl reload nginx || \
  die "کانفیگ Nginx معتبر نیست."

# ── گواهی SSL ────────────────────────────────────────────────
info "دریافت گواهی SSL برای $DOMAIN ..."
certbot certonly \
  --nginx \
  -d "$DOMAIN" \
  --non-interactive \
  --agree-tos \
  --email "admin@${DOMAIN}" \
  2>&1 || die "دریافت SSL شکست خورد.\n  ← DNS دامنه «${DOMAIN}» باید به IP این سرور اشاره کند.\n  ← پورت 80 باید باز باشد."
success "گواهی SSL دریافت شد."

# ── کانفیگ HTTPS کامل ────────────────────────────────────────
cat > "$NGINX_CONF" <<NGINXEOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;

    client_max_body_size 0;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
        proxy_connect_timeout 10s;
    }
}
NGINXEOF

nginx -t >/dev/null 2>&1 && systemctl reload nginx || \
  die "کانفیگ HTTPS Nginx معتبر نیست."
success "Nginx با HTTPS پیکربندی شد."

# ── به‌روزرسانی .env ──────────────────────────────────────────
WH_SECRET=$(openssl rand -hex 32)
_env_set "WEBHOOK_URL"        "https://${DOMAIN}"
_env_set "WEBHOOK_SECRET"     "${WH_SECRET}"
_env_set "OAUTH_REDIRECT_URI" "https://${DOMAIN}/oauth/callback"
_env_set "SERVER_HOST"        "127.0.0.1"
success ".env با تنظیمات دامنه به‌روز شد."

# ── تمدید خودکار SSL ─────────────────────────────────────────
# certbot.timer را چک می‌کنیم — اگر نبود، cron می‌گذاریم
_certbot_timer_active=0
systemctl list-timers --all 2>/dev/null | grep -q "certbot" && _certbot_timer_active=1 || true

if [[ $_certbot_timer_active -eq 1 ]]; then
  success "تمدید خودکار SSL فعال است (certbot.timer)."
else
  # crontab -l ممکن است exit code 1 برگرداند وقتی crontab خالی است
  # پس آن را جدا اجرا می‌کنیم و نتیجه را ذخیره می‌کنیم
  _existing_cron=$(crontab -l 2>/dev/null || true)
  _new_entry="0 3 * * * certbot renew --quiet && systemctl reload nginx"
  if echo "$_existing_cron" | grep -qF "certbot renew" 2>/dev/null; then
    success "تمدید SSL از طریق cron قبلاً تنظیم شده."
  else
    printf "%s\n%s\n" "$_existing_cron" "$_new_entry" | crontab - 2>/dev/null || \
      warn "تنظیم cron برای تمدید SSL شکست خورد — دستی اضافه کنید."
    success "تمدید SSL از طریق cron تنظیم شد."
  fi
fi

mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh <<'HOOKEOF'
#!/bin/bash
systemctl reload nginx
HOOKEOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/nginx-reload.sh

# ══════════════════════════════════════════════════════════════
#  کاربر سیستمی + سرویس systemd
# ══════════════════════════════════════════════════════════════
NOLOGIN=$(command -v nologin 2>/dev/null || true)
[[ -z "$NOLOGIN" ]] && NOLOGIN=/usr/sbin/nologin
[[ -x "$NOLOGIN" ]] || NOLOGIN=/sbin/nologin

if ! id "$BOT_USER" &>/dev/null; then
  useradd --system --no-create-home --shell "$NOLOGIN" "$BOT_USER" || \
    warn "ساخت کاربر $BOT_USER شکست خورد — احتمالاً از قبل وجود دارد."
fi

chown -R "$BOT_USER:$BOT_USER" "$INSTALL_DIR" || \
  warn "تغییر مالکیت شکست خورد."
chmod 600 "$ENV" || warn "⚠️ نمی‌توان .env را محدود کرد — مجوزها را دستی بررسی کنید: chmod 600 $ENV"

cat > "/etc/systemd/system/${SERVICE}.service" <<SVCEOF
[Unit]
Description=Telegram Drive Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${BOT_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV}
ExecStart=${VENV}/bin/python main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload || die "systemctl daemon-reload شکست خورد."
systemctl enable "$SERVICE" >/dev/null 2>&1 || true
success "سرویس systemd ثبت شد."

# ══════════════════════════════════════════════════════════════
#  راه‌اندازی + ثبت Webhook
# ══════════════════════════════════════════════════════════════
TG_TOKEN_LIVE=$(grep "^TELEGRAM_BOT_TOKEN=" "$ENV" 2>/dev/null | cut -d'=' -f2- || true)

if [[ -z "$TG_TOKEN_LIVE" ]] || \
   echo "$TG_TOKEN_LIVE" | grep -q "your_telegram_bot_token_here" 2>/dev/null; then
  warn "Telegram Token هنوز تنظیم نشده — سرویس شروع نمی‌شود."
  warn "  → sudo nano $ENV"
  warn "  → sudo systemctl start $SERVICE"
else
  systemctl restart "$SERVICE" || warn "ری‌استارت سرویس شکست خورد."
  info "سرویس ربات راه‌اندازی شد — منتظر آماده شدن (حداکثر ۶۰ ثانیه)..."

  READY=0
  for _i in $(seq 1 30); do
    if curl -sf --connect-timeout 2 "http://127.0.0.1:8080/health" >/dev/null 2>&1; then
      READY=1
      break
    fi
    printf "."
    sleep 2
  done
  echo ""

  if [[ $READY -eq 1 ]]; then
    success "ربات فعال و پاسخگوست ✓"

    info "ثبت Webhook در تلگرام..."
    # secret_token از یک فایل موقت خوانده می‌شود تا در ps aux نمایش داده نشود
    _wh_tmp=$(mktemp)
    printf '%s' "url=https://${DOMAIN}/webhook/${TG_TOKEN_LIVE}&drop_pending_updates=true&secret_token=${WH_SECRET}&allowed_updates=%5B%22message%22%2C%22callback_query%22%2C%22chat_member%22%5D" > "${_wh_tmp}"
    WH_RESULT=$(curl -sf --connect-timeout 15 \
      "https://api.telegram.org/bot${TG_TOKEN_LIVE}/setWebhook" \
      --data "@${_wh_tmp}" \
      2>&1 || echo '{"ok":false,"description":"curl error"}')
    rm -f "${_wh_tmp}"

    if echo "$WH_RESULT" | grep -q '"ok":true' 2>/dev/null; then
      success "Webhook تلگرام ثبت شد ✓"
    else
      warn "ثبت webhook: $WH_RESULT"
      warn "برای ثبت دستی:"
      warn "  curl -s 'https://api.telegram.org/bot${TG_TOKEN_LIVE}/setWebhook' \\"
      warn "    --data-urlencode 'url=https://${DOMAIN}/webhook/${TG_TOKEN_LIVE}'"
    fi
  else
    warn "ربات در ۶۰ ثانیه آماده نشد. لاگ:"
    warn "  sudo journalctl -u $SERVICE -n 30 --no-pager"
    warn ""
    warn "پس از راه‌اندازی ربات، webhook را دستی ثبت کنید:"
    warn "  curl -s 'https://api.telegram.org/bot${TG_TOKEN_LIVE}/setWebhook?url=https://${DOMAIN}/webhook/${TG_TOKEN_LIVE}'"
  fi
fi

# ══════════════════════════════════════════════════════════════
#  خلاصه نهایی
# ══════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ نصب با موفقیت انجام شد!                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
printf "  %-28s %s\n" "مسیر نصب:"      "$INSTALL_DIR"
printf "  %-28s %s\n" "فایل تنظیمات:" "$ENV"
printf "  %-28s %s\n" "آدرس:"          "https://${DOMAIN}"
echo ""
echo -e "  ${YELLOW}⚠️  مرحله باقی‌مانده — Google Drive API:${NC}"
echo ""
echo "  ۱. https://console.cloud.google.com → پروژه جدید"
echo "  ۲. APIs & Services → Google Drive API → Enable"
echo "  ۳. Credentials → OAuth 2.0 Client ID (Web application)"
echo -e "  ۴. Redirect URI: ${CYAN}https://${DOMAIN}/oauth/callback${NC}"
echo "  ۵. در ربات:"
echo -e "     ${CYAN}/admin → ⚙️ تنظیمات OAuth گوگل${NC}"
echo ""
hr
echo "  دستورات مدیریت:"
echo -e "  ${CYAN}sudo systemctl restart $SERVICE${NC}"
echo -e "  ${CYAN}sudo journalctl -u $SERVICE -f${NC}"
echo -e "  ${CYAN}curl https://${DOMAIN}/health${NC}"
echo -e "  ${CYAN}sudo bash $INSTALL_DIR/install.sh${NC}  ← به‌روزرسانی"
echo ""