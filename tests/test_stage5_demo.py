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


def test_public_deployment_installs_src_layout_package() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    assert "-e ." in requirements.splitlines()
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
