from triptwin.functional_examples import example_trip, field_description
from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine
from triptwin.runtime_agent import _inspection_leg
from triptwin.live_context import _precise_poi


def test_reviewed_multi_trip_is_normal_and_third_ticket_conflicts():
    normal = Trip.model_validate(example_trip("multi"))
    assert RiskEngine().analyze(normal).risk_count == 0
    assert RiskEngine().analyze(Trip.model_validate(example_trip("conflict"))).risk_count > 0


def test_railway_connection_checks_arrival_to_next_departure_station():
    assert _inspection_leg(Trip.model_validate(example_trip("multi"))) == ("大连站", "大连站")


def test_field_description_names_the_actual_event():
    text = field_description("events[1].start", example_trip("multi"))
    assert "第 2 项" in text and "K715" in text and "出发时间" in text


def test_poi_cannot_certify_unrelated_or_unrouted_coordinates():
    items = [{"name": "大连站", "location": "121.6,38.9"}]
    assert _precise_poi(items, "大连", "121.6,38.9")["level"] == "POI"
    assert _precise_poi(items, "大连", "121.7,38.9") is None
    assert _precise_poi(items, "秦皇岛", "121.6,38.9") is None


def test_ticket_demo_does_not_borrow_hangzhou_or_consume_agent_quota(monkeypatch):
    from app import build_twin, generate_plan_b_guarded
    from triptwin.functional_examples import example_paths
    from triptwin.session_history import ensure_active_session
    _, rows, _, _, state = build_twin(example_paths("multi"))
    assert state["trip_source"] == "ticket_example"
    assert len(rows[0]) == 3
    store, _ = ensure_active_session(None)
    monkeypatch.setattr("app.reserve_global", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected live call")))
    result = generate_plan_b_guarded(state, True, store)
    assert "184" in result[0]
    assert "西湖" not in result[0]
