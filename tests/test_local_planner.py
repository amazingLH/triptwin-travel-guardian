from copy import deepcopy

from triptwin.functional_examples import example_trip, example_paths
from triptwin.local_planner import schedule_options
from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine


def test_two_replayed_alternatives_resolve_conflict_and_keep_protected_leg():
    original = example_trip("conflict")
    options = schedule_options(original)
    assert len(options) == 2
    assert {option["known_cost"] for option in options} == {"166.5", "147.5"}
    for option in options:
        trip = Trip.model_validate(option["trip"])
        assert any(event.id == "train-sy-dl" for event in trip.events)
        assert trip.constraints.protected_event_ids == {"train-sy-dl"}
        assert RiskEngine().analyze(trip).risk_count == 0
    assert len(original["events"]) == 3


def test_cannot_remove_protected_or_depended_on_booking():
    payload = example_trip("conflict")
    payload["constraints"]["protected_event_ids"] = [event["id"] for event in payload["events"]]
    assert schedule_options(payload) == []


def test_confidence_of_obscured_train_is_not_full_and_panels_not_empty():
    from app import build_twin, generate_plan_b, apply_local_option, context_panels_for_state
    _, rows, _, _, state = build_twin(example_paths("conflict"))
    assert next(row[1] for row in rows if row[0] == "events[2].title") < 0.8
    _, _, planned, amap, inspection = generate_plan_b(state, True)
    assert "等待上传" not in amap + inspection
    selection = planned["local_plan_options"][0]["id"]
    _, _, risk_text, updated, plan_text, _, _ = apply_local_option(selection, planned)
    assert "0 个风险" in risk_text
    assert "已应用" in plan_text
    assert "等待上传" not in "".join(context_panels_for_state(updated))


def test_real_uploaded_schedule_conflict_uses_same_replay_without_paid_calls(monkeypatch):
    from app import generate_plan_b_guarded
    from triptwin.session_history import ensure_active_session
    state = {"trip": deepcopy(example_trip("conflict")), "trip_source": "uploaded_image"}
    store, _ = ensure_active_session(None)
    monkeypatch.setattr("app.reserve_global", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected paid call")))
    result = generate_plan_b_guarded(state, True, store)
    assert len(result[2]["local_plan_options"]) == 2


def test_live_inspection_replays_pending_options_without_applying_or_discarding(monkeypatch):
    import app
    from types import SimpleNamespace
    from datetime import UTC, datetime
    from triptwin.demo_service import load_json, AMAP_INSPECTION_PATH
    from triptwin.live_context import AmapInspection

    state = {"trip": example_trip("conflict"), "trip_source": "uploaded_image"}
    state["local_plan_options"] = schedule_options(state["trip"])
    selected = state["local_plan_options"][1]["id"]
    state["local_plan_choice"] = selected
    original = deepcopy(state)
    enriched = deepcopy(state["trip"])
    enriched["events"][0]["cost_cny"] = "60"
    inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    monkeypatch.setattr(app, "reserve_global", lambda *a: (True, 1, 350))
    def fake_run(payload, **kwargs):
        assert kwargs == {"inspect_only": True}
        return SimpleNamespace(trip=enriched, inspection=inspection, generated_at=datetime.now(UTC).isoformat())
    monkeypatch.setattr(app, "run_live_trip", fake_run)
    result = app.run_live_inspection_guarded(state, True, None)
    updated = result[2]
    assert state == original  # No in-place edits or destination auto-selection.
    assert len(updated["trip"]["events"]) == 3
    assert len(updated["local_plan_options"]) == 2
    assert {option["known_cost"] for option in updated["local_plan_options"]} == {"172", "153"}
    assert app.local_options_view(updated)[1]["value"] == selected
    assert "172" in app.plan_after_inspection(updated, "old prices")


def test_pending_choice_survives_autosave_history_and_cached_inspection(monkeypatch):
    import app

    state = {"trip": example_trip("conflict"), "trip_source": "ticket_example"}
    state["local_plan_options"] = schedule_options(state["trip"])
    selected = state["local_plan_options"][1]["id"]
    snapshot = app._session_snapshot(state, "built", True, "risk", "plan", "trace", [], "", "", local_choice=selected)
    restored = app._restored_history_view({"snapshot": snapshot})
    assert restored[-1]["value"] == selected
    monkeypatch.setattr(app, "run_live_trip", lambda *a, **k: (_ for _ in ()).throw(AssertionError("example must not call cloud")))
    updated = app.run_live_inspection_guarded(restored[12], True, None)[2]
    saved = app.persist_current_session(None, updated, "built", True, "risk", "plan", "trace", [], "", "", local_choice=selected)
    assert saved[-2]["value"] == selected
    assert len(updated["local_plan_options"]) == 2


def test_unusable_options_show_reason_instead_of_a_silent_disappearance(monkeypatch):
    import app
    from types import SimpleNamespace
    from datetime import UTC, datetime
    from triptwin.demo_service import load_json, AMAP_INSPECTION_PATH
    from triptwin.live_context import AmapInspection

    state = {"trip": example_trip("conflict"), "trip_source": "uploaded_image"}
    state["local_plan_options"] = schedule_options(state["trip"])
    no_conflict = deepcopy(state["local_plan_options"][0]["trip"])
    inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    monkeypatch.setattr(app, "reserve_global", lambda *a: (True, 1, 350))
    monkeypatch.setattr(app, "run_live_trip", lambda *a, **k: SimpleNamespace(trip=no_conflict, inspection=inspection, generated_at=datetime.now(UTC).isoformat()))
    updated = app.run_live_inspection_guarded(state, True, None)[2]
    assert not updated["local_plan_options"]
    assert "原局部方案需要重新生成" in app.plan_after_inspection(updated, "old table")


def test_failed_inspection_does_not_modify_pending_plan_or_selection(monkeypatch):
    import app
    import pytest

    state = {"trip": example_trip("conflict"), "trip_source": "uploaded_image"}
    state["local_plan_options"] = schedule_options(state["trip"])
    state["local_plan_choice"] = state["local_plan_options"][1]["id"]
    original = deepcopy(state)
    monkeypatch.setattr(app, "reserve_global", lambda *a: (True, 1, 350))
    def unavailable(*args, **kwargs):
        raise RuntimeError("测试中的工具超时")
    monkeypatch.setattr(app, "run_live_trip", unavailable)
    with pytest.raises(app.gr.Error, match="实时核验未完成"):
        app.run_live_inspection_guarded(state, True, None)
    assert state == original


def test_late_selection_event_after_apply_is_ignored_without_a_dropdown_error():
    import app

    state = {"trip": example_trip("conflict"), "local_plan_options": []}
    assert app.remember_local_choice("train-dl-qhd", state) == app.gr.skip()
    state["local_plan_options"] = schedule_options(state["trip"])
    selected = state["local_plan_options"][1]["id"]
    assert app.remember_local_choice(selected, state) == selected
