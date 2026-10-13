from __future__ import annotations

import json

from triptwin.usage_guard import (
    browser_can_consume,
    consume_browser,
    normalize_browser_usage,
    reserve_global,
)


def test_browser_usage_resets_and_stops_at_daily_limit(monkeypatch) -> None:
    monkeypatch.setenv("TRIPTWIN_BROWSER_QUESTION_LIMIT", "3")
    usage = normalize_browser_usage(None, day="2026-10-13")

    for _ in range(3):
        allowed, usage = browser_can_consume(
            usage, "questions", day="2026-10-13"
        )
        assert allowed is True
        usage = consume_browser(usage, "questions", day="2026-10-13")

    allowed, _ = browser_can_consume(usage, "questions", day="2026-10-13")
    assert allowed is False
    assert normalize_browser_usage(usage, day="2026-10-14")["questions"] == 0


def test_global_usage_is_persisted_and_capped(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRIPTWIN_GLOBAL_QUESTION_LIMIT", "2")
    path = tmp_path / "usage.json"

    assert reserve_global("questions", path=path, day="2026-10-13")[0] is True
    assert reserve_global("questions", path=path, day="2026-10-13")[0] is True
    allowed, count, limit = reserve_global(
        "questions", path=path, day="2026-10-13"
    )

    assert allowed is False
    assert (count, limit) == (2, 2)
    assert json.loads(path.read_text(encoding="utf-8"))["questions"] == 2
    assert reserve_global("questions", path=path, day="2026-10-14")[0] is True
