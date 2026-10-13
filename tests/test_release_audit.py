"""Regression coverage for the final product audit; no paid network calls."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from triptwin.bailian_client import AgentRun
from triptwin.demo_service import risk_markdown, tool_trace_markdown
from triptwin.exporter import export_trip_files
from triptwin.functional_examples import example_trip
from triptwin.input_completion import completion_rows, confirm_draft, cancelled_orders
from triptwin.models import Trip, TravelerProfile
from triptwin.risk_engine import RiskEngine
from triptwin.runtime_agent import _bind_candidate_sources, _verified_flyai_commands, _live_prompt
from triptwin.vision_parser import VisionExtraction, _normalize_extraction


def test_export_is_isolated_and_uses_utc_calendar():
    payload = example_trip("multi")
    first = export_trip_files(payload)
    changed = deepcopy(payload)
    changed["title"] = "another visitor"
    second = export_trip_files(changed)
    assert Path(first[0]).parent != Path(second[0]).parent
    assert "another visitor" not in Path(first[0]).read_text(encoding="utf-8")
    ics = Path(first[1]).read_text(encoding="utf-8")
    assert "DTSTART:20261025T175600Z" in ics
    assert "DTSTAMP:" in ics
    assert "UID:" in ics


@pytest.mark.parametrize("value", ["not-a-date", "2026-10-26T01:56:00"])
def test_completion_has_actionable_date_errors(value):
    payload = example_trip("multi")
    payload["events"][0]["start"] = None
    rows = completion_rows(payload)
    next(row for row in rows if row[0] == "events.0.start")[2] = value
    with pytest.raises(ValueError, match="第 1 项") as error:
        confirm_draft(payload, rows)
    assert "Invalid isoformat" not in str(error.value)


def test_invalid_window_can_be_corrected_as_timestamps():
    payload = example_trip("multi")
    payload["events"][0]["end"] = payload["events"][0]["start"]
    rows = completion_rows(payload)
    assert not any(row[0] == "events.0" for row in rows)
    assert {"events.0.start", "events.0.end"} <= {row[0] for row in rows}
    assert any("第 1 项" in row[1] for row in rows)
    next(row for row in rows if row[0] == "events.0.end")[2] = "2026-10-26T06:50:00+08:00"
    assert confirm_draft(payload, rows).events[0].end.hour == 6


def test_null_profile_and_metadata_do_not_crash():
    payload = example_trip("multi")
    payload["travelers"] = None
    payload["constraints"] = None
    payload["events"][0]["metadata"] = None
    normalized = _normalize_extraction({"trip": payload})
    assert isinstance(normalized["trip"]["travelers"], dict)
    assert cancelled_orders(payload) == []


def test_seniors_can_travel_without_separate_adult_count():
    assert TravelerProfile(adults=0, seniors=2).needs_accessible_pacing
    with pytest.raises(ValidationError, match="同行总人数"):
        TravelerProfile(adults=0, children=0, seniors=0)


@pytest.mark.parametrize("score", [-1, 2, float("nan")])
def test_confidence_is_bounded(score):
    with pytest.raises(ValidationError):
        VisionExtraction(trip=example_trip("multi"), field_confidence={"events[0].title": score})


def test_model_cannot_omit_low_confidence_warning():
    parsed = VisionExtraction(trip=example_trip("multi"), field_confidence={"events[0].title": 0.5})
    assert parsed.low_confidence_fields == ["events[0].title"]


def test_missing_links_do_not_skip_same_station_transfer():
    payload = example_trip("multi")
    event = payload["events"][1]
    event["depends_on"] = []
    event["transfer_from_event_id"] = None
    event["start"] = "2026-10-26T06:55:00+08:00"
    analysis = RiskEngine().analyze(Trip.model_validate(payload))
    assert any(risk.title == "同站换乘缓冲不足" for risk in analysis.risks)


def test_different_stations_without_route_are_unverified():
    payload = example_trip("multi")
    payload["events"][1]["transfer_from_event_id"] = None
    payload["events"][1]["origin"]["name"] = "大连北站"
    text = risk_markdown(payload, include_cached_amap=False)
    assert "大连北站" in text and "衔接未核验" in text
    assert "不代表整趟旅行已核验" in text


def test_overnight_transport_is_not_missing_hotel():
    payload = example_trip("multi")
    payload["events"] = payload["events"][:1]
    payload["events"][0].update(start="2026-10-25T22:00:00+08:00", end="2026-10-26T06:00:00+08:00")
    payload.update(start=payload["events"][0]["start"], end=payload["events"][0]["end"])
    assert not any(risk.id == "date_consistency:missing_accommodation_nights" for risk in RiskEngine().analyze(Trip.model_validate(payload)).risks)


def test_unknown_budget_warning_is_visible():
    payload = example_trip("multi")
    payload["constraints"]["budget_cny"] = None
    assert "未提供总预算" in risk_markdown(payload, include_cached_amap=False)


def test_invalid_protected_reference_is_rejected():
    payload = example_trip("multi")
    payload["constraints"]["protected_event_ids"] = ["missing"]
    with pytest.raises(ValidationError, match="受保护行程"):
        Trip.model_validate(payload)


def test_edit_clears_old_live_evidence_and_options():
    import app
    payload = example_trip("multi")
    payload["events"][0]["metadata"]["amap_route_evidence"] = {"status": "verified"}
    state = {"trip": payload, "trip_source": "uploaded_image", "live_inspection": {}, "local_plan_options": [1], "local_analysis_completed": True}
    result = app.apply_tripgraph_edits(Trip.model_validate(payload).model_dump_json(), state)
    updated = result[2]
    assert "local_plan_options" not in updated
    assert "live_inspection" not in updated
    assert "amap_route_evidence" not in updated["draft_trip"]["events"][0]["metadata"]
    assert "amap_route_evidence" in state["trip"]["events"][0]["metadata"]


def test_invalid_plan_request_does_not_reserve_quota(monkeypatch):
    import app
    monkeypatch.setattr(app, "reserve_global", lambda *a: pytest.fail("quota used"))
    with pytest.raises(Exception, match="补全必要信息"):
        app.generate_plan_b_guarded({}, False, None)


def test_corrupt_image_is_rejected_before_quota(monkeypatch, tmp_path):
    import app
    path = tmp_path / "invalid.png"
    path.write_bytes(b"not an image")
    monkeypatch.setattr(app, "reserve_global", lambda *a: pytest.fail("quota used"))
    with pytest.raises(Exception, match="不消耗解析次数"):
        app.build_twin_guarded([path], False, None)


def test_failed_cloud_attempts_cannot_bypass_server_limit(monkeypatch, tmp_path):
    import app
    path = tmp_path / "test.png"
    Image.new("RGB", (20, 20), "white").save(path)
    monkeypatch.setenv("TRIPTWIN_USAGE_COUNTER_PATH", str(tmp_path / "counts.sqlite3"))
    monkeypatch.setattr(app, "build_twin", lambda *a: (_ for _ in ()).throw(RuntimeError("upstream failed")))
    request = SimpleNamespace(client=SimpleNamespace(host="test-client"), headers={"user-agent": "audit"})
    for _ in range(2):
        with pytest.raises(Exception, match="计入解析次数"):
            app.build_twin_guarded([path], False, None, request)
    with pytest.raises(Exception, match="匿名访客今日已达到"):
        app.build_twin_guarded([path], False, None, request)


def test_chat_failure_is_not_cached(monkeypatch, tmp_path):
    import app
    monkeypatch.setenv("TRIPTWIN_USAGE_COUNTER_PATH", str(tmp_path / "counts.sqlite3"))
    monkeypatch.setattr(app, "answer_with_trip_context", lambda *a: (_ for _ in ()).throw(ValueError("no service")))
    _, history, store = app.answer_question_guarded("我的行程怎么样", [], {"trip": example_trip("multi")}, None)
    assert history[-1]["content"] == app.MODEL_UNAVAILABLE_REPLY
    assert not store["answer_cache"]


def test_long_question_and_unbuilt_example_do_not_call_model(monkeypatch):
    import app
    monkeypatch.setattr(app, "reserve_global", lambda *a: pytest.fail("quota used"))
    with pytest.raises(Exception, match="500 字"):
        app.answer_question_guarded("x" * 501, [], {}, None)
    _, history, _ = app.answer_question_guarded("为什么存在衔接风险？", [], {"trip_source": "synthetic_example"}, None)
    assert "完成第 2 步" in history[-1]["content"]


def cli_run(stdout):
    return AgentRun(session_id="test-session", status="end_turn", tool_calls=[{
        "content": [{"data": {"name": "bash", "call_id": "test-call", "arguments": {"command": "flyai search-hotel --dest-name TEST"}}}],
    }], tool_outputs=[{
        "content": [{"data": {"name": "bash", "call_id": "test-call", "output": {"exit_code": 0, "stdout": stdout}}}],
    }])


def test_exit_zero_without_business_json_is_not_verified():
    assert _verified_flyai_commands(cli_run("EXIT:0"))[0]["result_status"] is None


def test_candidates_must_match_actual_tool_name_url_and_price():
    run = cli_run({"status": 0, "data": [{"name": "Test Hotel", "price": "¥135", "detailUrl": "https://router.feizhu.com/test"}]})
    artifact = {"notes": [], "candidates": {"hotel": {"options": [
        {"name": "Test Hotel", "jumpUrl": "https://router.feizhu.com/test", "event_patch": {"cost_cny": 135}},
        {"name": "Test Hotel", "jumpUrl": "https://router.feizhu.com/test", "event_patch": {"cost_cny": 1}},
        {"name": "Fake", "jumpUrl": "https://router.feizhu.com/fake", "event_patch": {"cost_cny": 135}},
    ]}}, "additive_candidates": {}}
    _bind_candidate_sources(artifact, run)
    assert len(artifact["candidates"]["hotel"]["options"]) == 1
    assert artifact["notes"]


def test_real_inspection_prompt_is_weather_only_for_single_leg():
    payload = example_trip("multi")
    payload["events"] = payload["events"][:1]
    trip = Trip.model_validate(payload)
    prompt = _live_prompt(trip, RiskEngine().analyze(trip), origin_name="", destination_name="", inspect_only=True)
    assert "只用 maps_weather" in prompt
    assert "不查询 FlyAI" in prompt


def test_failed_tool_trace_does_not_claim_every_call_succeeded():
    text = tool_trace_markdown({"flyai_commands": [{"exit_code": 1, "result_status": 1, "command": "flyai search-hotel"}]})
    assert "已验证成功：**0 条**" in text


def test_chat_context_contains_actual_events_and_warnings():
    from triptwin.demo_service import chat_context
    context = chat_context(example_trip("multi"), include_cached_amap=False)
    assert context["trip"]["events"][0]["title"] == "K550 沈阳 → 大连"
    assert "data_quality_warnings" in context


def test_weather_from_another_city_is_not_applied():
    from triptwin.live_context import AmapInspection, apply_amap_evidence
    from triptwin.demo_service import load_json, AMAP_INSPECTION_PATH, GOLDEN_TRIP_PATH
    inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    payload = load_json(GOLDEN_TRIP_PATH)
    event = payload["events"][-1]
    event["location"]["city"] = "大连"
    event["start"] = "2026-10-12T14:00:00+08:00"
    event["weather_sensitive"] = True
    enriched = apply_amap_evidence(payload, inspection)
    evidence = enriched["events"][-1]["metadata"]["amap_weather_evidence"]
    assert evidence["status"] == "unverified"
    assert "城市" in evidence["warning"]


def test_inspect_button_performs_real_weather_check_even_without_risks(monkeypatch, tmp_path):
    import app
    from triptwin.live_context import AmapInspection
    from triptwin.demo_service import load_json, AMAP_INSPECTION_PATH
    calls = []
    from datetime import UTC, datetime
    inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    def fake_run(payload, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(trip=payload, inspection=inspection, generated_at=datetime.now(UTC).isoformat())
    monkeypatch.setenv("TRIPTWIN_USAGE_COUNTER_PATH", str(tmp_path / "counts.sqlite3"))
    monkeypatch.setattr(app, "run_live_trip", fake_run)
    state = {"trip": example_trip("multi"), "trip_source": "uploaded_image"}
    result = app.run_live_inspection_guarded(state, True, None)
    assert calls == [{"inspect_only": True}]
    assert result[-1]["usage"]["agent_runs"] == 1
    app.run_live_inspection_guarded(result[2], True, result[-1])
    assert len(calls) == 1  # Reuse clearly timestamped evidence without another charge.


def test_guarded_free_synonym_does_not_consume_quota(monkeypatch):
    import app
    monkeypatch.setattr(app, "reserve_global", lambda *a: pytest.fail("quota used"))
    _, _, store = app.answer_question_guarded("是否会自动预订？", [], {"trip": example_trip("multi"), "trip_source": "synthetic_example"}, None)
    assert store.get("usage", {}).get("questions", 0) == 0


def test_pending_view_reset_removes_previous_conversation_and_export():
    from app import reset_downstream_view
    result = reset_downstream_view()
    assert result[3:] == ([], "", None)
    assert "重新生成方案" in result[1]


def test_nan_candidate_price_is_rejected_not_an_exception():
    from triptwin.candidate_validator import _validate_option
    from decimal import Decimal
    assert _validate_option("test", [], {"name": "Test", "jumpUrl": "https://router.feizhu.com/test", "extra_cost_cny": "NaN"}, Decimal(500), require_simulation=False, additive=False) is None


def test_missing_or_old_evidence_is_not_reused_as_current():
    from app import live_evidence_is_recent
    from datetime import UTC, datetime, timedelta
    assert not live_evidence_is_recent({})
    assert not live_evidence_is_recent({"live_generated_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat()})
    assert live_evidence_is_recent({"live_generated_at": datetime.now(UTC).isoformat()})


def test_image_extraction_cannot_invent_external_evidence_or_store_extra_identity_keys():
    payload = example_trip("multi")
    payload["passenger_name"] = "not-a-public-field"
    payload["events"][0]["metadata"].update({"amap_weather_evidence": {"status": "verified"}, "passenger_id": "private"})
    result = _normalize_extraction({"trip": payload})["trip"]
    assert "passenger_name" not in result
    assert "amap_weather_evidence" not in result["events"][0]["metadata"]
    assert "passenger_id" not in result["events"][0]["metadata"]


def test_missing_internal_ids_are_generated_not_asked_of_user():
    payload = example_trip("multi")
    payload.pop("trip_id")
    payload.pop("version")
    payload["events"][0].pop("id")
    normalized = _normalize_extraction({"trip": payload})["trip"]
    assert normalized["trip_id"].startswith("trip-")
    assert normalized["version"] == "1.0"
    assert normalized["events"][0]["id"] == "event-1"


def test_export_can_use_managed_ui_cache_root(tmp_path):
    paths = export_trip_files(example_trip("multi"), directory_root=tmp_path)
    assert all(Path(path).is_relative_to(tmp_path) for path in paths)


def test_replacement_price_is_not_double_counted_during_replay():
    from triptwin.candidate_validator import validate_candidate_artifact
    payload = example_trip("multi")
    payload["constraints"]["budget_cny"] = "180"
    payload["events"][1]["start"] = "2026-10-26T06:30:00+08:00"
    trip = Trip.model_validate(payload)
    analysis = RiskEngine().analyze(trip)
    artifact = {"flyai_commands": [{"exit_code": 0, "result_status": 0}], "candidates": {
        "train-dl-qhd": {"risk_ids": [risk.id for risk in analysis.risks], "options": [{
            "name": "test replacement", "jumpUrl": "https://router.feizhu.com/test", "extra_cost_cny": 12,
            "source": "flyai", "event_patch": {"start": "2026-10-26T09:54:00+08:00", "cost_cny": 124, "proposed_extra_cost_cny": 12},
        }]},
    }}
    result = validate_candidate_artifact(trip, analysis, artifact, require_simulation=True)
    assert result.valid, result.rejection_reasons


def test_confirmed_low_score_is_kept_and_labelled_human_confirmed():
    from app import confirm_import, refresh_confidence
    payload = example_trip("multi")
    state = {"draft_trip": payload, "trip_source": "uploaded_image", "field_confidence": {"events[0].title": 0.5}, "low_confidence_fields": ["events[0].title"]}
    ready = confirm_import(completion_rows(payload), state)[2]
    rows, text = refresh_confidence(ready)
    assert rows[0][1] == 0.5
    assert "已人工确认" in text


def test_structural_reference_error_can_be_repaired_in_completion_form():
    payload = example_trip("multi")
    payload["events"][1]["depends_on"] = ["unknown"]
    rows = completion_rows(payload)
    target = next(row for row in rows if row[0] == "events.1.depends_on")
    target[2] = '["train-sy-dl"]'
    assert confirm_draft(payload, rows).events[1].depends_on == ["train-sy-dl"]
