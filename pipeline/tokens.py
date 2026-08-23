"""Encrypted token persistence for LinkedIn OAuth tokens."""
import json
import logging
import os
import sqlite3
from base64 import urlsafe_b64encode
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from config.settings import DB_PATH, TOKEN_SECRET, ensure_dirs

logger = logging.getLogger(__name__)

SALT = b"hermes-linkedin-pipeline-v1"
SERVICE = "linkedin"


def _derive_key(secret: str) -> bytes:
    """Derive a Fernet key from the user-provided TOKEN_SECRET."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=480_000,
    )
    return urlsafe_b64encode(kdf.derive(secret.encode()))


def _fernet() -> Fernet:
    if not TOKEN_SECRET:
        raise RuntimeError("TOKEN_SECRET is not set; cannot encrypt tokens")
    return Fernet(_derive_key(TOKEN_SECRET))


def _connection() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tokens_table() -> None:
    conn = _connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tokens (
            service TEXT PRIMARY KEY,
            encrypted_blob TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def save_tokens(access_token: str, refresh_token: str = "", expires_in: int = 0, author_urn: str = "") -> None:
    """Encrypt and store LinkedIn tokens."""
    init_tokens_table()
    blob = json.dumps(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "author_urn": author_urn,
        }
    )
    encrypted = _fernet().encrypt(blob.encode()).decode()
    conn = _connection()
    conn.execute(
        """
        INSERT INTO tokens (service, encrypted_blob, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET
            encrypted_blob=excluded.encrypted_blob,
            updated_at=excluded.updated_at
        """,
        (SERVICE, encrypted, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    # Restrict file permissions when possible
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        logger.warning("Could not chmod token database to 0o600", exc_info=True)


def load_tokens() -> dict | None:
    """Load and decrypt LinkedIn tokens, if they exist."""
    init_tokens_table()
    conn = _connection()
    row = conn.execute(
        "SELECT encrypted_blob FROM tokens WHERE service = ?", (SERVICE,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    if not TOKEN_SECRET:
        raise RuntimeError("TOKEN_SECRET is not set; cannot decrypt stored tokens")
    try:
        decrypted = _fernet().decrypt(row["encrypted_blob"].encode()).decode()
        return json.loads(decrypted)
    except Exception as e:
        logger.exception("Failed to decrypt LinkedIn tokens")
        raise RuntimeError(f"Failed to decrypt LinkedIn tokens: {e}") from e


def has_tokens() -> bool:
    try:
        return bool(load_tokens())
    except RuntimeError:
        return False


def clear_tokens() -> None:
    init_tokens_table()
    conn = _connection()
    conn.execute("DELETE FROM tokens WHERE service = ?", (SERVICE,))
    conn.commit()
    conn.close()
    logger.info("LinkedIn tokens cleared from database")
