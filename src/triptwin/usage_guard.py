"""Atomic daily quota guard for public model/tool calls.

SQLite ``BEGIN IMMEDIATE`` makes limits consistent across threads and worker
processes. The database contains counters only—no prompts, images or IPs.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal


UsageKind = Literal["questions", "images", "agent_runs"]
CHINA_TIME = timezone(timedelta(hours=8))


def current_day() -> str:
    return datetime.now(CHINA_TIME).date().isoformat()


def browser_limits() -> dict[UsageKind, int]:
    return {
        "questions": _positive_int("TRIPTWIN_BROWSER_QUESTION_LIMIT", 5),
        "images": _positive_int("TRIPTWIN_BROWSER_IMAGE_LIMIT", 2),
        "agent_runs": _positive_int("TRIPTWIN_BROWSER_AGENT_LIMIT", 1),
    }


def global_limits() -> dict[UsageKind, int]:
    return {
        "questions": _positive_int("TRIPTWIN_GLOBAL_QUESTION_LIMIT", 40),
        "images": _positive_int("TRIPTWIN_GLOBAL_IMAGE_LIMIT", 5),
        "agent_runs": _positive_int("TRIPTWIN_GLOBAL_AGENT_LIMIT", 8),
    }


def normalize_browser_usage(value: object, *, day: str | None = None) -> dict[str, object]:
    today = day or current_day()
    if not isinstance(value, dict) or value.get("date") != today:
        return {"date": today, "questions": 0, "images": 0, "agent_runs": 0}
    return {
        "date": today,
        "questions": _safe_count(value.get("questions")),
        "images": _safe_count(value.get("images")),
        "agent_runs": _safe_count(value.get("agent_runs")),
    }


def browser_can_consume(
    usage: object, kind: UsageKind, *, day: str | None = None
) -> tuple[bool, dict[str, object]]:
    normalized = normalize_browser_usage(usage, day=day)
    return int(normalized[kind]) < browser_limits()[kind], normalized


def consume_browser(
    usage: object, kind: UsageKind, *, day: str | None = None
) -> dict[str, object]:
    allowed, normalized = browser_can_consume(usage, kind, day=day)
    if allowed:
        normalized[kind] = int(normalized[kind]) + 1
    return normalized


def reserve_global(
    kind: UsageKind, *, path: str | Path | None = None, day: str | None = None
) -> tuple[bool, int, int]:
    return _reserve("global", "all", kind, global_limits()[kind], path=path, day=day)


def reserve_client(
    client_key: str,
    kind: UsageKind,
    *,
    path: str | Path | None = None,
    day: str | None = None,
) -> tuple[bool, int, int]:
    """Reserve a server-side anonymous-client slot (key is already hashed)."""

    return _reserve(
        "client", client_key[:128], kind, browser_limits()[kind], path=path, day=day
    )


def release_reservation(
    scope: str,
    subject: str,
    kind: UsageKind,
    *,
    path: str | Path | None = None,
    day: str | None = None,
) -> None:
    target = Path(path) if path else _counter_path()
    with _connect(target) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE usage SET count = MAX(count - 1, 0) "
            "WHERE day = ? AND scope = ? AND subject = ? AND kind = ?",
            (day or current_day(), scope, subject, kind),
        )
        connection.commit()


def _reserve(
    scope: str,
    subject: str,
    kind: UsageKind,
    limit: int,
    *,
    path: str | Path | None,
    day: str | None,
) -> tuple[bool, int, int]:
    target = Path(path) if path else _counter_path()
    today = day or current_day()
    with _connect(target) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM usage WHERE day < date(?, '-14 day')", (today,))
        row = connection.execute(
            "SELECT count FROM usage WHERE day=? AND scope=? AND subject=? AND kind=?",
            (today, scope, subject, kind),
        ).fetchone()
        count = int(row[0]) if row else 0
        if count >= limit:
            connection.rollback()
            return False, count, limit
        new_count = count + 1
        connection.execute(
            "INSERT INTO usage(day, scope, subject, kind, count) VALUES(?,?,?,?,?) "
            "ON CONFLICT(day, scope, subject, kind) DO UPDATE SET count=excluded.count",
            (today, scope, subject, kind, new_count),
        )
        connection.commit()
        return True, new_count, limit


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS usage("
        "day TEXT NOT NULL, scope TEXT NOT NULL, subject TEXT NOT NULL, "
        "kind TEXT NOT NULL, count INTEGER NOT NULL CHECK(count >= 0), "
        "PRIMARY KEY(day, scope, subject, kind))"
    )
    return connection


def _counter_path() -> Path:
    configured = os.getenv("TRIPTWIN_USAGE_COUNTER_PATH")
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "triptwin-usage.sqlite3"


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _safe_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
