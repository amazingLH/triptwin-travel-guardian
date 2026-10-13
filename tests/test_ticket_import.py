from triptwin.models import Trip, BudgetStatus
from triptwin.risk_engine import RiskEngine
from triptwin.vision_parser import VisionExtraction, _normalize_extraction
from triptwin.demo_service import timeline_html


def ticket_payload():
    # Synthetic fields matching the shape of a single railway order; no identity data.
    return {
        "trip": {
            "trip_id": "ticket-trip", "version": "1.0", "title": "单段铁路行程",
            "start": "2026-10-07T20:16:00+08:00",
            "end": "2026-10-07T22:18:00+08:00",
            "travelers": {"adults": 1},
            "constraints": {"budget_cny": None},
            "events": [{
                "id": "train-1", "event_type": "transport", "title": "G8156 列车",
                "start": "2026-10-07T20:16:00+08:00",
                "end": "2026-10-07T22:18:00+08:00",
                "origin": {"name": "长白山站", "city": "待确认"},
                "destination": {"name": "沈阳北站", "city": "沈阳"},
                "cost_cny": "292", "metadata": {"booking_status": "refunded"},
            }],
        }, "notes": ["总预算未提供"],
    }


def test_single_railway_ticket_without_budget_is_valid():
    extraction = VisionExtraction.model_validate(_normalize_extraction(ticket_payload()))
    result = RiskEngine().analyze(extraction.trip)
    assert len(extraction.trip.events) == 1
    assert extraction.trip.constraints.budget_cny is None
    assert result.budget.status == BudgetStatus.INDETERMINATE
    assert result.budget.known_cost_cny == 292


def test_refunded_ticket_is_not_treated_as_valid_booking():
    trip = Trip.model_validate(ticket_payload()["trip"])
    result = RiskEngine().analyze(trip)
    assert any(risk.id == "booking:train-1" for risk in result.risks)
    assert "已退票" in next(r.title for r in result.risks if r.id == "booking:train-1")


def test_new_upload_clears_every_previous_result():
    from app import reset_import_view
    values = reset_import_view()
    assert values[0] == {}
    assert values[5] == ""  # JSON
    assert values[8] == ""  # timeline
    assert values[14] == []  # conversation
    assert values[15] is None  # exports
    assert "杭州" not in str(values)


def test_railway_ticket_timeline_preserves_route_title():
    html = timeline_html(ticket_payload()["trip"])
    assert "G8156" in html
    assert "沈阳北站" in html
