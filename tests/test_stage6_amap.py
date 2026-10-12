from __future__ import annotations

import json
from pathlib import Path

from triptwin.demo_service import amap_inspection_markdown, load_json
from triptwin.live_context import AmapInspection, apply_amap_evidence
from triptwin.models import RiskType, Trip
from triptwin.risk_engine import RiskEngine


ROOT = Path(__file__).resolve().parents[1]
INSPECTION = ROOT / "docs" / "evidence" / "stage6-amap" / "inspection.json"
TRIP = ROOT / "examples" / "hangzhou_golden_trip.json"


def test_real_amap_evidence_is_complete_and_successful() -> None:
    inspection = AmapInspection.model_validate(load_json(INSPECTION))

    assert inspection.run_status == "end_turn"
    assert inspection.tool_call_count == inspection.tool_output_count == 4
    assert inspection.error_count == 0
    assert inspection.route is not None
    assert inspection.route.duration_seconds == 2331
    assert inspection.route.duration_minutes == 38.9
    assert inspection.route.distance_meters == 11408
    assert inspection.route.walking_distance_meters == 570


def test_route_fact_enters_connection_rule_with_provenance() -> None:
    payload = json.loads(TRIP.read_text(encoding="utf-8"))
    inspection = AmapInspection.model_validate(load_json(INSPECTION))
    enriched = apply_amap_evidence(payload, inspection)
    event = next(item for item in enriched["events"] if item["id"] == "west-lake-boat")

    assert event["travel_minutes_from_previous"] == 39
    assert event["metadata"]["amap_route_evidence"]["source_tool"] == (
        "maps_direction_transit_integrated"
    )

    analysis = RiskEngine().analyze(Trip.model_validate(enriched))
    risk = next(item for item in analysis.risks if item.id.startswith("time_connection:"))
    assert "预计路程=39分钟" in risk.evidence
    assert any("高德地图 MCP" in item for item in risk.evidence)
    assert risk.source_tool == "maps_direction_transit_integrated"
    assert risk.verification_status == "verified"


def test_uncovered_trip_weather_is_not_invented() -> None:
    payload = json.loads(TRIP.read_text(encoding="utf-8"))
    inspection = AmapInspection.model_validate(load_json(INSPECTION))
    enriched = apply_amap_evidence(payload, inspection)
    analysis = RiskEngine().analyze(Trip.model_validate(enriched))

    assert inspection.weather is not None
    assert inspection.weather.trip_dates_covered is False
    assert all(risk.risk_type is not RiskType.WEATHER for risk in analysis.risks)
    assert any("天气未核验" in warning for warning in analysis.data_quality_warnings)


def test_verified_adverse_weather_creates_weather_risk() -> None:
    payload = json.loads(TRIP.read_text(encoding="utf-8"))
    event = next(item for item in payload["events"] if item["id"] == "longjing-hike")
    event["metadata"]["amap_weather_evidence"] = {
        "source_tool": "maps_weather",
        "fetched_at": "2026-10-18T00:00:00Z",
        "event_date": "2026-10-19",
        "status": "verified",
        "forecast": {"dayweather": "大雨", "nightweather": "中雨"},
        "warning": None,
    }
    analysis = RiskEngine().analyze(Trip.model_validate(payload))

    risk = next(item for item in analysis.risks if item.risk_type is RiskType.WEATHER)
    assert risk.source_tool == "maps_weather"
    assert risk.verification_status == "verified"
    assert "大雨/中雨" in risk.description


def test_stage6_panel_is_explicit_about_precision_and_weather_scope() -> None:
    rendered = amap_inspection_markdown()

    assert "38.9 分钟" in rendered
    assert "maps_direction_transit_integrated" in rendered
    assert "未核验" in rendered
    assert "禁止" not in rendered or "不进行猜测" in rendered
    assert "sk-" not in rendered
