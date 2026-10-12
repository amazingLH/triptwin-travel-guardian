from __future__ import annotations

from triptwin.session_history import (
    create_session,
    ensure_active_session,
    history_choices,
    save_active_session,
    switch_session,
)


def _snapshot(title: str, answer: str) -> dict:
    return {
        "trip_state": {
            "trip": {"title": title, "events": [{"id": "example"}]},
            "field_confidence": {"trip.title": 0.99},
            "low_confidence_fields": [],
        },
        "status": "已构建",
        "confirmed": True,
        "risks": "风险结果",
        "plan_b": "Plan B",
        "trace": "工具轨迹",
        "chat_history": [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": answer},
        ],
        "amap_status": "高德证据",
        "inspection_status": "巡检状态",
    }


def test_every_new_session_has_a_unique_independent_id() -> None:
    store, first = ensure_active_session(None)
    store, second = create_session(store)

    assert first["id"].startswith("tts_")
    assert second["id"].startswith("tts_")
    assert first["id"] != second["id"]
    assert store["active_id"] == second["id"]
    assert len(store["sessions"]) == 2


def test_new_session_preserves_previous_session_snapshot() -> None:
    store, first = ensure_active_session(None)
    store, second = create_session(
        store, current_snapshot=_snapshot("杭州两日游", "第一条回答")
    )

    old = next(item for item in store["sessions"] if item["id"] == first["id"])
    assert old["title"] == "杭州两日游"
    assert old["snapshot"]["chat_history"][-1]["content"] == "第一条回答"
    assert second["snapshot"]["chat_history"] == []


def test_switching_history_restores_the_selected_session() -> None:
    store, first = ensure_active_session(None)
    store = save_active_session(store, _snapshot("会话一", "回答一"))
    store, second = create_session(store)
    store = save_active_session(store, _snapshot("会话二", "回答二"))

    store, restored = switch_session(store, first["id"])

    assert store["active_id"] == first["id"]
    assert restored["snapshot"]["chat_history"][-1]["content"] == "回答一"
    assert restored["id"] != second["id"]


def test_history_choices_contain_all_session_ids() -> None:
    store, first = ensure_active_session(None)
    store, second = create_session(store)

    choices = history_choices(store)

    assert {value for _, value in choices} == {first["id"], second["id"]}


def test_history_does_not_persist_uploaded_image_paths() -> None:
    store, _ = ensure_active_session(None)
    value = _snapshot("隐私测试", "回答")
    value["image_path"] = "C:/private/order.png"
    store = save_active_session(store, value)

    active = next(
        item for item in store["sessions"] if item["id"] == store["active_id"]
    )
    assert "image_path" not in active["snapshot"]
