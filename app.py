"""TripTwin Stage 5 Gradio P0 demo."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# ModelScope starts this file directly with `python app.py`.  Make the src-layout
# package importable even before an editable install has completed.
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import gradio as gr

from triptwin.demo_service import (
    SAMPLE_IMAGE_PATH,
    active_inspection_markdown,
    analyze_trip,
    amap_inspection_markdown,
    chat_context,
    load_cached_vision,
    plan_b_markdown,
    risk_markdown,
    timeline_html,
    tool_trace_markdown,
)
from triptwin.trip_assistant import answer_with_trip_context
from triptwin.session_history import (
    create_session,
    ensure_active_session,
    history_choices,
    save_active_session,
    switch_session,
)
from triptwin.vision_parser import extract_trip_from_image
from triptwin.usage_guard import (
    browser_can_consume,
    browser_limits,
    consume_browser,
    global_limits,
    reserve_global,
)


DISCLAIMER = (
    "价格、库存及开放时间具有时效性；结果仅用于风险分析与候选推荐。"
    "TripTwin 不代订、不支付；上传图片前请遮挡身份证号、手机号和票号。"
    "历史会话按当前浏览器隔离；公开合成示例的证据由所有访客共享，"
    "用户上传行程不会复用该示例结果。"
)

EMPTY_AMAP_STATUS = (
    "### 🛰️ 空间与天气核验\n\n"
    "等待上传行程并构建旅行数字孪生，或载入并构建公开合成示例。"
)
EMPTY_INSPECTION_STATUS = (
    "### ⏱️ 主动巡检\n\n"
    "等待上传行程并构建旅行数字孪生，或载入并构建公开合成示例。"
)
UPLOADED_AMAP_PENDING = (
    "### 🛰️ 当前上传行程 · 空间与天气核验\n\n"
    "尚未对这份行程执行实时高德 MCP 查询；不会复用杭州合成示例的路线或天气证据。"
)
UPLOADED_INSPECTION_PENDING = (
    "### ⏱️ 当前上传行程 · 主动巡检\n\n"
    "尚未对这份行程执行云端主动巡检。点击“手动巡检”可重新运行本地确定性风险规则。"
)

APP_CSS = """
.hero {background:linear-gradient(120deg,#f4f7ff,#dbeafe);padding:24px;border:1px solid #c7d7f4;border-radius:18px;color:#17233c}
.hero h1 {color:#17233c;margin-bottom:8px}.hero p {color:#475467;margin:0}
.timeline-item {display:grid;grid-template-columns:150px 1fr;gap:18px;padding:14px 0;border-bottom:1px solid #e6eaf2}
.timeline-time {color:#2563eb;font-weight:700}.timeline span{color:#667085}
.guide-card {background:#fff8e8;border:1px solid #f3d28b;border-radius:14px;padding:14px 18px}
.guide-card h3 {color:#7a4b00;margin-top:0}.guide-card p,.guide-card li {color:#694c20}
.guide-title-row {display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.guide-title-row h3 {margin:0}.example-free-note {font-size:12px;color:#9a5b00}
.chat-panel {border:1px solid #c7d7f4;border-radius:16px;background:#f8fbff;padding:8px}
.session-bar {border:1px solid #d9e2f2;border-radius:14px;background:#f8fafc;padding:10px 14px}
.quota-card {background:#fff7ed;border:1px solid #fdba74;border-radius:14px;padding:12px 16px;color:#7c2d12}
.quota-card b {color:#9a3412}
"""


def load_example() -> tuple[str, str, dict[str, str]]:
    return (
        str(SAMPLE_IMAGE_PATH),
        "✅ 已载入完全虚构的黄金案例，无真实个人信息。",
        {"trip_source": "synthetic_example"},
    )


def _sample_panel(markdown: str, title: str) -> str:
    """Label cached competition evidence so it cannot be mistaken for user data."""

    body = markdown.split("\n", 1)[1].lstrip() if "\n" in markdown else markdown
    return (
        f"### {title}\n\n"
        "> **公开合成示例证据：** 以下结果属于所有访客共享的杭州虚构案例，"
        "不含真实个人信息，也不是当前访客的历史记录。\n\n"
        f"{body}"
    )


def context_panels_for_state(
    state: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return truthful evidence panels for the current browser session state."""

    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        return EMPTY_AMAP_STATUS, EMPTY_INSPECTION_STATUS
    if state.get("trip_source") == "synthetic_example":
        return (
            _sample_panel(
                amap_inspection_markdown(),
                "🛰️ 合成示例 · 空间与天气核验",
            ),
            _sample_panel(
                active_inspection_markdown(),
                "⏱️ 合成示例 · 主动巡检",
            ),
        )
    return UPLOADED_AMAP_PENDING, UPLOADED_INSPECTION_PENDING


def safe_context_panels(
    state: dict[str, Any] | None,
    saved_amap: Any = None,
    saved_inspection: Any = None,
) -> tuple[str, str]:
    """Reject legacy/shared panels that do not belong to the current state."""

    default_amap, default_inspection = context_panels_for_state(state)
    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        return default_amap, default_inspection

    amap_text = str(saved_amap or "")
    inspection_text = str(saved_inspection or "")
    if state.get("trip_source") == "synthetic_example":
        if "公开合成示例证据" not in amap_text:
            amap_text = default_amap
        if "公开合成示例证据" not in inspection_text:
            inspection_text = default_inspection
    else:
        if not amap_text.startswith("### 🛰️ 当前上传行程"):
            amap_text = default_amap
        if not inspection_text.startswith("### ⏱️ 当前上传行程"):
            inspection_text = default_inspection
    return amap_text, inspection_text


def reset_uploaded_context() -> tuple[dict[str, Any], str, str]:
    """Clear evidence when a browser selects a new local image."""

    return {}, EMPTY_AMAP_STATUS, EMPTY_INSPECTION_STATUS


def run_manual_inspection_for_state(
    state: dict[str, Any] | None,
) -> tuple[str, str]:
    """Inspect only the current trip and never borrow another trip's evidence."""

    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        raise gr.Error("请先上传行程并构建旅行数字孪生，或载入并构建合成示例。")
    if state.get("trip_source") == "synthetic_example":
        amap_panel, inspection_panel = context_panels_for_state(state)
        _, analysis = analyze_trip(state["trip"], include_cached_amap=True)
        return (
            amap_panel,
            inspection_panel
            + f"\n- 本次确定性复核：**{analysis.risk_count} 个风险 / "
            f"{analysis.total_risk_score} 分**",
        )

    _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
    return (
        UPLOADED_AMAP_PENDING,
        "\n".join(
            [
                "### ⏱️ 当前上传行程 · 手动巡检",
                "",
                f"- 已重新运行当前 TripGraph 的本地确定性规则：**{analysis.risk_count} 个风险 / {analysis.total_risk_score} 分**",
                "- 本次未调用高德 MCP 或 Managed Agent；需要实时外部证据的项目保持未核验。",
                "- 未读取、展示或套用杭州合成示例的巡检记录。",
            ]
        ),
    )


def build_twin(image_path: str | None) -> tuple[Any, list[list[Any]], str, str, dict[str, Any]]:
    if not image_path:
        raise gr.Error("请先上传图片或点击“载入合成示例”。")
    image = Path(image_path).resolve()
    if _same_image(image, SAMPLE_IMAGE_PATH):
        evidence = load_cached_vision()
        trip_payload = evidence["trip"]
        confidence = evidence["field_confidence"]
        low_fields = evidence["low_confidence_fields"]
        model = evidence["model"]
        accuracy = f"{evidence['field_accuracy']:.1%}"
        request_note = f"复用已验真的云端解析证据 · 字段准确率 {accuracy}"
    else:
        extraction, metadata = extract_trip_from_image(image)
        trip_payload = extraction.trip.model_dump(mode="json")
        confidence = extraction.field_confidence
        low_fields = extraction.low_confidence_fields
        model = metadata["model"]
        request_note = "本次图片已完成实时云端解析"
    rows = [[name, round(float(value), 3)] for name, value in sorted(confidence.items())]
    low_text = (
        "✅ 没有低于 0.8 的字段。"
        if not low_fields
        else "⚠️ 请核对后勾选确认：" + "、".join(low_fields)
    )
    state = {
        "trip": trip_payload,
        "low_confidence_fields": low_fields,
        "field_confidence": confidence,
        "trip_source": (
            "synthetic_example"
            if _same_image(image, SAMPLE_IMAGE_PATH)
            else "uploaded_image"
        ),
    }
    status = f"✅ `{model}` 图片解析完成；{request_note}。"
    return trip_payload, rows, low_text, timeline_html(trip_payload), state


def build_twin_guarded(
    image_path: str | None, browser_store: dict[str, Any] | None
) -> tuple[Any, list[list[Any]], str, str, dict[str, Any], dict[str, Any]]:
    """Apply browser/global limits only to real user-uploaded image calls."""

    if not image_path:
        raise gr.Error("请先上传图片或点击“载入合成示例”。")
    image_path_obj = Path(image_path).resolve()
    store, _ = ensure_active_session(browser_store)
    if not _same_image(image_path_obj, SAMPLE_IMAGE_PATH):
        allowed, usage = browser_can_consume(store.get("usage"), "images")
        if not allowed:
            raise gr.Error(
                f"为保护有限 Token，每个浏览器每天最多解析 "
                f"{browser_limits()['images']} 张自行上传的图片；请明日再试。"
            )
        globally_allowed, _, global_limit = reserve_global("images")
        if not globally_allowed:
            raise gr.Error(
                f"今日全站图片解析已达到 {global_limit} 次；"
                "合成示例、风险检查和 Plan B 仍可正常体验。"
            )
        store["usage"] = consume_browser(usage, "images")
    result = build_twin(image_path)
    return *result, store


def _same_image(first: Path, second: Path) -> bool:
    if not first.is_file() or not second.is_file():
        return False
    if first.resolve() == second.resolve():
        return True
    return hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()


def check_risks(state: dict[str, Any], confirmed: bool) -> str:
    if not state or "trip" not in state:
        raise gr.Error("请先构建旅行数字孪生。")
    if state.get("low_confidence_fields") and not confirmed:
        raise gr.Error("请先核对并确认低置信字段。")
    return risk_markdown(
        state["trip"],
        include_cached_amap=state.get("trip_source") == "synthetic_example",
    )


def generate_plan_b(state: dict[str, Any], confirmed: bool) -> tuple[str, str]:
    if not state or "trip" not in state:
        raise gr.Error("请先构建旅行数字孪生。")
    if state.get("low_confidence_fields") and not confirmed:
        raise gr.Error("请先核对并确认低置信字段。")
    return (
        plan_b_markdown(
            state["trip"],
            include_cached_amap=state.get("trip_source") == "synthetic_example",
        ),
        tool_trace_markdown(),
    )


def answer_question(
    question: str,
    history: list[dict[str, Any]] | None,
    state: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    text = (question or "").strip()
    if not text:
        raise gr.Error("请先输入问题。")
    trip_payload = (
        state["trip"]
        if state and isinstance(state.get("trip"), dict)
        else load_cached_vision()["trip"]
    )
    conversation = list(history or [])
    conversation.append({"role": "user", "content": text})
    try:
        answer = answer_with_trip_context(
            text,
            chat_context(
                trip_payload,
                include_cached_amap=state.get("trip_source")
                == "synthetic_example",
            ),
        )
    except Exception:
        answer = "当前模型服务暂时不可用，请稍后重试；TripGraph 和已生成的 Plan B 不受影响。"
    conversation.append({"role": "assistant", "content": answer})
    return "", conversation


def answer_question_guarded(
    question: str,
    history: list[dict[str, Any]] | None,
    state: dict[str, Any],
    browser_store: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Answer with browser caching and bounded daily public model usage."""

    text = (question or "").strip()
    if not text:
        raise gr.Error("请先输入问题。")
    store, _ = ensure_active_session(browser_store)
    if not _has_question_context(state):
        conversation = list(history or [])
        conversation.extend(
            [
                {"role": "user", "content": text},
                {
                    "role": "assistant",
                    "content": (
                        "请先上传行程单并构建旅行数字孪生，"
                        "或点击“载入合成示例”后再提问。"
                    ),
                },
            ]
        )
        return "", conversation, store
    trip_payload = (
        state["trip"]
        if state and isinstance(state.get("trip"), dict)
        else load_cached_vision()["trip"]
    )

    # The bundled golden case is fixed and fully verified. The four canonical
    # showcase questions are quota-free; paraphrases still use the browser's
    # daily allowance even when their answer can be resolved locally.
    deterministic_answer = _synthetic_example_answer(text, state)
    cache_key = _answer_cache_key(text, trip_payload)
    cached = store.get("answer_cache", {}).get(cache_key)
    if isinstance(cached, str) and cached.strip():
        conversation = list(history or [])
        conversation.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": cached},
            ]
        )
        return "", conversation, store

    if deterministic_answer is not None and _is_free_synthetic_question(text, state):
        conversation = list(history or [])
        conversation.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": deterministic_answer},
            ]
        )
        cache = dict(store.get("answer_cache") or {})
        cache[cache_key] = deterministic_answer
        store["answer_cache"] = dict(list(cache.items())[-50:])
        return "", conversation, store

    allowed, usage = browser_can_consume(store.get("usage"), "questions")
    if not allowed:
        return _quota_answer(
            text,
            history,
            f"每个浏览器每天最多 {browser_limits()['questions']} 次提问",
            store,
        )

    if deterministic_answer is not None:
        conversation = list(history or [])
        conversation.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": deterministic_answer},
            ]
        )
        store["usage"] = consume_browser(usage, "questions")
        cache = dict(store.get("answer_cache") or {})
        cache[cache_key] = deterministic_answer
        store["answer_cache"] = dict(list(cache.items())[-50:])
        return "", conversation, store

    globally_allowed, _, global_limit = reserve_global("questions")
    if not globally_allowed:
        return _quota_answer(
            text,
            history,
            f"今日全站大模型问答已达到 {global_limit} 次",
            store,
        )

    _, conversation = answer_question(text, history, state)
    store["usage"] = consume_browser(usage, "questions")
    answer = conversation[-1].get("content") if conversation else None
    if isinstance(answer, str) and answer.strip():
        cache = dict(store.get("answer_cache") or {})
        cache[cache_key] = answer
        store["answer_cache"] = dict(list(cache.items())[-50:])
    return "", conversation, store


def _synthetic_example_answer(
    question: str, state: dict[str, Any] | None
) -> str | None:
    """Return verified local answers for common questions about the golden case."""

    if not isinstance(state, dict) or state.get("trip_source") != "synthetic_example":
        return None
    normalized = "".join(
        character
        for character in question.casefold()
        if character.isalnum() or "\u4e00" <= character <= "\u9fff"
    )
    if "衔接" in normalized and ("风险" in normalized or "为什么" in normalized):
        return (
            "存在衔接风险：高铁 10:00 到达杭州东站，西湖游船 10:35 开始，"
            "中间只有 35 分钟；行程预计需要 45 分钟交通，再加 20 分钟安全缓冲，"
            "合计至少需要 65 分钟，目前缺少 30 分钟。建议保留高铁，顺延或替换游船。"
        )
    if "第二晚" in normalized and any(
        keyword in normalized for keyword in ("推荐", "住哪", "酒店", "住宿")
    ):
        return (
            "第二晚推荐 **如家精选-杭州西湖景区苏堤店**：2026-10-19 入住、"
            "10月20日退房，查询价约 **¥135/晚**，低于 Plan B 的 ¥500 增量上限。"
            "该候选来自 FlyAI 酒店查询，价格和房态请以跳转后的飞猪页面为准；"
            "TripTwin 不会代订。"
        )
    if "自动" in normalized and any(
        keyword in normalized for keyword in ("预定", "预订", "下单", "支付")
    ):
        return (
            "不会。TripTwin 只进行风险分析并提供带来源链接的候选，"
            "不会替你预订、下单或支付；最终选择和操作始终由你完成。"
        )
    if "候选" in normalized and any(
        keyword in normalized for keyword in ("来源", "来自", "哪来", "数据")
    ):
        return (
            "Plan B 的景点和酒店候选来自官方 FlyAI Skill 的真实查询结果，"
            "并保留飞猪 jumpUrl 作为来源证据，不是由模型编造；"
            "路线和天气核验则来自高德地图 MCP。"
        )
    return None


def _is_free_synthetic_question(
    question: str, state: dict[str, Any] | None
) -> bool:
    if not isinstance(state, dict) or state.get("trip_source") != "synthetic_example":
        return False
    return _normalize_showcase_question(question) in {
        "为什么存在衔接风险",
        "第二晚推荐住哪里",
        "是否会自动预定",
        "候选数据来自哪里",
    }


def _has_question_context(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    if isinstance(state.get("trip"), dict):
        return True
    return state.get("trip_source") == "synthetic_example"


def _normalize_showcase_question(question: str) -> str:
    return "".join(
        character
        for character in question.casefold()
        if character.isalnum() or "\u4e00" <= character <= "\u9fff"
    )


def _answer_cache_key(question: str, trip_payload: dict[str, Any]) -> str:
    normalized_question = " ".join(question.casefold().split())
    payload = json.dumps(
        trip_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(
        (normalized_question + "\n" + payload).encode("utf-8")
    ).hexdigest()


def _quota_answer(
    question: str,
    history: list[dict[str, Any]] | None,
    reason: str,
    store: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    conversation = list(history or [])
    conversation.extend(
        [
            {"role": "user", "content": question},
            {
                "role": "assistant",
                "content": (
                    f"{reason}，为控制使用费用，本次不再调用模型。"
                    "合成示例、风险检查和 Plan B 仍可继续使用。"
                ),
            },
        ]
    )
    return "", conversation, store


def _session_snapshot(
    trip_state: dict[str, Any] | None,
    status: str | None,
    confirmed: bool,
    risks: str | None,
    plan_b: str | None,
    trace: str | None,
    chat_history: list[dict[str, Any]] | None,
    amap_status: str | None,
    inspection_status: str | None,
) -> dict[str, Any]:
    safe_amap, safe_inspection = safe_context_panels(
        trip_state, amap_status, inspection_status
    )
    return {
        "trip_state": trip_state if isinstance(trip_state, dict) else {},
        "status": str(status or "等待载入图片。"),
        "confirmed": bool(confirmed),
        "risks": str(risks or "### 风险卡片\n\n等待检查。"),
        "plan_b": str(plan_b or "### 原方案 / Plan B\n\n等待生成。"),
        "trace": str(trace or "### Agent 工具执行轨迹摘要\n\n等待生成。"),
        "chat_history": list(chat_history or []),
        "amap_status": safe_amap,
        "inspection_status": safe_inspection,
    }


def _history_update(store: dict[str, Any]) -> gr.Dropdown:
    return gr.Dropdown(
        choices=history_choices(store),
        value=store["active_id"],
        label="历史会话",
    )


def _session_badge(session: dict[str, Any]) -> str:
    return (
        "**当前页面 Session ID：** `"
        + str(session["id"])
        + "`  \n历史保存在本浏览器；原始上传图片不会写入历史会话。"
    )


def _session_view(session: dict[str, Any]) -> tuple[Any, ...]:
    snapshot = session.get("snapshot") or {}
    trip_state = snapshot.get("trip_state")
    if not isinstance(trip_state, dict):
        trip_state = {}
    trip = trip_state.get("trip")
    confidence_map = trip_state.get("field_confidence")
    confidence_rows = (
        [[name, round(float(value), 3)] for name, value in sorted(confidence_map.items())]
        if isinstance(confidence_map, dict)
        else []
    )
    low_fields = trip_state.get("low_confidence_fields")
    if not isinstance(low_fields, list):
        low_fields = []
    low_text = (
        "✅ 没有低于 0.8 的字段。"
        if trip and not low_fields
        else "⚠️ 请核对后勾选确认：" + "、".join(map(str, low_fields))
        if low_fields
        else "尚未解析。"
    )
    timeline = timeline_html(trip) if isinstance(trip, dict) else ""
    safe_amap, safe_inspection = safe_context_panels(
        trip_state,
        snapshot.get("amap_status"),
        snapshot.get("inspection_status"),
    )
    return (
        None,
        snapshot.get("status") or "等待载入图片。",
        trip if isinstance(trip, dict) else None,
        confidence_rows,
        low_text,
        timeline,
        bool(snapshot.get("confirmed")),
        snapshot.get("risks") or "### 风险卡片\n\n等待检查。",
        snapshot.get("plan_b") or "### 原方案 / Plan B\n\n等待生成。",
        snapshot.get("trace") or "### Agent 工具执行轨迹摘要\n\n等待生成。",
        "",
        snapshot.get("chat_history") or [],
        trip_state,
        safe_amap,
        safe_inspection,
    )


def initialize_session_history(browser_store: Any) -> tuple[Any, ...]:
    store, session = ensure_active_session(browser_store)
    return store, _history_update(store), _session_badge(session), *_session_view(session)


def persist_current_session(
    browser_store: Any,
    trip_state: dict[str, Any] | None,
    status: str | None,
    confirmed: bool,
    risks: str | None,
    plan_b: str | None,
    trace: str | None,
    chat_history: list[dict[str, Any]] | None,
    amap_status: str | None,
    inspection_status: str | None,
) -> tuple[dict[str, Any], gr.Dropdown, str]:
    snapshot = _session_snapshot(
        trip_state,
        status,
        confirmed,
        risks,
        plan_b,
        trace,
        chat_history,
        amap_status,
        inspection_status,
    )
    store = save_active_session(browser_store, snapshot)
    session = next(item for item in store["sessions"] if item["id"] == store["active_id"])
    return store, _history_update(store), _session_badge(session)


def create_new_history_session(
    browser_store: Any,
    trip_state: dict[str, Any] | None,
    status: str | None,
    confirmed: bool,
    risks: str | None,
    plan_b: str | None,
    trace: str | None,
    chat_history: list[dict[str, Any]] | None,
    amap_status: str | None,
    inspection_status: str | None,
) -> tuple[Any, ...]:
    snapshot = _session_snapshot(
        trip_state,
        status,
        confirmed,
        risks,
        plan_b,
        trace,
        chat_history,
        amap_status,
        inspection_status,
    )
    store, session = create_session(browser_store, current_snapshot=snapshot)
    return store, _history_update(store), _session_badge(session), *_session_view(session)


def open_history_session(
    target_id: str,
    browser_store: Any,
    trip_state: dict[str, Any] | None,
    status: str | None,
    confirmed: bool,
    risks: str | None,
    plan_b: str | None,
    trace: str | None,
    chat_history: list[dict[str, Any]] | None,
    amap_status: str | None,
    inspection_status: str | None,
) -> tuple[Any, ...]:
    if not target_id:
        raise gr.Error("请先选择一个历史会话。")
    snapshot = _session_snapshot(
        trip_state,
        status,
        confirmed,
        risks,
        plan_b,
        trace,
        chat_history,
        amap_status,
        inspection_status,
    )
    try:
        store, session = switch_session(
            browser_store, target_id, current_snapshot=snapshot
        )
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    return store, _history_update(store), _session_badge(session), *_session_view(session)


def create_app() -> gr.Blocks:
    with gr.Blocks(title="TripTwin 旅行数字孪生守护者") as demo:
        state = gr.State({})
        browser_store = gr.BrowserState(
            default_value={"version": 1, "active_id": None, "sessions": []},
            storage_key="triptwin_sessions_v1",
            secret=os.getenv(
                "TRIPTWIN_BROWSER_STATE_SECRET", "triptwin-local-v1"
            ),
        )
        gr.HTML("<div class='hero'><h1>TripTwin 旅行数字孪生守护者</h1><p>把行程截图变成 TripGraph，结合真实 FlyAI 与高德 MCP 证据发现衔接、日期、预算、天气和体力风险，并生成可验证 Plan B。</p></div>")
        gr.HTML(
            "<div class='quota-card'><b>使用额度说明：</b>腰包扁扁，费用有限。"
            f"每个浏览器每天最多 {browser_limits()['questions']} 次提问、"
            f"{browser_limits()['images']} 次自行上传图片解析；"
            f"全站每天最多 {global_limits()['questions']} 次大模型问答、"
            f"{global_limits()['images']} 次图片解析。重复问题会复用缓存。"
            "达到限制后，合成示例、风险检查和 Plan B 仍可正常体验。</div>"
        )
        gr.Markdown(f"> **隐私与服务声明：** {DISCLAIMER}")
        with gr.Row(elem_classes=["session-bar"]):
            with gr.Column(scale=3):
                history_select = gr.Dropdown(
                    choices=[], label="历史会话", interactive=True
                )
                session_badge = gr.Markdown("正在初始化独立会话……")
            with gr.Column(scale=1, min_width=180):
                open_session_button = gr.Button("打开所选会话")
                new_session_button = gr.Button(
                    "＋ 新建独立会话", variant="secondary"
                )
        with gr.Row():
            with gr.Column(scale=1):
                image = gr.Image(type="filepath", label="① 上传行程截图")
                load_button = gr.Button("载入合成示例", variant="secondary")
                build_button = gr.Button("② 构建旅行数字孪生", variant="primary")
                status = gr.Markdown("等待载入图片。")
            with gr.Column(scale=1):
                trip_json = gr.JSON(label="结构化 TripGraph")
                confidence = gr.Dataframe(
                    headers=["字段", "置信度"],
                    datatype=["str", "number"],
                    interactive=False,
                    label="字段置信度",
                )
                low_confidence = gr.Markdown("尚未解析。")
                confirmed = gr.Checkbox(label="我已核对并确认低置信字段")
        timeline = gr.HTML(label="TripGraph 时间线")
        with gr.Row():
            check_button = gr.Button("③ 检查风险", variant="primary")
            recheck_button = gr.Button("重新检查")
            plan_button = gr.Button("④ 生成 Plan B", variant="primary")
        with gr.Row():
            risks = gr.Markdown("### 风险卡片\n\n等待检查。")
            plan_b = gr.Markdown("### 原方案 / Plan B\n\n等待生成。")
        trace = gr.Markdown("### Agent 工具执行轨迹摘要\n\n等待生成。")
        with gr.Row():
            amap_status = gr.Markdown(EMPTY_AMAP_STATUS)
            inspection_status = gr.Markdown(EMPTY_INSPECTION_STATUS)
        inspect_button = gr.Button("⑤ 手动巡检", variant="secondary")
        with gr.Row():
            with gr.Column(scale=1, elem_classes=["guide-card"]):
                gr.HTML(
                    "<div class='guide-title-row'><h3>💡 演示操作提示</h3>"
                    "<span class='example-free-note'>使用“载入合成示例”后，以下四个标准问题"
                    "不消耗每日提问额度；"
                    "请完整复制到“向 TripTwin 提问”中，以免改写后计入额度。</span></div>"
                )
                gr.Markdown(
                    """1. **载入合成示例**
2. **构建旅行数字孪生**
3. **检查风险**
4. **生成 Plan B**

完成后可以提问：
- 为什么存在衔接风险？
- 第二晚推荐住哪里？
- 是否会自动预定？
- 候选数据来自哪里？"""
                )
            with gr.Column(scale=2, elem_classes=["chat-panel"]):
                chatbot = gr.Chatbot(
                    label="TripTwin 智能回复",
                    layout="bubble",
                    height=300,
                    placeholder="这里会以对话气泡显示基于当前 TripGraph 和 Plan B 的回答。",
                )
                with gr.Row():
                    question = gr.Textbox(
                        label="向 TripTwin 提问",
                        placeholder="可自由提问，不限于示例问题",
                        scale=5,
                    )
                    ask_button = gr.Button("发送", variant="primary", scale=1)

        session_inputs = [
            browser_store,
            state,
            status,
            confirmed,
            risks,
            plan_b,
            trace,
            chatbot,
            amap_status,
            inspection_status,
        ]
        session_outputs = [browser_store, history_select, session_badge]
        view_outputs = [
            image,
            status,
            trip_json,
            confidence,
            low_confidence,
            timeline,
            confirmed,
            risks,
            plan_b,
            trace,
            question,
            chatbot,
            state,
            amap_status,
            inspection_status,
        ]

        demo.load(
            initialize_session_history,
            inputs=[browser_store],
            outputs=[*session_outputs, *view_outputs],
        )
        load_event = load_button.click(
            load_example, outputs=[image, status, state], api_name="load_example"
        )
        image.upload(
            reset_uploaded_context,
            outputs=[state, amap_status, inspection_status],
            api_name=False,
        )
        load_context_event = load_event.then(
            context_panels_for_state,
            inputs=state,
            outputs=[amap_status, inspection_status],
        )
        load_context_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        build_event = build_button.click(
            build_twin_guarded,
            inputs=[image, browser_store],
            outputs=[
                trip_json,
                confidence,
                low_confidence,
                timeline,
                state,
                browser_store,
            ],
            api_name=False,
        ).then(lambda: "✅ TripGraph 已构建。", outputs=status)
        build_context_event = build_event.then(
            context_panels_for_state,
            inputs=state,
            outputs=[amap_status, inspection_status],
        )
        build_context_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        check_event = check_button.click(
            check_risks,
            inputs=[state, confirmed],
            outputs=risks,
            api_name="check_risks",
        )
        check_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        recheck_event = recheck_button.click(
            check_risks, inputs=[state, confirmed], outputs=risks
        )
        recheck_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        plan_event = plan_button.click(
            generate_plan_b,
            inputs=[state, confirmed],
            outputs=[plan_b, trace],
            api_name="generate_plan_b",
        )
        plan_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        inspect_event = inspect_button.click(
            run_manual_inspection_for_state,
            inputs=[state],
            outputs=[amap_status, inspection_status],
            api_name=False,
        )
        inspect_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        ask_event = ask_button.click(
            answer_question_guarded,
            inputs=[question, chatbot, state, browser_store],
            outputs=[question, chatbot, browser_store],
            api_name=False,
        )
        ask_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        submit_event = question.submit(
            answer_question_guarded,
            inputs=[question, chatbot, state, browser_store],
            outputs=[question, chatbot, browser_store],
            api_name=False,
        )
        submit_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        new_session_button.click(
            create_new_history_session,
            inputs=session_inputs,
            outputs=[*session_outputs, *view_outputs],
            api_name="new_session",
        )
        open_session_button.click(
            open_history_session,
            inputs=[history_select, *session_inputs],
            outputs=[*session_outputs, *view_outputs],
            api_name="open_session",
        )
    return demo


demo = create_app()


if __name__ == "__main__":
    server_port = int(
        os.getenv("PORT", os.getenv("GRADIO_SERVER_PORT", "7860"))
    )
    demo.launch(
        inbrowser=os.getenv("TRIPTWIN_NO_BROWSER") != "1",
        show_error=False,
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=server_port,
        theme=gr.themes.Soft(),
        css=APP_CSS,
        allowed_paths=[str(Path(__file__).resolve().parent / "assets")],
    )
