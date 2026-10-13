from __future__ import annotations

import json

from PIL import Image

from triptwin.browser_secrets import persistent_secret
from triptwin.history_media import capture_previews, previews_html, sanitize_previews, MAX_PREVIEW_CHARS
from triptwin.session_history import create_session, ensure_active_session, save_active_session, switch_session
from triptwin.functional_examples import example_trip


def test_saving_without_initialization_stores_snapshot():
    store = save_active_session(None, {"status": "saved", "trip_state": {"draft_trip": {"title": "车票草稿"}}})
    assert store["sessions"][0]["snapshot"]["status"] == "saved"
    assert store["sessions"][0]["title"] == "车票草稿"


def test_reselecting_active_session_does_not_erase_saved_results():
    store, first = ensure_active_session(None)
    store = save_active_session(store, {"status": "saved"})
    _, restored = switch_session(store, first["id"], current_snapshot={"status": "blank"})
    assert restored["snapshot"]["status"] == "saved"


def test_previews_are_bounded_and_do_not_retain_server_paths(tmp_path):
    image = tmp_path / "order.png"
    Image.new("RGB", (600, 1800), "blue").save(image)
    previews = capture_previews([image] * 6)
    assert len(previews) == 5
    assert all(len(item["data_url"]) <= MAX_PREVIEW_CHARS for item in previews)
    assert str(tmp_path) not in json.dumps(previews)
    image.unlink()
    assert "data:image/jpeg;base64," in previews_html(previews)
    previews[0]["name"] = '<img src=x onerror="bad">'
    assert "&lt;img" in previews_html(previews)
    assert sanitize_previews([{"name": "bad", "data_url": "javascript:alert(1)"}]) == []


def test_browser_secrets_survive_restart_and_configured_secret_takes_precedence(tmp_path):
    first = persistent_secret(None, tmp_path, "key")
    assert len(first) >= 32
    assert persistent_secret(None, tmp_path, "key") == first
    assert persistent_secret("configured", tmp_path, "key") == "configured"


def test_full_history_restore_and_refresh_are_isolated(tmp_path):
    import app
    path = tmp_path / "order.png"
    Image.new("RGB", (50, 100), "white").save(path)
    previews = capture_previews([path])
    trip = example_trip("conflict")
    state = {"trip": trip, "trip_source": "uploaded_image", "field_confidence": {"events[0].title": .9}}
    store, first = ensure_active_session(None)
    snapshot = app._session_snapshot(state, "已构建", True, "saved-risk", "saved-plan", "saved-trace", [{"role": "assistant", "content": "saved-answer"}], "", "", previews, json.dumps(trip), None, "unsent")
    store = save_active_session(store, snapshot)
    store, _ = create_session(store)
    result = app.open_history_session(first["id"], store, {}, "空会话", False, "", "", "", [], "", "")
    restored = result[3:]
    assert restored[1] == "已构建"
    assert json.loads(restored[2]) == trip
    assert restored[3][0][1] == .9
    assert "K550" in restored[5]
    assert restored[6] is True
    assert restored[7:10] == ("saved-risk", "saved-plan", "saved-trace")
    assert restored[10] == "unsent"
    assert restored[11][-1]["content"] == "saved-answer"
    assert restored[17] == previews
    assert "data:image/jpeg;base64," in restored[18]["value"]
    assert app.initialize_session_history(result[0])[3:] == restored
    assert store["active_id"] != first["id"]  # No in-place cross-session mutation.


def test_incomplete_form_and_unapplied_json_survive_switch():
    import app
    trip = example_trip("multi")
    state = {"draft_trip": trip, "trip_source": "uploaded_image"}
    rows = [["constraints.budget_cny", "总预算", "3200"]]
    snapshot = app._session_snapshot(state, "等待补全", False, "", "", "", [], "", "", [], "{unapplied draft", rows)
    restored = app._restored_history_view({"snapshot": snapshot})
    assert restored[2] == "{unapplied draft"
    assert restored[5] == ""  # A draft is not a built trip.
    assert restored[19]["visible"] is True
    assert restored[20] == rows
    assert restored[22]["visible"] is True
    assert "completion_rows" not in state


def test_history_selection_is_user_input_only_and_has_no_open_button():
    import app
    config = app.demo.config
    assert not any(c.get("props", {}).get("value") == "打开所选会话" for c in config["components"])
    deps = [d for d in config["dependencies"] if app.demo.fns[d["id"]].fn is app.open_history_session]
    assert len(deps) == 1
    assert deps[0]["targets"][0][1] == "input"
    assert len(deps[0]["outputs"]) == len(app.initialize_session_history(None))


def test_actual_gradio_chatbot_blocks_are_not_discarded():
    import gradio as gr
    bot = gr.Chatbot()
    raw = [{"role": "user", "content": "问题"}, {"role": "assistant", "content": "回答"}]
    blocks = bot.preprocess(bot.postprocess(raw))
    assert isinstance(blocks[0]["content"], list)
    store = save_active_session(None, {"chat_history": blocks})
    assert store["sessions"][0]["snapshot"]["chat_history"] == raw
