"""Small daily quota guard for the public demo's paid model calls."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal


UsageKind = Literal["questions", "images"]
CHINA_TIME = timezone(timedelta(hours=8))
_LOCK = threading.Lock()


def current_day() -> str:
    return datetime.now(CHINA_TIME).date().isoformat()


def browser_limits() -> dict[UsageKind, int]:
    return {
        "questions": _positive_int("TRIPTWIN_BROWSER_QUESTION_LIMIT", 5),
        "images": _positive_int("TRIPTWIN_BROWSER_IMAGE_LIMIT", 2),
    }


def global_limits() -> dict[UsageKind, int]:
    return {
        "questions": _positive_int("TRIPTWIN_GLOBAL_QUESTION_LIMIT", 40),
        "images": _positive_int("TRIPTWIN_GLOBAL_IMAGE_LIMIT", 5),
    }


def normalize_browser_usage(value: object, *, day: str | None = None) -> dict[str, object]:
    today = day or current_day()
    if not isinstance(value, dict) or value.get("date") != today:
        return {"date": today, "questions": 0, "images": 0}
    return {
        "date": today,
        "questions": _safe_count(value.get("questions")),
        "images": _safe_count(value.get("images")),
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
    if not allowed:
        return normalized
    normalized[kind] = int(normalized[kind]) + 1
    return normalized


def reserve_global(
    kind: UsageKind, *, path: str | Path | None = None, day: str | None = None
) -> tuple[bool, int, int]:
    """Atomically reserve one process-wide daily call slot."""

    target = Path(path) if path else _counter_path()
    today = day or current_day()
    limit = global_limits()[kind]
    with _LOCK:
        usage = _read_global(target, today)
        count = int(usage[kind])
        if count >= limit:
            return False, count, limit
        usage[kind] = count + 1
        _write_global(target, usage)
        return True, count + 1, limit


def _counter_path() -> Path:
    configured = os.getenv("TRIPTWIN_USAGE_COUNTER_PATH")
    return (
        Path(configured)
        if configured
        else Path(tempfile.gettempdir()) / "triptwin-public-usage.json"
    )


def _read_global(path: Path, day: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        value = None
    if not isinstance(value, dict) or value.get("date") != day:
        return {"date": day, "questions": 0, "images": 0}
    return {
        "date": day,
        "questions": _safe_count(value.get("questions")),
        "images": _safe_count(value.get("images")),
    }


def _write_global(path: Path, usage: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(usage, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _safe_count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
