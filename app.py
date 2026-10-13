"""TripTwin production-candidate Gradio application."""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import os
import secrets
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
    clear_sessions,
    create_session,
    delete_session,
    ensure_active_session,
    history_choices,
    save_active_session,
    switch_session,
)
from triptwin.runtime_agent import run_live_trip
from triptwin.exporter import export_trip_files
from triptwin.vision_parser import extract_trip_from_images
from triptwin.usage_guard import (
    browser_can_consume,
    browser_limits,
    consume_browser,
    global_limits,
    release_reservation,
    reserve_client,
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
.gradio-container {max-width:1180px!important;margin:auto!important}
.step-card {border:1px solid #e0e7f3!important;border-radius:18px!important;background:#fff!important;padding:20px!important;box-shadow:0 3px 16px #17233c06;margin-top:12px!important}
.step-heading {display:flex;gap:12px;align-items:center;margin-bottom:8px}
.step-number {display:grid;place-items:center;flex-shrink:0;width:34px;height:34px;border-radius:11px;background:#635bff;color:white;font-weight:700}
.step-heading h2 {font-size:19px;margin:0;color:#17233c}.step-heading p {margin:3px 0 0;color:#667085;font-size:13px}
.step-nav {display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.step-nav a {padding:8px 12px;background:#eef2ff;border-radius:20px;text-decoration:none;color:#5145cd;font-size:13px}
.step-card {scroll-margin-top:20px}
.session-bar {align-items:center!important}.session-bar button {min-height:38px!important}
@media(max-width:640px) {.step-card {padding:14px!important}.hero {padding:18px}.timeline-item {grid-template-columns:100px 1fr;gap:10px}}
#tripgraph-editor .codemirror-wrapper {height:360px!important;max-height:360px!important;overflow:hidden!important}
#tripgraph-editor .cm-editor {height:100%!important;max-height:100%!important}
#tripgraph-editor .cm-scroller {height:100%!important;max-height:100%!important;overflow-y:auto!important}
/* Keep ambient motion behind stationary, readable cards. */
body {background:#172440!important;isolation:isolate}
gradio-app {background:transparent!important}
body::before {content:"";position:fixed;inset:-20%;z-index:-2;pointer-events:none;background:radial-gradient(ellipse at 18% 24%,#28769d 0%,transparent 42%),radial-gradient(ellipse at 82% 28%,#684494 0%,transparent 40%),radial-gradient(ellipse at 50% 86%,#275477 0%,transparent 45%),#172440;animation:aurora-drift 26s ease-in-out infinite alternate;will-change:transform}
body::after {content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;background-image:linear-gradient(#7bc9ff09 1px,transparent 1px),linear-gradient(90deg,#7bc9ff09 1px,transparent 1px);background-size:54px 54px;mask-image:linear-gradient(to bottom,#000,transparent 95%)}
.gradio-container {background:transparent!important;padding-top:24px!important;padding-bottom:36px!important}
.hero {position:relative;overflow:hidden;background:linear-gradient(115deg,#244562e8,#403965e8);border:1px solid #72c9ff66;box-shadow:0 16px 60px #0004,inset 0 1px 0 #ffffff14;padding:30px}
.hero::before {content:"";position:absolute;width:280px;height:280px;right:-60px;top:-170px;border-radius:50%;background:#67bfff28;filter:blur(25px);pointer-events:none}
.hero h1 {color:#f0f8ff;letter-spacing:.5px}.hero p {color:#b7cfe4;line-height:1.8}
.step-card {background:linear-gradient(135deg,#fffffff7,#eef5fff5)!important;border:1px solid #b8d7f7aa!important;border-radius:20px!important;box-shadow:0 12px 38px #0003,inset 0 1px 0 #fff!important}
.step-number {background:linear-gradient(140deg,#277ad6,#7151e8);box-shadow:0 4px 14px #536fe640}
.step-nav a {color:#d5eaff;background:#1a3158b3;border:1px solid #8cbcff40;transition:background .2s,box-shadow .2s}
.step-nav a:hover {background:#304778;box-shadow:0 0 18px #6fa9ff30}
.quota-card {background:#2b3b58e8;color:#d3dfef;border-color:#7699cd55;line-height:1.8;box-shadow:0 8px 26px #0002}.quota-card b {color:#a9d9ff}
#service-notice {background:#253751c9;border:1px solid #799ecb33;border-radius:14px;padding:10px 16px;color:#cfdeee!important}
#service-notice p,#service-notice strong {color:#cfdeee!important}#service-notice blockquote {border-color:#70b9ef}
#session-management {background:#eaf3fff2;border:1px solid #bbdcff80;border-radius:14px;box-shadow:0 8px 25px #0002}
.guide-card {background:linear-gradient(120deg,#edf6ff,#f4f0ff);border-color:#ccdafa}.guide-card h3 {color:#314a83}.guide-card p,.guide-card li,.example-free-note {color:#4b5d80}
footer {color:#b7cfe4!important}footer a,footer button {color:#b7cfe4!important}
@keyframes aurora-drift {from {transform:translate3d(-2%,-1%,0) rotate(-3deg)}to {transform:translate3d(2%,2%,0) rotate(3deg)}}
@media(prefers-reduced-motion:reduce) {body::before {animation:none;will-change:auto}.step-nav a {transition:none}}
@media(max-width:640px) {body::before {animation:none;will-change:auto}.hero {padding:20px}}
"""

BROWSER_STATE_SECRET = os.getenv("TRIPTWIN_BROWSER_STATE_SECRET") or secrets.token_urlsafe(32)
RATE_LIMIT_SALT = os.getenv("TRIPTWIN_RATE_LIMIT_SALT") or secrets.token_urlsafe(32)


def load_example() -> tuple[list[str], str, dict[str, str]]:
    return (
        [str(SAMPLE_IMAGE_PATH)],
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


def _live_amap_panel(inspection: Any) -> str:
    return amap_inspection_markdown(inspection).replace(
        "### 🛰️ 空间与天气核验",
        "### 🛰️ 当前上传行程 · 空间与天气核验",
        1,
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


def reset_uploaded_context() -> tuple[dict[str, Any], str, str, bool]:
    """Clear evidence when a browser selects a new local image."""

    return {}, EMPTY_AMAP_STATUS, EMPTY_INSPECTION_STATUS, False


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

    if isinstance(state.get("live_inspection"), dict):
        from triptwin.live_context import AmapInspection

        inspection = AmapInspection.model_validate(state["live_inspection"])
        _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
        return (
            _live_amap_panel(inspection),
            "\n".join(
                [
                    "### ⏱️ 当前上传行程 · 实时巡检",
                    "",
                    f"- 最近实时核验：**{state.get('live_generated_at', '未知')}**",
                    f"- 当前确定性结果：**{analysis.risk_count} 个风险 / {analysis.total_risk_score} 分**",
                    "- 外部事实来自当前会话的高德 MCP；候选来自当前会话的 FlyAI 查询。",
                ]
            ),
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


def _image_paths(value: Any) -> list[Path]:
    values = value if isinstance(value, list) else [value] if value else []
    paths: list[Path] = []
    for item in values:
        candidate = item.get("path") if isinstance(item, dict) else item
        if isinstance(candidate, (str, os.PathLike)) and str(candidate):
            paths.append(Path(candidate).resolve())
    return paths


def _is_sample_upload(paths: list[Path]) -> bool:
    return len(paths) == 1 and _same_image(paths[0], SAMPLE_IMAGE_PATH)


def build_twin(image_paths: Any) -> tuple[str, list[list[Any]], str, str, dict[str, Any]]:
    paths = _image_paths(image_paths)
    if not paths:
        raise gr.Error("请先上传图片或点击“载入合成示例”。")
    if _is_sample_upload(paths):
        evidence = load_cached_vision()
        trip_payload = evidence["trip"]
        confidence = evidence["field_confidence"]
        low_fields = evidence["low_confidence_fields"]
        model = evidence["model"]
        accuracy = f"{evidence['field_accuracy']:.1%}"
        request_note = f"复用已验真的云端解析证据 · 字段准确率 {accuracy}"
    else:
        extraction, metadata = extract_trip_from_images(paths)
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
            if _is_sample_upload(paths)
            else "uploaded_image"
        ),
    }
    state["parse_summary"] = f"`{model}` · {request_note}"
    return (
        json.dumps(trip_payload, ensure_ascii=False, indent=2),
        rows,
        low_text,
        timeline_html(trip_payload),
        state,
    )


def build_twin_guarded(
    image_paths: Any,
    privacy_confirmed: bool,
    browser_store: dict[str, Any] | None,
    request: gr.Request | None = None,
) -> tuple[str, list[list[Any]], str, str, dict[str, Any], dict[str, Any]]:
    """Apply browser/global limits only to real user-uploaded image calls."""

    paths = _image_paths(image_paths)
    if not paths:
        raise gr.Error("请先上传图片或点击“载入合成示例”。")
    store, _ = ensure_active_session(browser_store)
    client_key = _anonymous_client_key(request)
    client_reserved = False
    global_reserved = False
    if not _is_sample_upload(paths):
        if not privacy_confirmed:
            raise gr.Error("请先确认图片已遮挡身份证号、手机号、票号等敏感信息。")
        allowed, usage = browser_can_consume(store.get("usage"), "images")
        if not allowed:
            raise gr.Error(
                f"为保护有限 Token，每个浏览器每天最多解析 "
                f"{browser_limits()['images']} 张自行上传的图片；请明日再试。"
            )
        if client_key:
            client_allowed, _, client_limit = reserve_client(client_key, "images")
            if not client_allowed:
                raise gr.Error(f"当前匿名访客今日已达到 {client_limit} 次图片解析上限。")
            client_reserved = True
        globally_allowed, _, global_limit = reserve_global("images")
        if not globally_allowed:
            if client_reserved:
                release_reservation("client", client_key, "images")
            raise gr.Error(
                f"今日全站图片解析已达到 {global_limit} 次；"
                "合成示例、确定性风险检查和已生成结果仍可查看。"
            )
        global_reserved = True
    try:
        result = build_twin(paths)
    except Exception:
        if global_reserved:
            release_reservation("global", "all", "images")
        if client_reserved:
            release_reservation("client", client_key, "images")
        raise
    if not _is_sample_upload(paths):
        store["usage"] = consume_browser(usage, "images")
    return *result, store


def _anonymous_client_key(request: gr.Request | None) -> str:
    if request is None:
        return ""
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", ""))
    headers = getattr(request, "headers", {}) or {}
    user_agent = str(headers.get("user-agent", ""))
    if not host and not user_agent:
        return ""
    return hashlib.sha256(
        (host + "\n" + user_agent + "\n" + RATE_LIMIT_SALT).encode("utf-8")
    ).hexdigest()


def apply_tripgraph_edits(
    trip_json_text: str, state: dict[str, Any] | None
) -> tuple[str, str, dict[str, Any], str, bool]:
    """Validate user corrections before replacing the active TripGraph."""

    try:
        payload = json.loads(trip_json_text)
        from triptwin.models import Trip

        trip = Trip.model_validate(payload)
    except Exception as exc:
        raise gr.Error(f"TripGraph 修改未通过校验：{exc}") from None
    updated = dict(state or {})
    updated["trip"] = trip.model_dump(mode="json")
    updated["trip_source"] = "user_corrected"
    updated.pop("live_candidate_artifact", None)
    updated.pop("live_inspection", None)
    return (
        trip.model_dump_json(indent=2),
        timeline_html(updated["trip"]),
        updated,
        "✅ 修改已通过类型、引用与依赖环校验；请重新检查风险。",
        False,
    )


def export_current_trip(state: dict[str, Any] | None) -> list[str]:
    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        raise gr.Error("请先构建旅行数字孪生。")
    return export_trip_files(state["trip"])


def render_state_trip(state: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        return "", ""
    return (
        json.dumps(state["trip"], ensure_ascii=False, indent=2),
        timeline_html(state["trip"]),
    )


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


def generate_plan_b(
    state: dict[str, Any], confirmed: bool
) -> tuple[str, str, dict[str, Any], str, str]:
    if not state or "trip" not in state:
        raise gr.Error("请先构建旅行数字孪生。")
    if state.get("low_confidence_fields") and not confirmed:
        raise gr.Error("请先核对并确认低置信字段。")
    if state.get("trip_source") == "synthetic_example":
        amap_panel, inspection_panel = context_panels_for_state(state)
        return (
            plan_b_markdown(state["trip"], include_cached_amap=True),
            tool_trace_markdown(),
            state,
            amap_panel,
            inspection_panel,
        )

    if isinstance(state.get("live_candidate_artifact"), dict) and isinstance(
        state.get("live_inspection"), dict
    ):
        from triptwin.live_context import AmapInspection

        inspection = AmapInspection.model_validate(state["live_inspection"])
        _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
        inspection_panel = "\n".join(
            [
                "### ⏱️ 当前上传行程 · 实时巡检",
                "",
                f"- 最近实时核验：**{state.get('live_generated_at', '未知')}**",
                f"- 云端会话：`{state.get('managed_session', '已脱敏')}`",
                f"- 当前确定性结果：**{analysis.risk_count} 个风险 / {analysis.total_risk_score} 分**",
            ]
        )
        return (
            plan_b_markdown(
                state["trip"],
                include_cached_amap=False,
                candidate_artifact=state["live_candidate_artifact"],
                require_simulation=True,
            ),
            tool_trace_markdown(state["live_candidate_artifact"], inspection),
            state,
            _live_amap_panel(inspection),
            inspection_panel,
        )

    try:
        result = run_live_trip(state["trip"])
    except Exception as exc:
        raise gr.Error(
            "当前行程实时核验失败，TripTwin 已停止生成，未套用任何示例数据："
            + str(exc)
        ) from None
    updated = dict(state)
    updated.update(
        {
            "trip": result.trip,
            "live_candidate_artifact": result.candidate_artifact,
            "live_inspection": result.inspection.model_dump(mode="json"),
            "live_generated_at": result.generated_at,
            "managed_session": result.session_id_masked,
        }
    )
    inspection_panel = "\n".join(
        [
            "### ⏱️ 当前上传行程 · 实时巡检",
            "",
            f"- 完成时间：**{result.generated_at}**",
            f"- 云端会话：`{result.session_id_masked}`（已脱敏）",
            f"- 运行状态：`{result.run_status}` · 工具调用 **{result.tool_call_count}** · 错误 **{result.error_count}**",
            f"- 当前确定性结果：**{result.analysis.risk_count} 个风险 / {result.analysis.total_risk_score} 分**",
        ]
    )
    return (
        plan_b_markdown(
            result.trip,
            include_cached_amap=False,
            candidate_artifact=result.candidate_artifact,
            require_simulation=True,
        ),
        tool_trace_markdown(result.candidate_artifact, result.inspection),
        updated,
        _live_amap_panel(result.inspection),
        inspection_panel,
    )


def generate_plan_b_guarded(
    state: dict[str, Any],
    confirmed: bool,
    browser_store: dict[str, Any] | None,
    request: gr.Request | None = None,
) -> tuple[str, str, dict[str, Any], str, str, dict[str, Any]]:
    store, _ = ensure_active_session(browser_store)
    if state.get("trip_source") == "synthetic_example":
        result = generate_plan_b(state, confirmed)
        return *result, store
    if isinstance(state.get("live_candidate_artifact"), dict):
        result = generate_plan_b(state, confirmed)
        return *result, store

    allowed, usage = browser_can_consume(store.get("usage"), "agent_runs")
    if not allowed:
        raise gr.Error(
            f"当前浏览器今天最多执行 {browser_limits()['agent_runs']} 次实时工具核验。"
        )
    client_key = _anonymous_client_key(request)
    client_reserved = False
    if client_key:
        client_allowed, _, client_limit = reserve_client(client_key, "agent_runs")
        if not client_allowed:
            raise gr.Error(f"当前匿名访客今日已达到 {client_limit} 次实时工具核验上限。")
        client_reserved = True
    global_allowed, _, global_limit = reserve_global("agent_runs")
    if not global_allowed:
        if client_reserved:
            release_reservation("client", client_key, "agent_runs")
        raise gr.Error(f"今日全站实时工具核验已达到 {global_limit} 次。")
    try:
        result = generate_plan_b(state, confirmed)
    except Exception:
        release_reservation("global", "all", "agent_runs")
        if client_reserved:
            release_reservation("client", client_key, "agent_runs")
        raise
    store["usage"] = consume_browser(usage, "agent_runs")
    return *result, store


def run_live_inspection_guarded(
    state: dict[str, Any],
    confirmed: bool,
    browser_store: dict[str, Any] | None,
    request: gr.Request | None = None,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        raise gr.Error("请先构建旅行数字孪生。")
    if state.get("low_confidence_fields") and not confirmed:
        raise gr.Error("请先核对并确认低置信字段，再执行外部工具核验。")
    _, _, updated, amap_panel, inspection_panel, store = generate_plan_b_guarded(
        state, confirmed, browser_store, request
    )
    return amap_panel, inspection_panel, updated, store


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
                candidate_artifact=state.get("live_candidate_artifact"),
                amap_inspection=state.get("live_inspection"),
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
    request: gr.Request | None = None,
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
    cache_key = _answer_cache_key(
        text,
        {
            "trip": trip_payload,
            "candidate_artifact": state.get("live_candidate_artifact"),
            "live_generated_at": state.get("live_generated_at"),
        },
    )
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

    client_key = _anonymous_client_key(request)
    client_reserved = False
    if client_key:
        client_allowed, _, client_limit = reserve_client(client_key, "questions")
        if not client_allowed:
            return _quota_answer(
                text, history, f"当前匿名访客每天最多 {client_limit} 次提问", store
            )
        client_reserved = True

    allowed, usage = browser_can_consume(store.get("usage"), "questions")
    if not allowed:
        if client_reserved:
            release_reservation("client", client_key, "questions")
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
        if client_reserved:
            release_reservation("client", client_key, "questions")
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
                    "合成示例、确定性风险检查和已生成结果仍可继续查看。"
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
        json.dumps(trip, ensure_ascii=False, indent=2) if isinstance(trip, dict) else "",
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
        None,
        False,
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


def delete_current_history_session(browser_store: Any) -> tuple[Any, ...]:
    store, active = ensure_active_session(browser_store)
    store, session = delete_session(store, active["id"])
    return store, _history_update(store), _session_badge(session), *_session_view(session)


def clear_all_history_sessions(browser_store: Any) -> tuple[Any, ...]:
    store, session = clear_sessions(browser_store)
    return store, _history_update(store), _session_badge(session), *_session_view(session)


def create_app() -> gr.Blocks:
    with gr.Blocks(title="TripTwin 旅行数字孪生守护者") as demo:
        state = gr.State({})
        browser_store = gr.BrowserState(
            default_value={"version": 1, "active_id": None, "sessions": []},
            storage_key="triptwin_sessions_v1",
            secret=BROWSER_STATE_SECRET,
        )
        gr.HTML("<div class='hero'><h1>TripTwin 旅行数字孪生守护者</h1><p>把行程截图变成 TripGraph，结合真实 FlyAI 与高德 MCP 证据发现衔接、日期、预算、天气和体力风险，并生成可验证 Plan B。</p></div>")
        gr.HTML(
            "<div class='quota-card'><b>使用额度说明：</b>作者腰包扁扁，短期内可承担的费用有限，"
            "后续将逐步增加 AI 使用次数。"
            f"当前版本每个浏览器每天最多 {browser_limits()['questions']} 次提问、"
            f"{browser_limits()['images']} 次自行上传图片解析；"
            f"全站每天最多 {global_limits()['questions']} 次大模型问答、"
            f"{global_limits()['images']} 次图片解析；每位访客每天最多 "
            f"{browser_limits()['agent_runs']} 次实时高德/FlyAI 核验，"
            f"全站最多 {global_limits()['agent_runs']} 次。重复问题会复用缓存。"
            "达到限制后，合成示例、确定性风险检查和已生成结果仍可查看。</div>"
        )
        gr.Markdown(f"> **隐私与服务声明：** {DISCLAIMER}", elem_id="service-notice")
        gr.HTML("<nav class='step-nav' aria-label='使用步骤'><a href='#step-import'>1 导入行程</a><a href='#step-build'>2 构建与校对</a><a href='#step-risk'>3 检查风险</a><a href='#step-plan'>4 生成 Plan B</a><a href='#step-chat'>5 提问与导出</a></nav>")
        with gr.Accordion("我的会话 · 新建 / 查看历史", open=False, elem_id="session-management"):
            with gr.Row(elem_classes=["session-bar"]):
                history_select = gr.Dropdown(
                    choices=[], label="历史会话", interactive=True, scale=3
                )
                open_session_button = gr.Button("打开所选会话")
                new_session_button = gr.Button(
                    "＋ 新建独立会话", variant="secondary"
                )
            session_badge = gr.Markdown("正在初始化独立会话……")
            with gr.Row():
                delete_session_button = gr.Button("删除当前会话", variant="stop")
                clear_sessions_button = gr.Button("清空全部历史", variant="stop")
        with gr.Column(elem_id="step-import", elem_classes=["step-card"]):
            gr.HTML("<div class='step-heading'><span class='step-number'>1</span><div><h2>导入行程</h2><p>上传自己的截图，或载入合成示例快速体验。完成后继续第 2 步。</p></div></div>")
            with gr.Row():
                image = gr.File(
                    type="filepath",
                    file_count="multiple",
                    file_types=["image"],
                    label="① 上传 1–5 张行程截图",
                    scale=3,
                )
                load_button = gr.Button("载入合成示例", variant="secondary", scale=1)
            privacy_confirmed = gr.Checkbox(
                label="自行上传前，我已遮挡身份证号、手机号和票号（合成示例无需勾选）"
            )
        with gr.Column(elem_id="step-build", elem_classes=["step-card"]):
            gr.HTML("<div class='step-heading'><span class='step-number'>2</span><div><h2>构建与校对行程</h2><p>点击构建后查看时间线；如需修正，展开校对区域。确认后继续第 3 步。</p></div></div>")
            build_button = gr.Button("② 构建旅行数字孪生", variant="primary")
            status = gr.Markdown("等待载入图片。")
            timeline = gr.HTML(label="TripGraph 时间线")
            with gr.Accordion("校对与修改 · 结构化行程", open=False):
                trip_json = gr.Code(
                    language="json",
                    label="结构化 TripGraph（可校对修改）",
                    interactive=True,
                    lines=14,
                    max_lines=14,
                    elem_id="tripgraph-editor",
                )
                apply_edits_button = gr.Button("应用并校验 TripGraph 修改")
            with gr.Accordion("查看字段识别置信度", open=False):
                confidence = gr.Dataframe(
                    headers=["字段", "置信度"],
                    datatype=["str", "number"],
                    interactive=False,
                    label="字段置信度",
                    max_height=240,
                )
            low_confidence = gr.Markdown("尚未解析。")
            confirmed = gr.Checkbox(label="我已核对并确认低置信字段")
        with gr.Column(elem_id="step-risk", elem_classes=["step-card"]):
            gr.HTML("<div class='step-heading'><span class='step-number'>3</span><div><h2>检查旅行风险</h2><p>检查时间衔接、日期、预算与体力等风险。修改行程后可重新检查。</p></div></div>")
            with gr.Row():
                check_button = gr.Button("③ 检查风险", variant="primary")
                recheck_button = gr.Button("重新检查")
            risks = gr.Markdown("### 风险卡片\n\n等待检查。")
        with gr.Column(elem_id="step-plan", elem_classes=["step-card"]):
            gr.HTML("<div class='step-heading'><span class='step-number'>4</span><div><h2>生成 Plan B</h2><p>基于当前行程生成替代方案。自行上传的行程会执行实时工具核验。</p></div></div>")
            plan_button = gr.Button("④ 生成 Plan B", variant="primary")
            plan_b = gr.Markdown("### 原方案 / Plan B\n\n等待生成。")
            with gr.Accordion("查看工具证据与实时巡检", open=False):
                inspect_button = gr.Button("查看 / 执行实时巡检", variant="secondary")
                amap_status = gr.Markdown(EMPTY_AMAP_STATUS)
                inspection_status = gr.Markdown(EMPTY_INSPECTION_STATUS)
                trace = gr.Markdown("### Agent 工具执行轨迹摘要\n\n等待生成。")
        with gr.Column(elem_id="step-chat", elem_classes=["step-card"]):
            gr.HTML("<div class='step-heading'><span class='step-number'>5</span><div><h2>提问与导出</h2><p>针对当前行程提问，或导出 JSON 与日历文件保存结果。</p></div></div>")
            with gr.Column(elem_classes=["guide-card"]):
                gr.HTML(
                    "<div class='guide-title-row'><h3>💡 演示操作提示</h3>"
                    "<span class='example-free-note'>使用“载入合成示例”后，以下四个标准问题"
                    "不消耗每日提问额度；"
                    "请完整复制到“向 TripTwin 提问”中，以免改写后计入额度。</span></div>"
                )
                gr.Markdown(
                    """完成前面的步骤后，可以提问：
- 为什么存在衔接风险？
- 第二晚推荐住哪里？
- 是否会自动预定？
- 候选数据来自哪里？"""
                )
            with gr.Column(elem_classes=["chat-panel"]):
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
            with gr.Accordion("导出行程 · JSON / 日历 ICS", open=False):
                export_button = gr.Button("导出 TripGraph JSON 与日历 ICS")
                export_files = gr.File(
                    label="导出文件", file_count="multiple", interactive=False
                )

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
            export_files,
            privacy_confirmed,
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
            outputs=[state, amap_status, inspection_status, privacy_confirmed],
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
            inputs=[image, privacy_confirmed, browser_store],
            outputs=[
                trip_json,
                confidence,
                low_confidence,
                timeline,
                state,
                browser_store,
            ],
            api_name=False,
        ).then(
            lambda current: "✅ TripGraph 已构建；" + str(current.get("parse_summary", "")),
            inputs=[state],
            outputs=status,
        )
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
        edit_event = apply_edits_button.click(
            apply_tripgraph_edits,
            inputs=[trip_json, state],
            outputs=[trip_json, timeline, state, status, confirmed],
            api_name=False,
        )
        edit_event.then(
            context_panels_for_state,
            inputs=state,
            outputs=[amap_status, inspection_status],
        ).then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        export_button.click(
            export_current_trip,
            inputs=[state],
            outputs=[export_files],
            api_name=False,
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
            generate_plan_b_guarded,
            inputs=[state, confirmed, browser_store],
            outputs=[plan_b, trace, state, amap_status, inspection_status, browser_store],
            api_name=False,
        )
        plan_render_event = plan_event.then(
            render_state_trip,
            inputs=[state],
            outputs=[trip_json, timeline],
        )
        plan_render_event.then(
            persist_current_session,
            inputs=session_inputs,
            outputs=session_outputs,
        )
        inspect_event = inspect_button.click(
            run_live_inspection_guarded,
            inputs=[state, confirmed, browser_store],
            outputs=[amap_status, inspection_status, state, browser_store],
            api_name=False,
        )
        inspect_render_event = inspect_event.then(
            render_state_trip,
            inputs=[state],
            outputs=[trip_json, timeline],
        )
        inspect_render_event.then(
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
        delete_session_button.click(
            delete_current_history_session,
            inputs=[browser_store],
            outputs=[*session_outputs, *view_outputs],
            api_name=False,
        )
        clear_sessions_button.click(
            clear_all_history_sessions,
            inputs=[browser_store],
            outputs=[*session_outputs, *view_outputs],
            api_name=False,
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
