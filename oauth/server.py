from __future__ import annotations

import html as _html
import logging
from typing import Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from telegram import Update
from telegram.ext import Application

import database.db as db
from services.auth import exchange_code
from config import TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET

logger = logging.getLogger(__name__)

_OK = """<!doctype html><html dir="rtl" lang="fa">
<head><meta charset="utf-8"><title>اتصال موفق</title>
<style>body{font-family:Tahoma,Arial,sans-serif;display:flex;align-items:center;
justify-content:center;height:100vh;margin:0;background:#f0f4f8}
.card{background:#fff;border-radius:14px;padding:40px 60px;text-align:center;
box-shadow:0 4px 24px rgba(0,0,0,.12)}h1{color:#22c55e}p{color:#555}</style>
</head><body><div class="card"><h1>✅ اتصال موفق!</h1>
<p>حساب گوگل شما با موفقیت متصل شد.</p>
<p>به تلگرام برگردید و شروع کنید.</p></div></body></html>"""

_ERR = """<!doctype html><html dir="rtl" lang="fa">
<head><meta charset="utf-8"><title>خطا</title></head>
<body dir="rtl" style="font-family:Tahoma;text-align:center;padding:50px">
<h1>❌ خطا</h1><p>{msg}</p></body></html>"""


def create_router(get_app: Callable[[], Application | None]) -> APIRouter:
    router = APIRouter()

    # ── Telegram webhook receiver ─────────────────────────────
    @router.post(f"/webhook/{TELEGRAM_BOT_TOKEN}")
    async def telegram_webhook(request: Request):
        # Verify secret token sent by Telegram
        if WEBHOOK_SECRET:
            incoming = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if incoming != WEBHOOK_SECRET:
                logger.warning("Webhook: invalid secret token from %s", request.client)
                return Response(status_code=403)

        app = get_app()
        if app is None:
            return Response(status_code=503)

        try:
            data = await request.json()
            update = Update.de_json(data, app.bot)
            # Put in PTB's update queue — dispatcher processes it async.
            # Never await process_update() directly: it blocks the HTTP response
            # and Telegram retries after a timeout, causing duplicate updates.
            await app.update_queue.put(update)
        except Exception:
            logger.exception("Error processing webhook update")
        return Response(status_code=200)

    # ── Google OAuth callback ─────────────────────────────────
    @router.get("/oauth/callback")
    async def oauth_callback(request: Request):
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            return HTMLResponse(_ERR.format(msg=_html.escape(str(error))), status_code=400)
        if not code or not state:
            return HTMLResponse(_ERR.format(msg="پارامترهای نامعتبر."), status_code=400)

        result = await db.pop_oauth_state(state)
        if not result:
            return HTMLResponse(
                _ERR.format(msg="Session منقضی شده. دوباره از ربات شروع کنید."),
                status_code=400,
            )
        user_id, extra_json = result

        try:
            tokens = await exchange_code(code)
        except Exception as e:
            logger.exception("Token exchange failed")
            return HTMLResponse(_ERR.format(msg=_html.escape(str(e))), status_code=500)

        # Check if this OAuth is for a public drive (admin connecting a shared account)
        is_public_drive = False
        pub_label = ""
        if extra_json:
            import json as _json
            try:
                extra = _json.loads(extra_json)
                is_public_drive = extra.get("is_public_drive", False)
                pub_label = extra.get("label", "")
            except Exception:
                pass

        app = get_app()
        if is_public_drive:
            await db.add_public_drive(pub_label, tokens)
            if app:
                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"✅ <b>درایو عمومی «{_html.escape(pub_label)}» متصل شد!</b>\n\n"
                            "کاربران بدون درایو شخصی می‌توانند از این درایو استفاده کنند."
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.warning("Could not notify admin %s", user_id)
        else:
            await db.save_tokens(user_id, tokens)
            if app:
                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text="✅ <b>اتصال به گوگل درایو موفق!</b>\n\nحالا می‌توانید فایل‌هایتان را آپلود کنید.",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.warning("Could not notify user %s", user_id)

        return HTMLResponse(_OK)

    # ── Health check ──────────────────────────────────────────
    @router.get("/health")
    async def health():
        return {"status": "ok"}

    return router
