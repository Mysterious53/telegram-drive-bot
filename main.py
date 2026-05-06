"""Telegram Drive Bot — webhook-only entry point.

Requires WEBHOOK_URL in .env (https://yourdomain.com).
The bot refuses to start without a valid domain and SSL.
"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from telegram.ext import Application

from config import TELEGRAM_BOT_TOKEN, SERVER_HOST, SERVER_PORT, WEBHOOK_URL, WEBHOOK_SECRET
from database.db import init_db
from bot.handlers import register
from services.queue import UploadQueue
from oauth.server import create_router

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_bot_app: Application | None = None


async def _register_webhook():
    """Delayed webhook registration — gives uvicorn time to bind the socket."""
    await asyncio.sleep(3)
    if _bot_app is None:
        return
    wh_url = f"{WEBHOOK_URL}/webhook/{TELEGRAM_BOT_TOKEN}"
    try:
        await _bot_app.bot.set_webhook(
            url=wh_url,
            secret_token=WEBHOOK_SECRET or None,
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query", "chat_member"],
        )
        info = await _bot_app.bot.get_webhook_info()
        logger.info("Webhook active: %s  (pending: %d)", info.url[:70], info.pending_update_count)
    except Exception:
        logger.exception("Failed to register webhook — check WEBHOOK_URL and SSL certificate")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _bot_app

    if not WEBHOOK_URL:
        logger.critical(
            "WEBHOOK_URL is not set in .env — this bot requires a domain with SSL.\n"
            "Run install.sh to configure a domain automatically."
        )
        sys.exit(1)

    await init_db()
    logger.info("Database initialized")

    queue = UploadQueue()

    _bot_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .updater(None)          # No polling — updates arrive via webhook
        .build()
    )
    _bot_app.bot_data["upload_queue"] = queue

    register(_bot_app)
    await _bot_app.initialize()
    await _bot_app.start()

    asyncio.create_task(queue.start(_bot_app.bot))
    asyncio.create_task(_register_webhook())
    logger.info("Bot starting in webhook mode → %s", WEBHOOK_URL)

    yield

    logger.info("Shutting down...")
    try:
        await _bot_app.bot.delete_webhook()
    except Exception:
        pass
    await _bot_app.stop()
    await _bot_app.shutdown()


web = FastAPI(lifespan=lifespan, title="Telegram Drive Bot")
web.include_router(create_router(lambda: _bot_app))

if __name__ == "__main__":
    uvicorn.run(web, host=SERVER_HOST, port=SERVER_PORT, log_level="info")
