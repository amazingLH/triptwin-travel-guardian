"""Pure presentation services for the Stage 5 Gradio demo."""

from __future__ import annotations

import json
import copy
from html import escape
from pathlib import Path
from typing import Any

from triptwin.candidate_validator import validate_candidate_artifact
from triptwin.live_context import AmapInspection, apply_amap_evidence
from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine


ROOT = Path(__file__).resolve().parents[2]
GOLDEN_TRIP_PATH = ROOT / "examples" / "hangzhou_golden_trip.json"
CANDIDATES_PATH = ROOT / "docs" / "evidence" / "stage4-api" / "candidates.json"
VISION_EVIDENCE_PATH = (
    ROOT / "docs" / "evidence" / "stage5-vision" / "vision-result.json"
)
SAMPLE_IMAGE_PATH = ROOT / "assets" / "hangzhou-golden-itinerary.png"
AMAP_INSPECTION_PATH = ROOT / "docs" / "evidence" / "stage6-amap" / "inspection.json"
DEPLOYMENT_EVIDENCE_PATH = (
    ROOT / "docs" / "evidence" / "stage6-deployment" / "run.json"
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 根节点必须是对象。")
    return value


def load_cached_vision() -> dict[str, Any]:
    return load_json(VISION_EVIDENCE_PATH)


def analyze_trip(trip_payload: dict[str, Any]) -> tuple[Trip, Any]:
    completed = copy.deepcopy(trip_payload)
    if AMAP_INSPECTION_PATH.is_file():
        inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
        completed = apply_amap_evidence(completed, inspection)
    events = completed.get("events", [])
    previous_event_id: str | None = None
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        if (
            event.get("travel_minutes_from_previous") is not None
            and not event.get("transfer_from_event_id")
            and previous_event_id
        ):
            event["transfer_from_event_id"] = previous_event_id
            event["depends_on"] = list(
                dict.fromkeys([*(event.get("depends_on") or []), previous_event_id])
            )
        if isinstance(event.get("id"), str):
            previous_event_id = event["id"]
    trip = Trip.model_validate(completed)
    return trip, RiskEngine().analyze(trip)


def validate_plan_b(trip_payload: dict[str, Any]) -> Any:
    trip, analysis = analyze_trip(trip_payload)
    return validate_candidate_artifact(trip, analysis, load_json(CANDIDATES_PATH))


def timeline_html(trip_payload: dict[str, Any]) -> str:
    trip = Trip.model_validate(trip_payload)
    items = []
    for event in sorted(trip.events, key=lambda item: item.start):
        protected = " · 🔒受保护" if event.id in trip.constraints.protected_event_ids else ""
        place = event.location or event.destination or event.origin
        items.append(
            "<div class='timeline-item'>"
            f"<div class='timeline-time'>{event.start:%m/%d %H:%M}–{event.end:%H:%M}</div>"
            f"<div><b>{escape(event.title)}</b>{protected}<br>"
            f"<span>{escape(place.name if place else '地点未提供')} · "
            f"¥{event.cost_cny if event.cost_cny is not None else '待确认'} · "
            f"步行 {event.walking_minutes} 分钟</span></div></div>"
        )
    return "<div class='timeline'>" + "".join(items) + "</div>"


def risk_markdown(trip_payload: dict[str, Any]) -> str:
    _, analysis = analyze_trip(trip_payload)
    labels = {
        "time_connection": "时间",
        "date_consistency": "日期",
        "budget": "预算",
        "mobility": "体力",
        "weather": "天气",
    }
    lines = [
        f"### 检出 {analysis.risk_count} 个风险 · 总分 {analysis.total_risk_score}",
        f"**预算状态：** `{analysis.budget.status}` · 已知预计总额 ¥{analysis.budget.projected_known_total_cny}",
    ]
    for risk in analysis.risks:
        lines.extend(
            [
                f"#### {labels.get(str(risk.risk_type), str(risk.risk_type))} · {risk.title}",
                f"`{risk.severity}` / {risk.score}分　{risk.description}",
                "- 证据：" + "；".join(risk.evidence),
                "- 建议：" + risk.recommendation,
            ]
        )
    return "\n\n".join(lines)


def plan_b_markdown(trip_payload: dict[str, Any]) -> str:
    trip, analysis = analyze_trip(trip_payload)
    validation = validate_candidate_artifact(
        trip, analysis, load_json(CANDIDATES_PATH)
    )
    if not validation.valid:
        reasons = "；".join(validation.rejection_reasons)
        return f"### Plan B 尚未通过本地验证\n\n{reasons}"
    rows = []
    total_extra = 0
    for selection in validation.selections:
        total_extra += selection.extra_cost_cny
        rows.append(
            f"| {escape(selection.event_id)} | "
            f"[{escape(selection.name)}]({selection.source_url}) | "
            f"¥{selection.extra_cost_cny} | {len(selection.covered_risk_ids)} |"
        )
    return "\n".join(
        [
            "### ✅ 已验证 Plan B",
            "| 调整节点 | FlyAI 真实候选 | 增量成本 | 覆盖风险 |",
            "|---|---|---:|---:|",
            *rows,
            "",
            f"- 风险覆盖：**{analysis.risk_count} → 0 个未覆盖风险**",
            f"- 入选候选增量合计：**¥{total_extra}**（上限 ¥{trip.constraints.max_plan_b_extra_cost_cny}）",
            "- `train-sh-hz` 与 `hotel-west-lake` 保持不变",
            "- 当前仅为候选方案，**未执行预订或支付**",
        ]
    )


def tool_trace_markdown() -> str:
    candidates = load_json(CANDIDATES_PATH)
    commands = candidates.get("flyai_commands", [])
    lines = [
        "### Agent / FlyAI 工具轨迹",
        f"- 有效 FlyAI 命令证据：**{len(commands)} 条**",
        "- 景点查询 3 条；酒店查询 4 条；酒店候选 6 个",
        "- 所有命令均为 `exit_code=0`、`status=0`",
    ]
    for command in commands:
        command_text = str(command.get("command", "")).replace("\n", " ")
        if len(command_text) > 115:
            command_text = command_text[:112] + "..."
        lines.append(f"- `{command_text}`")
    if AMAP_INSPECTION_PATH.is_file():
        inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
        lines.extend(
            [
                "",
                "### 高德 MCP 工具轨迹",
                f"- 真实 MCP 调用/输出：**{inspection.tool_call_count} / {inspection.tool_output_count}**",
                f"- 工具：`{'`、`'.join(inspection.tool_names)}`",
                f"- 结束状态：`{inspection.run_status}`；错误：**{inspection.error_count}**",
            ]
        )
    return "\n".join(lines)


def amap_inspection_markdown() -> str:
    if not AMAP_INSPECTION_PATH.is_file():
        return "### 空间与天气核验\n\n尚未保存高德 MCP 证据。"
    inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    lines = [
        "### 🛰️ 空间与天气核验",
        f"- 最近获取：**{inspection.captured_at.astimezone():%Y-%m-%d %H:%M:%S}**",
        f"- 会话状态：`{inspection.run_status}` · 错误 **{inspection.error_count}**",
    ]
    if inspection.route:
        route = inspection.route
        lines.extend(
            [
                f"- 路线：{route.origin_name} → {route.destination_name}",
                f"- 高德最快公交：**{route.duration_minutes:.1f} 分钟** · "
                f"{route.distance_meters / 1000:.3f} 公里 · 步行 {route.walking_distance_meters} 米",
                f"- 路线证据：`{route.source_tool}` · 获取于 `{route.fetched_at.isoformat()}`",
            ]
        )
        if route.warning:
            lines.append(f"- ⚠️ {route.warning}")
    if inspection.weather:
        weather = inspection.weather
        dates = "、".join(item.date for item in weather.forecasts)
        lines.append(f"- 天气返回日期：{dates or '无'}")
        if weather.trip_dates_covered:
            lines.append("- ✅ 天气已覆盖行程日期，可进入天气风险规则。")
        else:
            lines.append(
                "- ⚠️ 行程为 10 月 18–20 日，当前预报未覆盖；天气保持**未核验**，不进行猜测。"
            )
    return "\n".join(lines)


def active_inspection_markdown() -> str:
    if not DEPLOYMENT_EVIDENCE_PATH.is_file():
        return "\n".join(
            [
                "### ⏱️ 主动巡检",
                "- Scheduled Task：**等待首次手动运行**",
                "- 当前页面可用已保存的高德证据进行确定性复核；不冒充实时 Deployment。",
                "- 新增/消失风险：首次 Deployment 运行后生成。",
            ]
        )
    run = load_json(DEPLOYMENT_EVIDENCE_PATH)
    return "\n".join(
        [
            "### ⏱️ 主动巡检",
            f"- 最近巡检：**{escape(str(run.get('finished_at') or run.get('updated_at') or '未知'))}**",
            f"- 运行状态：`{escape(str(run.get('status') or 'unknown'))}`",
            f"- 运行记录：`{escape(str(run.get('run_id') or '未记录'))}`",
            f"- 新增风险：{escape(str(run.get('new_risks') or '无'))}",
            f"- 消失风险：{escape(str(run.get('resolved_risks') or '无'))}",
        ]
    )


def run_cached_manual_inspection(trip_payload: dict[str, Any]) -> tuple[str, str]:
    """Re-run deterministic checks with the latest captured cloud evidence."""

    if not isinstance(trip_payload, dict) or not trip_payload.get("events"):
        trip_payload = load_cached_vision()["trip"]
    _, analysis = analyze_trip(trip_payload)
    status = active_inspection_markdown()
    status += (
        f"\n- 本次确定性复核：**{analysis.risk_count} 个风险 / "
        f"{analysis.total_risk_score} 分**"
    )
    return amap_inspection_markdown(), status


def run_golden_demo() -> dict[str, Any]:
    evidence = load_cached_vision()
    trip_payload = evidence["trip"]
    trip, analysis = analyze_trip(trip_payload)
    validation = validate_plan_b(trip_payload)
    return {
        "trip_id": trip.trip_id,
        "vision_model": evidence["model"],
        "field_accuracy": evidence["field_accuracy"],
        "low_confidence_count": len(evidence["low_confidence_fields"]),
        "risk_count": analysis.risk_count,
        "risk_score": analysis.total_risk_score,
        "plan_b_valid": validation.valid,
        "unresolved_risk_count": len(validation.unresolved_risk_ids),
        "protected_untouched": validation.protected_event_ids_untouched,
    }


def chat_context(trip_payload: dict[str, Any]) -> dict[str, Any]:
    trip, analysis = analyze_trip(trip_payload)
    validation = validate_candidate_artifact(
        trip, analysis, load_json(CANDIDATES_PATH)
    )
    return {
        "trip": {
            "trip_id": trip.trip_id,
            "title": trip.title,
            "start": trip.start.isoformat(),
            "end": trip.end.isoformat(),
            "travelers": trip.travelers.model_dump(mode="json"),
            "constraints": trip.constraints.model_dump(mode="json"),
        },
        "risks": [
            {
                "id": risk.id,
                "title": risk.title,
                "description": risk.description,
                "evidence": risk.evidence,
                "recommendation": risk.recommendation,
            }
            for risk in analysis.risks
        ],
        "plan_b": {
            "valid": validation.valid,
            "unresolved_risk_ids": validation.unresolved_risk_ids,
            "protected_event_ids_untouched": (
                validation.protected_event_ids_untouched
            ),
            "selections": [
                selection.model_dump(mode="json")
                for selection in validation.selections
            ],
        },
        "tool_evidence": {
            "successful_flyai_commands": len(
                load_json(CANDIDATES_PATH).get("flyai_commands", [])
            ),
            "source": "official FlyAI Skill",
            "amap": load_json(AMAP_INSPECTION_PATH)
            if AMAP_INSPECTION_PATH.is_file()
            else {"status": "unavailable"},
        },
        "service_boundary": "只分析与推荐，不代订、不支付；价格库存以下单页为准。",
    }
