"""Tests for the auth module (token store).

Uses tmp_path for SQLite isolation, matching test_config.py conventions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from opencobalt.core.auth import (
    AuthError,
    AuthStore,
    ExpiredTokenError,
    InvalidTokenError,
    RevokedTokenError,
    ScopeError,
)


def _store(tmp_path) -> AuthStore:
    return AuthStore(tmp_path / "ledger.db")


class TestCreateToken:
    def test_create_returns_plaintext_token_with_prefix(self, tmp_path):
        issued = _store(tmp_path).create_token("dashboard")
        assert issued.token.startswith("ocb_")
        assert len(issued.token) > 30

    def test_create_records_name_and_scopes(self, tmp_path):
        issued = _store(tmp_path).create_token("ci", scopes=["read", "write"])
        assert issued.record.name == "ci"
        assert issued.record.scopes == ["read", "write"]

    def test_default_scope_is_read(self, tmp_path):
        issued = _store(tmp_path).create_token("viewer")
        assert issued.record.scopes == ["read"]

    def test_plaintext_token_is_not_stored(self, tmp_path):
        import sqlite3

        store = _store(tmp_path)
        issued = store.create_token("secret-check")
        with sqlite3.connect(store.db_path) as conn:
            rows = conn.execute("SELECT * FROM auth_tokens").fetchall()
        flat = " ".join(str(v) for row in rows for v in row)
        assert issued.token not in flat

    def test_record_keeps_identifying_prefix_only(self, tmp_path):
        issued = _store(tmp_path).create_token("prefix-check")
        assert issued.record.token_prefix == issued.token[:12]

    def test_unknown_scope_rejected(self, tmp_path):
        with pytest.raises(ScopeError):
            _store(tmp_path).create_token("bad", scopes=["root"])

    def test_empty_name_rejected(self, tmp_path):
        with pytest.raises(AuthError):
            _store(tmp_path).create_token("  ")

    def test_expiry_recorded(self, tmp_path):
        issued = _store(tmp_path).create_token("temp", expires_in_days=7)
        assert issued.record.expires_at is not None
        delta = issued.record.expires_at - datetime.now(timezone.utc)
        assert timedelta(days=6) < delta <= timedelta(days=7)


class TestVerify:
    def test_verify_valid_token_returns_record(self, tmp_path):
        store = _store(tmp_path)
        issued = store.create_token("worker", scopes=["write"])
        record = store.verify(issued.token)
        assert record.id == issued.record.id
        assert record.scopes == ["write"]

    def test_verify_unknown_token_raises(self, tmp_path):
        store = _store(tmp_path)
        store.create_token("real")
        with pytest.raises(InvalidTokenError):
            store.verify("ocb_not-a-real-token-value-000000000000")

    def test_verify_empty_token_raises(self, tmp_path):
        with pytest.raises(InvalidTokenError):
            _store(tmp_path).verify("")

    def test_verify_revoked_token_raises(self, tmp_path):
        store = _store(tmp_path)
        issued = store.create_token("doomed")
        store.revoke(issued.record.id)
        with pytest.raises(RevokedTokenError):
            store.verify(issued.token)

    def test_verify_expired_token_raises(self, tmp_path):
        import sqlite3

        store = _store(tmp_path)
        issued = store.create_token("stale", expires_in_days=1)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with sqlite3.connect(store.db_path) as conn:
            conn.execute(
                "UPDATE auth_tokens SET expires_at=? WHERE id=?",
                (past, issued.record.id),
            )
        with pytest.raises(ExpiredTokenError):
            store.verify(issued.token)

    def test_verify_updates_last_used(self, tmp_path):
        store = _store(tmp_path)
        issued = store.create_token("tracked")
        assert issued.record.last_used_at is None
        store.verify(issued.token)
        records = store.list_tokens()
        assert records[0].last_used_at is not None

    def test_verify_with_required_scope(self, tmp_path):
        store = _store(tmp_path)
        issued = store.create_token("reader", scopes=["read"])
        store.verify(issued.token, required_scope="read")
        with pytest.raises(ScopeError):
            store.verify(issued.token, required_scope="write")

    def test_admin_scope_implies_all(self, tmp_path):
        store = _store(tmp_path)
        issued = store.create_token("root", scopes=["admin"])
        store.verify(issued.token, required_scope="read")
        store.verify(issued.token, required_scope="write")


class TestManagement:
    def test_list_tokens_orders_newest_first(self, tmp_path):
        store = _store(tmp_path)
        store.create_token("first")
        store.create_token("second")
        names = [r.name for r in store.list_tokens()]
        assert names == ["second", "first"]

    def test_revoke_unknown_id_raises(self, tmp_path):
        with pytest.raises(InvalidTokenError):
            _store(tmp_path).revoke("no-such-id")

    def test_revoke_is_idempotent_flag(self, tmp_path):
        store = _store(tmp_path)
        issued = store.create_token("twice")
        store.revoke(issued.record.id)
        store.revoke(issued.record.id)
        assert store.list_tokens()[0].revoked is True

    def test_count_tokens(self, tmp_path):
        store = _store(tmp_path)
        assert store.count_tokens() == 0
        store.create_token("a")
        store.create_token("b")
        assert store.count_tokens() == 2
