from __future__ import annotations

import aiosqlite
from datetime import date
from typing import Optional

from config import DATABASE_PATH, REQUIRED_CHANNELS
from database.encryption import encrypt, decrypt, encrypt_str, decrypt_str


# ── Schema ────────────────────────────────────────────────────

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id           INTEGER PRIMARY KEY,
                username          TEXT,
                first_name        TEXT,
                last_name         TEXT,
                joined_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked        INTEGER   DEFAULT 0,
                total_uploads     INTEGER   DEFAULT 0,
                total_link_ups    INTEGER   DEFAULT 0,
                total_file_ups    INTEGER   DEFAULT 0,
                total_size_bytes  INTEGER   DEFAULT 0,
                daily_uploads     INTEGER   DEFAULT 0,
                daily_reset_date  DATE      DEFAULT (date('now'))
            );

            CREATE TABLE IF NOT EXISTS oauth_tokens (
                user_id           INTEGER PRIMARY KEY,
                encrypted_tokens  TEXT      NOT NULL,
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS uploads (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           INTEGER   NOT NULL,
                filename          TEXT      NOT NULL,
                file_size         INTEGER   DEFAULT 0,
                upload_type       TEXT      NOT NULL,
                drive_file_id     TEXT,
                drive_view_link   TEXT,
                drive_dl_link     TEXT,
                uploaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS oauth_states (
                state       TEXT      PRIMARY KEY,
                user_id     INTEGER   NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS required_channels (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id  TEXT    NOT NULL UNIQUE,
                title       TEXT    DEFAULT '',
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tutorial_media (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id       TEXT    NOT NULL,
                file_type     TEXT    NOT NULL,
                caption       TEXT    DEFAULT '',
                display_order INTEGER DEFAULT 0,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS software_files (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                platform      TEXT    NOT NULL,
                file_id       TEXT    NOT NULL,
                file_type     TEXT    NOT NULL,
                name          TEXT    NOT NULL DEFAULT '',
                filename      TEXT    DEFAULT '',
                caption       TEXT    DEFAULT '',
                display_order INTEGER DEFAULT 0,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Purge stale OAuth states
        await db.execute("DELETE FROM oauth_states WHERE created_at < datetime('now', '-15 minutes')")

        # Seed required_channels from config if the table is empty
        async with db.execute("SELECT COUNT(*) FROM required_channels") as cur:
            if (await cur.fetchone())[0] == 0 and REQUIRED_CHANNELS:
                for ch in REQUIRED_CHANNELS:
                    await db.execute(
                        "INSERT OR IGNORE INTO required_channels (channel_id) VALUES (?)", (ch,)
                    )

        await db.commit()


# ── Users ─────────────────────────────────────────────────────

async def get_or_create_user(user_id: int, username: str, first_name: str, last_name: str = "") -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()

        if row:
            await db.execute(
                "UPDATE users SET username=?, first_name=?, last_name=? WHERE user_id=?",
                (username, first_name, last_name, user_id),
            )
            await db.commit()
            return dict(row)

        await db.execute(
            "INSERT INTO users (user_id, username, first_name, last_name) VALUES (?,?,?,?)",
            (user_id, username, first_name, last_name),
        )
        await db.commit()
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            return dict(await cur.fetchone())


async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def is_blocked(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and user["is_blocked"])


async def set_blocked(user_id: int, blocked: bool):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET is_blocked=? WHERE user_id=?",
            (1 if blocked else 0, user_id),
        )
        await db.commit()


async def search_users(query: str) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        if query.lstrip("-").isdigit():
            async with db.execute("SELECT * FROM users WHERE user_id=?", (int(query),)) as cur:
                rows = await cur.fetchall()
        else:
            q = f"%{query.lstrip('@')}%"
            async with db.execute(
                "SELECT * FROM users WHERE username LIKE ? OR first_name LIKE ? LIMIT 10",
                (q, q),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_total_users() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            return (await cur.fetchone())[0]


# ── Daily upload limit ────────────────────────────────────────

async def check_daily_limit(user_id: int, limit: int) -> tuple[bool, int]:
    """Returns (can_upload, uploads_used_today)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT daily_uploads, daily_reset_date FROM users WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return False, 0

        today = date.today().isoformat()
        used = row["daily_uploads"]

        if row["daily_reset_date"] != today:
            used = 0
            await db.execute(
                "UPDATE users SET daily_uploads=0, daily_reset_date=? WHERE user_id=?",
                (today, user_id),
            )
            await db.commit()

        return used < limit, used


async def increment_daily(user_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE users SET daily_uploads=daily_uploads+1 WHERE user_id=?", (user_id,)
        )
        await db.commit()


# ── Upload records ────────────────────────────────────────────

async def record_upload(
    user_id: int,
    filename: str,
    file_size: int,
    upload_type: str,
    drive_file_id: str,
    drive_view_link: str,
    drive_dl_link: str,
):
    col = "total_link_ups" if upload_type == "link" else "total_file_ups"
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO uploads
               (user_id, filename, file_size, upload_type, drive_file_id, drive_view_link, drive_dl_link)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, filename, file_size, upload_type, drive_file_id, drive_view_link, drive_dl_link),
        )
        await db.execute(
            f"""UPDATE users SET
                total_uploads=total_uploads+1,
                {col}={col}+1,
                total_size_bytes=total_size_bytes+?
               WHERE user_id=?""",
            (file_size, user_id),
        )
        await db.commit()


async def get_user_uploads(user_id: int, limit: int = 10, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM uploads WHERE user_id=? ORDER BY uploaded_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def count_user_uploads(user_id: int) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM uploads WHERE user_id=?", (user_id,)) as cur:
            return (await cur.fetchone())[0]


# ── OAuth tokens (encrypted) ──────────────────────────────────

async def save_tokens(user_id: int, tokens: dict):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO oauth_tokens (user_id, encrypted_tokens, updated_at)
               VALUES (?,?,CURRENT_TIMESTAMP)""",
            (user_id, encrypt(tokens)),
        )
        await db.commit()


async def get_tokens(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT encrypted_tokens FROM oauth_tokens WHERE user_id=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return decrypt(row[0]) if row else None


async def delete_tokens(user_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM oauth_tokens WHERE user_id=?", (user_id,))
        await db.commit()


async def has_tokens(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM oauth_tokens WHERE user_id=?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None


# ── OAuth states ──────────────────────────────────────────────

async def save_oauth_state(state: str, user_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO oauth_states (state, user_id) VALUES (?,?)", (state, user_id)
        )
        await db.commit()


async def pop_oauth_state(state: str) -> Optional[int]:
    """Returns user_id and deletes the state atomically (EXCLUSIVE lock to prevent TOCTOU)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("BEGIN EXCLUSIVE")
        async with db.execute(
            "SELECT user_id FROM oauth_states WHERE state=?", (state,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            await db.execute("ROLLBACK")
            return None
        await db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
        await db.commit()
        return row[0]


# ── Required channels ─────────────────────────────────────────

async def get_required_channels() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM required_channels ORDER BY added_at"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def add_required_channel(channel_id: str, title: str = "") -> bool:
    """Returns False if channel already exists."""
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO required_channels (channel_id, title) VALUES (?, ?)",
                (channel_id, title),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def update_channel_title(channel_id: str, title: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE required_channels SET title=? WHERE channel_id=?",
            (title, channel_id),
        )
        await db.commit()


async def get_all_users(limit: int = 15, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_upload_by_id(upload_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def delete_upload_record(upload_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, file_size, upload_type FROM uploads WHERE id=?", (upload_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return
        col = "total_link_ups" if row["upload_type"] == "link" else "total_file_ups"
        await db.execute(
            f"UPDATE users SET "
            f"total_uploads=MAX(0,total_uploads-1), "
            f"{col}=MAX(0,{col}-1), "
            f"total_size_bytes=MAX(0,total_size_bytes-?) "
            f"WHERE user_id=?",
            (row["file_size"], row["user_id"]),
        )
        await db.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
        await db.commit()


async def remove_required_channel(channel_id: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "DELETE FROM required_channels WHERE channel_id=?", (channel_id,)
        )
        await db.commit()


# ── App settings (encrypted for sensitive keys) ───────────────

async def get_app_setting(key: str, *, encrypted: bool = False) -> Optional[str]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT value FROM app_settings WHERE key=?", (key,)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return decrypt_str(row[0]) if encrypted else row[0]


async def set_app_setting(key: str, value: str, *, encrypted: bool = False):
    stored = encrypt_str(value) if encrypted else value
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO app_settings (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (key, stored),
        )
        await db.commit()


async def delete_app_setting(key: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM app_settings WHERE key=?", (key,))
        await db.commit()


# ── Tutorial media ────────────────────────────────────────────

async def add_tutorial_media(file_id: str, file_type: str, caption: str = "") -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COALESCE(MAX(display_order),0)+1 FROM tutorial_media") as cur:
            order = (await cur.fetchone())[0]
        cur2 = await db.execute(
            "INSERT INTO tutorial_media (file_id, file_type, caption, display_order) VALUES (?,?,?,?)",
            (file_id, file_type, caption, order),
        )
        await db.commit()
        return cur2.lastrowid


async def get_tutorial_media() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tutorial_media ORDER BY display_order") as cur:
            return [dict(r) for r in await cur.fetchall()]


async def count_tutorial_media() -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM tutorial_media") as cur:
            return (await cur.fetchone())[0]


async def delete_tutorial_media(item_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM tutorial_media WHERE id=?", (item_id,))
        await db.commit()


# ── Software files ────────────────────────────────────────────

async def add_software_file(
    platform: str, file_id: str, file_type: str,
    name: str, filename: str = "", caption: str = "",
) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute(
            "SELECT COALESCE(MAX(display_order),0)+1 FROM software_files WHERE platform=?", (platform,)
        ) as cur:
            order = (await cur.fetchone())[0]
        cur2 = await db.execute(
            """INSERT INTO software_files
               (platform, file_id, file_type, name, filename, caption, display_order)
               VALUES (?,?,?,?,?,?,?)""",
            (platform, file_id, file_type, name, filename, caption, order),
        )
        await db.commit()
        return cur2.lastrowid


async def get_software_files(platform: str) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM software_files WHERE platform=? ORDER BY display_order", (platform,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_software_file(file_db_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM software_files WHERE id=?", (file_db_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def delete_software_file(file_db_id: int):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM software_files WHERE id=?", (file_db_id,))
        await db.commit()
