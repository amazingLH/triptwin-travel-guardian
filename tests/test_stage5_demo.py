from pathlib import Path

from triptwin.demo_service import (
    SAMPLE_IMAGE_PATH,
    load_cached_vision,
    plan_b_markdown,
    risk_markdown,
    run_golden_demo,
    timeline_html,
    tool_trace_markdown,
)


def test_public_deployment_bootstraps_src_layout_before_imports() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    # ModelScope installs requirements before copying the project into its
    # image, so an editable local install cannot work during that build step.
    assert "-e ." not in requirements.splitlines()
    assert Path("app.py").read_text(encoding="utf-8").find("sys.path.insert") > 0


def test_real_vision_evidence_is_accurate_and_private() -> None:
    evidence = load_cached_vision()
    assert evidence["model"] == "qwen3.8-flash"
    assert evidence["field_accuracy"] >= 0.9
    assert evidence["contains_real_personal_information"] is False
    assert SAMPLE_IMAGE_PATH.is_file()


def test_golden_demo_closes_the_p0_loop() -> None:
    result = run_golden_demo()
    assert result["risk_count"] == 5
    assert result["risk_score"] == 335
    assert result["plan_b_valid"] is True
    assert result["unresolved_risk_count"] == 0
    assert result["protected_untouched"] is True


def test_loading_example_marks_chat_as_deterministic() -> None:
    import app

    image, _, state = app.load_example()

    assert Path(image) == SAMPLE_IMAGE_PATH
    assert state == {"trip_source": "synthetic_example"}


def test_golden_demo_is_repeatable_three_times() -> None:
    runs = [run_golden_demo() for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_rendered_demo_contains_no_secret_prefixes() -> None:
    trip = load_cached_vision()["trip"]
    rendered = "\n".join(
        [timeline_html(trip), risk_markdown(trip), plan_b_markdown(trip), tool_trace_markdown()]
    )
    assert "sk-" not in rendered
    assert "Bearer " not in rendered
    assert "DASHSCOPE_API_KEY" not in rendered


def test_chat_uses_contextual_model_answer(monkeypatch) -> None:
    import app

    monkeypatch.setattr(
        app,
        "answer_with_trip_context",
        lambda question, context: "不会自动预定；只提供已验证候选。",
    )
    question, history = app.answer_question(
        "是否会自动预定？",
        [],
        {"trip": load_cached_vision()["trip"]},
    )
    assert question == ""
    assert history[-2] == {"role": "user", "content": "是否会自动预定？"}
    assert history[-1]["role"] == "assistant"
    assert "不会自动预定" in history[-1]["content"]


def test_public_chat_reuses_browser_cache_without_second_model_call(monkeypatch) -> None:
    import app

    calls = {"count": 0}

    def fake_answer(question, context):
        calls["count"] += 1
        return "不会自动预定；只提供已验证候选。"

    monkeypatch.setattr(app, "answer_with_trip_context", fake_answer)
    monkeypatch.setattr(app, "reserve_global", lambda kind: (True, 1, 25))
    state = {"trip": load_cached_vision()["trip"]}

    _, history, store = app.answer_question_guarded(
        "是否会自动预定？", [], state, None
    )
    _, repeated_history, repeated_store = app.answer_question_guarded(
        " 是否会自动预定？ ", history, state, store
    )

    assert calls["count"] == 1
    assert repeated_store["usage"]["questions"] == 1
    assert repeated_history[-1]["content"] == history[-1]["content"]


def test_synthetic_common_question_uses_browser_quota_but_not_model(monkeypatch) -> None:
    import app

    monkeypatch.setattr(
        app,
        "answer_with_trip_context",
        lambda *_: (_ for _ in ()).throw(AssertionError("model must not be called")),
    )
    monkeypatch.setattr(
        app,
        "reserve_global",
        lambda *_: (_ for _ in ()).throw(AssertionError("quota must not be used")),
    )
    state = {
        "trip": load_cached_vision()["trip"],
        "trip_source": "synthetic_example",
    }

    _, history, store = app.answer_question_guarded(
        "是否会自动预定？", [], state, None
    )

    assert "不会替你预订" in history[-1]["content"]
    assert store.get("usage", {}).get("questions", 0) == 1

    _, repeated_history, repeated_store = app.answer_question_guarded(
        " 是否会自动预定？ ", history, state, store
    )
    assert repeated_history[-1]["content"] == history[-1]["content"]
    assert repeated_store["usage"]["questions"] == 1


def test_uploaded_trip_common_question_still_uses_model(monkeypatch) -> None:
    import app

    calls = {"count": 0}

    def fake_answer(*_):
        calls["count"] += 1
        return "根据用户上传的当前行程回答。"

    monkeypatch.setattr(app, "answer_with_trip_context", fake_answer)
    monkeypatch.setattr(app, "reserve_global", lambda kind: (True, 1, 25))
    state = {
        "trip": load_cached_vision()["trip"],
        "trip_source": "uploaded_image",
    }

    _, history, _ = app.answer_question_guarded(
        "是否会自动预定？", [], state, None
    )

    assert calls["count"] == 1
    assert history[-1]["content"] == "根据用户上传的当前行程回答。"


def test_public_chat_stops_after_browser_daily_limit(monkeypatch) -> None:
    import app
    from triptwin.usage_guard import current_day

    monkeypatch.setenv("TRIPTWIN_BROWSER_QUESTION_LIMIT", "3")
    store = {
        "version": 1,
        "active_id": None,
        "sessions": [],
        "usage": {"date": current_day(), "questions": 3, "images": 0},
        "answer_cache": {},
    }

    _, history, returned_store = app.answer_question_guarded(
        "还能继续问吗？", [], {"trip": load_cached_vision()["trip"]}, store
    )

    assert "每天最多 3 次提问" in history[-1]["content"]
    assert returned_store["usage"]["questions"] == 3
