from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from triptwin.models import BudgetStatus, RiskType, Trip
from triptwin.risk_engine import RiskEngine


ROOT = Path(__file__).resolve().parents[1]


def load_payload(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


@pytest.fixture
def golden_trip() -> Trip:
    return Trip.model_validate(load_payload("hangzhou_golden_trip.json"))


@pytest.fixture
def plan_b_trip() -> Trip:
    return Trip.model_validate(load_payload("hangzhou_plan_b_trip.json"))


def test_golden_case_detects_all_four_risk_families(golden_trip: Trip) -> None:
    analysis = RiskEngine().analyze(golden_trip)

    assert {risk.risk_type for risk in analysis.risks} == {
        RiskType.TIME_CONNECTION,
        RiskType.DATE_CONSISTENCY,
        RiskType.BUDGET,
        RiskType.MOBILITY,
    }
    assert analysis.risk_count == 5
    assert analysis.total_risk_score > 0


def test_connection_evidence_uses_route_plus_buffer(golden_trip: Trip) -> None:
    analysis = RiskEngine().analyze(golden_trip)
    risk = next(
        item for item in analysis.risks if item.risk_type is RiskType.TIME_CONNECTION
    )

    assert "可用间隔=35分钟" in risk.evidence
    assert "预计路程=45分钟" in risk.evidence
    assert "安全缓冲=20分钟" in risk.evidence
    assert "缺口=30分钟" in risk.evidence


def test_missing_second_hotel_night_is_detected(golden_trip: Trip) -> None:
    analysis = RiskEngine().analyze(golden_trip)
    risk = next(
        item
        for item in analysis.risks
        if item.id == "date_consistency:missing_accommodation_nights"
    )

    assert "2026-10-19" in risk.evidence[0]


def test_plan_b_reduces_all_deterministic_risks(
    golden_trip: Trip, plan_b_trip: Trip
) -> None:
    before = RiskEngine().analyze(golden_trip)
    after = RiskEngine().analyze(plan_b_trip)

    assert before.risk_count == 5
    assert after.risk_count == 0
    assert after.total_risk_score < before.total_risk_score
    assert after.budget.status is BudgetStatus.WITHIN_BUDGET


def test_null_price_is_indeterminate_not_zero(plan_b_trip: Trip) -> None:
    payload = plan_b_trip.model_dump(mode="json")
    hotel = next(event for event in payload["events"] if event["id"] == "hotel-west-lake")
    hotel["cost_cny"] = None

    analysis = RiskEngine().analyze(Trip.model_validate(payload))

    assert analysis.budget.status is BudgetStatus.INDETERMINATE
    assert analysis.budget.unknown_cost_event_ids == ["hotel-west-lake"]
    assert any("不能把 null 当作 0" in item for item in analysis.data_quality_warnings)


@pytest.mark.parametrize(
    "invalid_start",
    ["not-a-date", "2026/10/18 08:30", "2026-10-18T08:30:00"],
)
def test_invalid_or_timezone_naive_time_is_rejected(
    invalid_start: str,
) -> None:
    payload = load_payload("hangzhou_golden_trip.json")
    payload["events"][0]["start"] = invalid_start

    with pytest.raises(ValidationError):
        Trip.model_validate(payload)


def test_unknown_dependency_is_rejected() -> None:
    payload = load_payload("hangzhou_golden_trip.json")
    payload["events"][1]["depends_on"] = ["missing-event"]

    with pytest.raises(ValidationError, match="unknown event ids"):
        Trip.model_validate(payload)


def test_duplicate_event_id_is_rejected() -> None:
    payload = load_payload("hangzhou_golden_trip.json")
    payload["events"][1]["id"] = payload["events"][0]["id"]

    with pytest.raises(ValidationError, match="event ids must be unique"):
        Trip.model_validate(payload)


def test_event_end_before_start_is_rejected() -> None:
    payload = load_payload("hangzhou_golden_trip.json")
    payload["events"][0]["end"] = "2026-10-18T08:00:00+08:00"

    with pytest.raises(ValidationError, match="event end must be later"):
        Trip.model_validate(payload)


def test_weather_sensitive_flag_is_reserved_for_stage_six(golden_trip: Trip) -> None:
    analysis = RiskEngine().analyze(golden_trip)

    assert all(risk.risk_type.value != "weather" for risk in analysis.risks)

