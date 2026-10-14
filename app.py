"""途证哨 production-candidate Gradio application."""
# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import sys
from html import escape
from urllib.parse import quote
from pathlib import Path
from typing import Any
from datetime import UTC, datetime
from dotenv import dotenv_values

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
from triptwin.history_media import (
    attach_original_reference, capture_previews, file_digest, materialize_preview,
    previews_html, restore_original, sanitize_previews,
)
from triptwin.browser_secrets import persistent_secret
from triptwin.branding import PRODUCT_TITLE
from triptwin.runtime_agent import run_live_trip
from triptwin.exporter import export_trip_files
from triptwin.input_completion import completion_rows, cancelled_orders, confirm_draft, validation_message
from triptwin.functional_examples import example_kind, example_paths, example_trip, field_description
from triptwin.local_planner import schedule_options, options_markdown
from triptwin.vision_parser import extract_trip_from_images, validate_image_files
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
    "途证哨 不代订、不支付；上传图片前请遮挡身份证号、手机号和票号。"
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
    "实时路线与天气尚未核验。"
)
UPLOADED_INSPECTION_PENDING = (
    "### ⏱️ 当前上传行程 · 主动巡检\n\n"
    "尚未执行实时核验。"
)
MODEL_UNAVAILABLE_REPLY = "当前模型服务暂时不可用，请稍后重试；TripGraph 和已生成的 Plan B 不受影响。"

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
.import-photo-list {max-height:340px;overflow-y:auto;overscroll-behavior:contain;border:1px solid #d6e2f2;border-radius:12px;background:#f5f8fe;scrollbar-gutter:stable}
.import-photo-list figure {margin:0;padding:8px;border-bottom:1px solid #d6e2f2}
.import-photo-list figure:last-child {border-bottom:0}
.import-photo-list img {display:block;width:100%;height:300px;object-fit:contain;cursor:default}
.import-photo-list figcaption {font-size:12px;color:#566880;text-align:center;overflow-wrap:anywhere;margin-top:4px}
#functional-examples {border:1px solid #d6e2f2;border-radius:12px;background:#f5f8fe}
.example-actions {display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:6px!important}
.example-actions button {min-width:0!important;font-size:12px!important;padding:8px 4px!important;white-space:normal!important}
.gradio-container {max-width:1180px!important;margin:auto!important}
.step-card {border:1px solid #e0e7f3!important;border-radius:18px!important;background:#fff!important;padding:20px!important;box-shadow:0 3px 16px #17233c06;margin-top:12px!important}
.step-heading {display:flex;gap:12px;align-items:center;margin-bottom:8px}
.step-number {display:grid;place-items:center;flex-shrink:0;width:34px;height:34px;border-radius:11px;background:#635bff;color:white;font-weight:700}
.step-heading h2 {font-size:19px;margin:0;color:#17233c}.step-heading p {margin:3px 0 0;color:#667085;font-size:13px}
.step-nav {display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.step-nav a {padding:8px 12px;background:#eef2ff;border-radius:20px;text-decoration:none;color:#5145cd;font-size:13px}
.step-card {scroll-margin-top:20px}
#step-plan table td:nth-last-child(-n+2) {white-space:nowrap}
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

_LOCAL_ENV = dotenv_values(PROJECT_ROOT / ".env")
_LOCAL_SECRET_DIR = Path(os.getenv("LOCALAPPDATA") or os.getenv("XDG_STATE_HOME") or tempfile.gettempdir()) / "triptwin" / hashlib.sha256(str(PROJECT_ROOT).encode()).hexdigest()[:16]
BROWSER_STATE_SECRET = persistent_secret(os.getenv("TRIPTWIN_BROWSER_STATE_SECRET") or _LOCAL_ENV.get("TRIPTWIN_BROWSER_STATE_SECRET"), _LOCAL_SECRET_DIR, "browser-state-secret")
RATE_LIMIT_SALT = persistent_secret(os.getenv("TRIPTWIN_RATE_LIMIT_SALT") or _LOCAL_ENV.get("TRIPTWIN_RATE_LIMIT_SALT"), _LOCAL_SECRET_DIR, "rate-limit-salt")
HISTORY_FILE_SECRET = persistent_secret(None, _LOCAL_SECRET_DIR, "history-file-signing-secret")
HISTORY_VIEW_OUTPUT_COUNT = 25


def live_evidence_is_recent(state):
    try:
        captured = datetime.fromisoformat(str(state.get("live_generated_at") or ""))
        if captured.utcoffset() is None:
            return False
        age = (datetime.now(UTC) - captured).total_seconds()
        return 0 <= age <= 3600
    except (ValueError, TypeError):
        return False


def load_example() -> tuple[list[str], str, dict[str, str]]:
    return (
        [str(SAMPLE_IMAGE_PATH)],
        "✅ 已载入完全虚构的黄金案例，无真实个人信息。",
        {"trip_source": "synthetic_example"},
    )


def load_railway_example(kind):
    paths = example_paths(kind)
    return [str(path) for path in paths], "已载入脱敏车票功能示例，请点击第 2 步。预算 2000 元、同行人数 1 人为演示设置。", {}


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
    if state.get("trip_source") == "ticket_example":
        _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
        return (
            "### 🛰️ 车票功能示例 · 空间与天气核验\n\n行程已构建。本示例只使用图片里的车站、日期和时刻；没有调用高德 MCP，实时路线及天气保持未核验。",
            f"### ⏱️ 车票功能示例 · 本地巡检\n\n已对当前行程运行确定性风险规则：{analysis.risk_count} 个风险，{analysis.total_risk_score} 分。\n\n没有发起云端定时巡检。",
        )
    if state.get("local_analysis_completed"):
        _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
        return UPLOADED_AMAP_PENDING, f"### ⏱️ 当前上传行程 · 本地回放复检\n\n已重新检查当前方案：{analysis.risk_count} 个风险，{analysis.total_risk_score} 分。未调用云端工具或执行实际退改。"
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
    elif state.get("trip_source") == "ticket_example":
        return default_amap, default_inspection
    else:
        if not amap_text.startswith("### 🛰️ 当前上传行程"):
            amap_text = default_amap
        if not inspection_text.startswith("### ⏱️ 当前上传行程"):
            inspection_text = default_inspection
        # Older browser snapshots may still contain obsolete UI instructions.
        if "不会复用杭州合成示例" in amap_text:
            amap_text = default_amap
        if "手动巡检" in inspection_text:
            inspection_text = default_inspection
    return amap_text, inspection_text


def reset_uploaded_context() -> tuple[dict[str, Any], str, str, bool]:
    """Clear evidence when a browser selects a new local image."""

    return {}, EMPTY_AMAP_STATUS, EMPTY_INSPECTION_STATUS, False


def reset_import_view() -> tuple[Any, ...]:
    """Invalidate every previous result before processing a different upload."""
    return (
        {}, EMPTY_AMAP_STATUS, EMPTY_INSPECTION_STATUS, False,
        "已更换图片，请点击第 2 步重新构建。旧行程结果已清空。",
        "", [], "等待解析新图片。", "", False,
        "### 风险卡片\n\n等待检查。", "### 原方案 / Plan B\n\n等待生成。",
        "### Agent 工具执行轨迹摘要\n\n等待生成。", "", [], None,
    )


def reset_import_for_files(files, current):
    result = list(reset_import_view())
    expired = (current or {}).get("_history_preview_digests") or []
    retained = []
    for path in _image_paths(files):
        if path.is_file() and file_digest(path) in expired:
            retained.append(file_digest(path))
    if retained:
        result[0] = {"_history_preview_digests": retained}
    return tuple(result)


def reset_downstream_view():
    """Invalidate results tied to an earlier graph after rebuilding/editing."""
    return (
        "### 风险卡片\n\n行程已更新，请重新检查风险。",
        "### 原方案 / Plan B\n\n行程已更新，请重新生成方案。",
        "### Agent 工具执行轨迹摘要\n\n等待当前行程核验。",
        [], "", None,
    )


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
                    "- 外部事实来自当前会话的高德 MCP；天气只核验工具实际返回的日期。",
                ]
            ),
        )
    _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
    return (
        UPLOADED_AMAP_PENDING,
        "\n".join(
            [
                "### ⏱️ 当前上传行程 · 本地风险复检",
                "",
                f"- 已重新运行当前 TripGraph 的本地确定性规则：**{analysis.risk_count} 个风险 / {analysis.total_risk_score} 分**",
                "- 本次未调用高德 MCP 或 Managed Agent；需要实时外部证据的项目保持未核验。",
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


def _is_functional_example(paths):
    return _is_sample_upload(paths) or example_kind(paths) is not None


def build_twin(image_paths: Any) -> tuple[str, list[list[Any]], str, str, dict[str, Any]]:
    paths = _image_paths(image_paths)
    if not paths:
        raise gr.Error("请先上传图片，或展开“行程功能示例”并选择一个示例。")
    kind = example_kind(paths)
    if kind:
        trip_payload = example_trip(kind)
        confidence = {f"events[{i}].{key}": 1.0 for i in range(len(trip_payload["events"])) for key in ("title", "start", "end", "cost_cny")}
        low_fields = []
        if kind == "conflict":
            confidence["events[2].title"] = 0.65
            low_fields = ["第 3 项车次在图片中被遮挡，暂记为“车次待确认”；请核对或确认已知限制"]
        model = "本地人工核对示例"
        request_note = "复用脱敏车票示例，不调用模型；预算与人数为演示设置，工具证据保持未核验"
    elif _is_sample_upload(paths):
        evidence = load_cached_vision()
        trip_payload = evidence["trip"]
        confidence = evidence["field_confidence"]
        low_fields = evidence["low_confidence_fields"]
        model = evidence["model"]
        accuracy = f"{evidence['field_accuracy']:.1%}"
        request_note = f"复用已验真的云端解析证据 · 字段准确率 {accuracy}"
    else:
        extraction, metadata = extract_trip_from_images(paths)
        trip_payload = (
            extraction.trip.model_dump(mode="json")
            if hasattr(extraction.trip, "model_dump") else extraction.trip
        )
        confidence = extraction.field_confidence
        low_fields = extraction.low_confidence_fields
        model = metadata["model"]
        request_note = f"本次图片已完成云端解析 · 已逐图核齐 {len(paths)} 张截图，共 {len(trip_payload['events'])} 项行程"
    rows = [[name, round(float(value), 3), field_description(name, trip_payload)] for name, value in sorted(confidence.items())]
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
            else "ticket_example" if kind else "uploaded_image"
        ),
    }
    state["parse_summary"] = f"`{model}` · {request_note}"
    if not _is_functional_example(paths):
        report = metadata.get("image_report") or []
        expected = set(range(1, len(paths) + 1))
        if len(paths) > 1 and (
            len(report) != len(paths) or {item.get("image_index") for item in report} != expected
            or any(not item.get("event_indices") for item in report)
        ):
            raise gr.Error("多图解析未逐张核齐，已停止构建。请重新解析或分开上传；不能据此报告 0 风险。")
        state["image_coverage"] = {
            "version": 1, "image_count": len(paths), "images": report,
        }
        state["draft_trip"] = state.pop("trip")
        state["stage"] = "needs_confirmation"
        state["image_report_text"] = "\n\n### 截图处理核对\n" + "\n".join(
            f"- 第 {item['image_index']} 张：对应行程 " + "、".join(str(i + 1) for i in item['event_indices'])
            for item in report
        )
        low_text += state["image_report_text"]
    if not _is_functional_example(paths) and extraction.notes:
        low_text += "\n\n" + "\n".join("- " + note for note in extraction.notes)
    return (
        json.dumps(trip_payload, ensure_ascii=False, indent=2),
        rows,
        low_text,
        timeline_html(trip_payload) if _is_functional_example(paths) else "",
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
        raise gr.Error("请先上传图片，或展开“行程功能示例”并选择一个示例。")
    try:
        validate_image_files(paths)
    except ValueError as exc:
        raise gr.Error(str(exc) + " 本次未调用模型，不消耗解析次数。") from None
    store, _ = ensure_active_session(browser_store)
    client_key = _anonymous_client_key(request)
    client_reserved = False
    global_reserved = False
    if not _is_functional_example(paths):
        allowed, usage = browser_can_consume(store.get("usage"), "images")
        if not allowed:
            raise gr.Error(
                f"为保护有限 Token，每个浏览器每天最多解析 "
                f"{browser_limits()['images']} 次自行上传图片解析；请明日再试。"
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
    except Exception as exc:
        quota_note = " 已发起云端解析请求，本次计入解析次数；请勿连续重试，先确认配置或图片内容。" if global_reserved else ""
        if isinstance(exc, gr.Error):
            raise
        import httpx
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            message = (
                "图片解析服务拒绝了请求。请检查创空间的视觉模型名称、调用权限及账户余额/额度。"
                f"（HTTP {code}）"
            )
        elif isinstance(exc, httpx.TimeoutException):
            message = "图片解析超时，请稍后再试。"
        elif isinstance(exc, ValueError):
            message = "图片解析未完成：" + str(exc)[:400]
        else:
            message = "图片解析服务异常，请查看创空间运行日志。"
        raise gr.Error(message + quota_note) from None
    if not _is_functional_example(paths):
        store["usage"] = consume_browser(usage, "images")
    return *result, store


def parse_current_import(files, privacy_confirmed, browser_store, current, request: gr.Request | None = None):
    """Permit history re-parsing, but never pass a low-resolution fallback to LLM."""
    current = dict(current or {})
    paths = _image_paths(files)
    expired = current.get("_history_preview_digests") or []
    if any(path.is_file() and file_digest(path) in expired for path in paths) or (
        not paths and isinstance(current.get("trip") or current.get("draft_trip"), dict)
    ):
        _require_image_coverage(current)
        if not isinstance(current.get("trip") or current.get("draft_trip"), dict):
            raise gr.Error("这份历史行程的原图已过期，当前显示的是预览副本；尚无可复用的完整解析。请重新上传原图后解析，预览不会替代原图发送给模型。本次不消耗解析次数。")
        current["_history_cached_parse"] = True
        current["parse_summary"] = "原图已过期，本次复用此会话已保存的解析结果，保留已确认信息；未重新调用模型，不消耗解析次数。重新识别请上传原图。"
        view = _session_view({"snapshot": {"trip_state": current}})
        store, _ = ensure_active_session(browser_store)
        return view[2], view[3], view[4], view[5], current, store
    return build_twin_guarded(files, privacy_confirmed, browser_store, request)


def reset_after_parse(current):
    if (current or {}).get("_history_cached_parse"):
        return (*(gr.skip() for _ in range(6)), gr.skip())
    return *reset_downstream_view(), False


def completion_panel(state):
    draft = (state or {}).get("draft_trip")
    if not isinstance(draft, dict):
        return gr.update(visible=False), [], ""
    invalid = cancelled_orders(draft)
    message = (
        "### ⚠️ 订单已失效\n\n" + "、".join(invalid) +
        " 已退票或取消，无法据此构建有效出行计划。请点击“清空已导入行程”，上传当前有效订单。"
        if invalid else
        "### 请补全并确认必要信息\n\n只编辑表格的“填写值”列。空白项为图片未提供的信息；预填规则和人数也请核对。"
        "填写后点击“确认信息并构建旅行数字孪生”。也可清空并重新上传更详细的行程截图。"
    )
    if (state or {}).get("completion_error"):
        message = "### ⚠️ " + state["completion_error"] + "\n\n" + message
    return gr.update(visible=True), (state or {}).get("completion_rows") or completion_rows(draft), message


def confirm_import(rows, state):
    current = dict(state or {})
    _require_image_coverage(current)
    if not isinstance(current.get("draft_trip"), dict):
        raise gr.Error("请先解析行程截图。")
    try:
        trip = confirm_draft(current["draft_trip"], rows)
    except Exception as exc:
        current["completion_rows"] = rows
        message = str(exc)[:700]
        current["completion_error"] = message
        gr.Warning(message)
        return "⚠️ " + message, "", current, "", False
    current["trip"] = trip.model_dump(mode="json")
    current.pop("draft_trip", None)
    current.pop("completion_rows", None)
    current.pop("completion_error", None)
    current["stage"] = "ready"
    current["recognition_confirmed"] = True
    current["low_confidence_fields"] = []
    return (
        "✅ 信息已补全并确认，旅行数字孪生已构建；可以继续第 3 步检查风险。",
        timeline_html(current["trip"]), current, trip.model_dump_json(indent=2), True,
    )


def import_preview(files, block):
    paths = _image_paths(files)
    photos = []
    for path in paths:
        cached = block.move_resource_to_block_cache(str(path))
        name = escape(path.name, quote=True)
        url = "gradio_api/file=" + quote(str(cached), safe="")
        photos.append(f'<figure title="{name}"><img src="{url}" alt="{name}" title="{name}"><figcaption>{name}</figcaption></figure>')
    return gr.update(value='<div class="import-photo-list" aria-label="已导入截图">' + "".join(photos) + "</div>", visible=bool(paths))


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

    if not (trip_json_text or "").strip():
        raise gr.Error("尚未生成行程。请先解析截图、补全必要信息，再点击“确认信息并构建旅行数字孪生”。")
    try:
        payload = json.loads(trip_json_text)
        from triptwin.models import Trip

        trip = Trip.model_validate(payload)
    except json.JSONDecodeError as exc:
        raise gr.Error(f"JSON 格式不正确：请检查第 {exc.lineno} 行附近的引号、逗号和括号。原行程未修改。") from None
    except Exception as exc:
        from pydantic import ValidationError
        message = validation_message(exc) if isinstance(exc, ValidationError) else "请输入完整的行程 JSON 对象。"
        raise gr.Error(message + " 原行程未修改。") from None
    updated = dict(state or {})
    updated["trip"] = trip.model_dump(mode="json")
    needs_confirmation = True
    if needs_confirmation:
        updated["draft_trip"] = updated.pop("trip")
    updated["trip_source"] = "user_corrected"
    for key in ("live_candidate_artifact", "live_inspection", "live_generated_at", "managed_session", "local_plan_options", "local_analysis_completed", "completion_rows", "completion_error", "recognition_confirmed"):
        updated.pop(key, None)
    payload_to_clean = updated.get("trip") or updated.get("draft_trip")
    for event in payload_to_clean["events"]:
        metadata = event.get("metadata") or {}
        metadata.pop("amap_route_evidence", None)
        metadata.pop("amap_weather_evidence", None)
    return (
        trip.model_dump_json(indent=2),
        "" if needs_confirmation else timeline_html(updated["trip"]),
        updated,
        "✅ 修改已校验，请补全并确认参数后重新构建。" if needs_confirmation else "✅ 修改已通过校验；请重新检查风险。",
        False,
    )


def export_current_trip(state: dict[str, Any] | None, *, cache_root=None) -> list[str]:
    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        raise gr.Error("请先构建旅行数字孪生。")
    return export_trip_files(state["trip"], directory_root=cache_root)


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


def _require_image_coverage(state):
    if (state or {}).get("legacy_image_coverage_missing"):
        raise gr.Error("此历史会话由旧版多图解析生成，尚未逐张核齐，不能据此进行风险分析、Plan B 或行程问答。请点击解析重新核对所有原图；原图已过期时请重新上传。本次未调用模型或外部工具。")


def check_risks(state: dict[str, Any], confirmed: bool) -> str:
    _require_image_coverage(state)
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
    _require_image_coverage(state)
    if not state or "trip" not in state:
        raise gr.Error("请先构建旅行数字孪生。")
    if state.get("low_confidence_fields") and not confirmed:
        raise gr.Error("请先核对并确认低置信字段。")
    if state.get("trip_source") == "ticket_example":
        _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
        options = schedule_options(state["trip"])
        updated = dict(state)
        updated["local_plan_options"] = options
        text = (
            _normal_ticket_plan(state["trip"])
            if analysis.risk_count == 0 else
            options_markdown(state["trip"], options) if options else
            "### 当前无法自动生成有效的局部调整方案\n\n没有找到满足受保护行程与依赖约束的方案，请补充目的地优先级或查询新的车次。"
        )
        amap_panel, inspection_panel = context_panels_for_state(updated)
        return text, "### 本地计划回放轨迹\n\n读取当前行程 → 检查时间冲突 → 保护首段行程 → 枚举局部调整 → 校验依赖与预算 → 重新运行风险规则。\n\n本次未调用高德 MCP 或 FlyAI。", updated, amap_panel, inspection_panel
    if state.get("trip_source") != "synthetic_example":
        _, analysis = analyze_trip(state["trip"], include_cached_amap=False)
        if analysis.risk_count == 0:
            amap_panel, inspection_panel = context_panels_for_state(state)
            return plan_b_markdown(state["trip"], include_cached_amap=False), "当前未检出风险，无需替代候选，本次未调用外部工具。", state, amap_panel, inspection_panel
        options = schedule_options(state["trip"])
        if options:
            updated = dict(state)
            updated["local_plan_options"] = options
            updated["local_analysis_completed"] = True
            amap_panel, inspection_panel = context_panels_for_state(updated)
            return options_markdown(state["trip"], options), "已基于当前上传行程生成局部调整候选，并重新校验结构、依赖、保护节点、预算和风险。未调用外部工具。", updated, amap_panel, inspection_panel
    if state.get("trip_source") == "synthetic_example":
        amap_panel, inspection_panel = context_panels_for_state(state)
        return (
            plan_b_markdown(state["trip"], include_cached_amap=True),
            tool_trace_markdown(),
            state,
            amap_panel,
            inspection_panel,
        )

    if live_evidence_is_recent(state) and isinstance(state.get("live_candidate_artifact"), dict) and isinstance(
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
            "当前行程实时核验失败，途证哨 已停止生成，未套用任何示例数据："
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


def _normal_ticket_plan(payload):
    from triptwin.models import Trip
    events = sorted(Trip.model_validate(payload).events, key=lambda event: event.start)
    lines = ["### ✅ 当前行程本地复检通过", "", "当前本地规则没有检出风险，无需新增替代订单。"]
    for previous, current in zip(events, events[1:]):
        minutes = int((current.start - previous.end).total_seconds() // 60)
        lines.append(f"- {previous.title} → {current.title}：到达与下一次出发间隔 {minutes} 分钟。")
    lines.append("\n实时交通、天气和余票未查询；这个结论只覆盖当前已知字段及本地规则。")
    return "\n".join(lines)


def local_options_view(state):
    options = (state or {}).get("local_plan_options") or []
    return gr.update(visible=bool(options)), gr.update(choices=[(option["label"], option["id"]) for option in options], value=options[0]["id"] if options else None)


def apply_local_option(selected, state):
    _require_image_coverage(state)
    if not isinstance((state or {}).get("trip"), dict):
        raise gr.Error("请先构建行程并生成 Plan B。")
    # Recompute from current state, never trust a candidate passed back by the UI.
    options = schedule_options(state["trip"])
    option = next((item for item in options if item["id"] == selected), None)
    if option is None:
        raise gr.Error("方案已失效，请基于当前行程重新生成 Plan B。")
    updated = dict(state)
    updated["trip"] = option["trip"]
    updated["local_plan_options"] = []
    updated["local_analysis_completed"] = True
    updated.pop("live_candidate_artifact", None)
    updated.pop("live_inspection", None)
    # Remap evidence to retained events instead of showing removed-event rows.
    import re
    original_ids = [event["id"] for event in state["trip"]["events"]]
    retained_indices = {event["id"]: index for index, event in enumerate(option["trip"]["events"])}
    remapped = {}
    for key, value in (state.get("field_confidence") or {}).items():
        match = re.search(r"events\[(\d+)\]", key)
        if match:
            old_index = int(match.group(1))
            if old_index >= len(original_ids) or original_ids[old_index] not in retained_indices:
                continue
            key = key.replace(match.group(0), f"events[{retained_indices[original_ids[old_index]]}]")
        remapped[key] = value
    updated["field_confidence"] = remapped
    updated["low_confidence_fields"] = [key for key, value in remapped.items() if float(value) < 0.8]
    message = "✅ 已应用到页面行程并完成风险复检；没有实际退票、改签或支付。"
    return (
        json.dumps(option["trip"], ensure_ascii=False, indent=2), timeline_html(option["trip"]),
        risk_markdown(option["trip"], include_cached_amap=False), updated,
        f"### 已应用：{option['label']}\n\n{message}\n\n保留行程票面金额 ¥{option['known_cost']}；本地风险 {option['before_risks']} → {option['after_risks']}。退款和手续费未知。",
        message, True,
    )


def refresh_confidence(state):
    values = (state or {}).get("field_confidence") or {}
    rows = [[key, round(float(value), 3), field_description(key, state.get("trip"))] for key, value in sorted(values.items())]
    low = (state or {}).get("low_confidence_fields") or []
    report = str((state or {}).get("image_report_text") or "")
    if (state or {}).get("recognition_confirmed"):
        return rows, "✅ 已人工确认识别结果。表格保留原始模型置信度，人工确认不会将低分改成 1。" + report
    return rows, ("已确认仍存在的识别限制：" + "、".join(low) if low else "✅ 当前保留行程没有低于 0.8 的已标注字段。") + report


def render_step_panels(state):
    """Refresh local derived controls together, without another queued job."""
    current = state or {}
    return (
        *completion_panel(current),
        *local_options_view(current),
        gr.update(visible=isinstance(current.get("trip"), dict) or isinstance(current.get("draft_trip"), dict)),
    )


def generate_plan_b_guarded(
    state: dict[str, Any],
    confirmed: bool,
    browser_store: dict[str, Any] | None,
    request: gr.Request | None = None,
) -> tuple[str, str, dict[str, Any], str, str, dict[str, Any]]:
    _require_image_coverage(state)
    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        raise gr.Error("请先解析截图、补全必要信息并构建旅行数字孪生。")
    if state.get("low_confidence_fields") and not confirmed:
        raise gr.Error("请先核对并确认低置信字段。")
    store, _ = ensure_active_session(browser_store)
    if state.get("trip_source") in {"synthetic_example", "ticket_example"}:
        result = generate_plan_b(state, confirmed)
        return *result, store
    if isinstance(state.get("trip"), dict) and analyze_trip(state["trip"], include_cached_amap=False)[1].risk_count == 0:
        return *generate_plan_b(state, confirmed), store
    if isinstance(state.get("trip"), dict) and schedule_options(state["trip"]):
        return *generate_plan_b(state, confirmed), store
    if live_evidence_is_recent(state) and isinstance(state.get("live_candidate_artifact"), dict):
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
    except Exception as exc:
        # A timed-out/invalid cloud result may still incur upstream charges.
        # Retain server-side reservations so retries cannot bypass the cost cap.
        raise gr.Error(str(exc) + " 本次已发起云端请求，计入核验次数，避免反复重试造成额外费用。") from None
    store["usage"] = consume_browser(usage, "agent_runs")
    return *result, store


def run_live_inspection_guarded(
    state: dict[str, Any],
    confirmed: bool,
    browser_store: dict[str, Any] | None,
    request: gr.Request | None = None,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    _require_image_coverage(state)
    if not isinstance(state, dict) or not isinstance(state.get("trip"), dict):
        raise gr.Error("请先构建旅行数字孪生。")
    if state.get("low_confidence_fields") and not confirmed:
        raise gr.Error("请先核对并确认低置信字段，再执行外部工具核验。")
    store, _ = ensure_active_session(browser_store)
    if state.get("trip_source") in {"synthetic_example", "ticket_example"}:
        return *run_manual_inspection_for_state(state), state, store
    if live_evidence_is_recent(state) and isinstance(state.get("live_inspection"), dict):
        return *run_manual_inspection_for_state(state), state, store
    allowed, usage = browser_can_consume(store.get("usage"), "agent_runs")
    if not allowed:
        raise gr.Error("今日实时核验次数已用完，仍可检查本地风险和查看已有结果。")
    client_key = _anonymous_client_key(request)
    if client_key and not reserve_client(client_key, "agent_runs")[0]:
        raise gr.Error("当前匿名访客今日实时核验次数已用完。")
    global_allowed, _, global_limit = reserve_global("agent_runs")
    if not global_allowed:
        if client_key:
            release_reservation("client", client_key, "agent_runs")
        raise gr.Error(f"今日全站实时核验已达到 {global_limit} 次。")
    try:
        analysis = analyze_trip(state["trip"], include_cached_amap=False)[1]
        needs_candidates = analysis.risk_count > 0 and not schedule_options(state["trip"])
        result = run_live_trip(state["trip"], inspect_only=not needs_candidates)
    except Exception as exc:
        raise gr.Error("实时核验未完成：" + str(exc)[:500] + " 本次已发起云端请求，计入核验次数；本地风险检查仍可使用。") from None
    updated = dict(state)
    updated.update(trip=result.trip, live_inspection=result.inspection.model_dump(mode="json"), live_generated_at=result.generated_at)
    if needs_candidates:
        updated["live_candidate_artifact"] = result.candidate_artifact
    else:
        updated.pop("live_candidate_artifact", None)
    updated.pop("local_plan_options", None)
    store["usage"] = consume_browser(usage, "agent_runs")
    amap_panel, inspection_panel = run_manual_inspection_for_state(updated)
    return amap_panel, inspection_panel, updated, store


def current_tool_trace(state):
    if state.get("trip_source") == "synthetic_example":
        return tool_trace_markdown()
    if isinstance(state.get("live_inspection"), dict):
        from triptwin.live_context import AmapInspection
        return tool_trace_markdown(state.get("live_candidate_artifact") or {"flyai_commands": []}, AmapInspection.model_validate(state["live_inspection"]))
    return "### 本地风险检查\n\n本次未调用外部工具，实时信息尚未核验。"


def answer_question(
    question: str,
    history: list[dict[str, Any]] | None,
    state: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    _require_image_coverage(state)
    text = (question or "").strip()
    if not text:
        raise gr.Error("请先输入问题。")
    if len(text) > 500:
        raise gr.Error("问题请控制在 500 字以内，便于简洁回答并控制费用。")
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
        answer = MODEL_UNAVAILABLE_REPLY
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

    _require_image_coverage(state)
    text = (question or "").strip()
    if not text:
        raise gr.Error("请先输入问题。")
    if len(text) > 500:
        raise gr.Error("问题请控制在 500 字以内，本次未调用模型。")
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
                        "或展开“行程功能示例”、选择示例并完成第 2 步后再提问。"
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
    if isinstance(answer, str) and answer.strip() and answer != MODEL_UNAVAILABLE_REPLY:
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
            "途证哨 不会代订。"
        )
    if "自动" in normalized and any(
        keyword in normalized for keyword in ("预定", "预订", "下单", "支付")
    ):
        return (
            "不会。途证哨 只进行风险分析并提供带来源链接的候选，"
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
        "是否会自动预订",
    }


def _has_question_context(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    if isinstance(state.get("trip"), dict):
        return True
    return False


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
    image_previews: Any = None,
    editor_text: str | None = None,
    completion_values: Any = None,
    question_text: str | None = None,
) -> dict[str, Any]:
    trip_state = dict(trip_state or {})
    for key in ("_history_preview_digests", "_history_cached_parse"):
        trip_state.pop(key, None)
    if isinstance(trip_state.get("draft_trip"), dict) and isinstance(completion_values, list):
        trip_state["completion_rows"] = completion_values
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
        "image_previews": sanitize_previews(image_previews),
        "editor_text": editor_text,
        "question_text": str(question_text or ""),
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
        + "`  \n选择历史会话即可自动切换。行程、解析结果、风险、Plan B、对话及小尺寸截图预览保存在本浏览器；服务器原图仍定期清理。"
    )


def _session_view(session: dict[str, Any]) -> tuple[Any, ...]:
    snapshot = session.get("snapshot") or {}
    trip_state = snapshot.get("trip_state")
    if not isinstance(trip_state, dict):
        trip_state = {}
    trip = trip_state.get("trip")
    draft = trip_state.get("draft_trip")
    confidence_map = trip_state.get("field_confidence")
    confidence_rows = (
        [[name, round(float(value), 3), field_description(name, trip or draft)] for name, value in sorted(confidence_map.items())]
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
    if trip_state.get("recognition_confirmed") and isinstance(trip, dict):
        low_text = "✅ 已人工确认识别结果。表格保留原始模型置信度，人工确认不会将低分改成 1。"
    low_text += str(trip_state.get("image_report_text") or "")
    timeline = timeline_html(trip) if isinstance(trip, dict) else ""
    safe_amap, safe_inspection = safe_context_panels(
        trip_state,
        snapshot.get("amap_status"),
        snapshot.get("inspection_status"),
    )
    return (
        None,
        snapshot.get("status") or "等待载入图片。",
        snapshot.get("editor_text") if isinstance(snapshot.get("editor_text"), str) else json.dumps(trip if isinstance(trip, dict) else draft, ensure_ascii=False, indent=2) if isinstance(trip, dict) or isinstance(draft, dict) else "",
        confidence_rows,
        low_text,
        timeline,
        bool(snapshot.get("confirmed")),
        snapshot.get("risks") or "### 风险卡片\n\n等待检查。",
        snapshot.get("plan_b") or "### 原方案 / Plan B\n\n等待生成。",
        snapshot.get("trace") or "### Agent 工具执行轨迹摘要\n\n等待生成。",
        snapshot.get("question_text") or "",
        snapshot.get("chat_history") or [],
        trip_state,
        safe_amap,
        safe_inspection,
        None,
        False,
    )


def _restored_history_view(session: dict[str, Any]) -> tuple[Any, ...]:
    """Restore every visible panel directly, including unchanged State values."""
    snapshot = session.get("snapshot") or {}
    state = dict(snapshot.get("trip_state") or {})
    previews = sanitize_previews(snapshot.get("image_previews"))
    if len(previews) > 1 and state.get("trip_source") in {"uploaded_image", "user_corrected"} and not state.get("image_coverage"):
        state["legacy_image_coverage_missing"] = True
        state["image_report_text"] = "\n\n⚠️ 此历史会话来自旧版多图解析，尚无逐图核对记录。请重新解析原图后再检查风险或生成 Plan B；原图已过期则需重新上传。旧结果仅供查看，不能视为已核验全部截图。"
    # Old public examples can recover previews from known assets, not arbitrary paths.
    known_paths = []
    if state.get("trip_source") == "synthetic_example":
        known_paths = [SAMPLE_IMAGE_PATH]
    elif state.get("trip_source") == "ticket_example":
        trip = state.get("trip") or {}
        known_paths = example_paths("conflict" if len(trip.get("events", [])) == 3 else "multi")
    if not previews and known_paths:
        previews = capture_previews(known_paths)
    files = []
    expired = []
    for photo in previews:
        # Public examples follow the current bundled asset after a brand refresh,
        # so an older Gradio copy does not become a paid user-image parse.
        original = next((path for path in known_paths if path.name == photo["name"]), None)
        if original is None:
            original = restore_original(photo, HISTORY_FILE_SECRET, [Path(gr.utils.get_upload_folder()), PROJECT_ROOT / "assets"])
        if original is None:
            try:
                original = materialize_preview(photo, Path(gr.utils.get_upload_folder()))
                expired.append(file_digest(original))
            except (OSError, ValueError):
                continue
        files.append(str(original))
    if expired:
        state["_history_preview_digests"] = expired
    snapshot = {**snapshot, "trip_state": state}
    view = list(_session_view({"snapshot": snapshot}))
    view[0] = files or None
    if state.get("legacy_image_coverage_missing"):
        view[1] = "⚠️ 旧版多图解析尚未核齐，请重新解析。"
        view[7] = "### ⚠️ 旧风险结果待复核\n\n原解析缺少逐图覆盖记录，不能据此报告 0 风险。请重新解析原图。"
        view[8] = "### ⚠️ 原 Plan B 待复核\n\n请先重新解析并核齐所有图片，再生成 Plan B。"
    return (
        *view, previews,
        gr.update(value=previews_html(previews), visible=bool(previews)),
        *completion_panel(state),
        gr.update(visible=isinstance(state.get("trip"), dict) or isinstance(state.get("draft_trip"), dict)),
        *local_options_view(state),
    )


def initialize_session_history(browser_store: Any) -> tuple[Any, ...]:
    store, session = ensure_active_session(browser_store)
    return store, _history_update(store), _session_badge(session), *_restored_history_view(session)


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
    image_previews: Any = None,
    editor_text: str | None = None,
    completion_values: Any = None,
    question_text: str | None = None,
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
        image_previews, editor_text, completion_values, question_text,
    )
    store = save_active_session(browser_store, snapshot)
    session = next(item for item in store["sessions"] if item["id"] == store["active_id"])
    # Return the browser mirror and local controls explicitly. Non-queued
    # callbacks do not consistently dispatch State.change in Gradio's client;
    # relying on those events loses history or leaves stale derived controls.
    return store, _history_update(store), _session_badge(session), store, *render_step_panels(snapshot["trip_state"])


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
    image_previews: Any = None,
    editor_text: str | None = None,
    completion_values: Any = None,
    question_text: str | None = None,
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
        image_previews, editor_text, completion_values, question_text,
    )
    store, session = create_session(browser_store, current_snapshot=snapshot)
    return store, _history_update(store), _session_badge(session), *_restored_history_view(session)


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
    image_previews: Any = None,
    editor_text: str | None = None,
    completion_values: Any = None,
    question_text: str | None = None,
) -> tuple[Any, ...]:
    if not target_id or target_id == (browser_store or {}).get("active_id"):
        # Dropdown blur can emit input even when selection never changed.
        # Leave ALL components untouched, especially File and unsaved edits.
        return tuple(gr.skip() for _ in range(3 + HISTORY_VIEW_OUTPUT_COUNT))
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
        image_previews, editor_text, completion_values, question_text,
    )
    try:
        store, session = switch_session(
            browser_store, target_id, current_snapshot=snapshot
        )
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    return store, _history_update(store), _session_badge(session), *_restored_history_view(session)


def delete_current_history_session(browser_store: Any) -> tuple[Any, ...]:
    store, active = ensure_active_session(browser_store)
    store, session = delete_session(store, active["id"])
    return store, _history_update(store), _session_badge(session), *_restored_history_view(session)


def clear_all_history_sessions(browser_store: Any) -> tuple[Any, ...]:
    store, session = clear_sessions(browser_store)
    return store, _history_update(store), _session_badge(session), *_restored_history_view(session)


def create_app() -> gr.Blocks:
    with gr.Blocks(title=PRODUCT_TITLE, delete_cache=(3600, 3600)) as demo:
        state = gr.State({})
        image_previews = gr.State([])
        browser_store = gr.BrowserState(
            default_value={"version": 1, "active_id": None, "sessions": []},
            storage_key="triptwin_sessions_v1",
            secret=BROWSER_STATE_SECRET,
        )
        # BrowserState encryption is asynchronous on the frontend. Use a
        # tab-local server State as the authority between callbacks, then mirror
        # updates to localStorage rather than reading a stale browser snapshot.
        history_store = gr.State({})
        gr.HTML(f"<div class='hero'><h1>{PRODUCT_TITLE}</h1><p>把行程截图变成 TripGraph，结合真实 FlyAI 与高德 MCP 证据发现衔接、日期、预算、天气和体力风险，并生成可验证 Plan B。</p></div>")
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
                with gr.Column(scale=2, min_width=260):
                    with gr.Accordion("行程功能示例", open=False, elem_id="functional-examples"):
                        with gr.Row(elem_classes=["example-actions"]):
                            single_example_button = gr.Button("单行程正常示例", size="sm", min_width=0)
                            multi_example_button = gr.Button("多行程正常示例", size="sm", min_width=0)
                            conflict_example_button = gr.Button("行程冲突异常示例", size="sm", min_width=0)
                        gr.Markdown("单行程按钮展示杭州完整行程及其风险；多行程和冲突按钮使用脱敏车票。示例预算与人数为演示设置。")
                    preview = gr.HTML(value="", visible=False)
                    clear_import_button = gr.Button("清空已导入行程", variant="secondary")
            privacy_confirmed = gr.Checkbox(
                label="隐私提醒状态", visible=False
            )
            gr.Markdown("支持 12306 车票、机票、酒店订单或完整行程截图，**无需固定模板**。截图缺少的必要信息会在第 2 步提示手动补充；也可清空后上传更详细的行程截图。请裁掉广告并遮挡姓名、订单号、流水号等信息。")
            gr.Markdown("自行上传的截图会发送至百炼解析，系统不会自动给原图打码。服务器临时上传与导出文件约 1–2 小时后清理；原图过期后仍可查看和使用已保存的行程，重新识别原图或下载原图需重新上传，导出文件可重新生成。")
            gr.Markdown("历史会话恢复文件列表、截图预览和已解析行程。原图仍有效时可再次解析（正常计入额度）；原图过期时，点击解析会复用该会话已保存结果，不将低清预览当原图重新识别、不消耗解析次数。尚未解析过或希望重新识别时，请重新上传原图。旧版本未保存的截图无法补回。")
        with gr.Column(elem_id="step-build", elem_classes=["step-card"]):
            gr.HTML("<div class='step-heading'><span class='step-number'>2</span><div><h2>解析、补全与构建</h2><p>先解析截图，再补全并确认必要信息，构建完成后继续第 3 步。合成示例的信息已完整。</p></div></div>")
            build_button = gr.Button("② 解析行程截图", variant="primary")
            status = gr.Markdown("等待载入图片。")
            with gr.Column(visible=False) as completion_section:
                completion_message = gr.Markdown()
                completion_table = gr.Dataframe(
                    headers=["参数路径", "需要补充或确认", "填写值"],
                    datatype=["str", "str", "str"], type="array", interactive=True,
                    column_count=(3, "fixed"), max_height=350,
                    label="补充信息 · 只修改填写值列",
                )
                confirm_import_button = gr.Button("确认信息并构建旅行数字孪生", variant="primary")
            timeline = gr.HTML(label="TripGraph 时间线")
            with gr.Accordion("校对与修改 · 结构化行程", open=False, visible=False) as editor_section:
                gr.Markdown("高级校对：草稿不代表已构建行程；通常只需补全上方表格。若识别的车次、日期或关联编号有误，可在此修改完整 JSON 后校验，仍需确认必要参数。")
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
                gr.Markdown("**识别置信度表示字段读得是否可靠，不表示行程是否合理。** 时间读准了仍可能冲突，请看第 3 步风险检查。车票示例的 1 表示人工核对清晰可见字段；被遮挡或缺失的字段会降低置信度。")
                confidence = gr.Dataframe(
                    headers=["字段", "置信度", "备注说明"],
                    datatype=["str", "number", "str"],
                    interactive=False,
                    label="字段置信度",
                    max_height=240,
                    elem_id="field-confidence",
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
            gr.HTML("<div class='step-heading'><span class='step-number'>4</span><div><h2>生成 Plan B</h2><p>先尝试本地冲突调整；需要新候选时才执行实时工具核验。没有风险时无需替代方案。</p></div></div>")
            plan_button = gr.Button("④ 生成 Plan B", variant="primary")
            plan_b = gr.Markdown("### 原方案 / Plan B\n\n等待生成。")
            with gr.Column(visible=False) as local_options_section:
                local_choice = gr.Dropdown(choices=[], label="选择保留的行程方案", interactive=True)
                apply_local_button = gr.Button("应用到当前行程 · 不执行实际退改", variant="primary")
            with gr.Accordion("查看工具证据与实时巡检", open=False):
                inspect_button = gr.Button("查看 / 执行实时巡检", variant="secondary")
                gr.Markdown("用户行程首次执行会调用高德并计入实时核验次数；1 小时内复用已有核验，过期后再次执行仍受每日额度限制。单段交通或同站衔接不查询跨城公交。云端核验可能需要数分钟，超时会提示失败，已生成内容仍可查看，请勿连续重复点击。功能示例仅查看已有演示证据或本地复检；本页面不会自动后台巡检。")
                amap_status = gr.Markdown(EMPTY_AMAP_STATUS, elem_id="amap-evidence")
                inspection_status = gr.Markdown(EMPTY_INSPECTION_STATUS, elem_id="inspection-evidence")
                trace = gr.Markdown("### Agent 工具执行轨迹摘要\n\n等待生成。", elem_id="tool-trace")
        with gr.Column(elem_id="step-chat", elem_classes=["step-card"]):
            gr.HTML("<div class='step-heading'><span class='step-number'>5</span><div><h2>提问与导出</h2><p>针对当前行程提问，或导出 JSON 与日历文件保存结果。</p></div></div>")
            with gr.Column(elem_classes=["guide-card"]):
                gr.HTML(
                    "<div class='guide-title-row'><h3>💡 演示操作提示</h3>"
                    "<span class='example-free-note'>通过“行程功能示例”选择“单行程正常示例”后，以下四个标准问题"
                    "不消耗每日提问额度；"
                    "请完整复制到“向途证哨提问”中，以免改写后计入额度。</span></div>"
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
                    label="途证哨智能回复",
                    layout="bubble",
                    height=300,
                    placeholder="这里会以对话气泡显示基于当前 TripGraph 和 Plan B 的回答。",
                )
                with gr.Row():
                    question = gr.Textbox(
                        label="向途证哨提问",
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
            history_store,
            state,
            status,
            confirmed,
            risks,
            plan_b,
            trace,
            chatbot,
            amap_status,
            inspection_status,
            image_previews,
            trip_json,
            completion_table,
            question,
        ]
        session_outputs = [history_store, history_select, session_badge]
        persist_outputs = [
            *session_outputs, browser_store, completion_section, completion_table,
            completion_message, local_options_section, local_choice, editor_section,
        ]
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
            image_previews,
            preview,
            completion_section,
            completion_table,
            completion_message,
            editor_section,
            local_options_section,
            local_choice,
        ]

        # Local rendering/persistence must not depend on the queue's SSE stream.
        # In particular, a background history write must never mask an already
        # rendered confidence table or tool evidence with a full loading overlay.
        local_event = {"queue": False, "show_progress": "hidden"}
        # Keep user actions which can raise gr.Error on the queued transport:
        # this Gradio release drops toast metadata on direct HTTP failures.
        # Their progress is scoped to one small area, never the whole view.
        work_event = {"queue": True, "show_progress": "minimal", "trigger_mode": "once"}
        demo.load(
            initialize_session_history,
            inputs=[browser_store],
            outputs=[*session_outputs, *view_outputs],
            **local_event,
        ).success(
            lambda current: current, inputs=history_store, outputs=browser_store,
            api_name=False, **local_event,
        )
        import_outputs = [
            state, amap_status, inspection_status, privacy_confirmed, status,
            trip_json, confidence, low_confidence, timeline, confirmed,
            risks, plan_b, trace, question, chatbot, export_files,
        ]
        downstream_outputs = [risks, plan_b, trace, chatbot, question, export_files]
        load_event = single_example_button.click(
            reset_import_view, outputs=import_outputs, api_name=False, **local_event,
        ).success(load_example, outputs=[image, status, state], api_name="load_example", **local_event)
        def capture_import_preview(files, current):
            paths = _image_paths(files)
            photos = []
            expired = (current or {}).get("_history_preview_digests") or []
            for path in paths[:5]:
                captured = capture_previews([path])
                if captured:
                    photo = captured[0]
                    if file_digest(path) not in expired:
                        attach_original_reference(photo, path, HISTORY_FILE_SECRET)
                    photos.append(photo)
            return import_preview(files, preview), photos

        # Only actual upload/delete/clear actions capture new media. Restoring a
        # session programmatically must not clear its saved previews/results.
        for event in (image.upload, image.clear, image.delete):
            event(reset_import_for_files, inputs=[image, state], outputs=import_outputs, api_name=False, **local_event).success(
                capture_import_preview, inputs=[image, state], outputs=[preview, image_previews], api_name=False, **local_event,
            ).success(persist_current_session, inputs=session_inputs, outputs=persist_outputs, api_name=False, **local_event)
        load_context_event = load_event.success(
            context_panels_for_state,
            inputs=state,
            outputs=[amap_status, inspection_status],
            **local_event,
        )
        for button, kind in ((multi_example_button, "multi"), (conflict_example_button, "conflict")):
            def make_loader(selected):
                def loader():
                    return load_railway_example(selected)
                return loader
            selected_event = button.click(reset_import_view, outputs=import_outputs, api_name=False, **local_event).success(
                make_loader(kind), outputs=[image, status, state], api_name=False, **local_event,
            )
            selected_event.success(context_panels_for_state, inputs=state, outputs=[amap_status, inspection_status], **local_event).success(
                capture_import_preview, inputs=[image, state], outputs=[preview, image_previews], api_name=False, **local_event,
            ).success(
                persist_current_session, inputs=session_inputs, outputs=persist_outputs, api_name=False, **local_event,
            )
        clear_import_button.click(lambda: None, outputs=image, api_name=False, **local_event).success(
            reset_import_view, outputs=import_outputs, **local_event,
        ).success(
            capture_import_preview, inputs=[image, state], outputs=[preview, image_previews], api_name=False, **local_event,
        ).success(
            persist_current_session, inputs=session_inputs, outputs=persist_outputs, api_name=False, **local_event,
        )
        load_context_event.success(
            capture_import_preview, inputs=[image, state], outputs=[preview, image_previews], api_name=False, **local_event,
        ).success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        build_event = build_button.click(
            parse_current_import,
            inputs=[image, privacy_confirmed, history_store, state],
            outputs=[
                trip_json,
                confidence,
                low_confidence,
                timeline,
                state,
                history_store,
            ],
            api_name=False,
            show_progress_on=[status], **work_event,
        ).success(
            lambda current: (
                "✅ 截图已解析，等待补全并确认；" if current.get("draft_trip") else "✅ TripGraph 已构建；"
            ) + str(current.get("parse_summary", "")),
            inputs=[state],
            outputs=status,
            **local_event,
        ).success(reset_after_parse, inputs=state, outputs=[*downstream_outputs, confirmed], api_name=False, **local_event)
        confirm_import_button.click(
            confirm_import, inputs=[completion_table, state],
            outputs=[status, timeline, state, trip_json, confirmed], api_name=False,
            show_progress_on=[status], **work_event,
        ).success(reset_downstream_view, outputs=downstream_outputs, api_name=False, **local_event).success(refresh_confidence, inputs=state, outputs=[confidence, low_confidence], **local_event).success(
            context_panels_for_state, inputs=state, outputs=[amap_status, inspection_status], **local_event,
        ).success(persist_current_session, inputs=session_inputs, outputs=persist_outputs, api_name=False, **local_event)
        build_context_event = build_event.success(
            context_panels_for_state,
            inputs=state,
            outputs=[amap_status, inspection_status],
            **local_event,
        )
        build_context_event.success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        edit_event = apply_edits_button.click(
            apply_tripgraph_edits,
            inputs=[trip_json, state],
            outputs=[trip_json, timeline, state, status, confirmed],
            api_name=False,
            show_progress_on=[status], **work_event,
        ).success(reset_downstream_view, outputs=downstream_outputs, api_name=False, **local_event)
        edit_event.success(
            context_panels_for_state,
            inputs=state,
            outputs=[amap_status, inspection_status],
            **local_event,
        ).success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        def export_callback(current):
            return export_current_trip(current, cache_root=export_files.GRADIO_CACHE)
        export_button.click(
            export_callback,
            inputs=[state],
            outputs=[export_files],
            api_name=False,
            show_progress_on=[export_files], **work_event,
        )
        check_event = check_button.click(
            check_risks,
            inputs=[state, confirmed],
            outputs=risks,
            api_name="check_risks",
            show_progress_on=[risks], **work_event,
        )
        check_event.success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        recheck_event = recheck_button.click(
            check_risks, inputs=[state, confirmed], outputs=risks,
            show_progress_on=[risks], **work_event,
        )
        recheck_event.success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        plan_event = plan_button.click(
            generate_plan_b_guarded,
            inputs=[state, confirmed, history_store],
            outputs=[plan_b, trace, state, amap_status, inspection_status, history_store],
            api_name=False,
            show_progress_on=[plan_b], **work_event,
        )
        plan_render_event = plan_event.success(
            render_state_trip,
            inputs=[state],
            outputs=[trip_json, timeline],
            **local_event,
        ).success(check_risks, inputs=[state, confirmed], outputs=risks, api_name=False,
                  show_progress_on=[risks], **work_event)
        plan_render_event.success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        plan_event.success(local_options_view, inputs=state, outputs=[local_options_section, local_choice], **local_event)
        apply_local_button.click(
            apply_local_option, inputs=[local_choice, state],
            outputs=[trip_json, timeline, risks, state, plan_b, status, confirmed], api_name=False,
            show_progress_on=[status], **work_event,
        ).success(lambda: ([], "", None), outputs=[chatbot, question, export_files], api_name=False, **local_event).success(refresh_confidence, inputs=state, outputs=[confidence, low_confidence], **local_event).success(
            context_panels_for_state, inputs=state, outputs=[amap_status, inspection_status], **local_event,
        ).success(
            persist_current_session, inputs=session_inputs, outputs=persist_outputs, api_name=False, **local_event,
        )
        inspect_event = inspect_button.click(
            run_live_inspection_guarded,
            inputs=[state, confirmed, history_store],
            outputs=[amap_status, inspection_status, state, history_store],
            api_name=False,
            show_progress_on=[trace], **work_event,
        )
        inspect_render_event = inspect_event.success(
            render_state_trip,
            inputs=[state],
            outputs=[trip_json, timeline],
            **local_event,
        ).success(check_risks, inputs=[state, confirmed], outputs=risks, api_name=False,
                  show_progress_on=[risks], **work_event).success(
            current_tool_trace, inputs=state, outputs=trace, api_name=False, **local_event,
        )
        inspect_render_event.success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        ask_event = ask_button.click(
            answer_question_guarded,
            inputs=[question, chatbot, state, history_store],
            outputs=[question, chatbot, history_store],
            api_name=False,
            show_progress_on=[chatbot], **work_event,
        )
        ask_event.success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        submit_event = question.submit(
            answer_question_guarded,
            inputs=[question, chatbot, state, history_store],
            outputs=[question, chatbot, history_store],
            api_name=False,
            show_progress_on=[chatbot], **work_event,
        )
        submit_event.success(
            persist_current_session,
            inputs=session_inputs,
            outputs=persist_outputs, api_name=False,
            **local_event,
        )
        new_session_button.click(
            create_new_history_session,
            inputs=session_inputs,
            outputs=[*session_outputs, *view_outputs],
            api_name="new_session",
            show_progress_on=[session_badge], **work_event,
        ).success(lambda current: current, inputs=history_store, outputs=browser_store, api_name=False, **local_event)
        history_select.input(
            open_history_session,
            inputs=[history_select, *session_inputs],
            outputs=[*session_outputs, *view_outputs],
            api_name=False,
            trigger_mode="always_last",
            queue=True, show_progress="minimal", show_progress_on=[session_badge],
        ).success(lambda current: current, inputs=history_store, outputs=browser_store, api_name=False, **local_event)
        delete_session_button.click(
            delete_current_history_session,
            inputs=[history_store],
            outputs=[*session_outputs, *view_outputs],
            api_name=False,
            show_progress_on=[session_badge], **work_event,
        ).success(lambda current: current, inputs=history_store, outputs=browser_store, api_name=False, **local_event)
        clear_sessions_button.click(
            clear_all_history_sessions,
            inputs=[history_store],
            outputs=[*session_outputs, *view_outputs],
            api_name=False,
            show_progress_on=[session_badge], **work_event,
        ).success(lambda current: current, inputs=history_store, outputs=browser_store, api_name=False, **local_event)
        for component in (trip_json, completion_table):
            component.input(
                persist_current_session, inputs=session_inputs, outputs=persist_outputs,
                api_name=False, trigger_mode="always_last",
                **local_event,
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
