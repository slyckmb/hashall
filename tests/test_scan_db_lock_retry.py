import sqlite3

import pytest

from hashall.scan import _run_with_db_lock_retry


def test_run_with_db_lock_retry_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("HASHALL_DB_LOCK_RETRY_SECS", "1")
    monkeypatch.setenv("HASHALL_DB_LOCK_MAX_RETRIES", "5")

    sleep_calls = []
    monkeypatch.setattr("hashall.scan.time.sleep", lambda s: sleep_calls.append(s))

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    result = _run_with_db_lock_retry(flaky, quiet=True, label="test-op")

    assert result == "ok"
    assert attempts["n"] == 3
    assert sleep_calls == [1, 1]


def test_run_with_db_lock_retry_respects_max_retries(monkeypatch):
    monkeypatch.setenv("HASHALL_DB_LOCK_RETRY_SECS", "2")
    monkeypatch.setenv("HASHALL_DB_LOCK_MAX_RETRIES", "2")

    sleep_calls = []
    monkeypatch.setattr("hashall.scan.time.sleep", lambda s: sleep_calls.append(s))

    attempts = {"n": 0}

    def always_locked():
        attempts["n"] += 1
        raise sqlite3.OperationalError("database table is locked")

    with pytest.raises(sqlite3.OperationalError):
        _run_with_db_lock_retry(always_locked, quiet=True, label="test-op")

    assert attempts["n"] == 3
    assert sleep_calls == [2, 2]


def test_run_with_db_lock_retry_does_not_retry_non_lock_errors(monkeypatch):
    monkeypatch.setenv("HASHALL_DB_LOCK_RETRY_SECS", "1")
    monkeypatch.setenv("HASHALL_DB_LOCK_MAX_RETRIES", "5")

    sleep_calls = []
    monkeypatch.setattr("hashall.scan.time.sleep", lambda s: sleep_calls.append(s))

    attempts = {"n": 0}

    def wrong_error():
        attempts["n"] += 1
        raise sqlite3.OperationalError("no such table: files_123")

    with pytest.raises(sqlite3.OperationalError):
        _run_with_db_lock_retry(wrong_error, quiet=True, label="test-op")

    assert attempts["n"] == 1
    assert sleep_calls == []
