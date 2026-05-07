from __future__ import annotations

import asyncio
from functools import partial

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

import database.db as db
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, OAUTH_REDIRECT_URI

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


async def _get_client_config() -> dict:
    """Load client credentials from DB first, fall back to .env (ignoring placeholders)."""
    db_id = await db.get_app_setting("google_client_id", encrypted=True)
    db_secret = await db.get_app_setting("google_client_secret", encrypted=True)
    client_id = (db_id if _is_real(db_id) else None) or (GOOGLE_CLIENT_ID if _is_real(GOOGLE_CLIENT_ID) else "")
    client_secret = (db_secret if _is_real(db_secret) else None) or (GOOGLE_CLIENT_SECRET if _is_real(GOOGLE_CLIENT_SECRET) else "")
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [OAUTH_REDIRECT_URI],
        }
    }


_PLACEHOLDERS = {
    "your_client_id.apps.googleusercontent.com",
    "your_client_secret",
    "your_client_id",
    "",
}


def _is_real(val: str | None) -> bool:
    return bool(val) and val.strip() not in _PLACEHOLDERS


async def has_oauth_config() -> bool:
    """True if real (non-placeholder) client_id and client_secret are available."""
    client_id = await db.get_app_setting("google_client_id", encrypted=True) or GOOGLE_CLIENT_ID
    client_secret = await db.get_app_setting("google_client_secret", encrypted=True) or GOOGLE_CLIENT_SECRET
    return _is_real(client_id) and _is_real(client_secret)


def _make_flow(config: dict) -> Flow:
    return Flow.from_client_config(config, scopes=SCOPES, redirect_uri=OAUTH_REDIRECT_URI)


async def get_auth_url(state: str) -> str:
    config = await _get_client_config()
    loop = asyncio.get_running_loop()
    flow = await loop.run_in_executor(None, partial(_make_flow, config))
    url, _ = flow.authorization_url(access_type="offline", state=state, prompt="consent")
    return url


async def exchange_code(code: str) -> dict:
    config = await _get_client_config()
    loop = asyncio.get_running_loop()
    flow = await loop.run_in_executor(None, partial(_make_flow, config))

    def _fetch(f: Flow) -> Flow:
        f.fetch_token(code=code)
        return f

    flow = await loop.run_in_executor(None, _fetch, flow)
    return _to_dict(flow.credentials)


_ALLOWED_TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_credentials(tokens: dict) -> Credentials:
    if tokens.get("token_uri") != _ALLOWED_TOKEN_URI:
        raise ValueError("token_uri نامعتبر است.")
    creds = Credentials(
        token=tokens["token"],
        refresh_token=tokens["refresh_token"],
        token_uri=_ALLOWED_TOKEN_URI,
        client_id=tokens["client_id"],
        client_secret=tokens["client_secret"],
        scopes=tokens["scopes"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _to_dict(creds: Credentials) -> dict:
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }


def creds_to_dict(creds: Credentials) -> dict:
    return _to_dict(creds)
