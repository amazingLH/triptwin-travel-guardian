"""Exercise the HTTP parser -> merge -> completion -> risk path without paid calls."""
import copy
import json

import httpx
import pytest
from PIL import Image

from triptwin.config import ModelSettings
from triptwin.functional_examples import example_trip
from triptwin.history_media import capture_previews
from triptwin.image_merge import merge_image_records
from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine
from triptwin.vision_parser import extract_trip_from_images


def ticket_record(index, destination="huludao"):
    trip = example_trip("conflict")
    event = trip["events"][2 if destination == "huludao" else 1]
    # Two separate photos can independently assign the very same local event ID.
    event.update(id="transport-1", depends_on=[], transfer_from_event_id=None, travel_minutes_from_previous=None)
    trip.update(events=[event], start=event["start"], end=event["end"])
    trip["constraints"].update(budget_cny=None, protected_event_ids=[])
    return {
        "image_index": index, "trip": trip,
        "field_confidence": {"events[0].start": .95, "events[0].end": .95,
                             "events[0].title": .65 if destination == "huludao" else .95},
        "low_confidence_fields": ["events[0].title"] if destination == "huludao" else [],
        "notes": ["总预算未提供"],
    }


def install_mock_model(monkeypatch, responses):
    calls = []
    original_client = httpx.Client
    def respond(request):
        calls.append(json.loads(request.content))
        body = responses[min(len(calls) - 1, len(responses) - 1)]
        return httpx.Response(200, json={
            "id": "offline-test", "usage": {"total_tokens": 100},
            "choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}],
        })
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr("triptwin.vision_parser.httpx.Client", lambda **kw: original_client(transport=transport, **kw))
    settings = ModelSettings(dashscope_api_key="not-a-real-key", bailian_workspace_id="offline-test")
    monkeypatch.setattr(ModelSettings, "from_env", classmethod(lambda cls, *a, **kw: settings))
    return calls


def photos(tmp_path, identical=False):
    paths = [tmp_path / "first.png", tmp_path / "second.png"]
    for i, path in enumerate(paths):
        Image.new("RGB", (50, 100), "blue" if i == 0 or identical else "green").save(path)
    return paths


def test_two_photos_keep_both_legs_through_http_completion_and_risk(monkeypatch, tmp_path):
    import app
    calls = install_mock_model(monkeypatch, [{"images": [ticket_record(2, "qinhuangdao"), ticket_record(1)]}])
    paths = photos(tmp_path)
    _, confidence, detail, _, pending = app.build_twin(paths)
    assert len(calls) == 1  # One batch request, NOT a paid call for each image.
    blocks = calls[0]["messages"][1]["content"]
    assert len([b for b in blocks if b["type"] == "image_url"]) == 2
    urls = [b["image_url"]["url"] for b in blocks if b["type"] == "image_url"]
    assert urls[0] != urls[1]
    assert calls[0]["max_tokens"] == 5000
    assert calls[0]["enable_thinking"] is False
    assert len(pending["draft_trip"]["events"]) == 2
    assert "截图处理核对" in detail
    assert pending["image_coverage"]["images"] == [
        {"image_index": 1, "event_indices": [0]}, {"image_index": 2, "event_indices": [1]},
    ]
    assert len({e["id"] for e in pending["draft_trip"]["events"]}) == 2
    assert pending["low_confidence_fields"] == ["events[0].title"]
    assert any(row[0] == "events[1].start" for row in confidence)
    rows = app.completion_panel(pending)[1]
    rows[0][2] = "300"
    _, timeline, ready, _, confirmed = app.confirm_import(rows, pending)
    result = app.check_risks(ready, confirmed)
    assert "葫芦岛" in timeline and "秦皇岛" in timeline
    assert "时间发生重叠" in result and "75" in result
    assert "205" in result
    plans = app.generate_plan_b(ready, True)[0]
    assert "保留前往" in plans and "秦皇岛" in plans and "葫芦岛" in plans
    assert len(calls) == 1  # Confirmation, deterministic risk and local Plan B are free.


@pytest.mark.parametrize("response,expected", [
    ({key: value for key, value in ticket_record(1, "qinhuangdao").items() if key != "image_index"}, "未返回逐张图片解析"),
    ({"images": [ticket_record(2, "qinhuangdao")]}, "第 1 张"),
    ({"images": [ticket_record(1), ticket_record(1)]}, "未核齐"),
])
def test_global_single_leg_or_missing_image_is_not_accepted(monkeypatch, tmp_path, response, expected):
    calls = install_mock_model(monkeypatch, [response])
    with pytest.raises(ValueError, match=expected):
        extract_trip_from_images(photos(tmp_path))
    assert len(calls) == 2  # Existing bounded repair policy, never infinite retries.
    assert "逐图覆盖" in calls[1]["messages"][-1]["content"]


def test_missing_image_can_be_repaired_without_losing_conflict(monkeypatch, tmp_path):
    calls = install_mock_model(monkeypatch, [
        {"images": [ticket_record(2, "qinhuangdao")]},
        {"images": [ticket_record(1), ticket_record(2, "qinhuangdao")]},
    ])
    extraction, meta = extract_trip_from_images(photos(tmp_path))
    assert len(calls) == meta["attempts"] == 2
    assert meta["image_count"] == len(meta["image_report"]) == 2
    assert RiskEngine().analyze(Trip.model_validate(extraction.trip)).risk_count == 1


def test_unreadable_first_image_is_named_and_blocks_complete_result(monkeypatch, tmp_path):
    first = ticket_record(1)
    first["trip"]["events"] = []
    install_mock_model(monkeypatch, [{"images": [first, ticket_record(2, "qinhuangdao")]}])
    with pytest.raises(ValueError, match="第 1 张图片"):
        extract_trip_from_images(photos(tmp_path))


def test_identical_uploaded_bytes_can_share_one_event_but_different_photos_cannot():
    first, second = ticket_record(1, "qinhuangdao"), ticket_record(2, "qinhuangdao")
    distinct, report = merge_image_records([first, second], ["different-photo-one", "different-photo-two"])
    assert len(distinct["trip"]["events"]) == 2
    same, report = merge_image_records([first, second], ["same-file", "same-file"])
    assert len(same["trip"]["events"]) == 1
    assert same["trip"]["events"][0]["metadata"]["source_image_indices"] == [1, 2]
    assert report == [{"image_index": 1, "event_indices": [0]}, {"image_index": 2, "event_indices": [0]}]


def test_missing_fields_do_not_delete_a_ticket(monkeypatch, tmp_path):
    first = ticket_record(1)
    first["trip"]["events"][0]["end"] = None
    install_mock_model(monkeypatch, [{"images": [first, ticket_record(2, "qinhuangdao")]}])
    extraction, _ = extract_trip_from_images(photos(tmp_path))
    assert isinstance(extraction.trip, dict)
    assert len(extraction.trip["events"]) == 2
    from triptwin.input_completion import completion_rows
    assert any(row[0] == "events.0.end" for row in completion_rows(extraction.trip))


def test_multiple_orders_inside_one_image_are_never_collapsed():
    first = ticket_record(1, "qinhuangdao")
    additional = copy.deepcopy(first["trip"]["events"][0])
    additional["id"] = "second-order"
    first["trip"]["events"].append(additional)
    second = copy.deepcopy(first)
    second["image_index"] = 2
    result, report = merge_image_records([first, second], ["same-file", "same-file"])
    assert len(result["trip"]["events"]) == 2
    assert report[0]["event_indices"] == report[1]["event_indices"] == [0, 1]


def test_same_file_with_inconsistent_model_facts_cannot_silently_drop_disagreement():
    with pytest.raises(ValueError, match="识别内容不一致"):
        merge_image_records([ticket_record(1), ticket_record(2, "qinhuangdao")], ["same-file", "same-file"])


def test_single_image_output_keeps_existing_contract(monkeypatch, tmp_path):
    data = ticket_record(1)
    data.pop("image_index")
    calls = install_mock_model(monkeypatch, [data])
    extraction, meta = extract_trip_from_images(photos(tmp_path)[:1])
    assert len(calls) == 1
    assert len(extraction.trip.events) == 1
    assert meta["image_report"] == [{"image_index": 1, "event_indices": [0]}]


def test_legacy_multiphoto_history_cannot_reuse_silent_zero_risk(monkeypatch, tmp_path):
    import app
    trip = ticket_record(1, "qinhuangdao")["trip"]
    trip["constraints"]["budget_cny"] = "300"
    snapshot = {"trip_state": {"trip_source": "uploaded_image", "trip": trip},
                "image_previews": capture_previews(photos(tmp_path)),
                "risks": "0 risks", "plan_b": "no Plan B needed"}
    monkeypatch.setattr(app.gr.utils, "get_upload_folder", lambda: str(tmp_path))
    restored = app._restored_history_view({"snapshot": snapshot})
    state = restored[12]
    assert state["legacy_image_coverage_missing"] is True
    assert "旧风险结果待复核" in restored[7]
    assert "原 Plan B 待复核" in restored[8]
    monkeypatch.setattr(app, "reserve_global", lambda *a: pytest.fail("must not consume quota"))
    with pytest.raises(Exception, match="尚未逐张核齐"):
        app.check_risks(state, True)
    with pytest.raises(Exception, match="尚未逐张核齐"):
        app.generate_plan_b_guarded(state, True, None)
    with pytest.raises(Exception, match="尚未逐张核齐"):
        app.run_live_inspection_guarded(state, True, None)
    with pytest.raises(Exception, match="尚未逐张核齐"):
        app.answer_question_guarded("有没有冲突？", [], state, None)
    with pytest.raises(Exception, match="尚未逐张核齐"):
        app.parse_current_import(restored[0], False, None, state)
    assert snapshot["trip_state"] == {"trip_source": "uploaded_image", "trip": trip}
