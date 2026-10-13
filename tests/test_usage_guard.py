from __future__ import annotations

import sqlite3

import pytest

from triptwin.usage_guard import (
    browser_can_consume,
    browser_limits,
    consume_browser,
    global_limits,
    normalize_browser_usage,
    reserve_global,
    reserve_client,
)


def test_default_public_limits(monkeypatch) -> None:
    for name in (
        "TRIPTWIN_BROWSER_QUESTION_LIMIT",
        "TRIPTWIN_BROWSER_IMAGE_LIMIT",
        "TRIPTWIN_GLOBAL_QUESTION_LIMIT",
        "TRIPTWIN_GLOBAL_IMAGE_LIMIT",
        "TRIPTWIN_BROWSER_AGENT_LIMIT",
        "TRIPTWIN_GLOBAL_AGENT_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    assert browser_limits() == {"questions": 30, "images": 15, "agent_runs": 15}
    assert global_limits() == {"questions": 500, "images": 300, "agent_runs": 350}


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


@pytest.mark.parametrize(
    "kind,browser_limit,global_limit",
    [("questions", 30, 500), ("images", 15, 300), ("agent_runs", 15, 350)],
)
def test_new_limits_enforced_across_browser_and_server(
    monkeypatch, tmp_path, kind, browser_limit, global_limit
) -> None:
    for suffix in ("QUESTION", "IMAGE", "AGENT"):
        for scope in ("BROWSER", "GLOBAL"):
            monkeypatch.delenv(f"TRIPTWIN_{scope}_{suffix}_LIMIT", raising=False)
    day = "2026-10-13"
    usage = normalize_browser_usage(None, day=day)
    path = tmp_path / "usage.sqlite3"
    for _ in range(browser_limit):
        assert browser_can_consume(usage, kind, day=day)[0]
        usage = consume_browser(usage, kind, day=day)
        assert reserve_client("visitor", kind, path=path, day=day)[0]
    assert not browser_can_consume(usage, kind, day=day)[0]
    assert reserve_client("visitor", kind, path=path, day=day) == (
        False, browser_limit, browser_limit
    )
    for _ in range(global_limit):
        assert reserve_global(kind, path=path, day=day)[0]
    assert reserve_global(kind, path=path, day=day) == (
        False, global_limit, global_limit
    )


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
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count FROM usage WHERE day=? AND scope=? AND kind=?",
            ("2026-10-13", "global", "questions"),
        ).fetchone()[0] == 2
    assert reserve_global("questions", path=path, day="2026-10-14")[0] is True
