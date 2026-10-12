import json
from pathlib import Path

from triptwin.agent_prompt import build_replanning_prompt
from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine


def test_prompt_protects_orders_and_scopes_affected_nodes() -> None:
    trip = Trip.model_validate_json(
        Path("examples/hangzhou_golden_trip.json").read_text(encoding="utf-8")
    )
    analysis = RiskEngine().analyze(trip)

    prompt = build_replanning_prompt(trip, analysis)
    context = json.loads(prompt.split("TripGraph context:\n", 1)[1])

    assert "飞猪旅行" in prompt
    assert "至少执行一次 FlyAI 查询" in prompt
    assert "train-sh-hz" in context["protected_event_ids"]
    affected_ids = {event["id"] for event in context["affected_events"]}
    assert "train-sh-hz" not in affected_ids
    assert "west-lake-boat" in affected_ids
    additive_ids = {item["risk_id"] for item in context["additive_repairs"]}
    assert "date_consistency:missing_accommodation_nights" in additive_ids
    assert "additive_candidates" in prompt

