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

    assert len(image) == 1
    assert Path(image[0]) == SAMPLE_IMAGE_PATH
    assert state == {"trip_source": "synthetic_example"}


def test_blank_session_does_not_show_shared_golden_evidence() -> None:
    import app

    amap_panel, inspection_panel = app.context_panels_for_state({})

    assert "等待上传行程" in amap_panel
    assert "等待上传行程" in inspection_panel
    assert "杭州东站" not in amap_panel
    assert "drun_" not in inspection_panel


def test_synthetic_panels_are_explicitly_shared_public_evidence() -> None:
    import app

    state = {
        "trip": load_cached_vision()["trip"],
        "trip_source": "synthetic_example",
    }
    amap_panel, inspection_panel = app.context_panels_for_state(state)

    assert "公开合成示例证据" in amap_panel
    assert "所有访客共享" in amap_panel
    assert "杭州东站" in amap_panel
    assert "公开合成示例证据" in inspection_panel


def test_uploaded_trip_never_reuses_golden_cloud_evidence() -> None:
    import app

    state = {
        "trip": load_cached_vision()["trip"],
        "trip_source": "uploaded_image",
    }
    amap_panel, inspection_panel = app.run_manual_inspection_for_state(state)

    assert "不会复用杭州合成示例" in amap_panel
    assert "38.9" not in amap_panel
    assert "未调用高德 MCP 或 Managed Agent" in inspection_panel
    assert "drun_" not in inspection_panel


def test_uploaded_trip_without_live_candidates_never_gets_golden_plan_b() -> None:
    trip = load_cached_vision()["trip"]

    rendered = plan_b_markdown(trip, include_cached_amap=False)

    assert "没有专属的实时 FlyAI 候选证据" in rendered
    assert "如家精选" not in rendered


def test_legacy_blank_history_is_sanitized_on_restore() -> None:
    import app

    session = {
        "snapshot": {
            "trip_state": {},
            "amap_status": "杭州东站 → 西湖少年宫码头",
            "inspection_status": "drun_old_shared_record",
        }
    }
    restored = app._session_view(session)

    assert "等待上传行程" in restored[-4]
    assert "杭州东站" not in restored[-4]
    assert "等待上传行程" in restored[-3]
    assert "drun_" not in restored[-3]


def test_current_uploaded_live_panel_survives_its_own_session_restore() -> None:
    import app
    from triptwin.live_context import AmapInspection
    from triptwin.demo_service import AMAP_INSPECTION_PATH, load_json

    inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    state = {
        "trip": load_cached_vision()["trip"],
        "trip_source": "uploaded_image",
        "live_inspection": inspection.model_dump(mode="json"),
    }
    amap_panel = app._live_amap_panel(inspection)
    saved = app._session_snapshot(
        state, "ok", False, "risk", "plan", "trace", [], amap_panel,
        "### ⏱️ 当前上传行程 · 实时巡检\n\n已完成",
    )
    restored = app._session_view({"snapshot": saved})

    assert "杭州东站" in restored[-4]
    assert "已完成" in restored[-3]


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


def test_canonical_synthetic_questions_are_quota_free(monkeypatch) -> None:
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

    history = []
    store = None
    for question in (
        "为什么存在衔接风险？",
        "第二晚推荐住哪里？",
        "是否会自动预定？",
        "候选数据来自哪里？",
    ):
        _, history, store = app.answer_question_guarded(
            question, history, state, store
        )

    assert store.get("usage", {}).get("questions", 0) == 0

    _, repeated_history, repeated_store = app.answer_question_guarded(
        " 是否会自动预定？ ", history, state, store
    )
    assert "不会替你预订" in repeated_history[-1]["content"]
    assert repeated_store.get("usage", {}).get("questions", 0) == 0


def test_paraphrased_synthetic_question_uses_browser_quota(monkeypatch) -> None:
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
        "它会不会帮我自动预订？", [], state, None
    )

    assert "不会替你预订" in history[-1]["content"]
    assert store["usage"]["questions"] == 1


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

    _, history, store = app.answer_question_guarded(
        "是否会自动预定？", [], state, None
    )

    assert calls["count"] == 1
    assert history[-1]["content"] == "根据用户上传的当前行程回答。"
    assert store["usage"]["questions"] == 1


def test_question_without_trip_context_returns_local_instruction(monkeypatch) -> None:
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

    _, history, store = app.answer_question_guarded(
        "为什么有风险？", [], {}, None
    )

    assert "请先上传行程单" in history[-1]["content"]
    assert "载入合成示例" in history[-1]["content"]
    assert store.get("usage", {}).get("questions", 0) == 0


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
