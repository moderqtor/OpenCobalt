"""Token-based auth for the OpenCobalt API server.

Tokens are random, shown once at creation, and stored only as SHA-256 hashes
in the SQLite ledger. Auth is disabled by default to keep the local-first,
zero-config workflow intact; enable it with `opencobalt auth enable`.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config

TOKEN_PREFIX = "ocb_"
PREFIX_CHARS = 12
KNOWN_SCOPES = ("read", "write", "admin")
_AUTH_ENABLED_KEY = "auth_enabled"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_tokens (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    token_hash   TEXT NOT NULL UNIQUE,
    token_prefix TEXT NOT NULL,
    scopes       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT,
    last_used    TEXT,
    revoked      INTEGER NOT NULL DEFAULT 0
);
"""


class AuthError(Exception):
    """Base error for auth failures."""


class InvalidTokenError(AuthError):
    """Token is empty, malformed, or unknown."""


class ExpiredTokenError(AuthError):
    """Token exists but is past its expiry."""


class RevokedTokenError(AuthError):
    """Token exists but was revoked."""


class ScopeError(AuthError):
    """Unknown scope requested, or required scope not granted."""


@dataclass
class TokenRecord:
    """Stored token metadata. Never contains the plaintext value."""

    id: str
    name: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked: bool


@dataclass
class IssuedToken:
    """Plaintext value plus its stored record. Returned exactly once."""

    token: str
    record: TokenRecord


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_to_record(row: sqlite3.Row) -> TokenRecord:
    return TokenRecord(
        id=row["id"],
        name=row["name"],
        token_prefix=row["token_prefix"],
        scopes=json.loads(row["scopes"]),
        created_at=_parse_dt(row["created_at"]) or _now(),
        expires_at=_parse_dt(row["expires_at"]),
        last_used_at=_parse_dt(row["last_used"]),
        revoked=bool(row["revoked"]),
    )


class AuthStore:
    """SQLite-backed token store. Only SHA-256 hashes are persisted."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_token(
        self,
        name: str,
        *,
        scopes: list[str] | None = None,
        expires_in_days: int | None = None,
    ) -> IssuedToken:
        """Create a named token. The plaintext is returned exactly once."""
        if not name or not name.strip():
            raise AuthError("token name must be non-empty")
        name = name.strip()

        granted = list(scopes) if scopes else ["read"]
        unknown = [s for s in granted if s not in KNOWN_SCOPES]
        if unknown:
            raise ScopeError(f"unknown scope(s): {', '.join(unknown)}")

        plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
        created = _now()
        expires = None
        if expires_in_days is not None:
            expires = created + timedelta(days=expires_in_days)

        record = TokenRecord(
            id=uuid.uuid4().hex,
            name=name,
            token_prefix=plaintext[:PREFIX_CHARS],
            scopes=granted,
            created_at=created,
            expires_at=expires,
            last_used_at=None,
            revoked=False,
        )
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO auth_tokens "
                    "(id, name, token_hash, token_prefix, scopes, created_at, expires_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        record.id,
                        name,
                        _hash_token(plaintext),
                        record.token_prefix,
                        json.dumps(granted),
                        created.isoformat(),
                        expires.isoformat() if expires else None,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AuthError(f"token name already exists: {name}") from exc
        return IssuedToken(plaintext, record)

    def verify(self, candidate: str, *, required_scope: str | None = None) -> TokenRecord:
        """Validate a plaintext value and return its record.

        Raises InvalidTokenError, RevokedTokenError, ExpiredTokenError, or
        ScopeError. Updates last_used on success.
        """
        if not candidate:
            raise InvalidTokenError("empty token")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_tokens WHERE token_hash=?",
                (_hash_token(candidate),),
            ).fetchone()
            if row is None:
                raise InvalidTokenError("unknown token")
            if row["revoked"]:
                raise RevokedTokenError(f"token revoked: {row['name']}")
            expires = _parse_dt(row["expires_at"])
            if expires is not None and expires < _now():
                raise ExpiredTokenError(f"token expired: {row['name']}")

            record = _row_to_record(row)
            has_scope = required_scope is None or required_scope in record.scopes
            if not has_scope and "admin" not in record.scopes:
                raise ScopeError(f"required scope not granted: {required_scope}")

            stamp = _now()
            conn.execute(
                "UPDATE auth_tokens SET last_used=? WHERE id=?",
                (stamp.isoformat(), row["id"]),
            )
            record.last_used_at = stamp
        return record

    def revoke(self, token_id: str) -> None:
        """Revoke a token by id. Idempotent for known ids."""
        with self._connect() as conn:
            cur = conn.execute("UPDATE auth_tokens SET revoked=1 WHERE id=?", (token_id,))
            if cur.rowcount == 0:
                raise InvalidTokenError(f"no token with id: {token_id}")

    def list_tokens(self) -> list[TokenRecord]:
        """All token records, newest first."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM auth_tokens ORDER BY rowid DESC").fetchall()
        return [_row_to_record(r) for r in rows]

    def count_tokens(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM auth_tokens").fetchone()
        return int(row["n"])


def auth_enabled(db_path: Path) -> bool:
    return Config(db_path).get(_AUTH_ENABLED_KEY, "false") == "true"


def set_auth_enabled(db_path: Path, enabled: bool) -> None:
    Config(db_path).set(_AUTH_ENABLED_KEY, "true" if enabled else "false")
