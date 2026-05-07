import base64
import hashlib
import json
from cryptography.fernet import Fernet
from config import ENCRYPTION_KEY


def _cipher() -> Fernet:
    if not ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY در فایل .env تنظیم نشده است.")
    # اگر key از قبل یک Fernet key معتبر (44 کاراکتر base64-url) باشد، مستقیم استفاده کن.
    # در غیر این صورت از SHA-256 derive می‌شود (برای سازگاری با نسخه‌های قدیمی).
    key_bytes = ENCRYPTION_KEY.encode()
    try:
        if len(key_bytes) == 44:
            return Fernet(key_bytes)
    except Exception:
        pass
    key = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
    return Fernet(key)


def encrypt(data: dict) -> str:
    return _cipher().encrypt(json.dumps(data).encode()).decode()


def decrypt(token: str) -> dict:
    return json.loads(_cipher().decrypt(token.encode()).decode())


def encrypt_str(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_str(token: str) -> str:
    return _cipher().decrypt(token.encode()).decode()
