"""
Secret box – encrypts credentials saved in Settings (cloud keys, environment variables) before they are stored.

Key: `settings_secret_key` from .env when set, else a key generated once into cip-api/.settings.key (git-ignored).
Values are encrypted with Fernet (AES-128-CBC + HMAC); the API never returns them – the UI only sees "saved".
"""

from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from core.settings import env

KEY_FILE = Path(__file__).resolve().parents[1] / ".settings.key"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = env("settings_secret_key", "")
    if not key:
        if not KEY_FILE.exists():
            KEY_FILE.write_text(Fernet.generate_key().decode(), encoding="utf-8")
            KEY_FILE.chmod(0o600)                    # owner only (ignored on Windows)
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return Fernet(key.encode())


def seal(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def unseal(token: str) -> str:
    """For the deploy steps that will use the credentials (never sent to the UI)."""
    return _fernet().decrypt(token.encode()).decode()
