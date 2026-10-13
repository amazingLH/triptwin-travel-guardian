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
