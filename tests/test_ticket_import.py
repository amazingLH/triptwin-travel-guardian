from triptwin.models import Trip, BudgetStatus
from triptwin.risk_engine import RiskEngine
from triptwin.vision_parser import VisionExtraction, _normalize_extraction
from triptwin.demo_service import timeline_html
from triptwin.input_completion import completion_rows, confirm_draft
import pytest


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


def valid_order():
    payload = ticket_payload()["trip"]
    payload["events"][0]["metadata"] = {"booking_status": "confirmed"}
    payload["events"][0]["origin"]["city"] = "安图"
    return payload


def test_budget_must_be_filled_before_construction():
    payload = valid_order()
    rows = completion_rows(payload)
    with pytest.raises(ValueError, match="总预算"):
        confirm_draft(payload, rows)
    rows[0][2] = "2000"
    trip = confirm_draft(payload, rows)
    assert trip.constraints.budget_cny == 2000


def test_incomplete_dates_remain_a_draft_until_user_fills_them():
    payload = valid_order()
    payload["events"][0]["start"] = None
    extraction = VisionExtraction.model_validate({"trip": payload})
    assert isinstance(extraction.trip, dict)
    rows = completion_rows(payload)
    rows[0][2] = "2000"
    with pytest.raises(ValueError):
        confirm_draft(payload, rows)
    for row in rows:
        if row[0] == "events.0.start":
            row[2] = "2026-10-07T20:16:00+08:00"
    assert confirm_draft(payload, rows).events[0].start.hour == 20


def test_refunded_ticket_blocks_construction_with_specific_message():
    payload = ticket_payload()["trip"]
    rows = completion_rows(payload)
    rows[0][2] = "2000"
    with pytest.raises(ValueError, match="上传当前有效订单"):
        confirm_draft(payload, rows)


def test_pending_draft_cannot_check_risks_or_export():
    from app import check_risks, export_current_trip, confirm_import
    state = {"draft_trip": valid_order(), "trip_source": "uploaded_image"}
    with pytest.raises(Exception, match="构建旅行数字孪生"):
        check_risks(state, True)
    with pytest.raises(Exception, match="构建旅行数字孪生"):
        export_current_trip(state)
    rows = completion_rows(state["draft_trip"])
    rows[0][2] = "2000"
    status, timeline, ready, _, _ = confirm_import(rows, state)
    assert "已构建" in status
    assert "G8156" in timeline
    assert "trip" in ready and "draft_trip" not in ready


def test_uploaded_image_parsing_does_not_require_privacy_checkbox(monkeypatch, tmp_path):
    from app import build_twin_guarded
    from PIL import Image
    path = tmp_path / "ordinary-ticket.png"
    Image.new("RGB", (20, 20), "white").save(path)
    monkeypatch.setattr("app.build_twin", lambda paths: ("{}", [], "", "", {"draft_trip": valid_order()}))
    monkeypatch.setattr("app.reserve_global", lambda kind: (True, 1, 5))
    result = build_twin_guarded([str(path)], False, None)
    assert "draft_trip" in result[4]
    assert result[5]["usage"]["images"] == 1
