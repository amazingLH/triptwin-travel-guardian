"""Pure presentation services for the Stage 5 Gradio demo."""

from __future__ import annotations

import json
import copy
from html import escape
from pathlib import Path
from typing import Any
from datetime import timedelta, timezone

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
CHINA_TIME = timezone(timedelta(hours=8))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 根节点必须是对象。")
    return value


def load_cached_vision() -> dict[str, Any]:
    return load_json(VISION_EVIDENCE_PATH)


def analyze_trip(
    trip_payload: dict[str, Any], *, include_cached_amap: bool = True
) -> tuple[Trip, Any]:
    completed = copy.deepcopy(trip_payload)
    if include_cached_amap and AMAP_INSPECTION_PATH.is_file():
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


def validate_plan_b(
    trip_payload: dict[str, Any], *, include_cached_amap: bool = True
) -> Any:
    trip, analysis = analyze_trip(
        trip_payload, include_cached_amap=include_cached_amap
    )
    return validate_candidate_artifact(trip, analysis, load_json(CANDIDATES_PATH))


def timeline_html(trip_payload: dict[str, Any]) -> str:
    trip = Trip.model_validate(trip_payload)
    items = []
    for event in sorted(trip.events, key=lambda item: item.start):
        protected = " · 🔒受保护" if event.id in trip.constraints.protected_event_ids else ""
        place = event.location or event.destination or event.origin
        items.append(
            "<div class='timeline-item'>"
            f"<div class='timeline-time'>{event.start:%m/%d %H:%M}–"
            f"{event.end.strftime('%H:%M') if event.start.date() == event.end.date() else event.end.strftime('%m/%d %H:%M')}</div>"
            f"<div><b>{escape(event.title)}</b>{protected}<br>"
            f"<span>{escape(place.name if place else '地点未提供')} · "
            f"¥{event.cost_cny if event.cost_cny is not None else '待确认'} · "
            f"步行 {event.walking_minutes} 分钟</span></div></div>"
        )
    return "<div class='timeline'>" + "".join(items) + "</div>"


def risk_markdown(
    trip_payload: dict[str, Any], *, include_cached_amap: bool = True
) -> str:
    _, analysis = analyze_trip(
        trip_payload, include_cached_amap=include_cached_amap
    )
    labels = {
        "time_connection": "时间",
        "date_consistency": "日期",
        "budget": "预算",
        "mobility": "体力",
        "weather": "天气",
        "schedule": "日程",
    }
    severity_labels = {"critical": "严重", "high": "高风险", "medium": "中风险", "low": "低风险"}
    lines = [
        f"### 检出 {analysis.risk_count} 个风险 · 总分 {analysis.total_risk_score}",
        f"**预算状态：** { {'within_budget': '已知费用未超预算', 'exceeded': '已知费用超限', 'indeterminate': '未核验（信息不足）'}[analysis.budget.status] } · 已知预计总额 ¥{analysis.budget.projected_known_total_cny}",
        "检查范围仅为已导入行程及现有证据；未检出风险不代表整趟旅行已核验或绝对安全。",
    ]
    if analysis.data_quality_warnings:
        lines.extend(["#### 待核验信息", *("- " + escape(warning) for warning in analysis.data_quality_warnings)])
    for risk in analysis.risks:
        lines.extend(
            [
                f"#### {labels.get(str(risk.risk_type), str(risk.risk_type))} · {risk.title}",
                f"{severity_labels[str(risk.severity)]} / {risk.score}分　{escape(risk.description)}",
                "- 证据：" + "；".join(risk.evidence),
                "- 建议：" + risk.recommendation,
            ]
        )
    return "\n\n".join(lines)


def plan_b_markdown(
    trip_payload: dict[str, Any], *, include_cached_amap: bool = True,
    candidate_artifact: dict[str, Any] | None = None,
    require_simulation: bool = False,
) -> str:
    trip, analysis = analyze_trip(
        trip_payload, include_cached_amap=include_cached_amap
    )
    if analysis.risk_count == 0:
        return (
            "### ✅ 当前无需 Plan B\n\n"
            "现有 TripGraph 未触发确定性风险规则。价格、库存和天气仍可能变化，"
            "出发前请重新核验；TripTwin 不会自动预订或支付。"
        )
    artifact = candidate_artifact
    if artifact is None and include_cached_amap:
        artifact = load_json(CANDIDATES_PATH)
    if artifact is None:
        return (
            "### Plan B 尚未生成\n\n"
            "当前行程没有专属的实时 FlyAI 候选证据。为避免把公开杭州示例套用到您的行程，"
            "TripTwin 不会展示静态候选；请执行实时核验后再生成。"
        )
    validation = validate_candidate_artifact(
        trip, analysis, artifact, require_simulation=require_simulation
    )
    if not validation.valid:
        reasons = "；".join(validation.rejection_reasons)
        return f"### Plan B 尚未通过本地验证\n\n{reasons}"
    rows = []
    total_extra = validation.total_extra_cost_cny
    titles = {event.id: event.title for event in trip.events}
    for selection in validation.selections:
        change_label = (
            "补齐缺失住宿" if selection.event_id == "additive:date_consistency:missing_accommodation_nights"
            else "新增行程" if selection.event_id.startswith("additive:")
            else titles.get(selection.event_id, selection.event_id)
        )
        rows.append(
            f"| {escape(change_label)} | "
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
            f"- 候选获取时间：`{escape(str(artifact.get('fetched_at') or '历史合成证据'))}`；价格与库存以下单页为准",
            "- 所有受保护节点保持不变",
            "- 当前仅为候选方案，**未执行预订或支付**",
        ]
    )


def tool_trace_markdown(
    candidate_artifact: dict[str, Any] | None = None,
    inspection: AmapInspection | None = None,
) -> str:
    candidates = (
        candidate_artifact
        if candidate_artifact is not None
        else load_json(CANDIDATES_PATH)
    )
    raw_commands = candidates.get("flyai_commands", [])
    commands = (
        [command for command in raw_commands if isinstance(command, dict)]
        if isinstance(raw_commands, list)
        else []
    )
    lines = [
        "### Agent / FlyAI 工具轨迹",
        f"- FlyAI 命令证据：**{len(commands)} 条**",
        f"- 已验证成功：**{sum(command.get('exit_code') == 0 and command.get('result_status') == 0 for command in commands)} 条**；其余未通过验证",
    ]
    if candidate_artifact is None:
        lines.insert(2, "- 合成示例证据：景点查询 3 条；酒店查询 4 条；酒店候选 6 个")
    else:
        categories = sorted(
            {
                str(command.get("command", "")).split("flyai ", 1)[1].split()[0]
                for command in commands
                if "flyai " in str(command.get("command", ""))
            }
        )
        lines.insert(2, "- 本次查询类型：" + ("、".join(categories) or "无已验证查询"))
    for command in commands:
        command_text = str(command.get("command", "")).replace("\n", " ")
        if len(command_text) > 115:
            command_text = command_text[:112] + "..."
        lines.append(f"- `{command_text}`")
    if inspection is None and candidate_artifact is None and AMAP_INSPECTION_PATH.is_file():
        inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    if inspection is not None:
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


def amap_inspection_markdown(inspection: AmapInspection | None = None) -> str:
    if inspection is None and not AMAP_INSPECTION_PATH.is_file():
        return "### 空间与天气核验\n\n尚未保存高德 MCP 证据。"
    if inspection is None:
        inspection = AmapInspection.model_validate(load_json(AMAP_INSPECTION_PATH))
    lines = [
        "### 🛰️ 空间与天气核验",
        f"- 最近获取：**{inspection.captured_at.astimezone(CHINA_TIME):%Y-%m-%d %H:%M:%S}**",
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
            lines.append("- ⚠️ 当前预报未覆盖完整行程；未覆盖日期保持**未核验**，不进行猜测。")
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


def chat_context(
    trip_payload: dict[str, Any], *, include_cached_amap: bool = True,
    candidate_artifact: dict[str, Any] | None = None,
    amap_inspection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trip, analysis = analyze_trip(
        trip_payload, include_cached_amap=include_cached_amap
    )
    artifact = candidate_artifact
    if artifact is None and include_cached_amap:
        artifact = load_json(CANDIDATES_PATH)
    validation = (
        validate_candidate_artifact(
            trip,
            analysis,
            artifact,
            require_simulation=bool(candidate_artifact is not None and not include_cached_amap),
        )
        if artifact is not None
        else None
    )
    return {
        "trip": {
            "trip_id": trip.trip_id,
            "title": trip.title,
            "start": trip.start.isoformat(),
            "end": trip.end.isoformat(),
            "travelers": trip.travelers.model_dump(mode="json"),
            "constraints": trip.constraints.model_dump(mode="json"),
            "events": [event.model_dump(mode="json", exclude={"metadata"}) for event in trip.events],
        },
        "data_quality_warnings": analysis.data_quality_warnings,
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
            "valid": validation.valid if validation else False,
            "unresolved_risk_ids": validation.unresolved_risk_ids if validation else [risk.id for risk in analysis.risks],
            "protected_event_ids_untouched": (
                validation.protected_event_ids_untouched if validation else True
            ),
            "selections": [
                selection.model_dump(mode="json")
                for selection in (validation.selections if validation else [])
            ],
        },
        "tool_evidence": {
            "successful_flyai_commands": len(
                artifact.get("flyai_commands", []) if artifact else []
            ),
            "source": "official FlyAI Skill" if artifact else "not_run_for_current_trip",
            "amap": (
                amap_inspection
                if isinstance(amap_inspection, dict)
                else load_json(AMAP_INSPECTION_PATH)
                if include_cached_amap and AMAP_INSPECTION_PATH.is_file()
                else {"status": "not_run_for_current_trip"}
            ),
        },
        "service_boundary": "只分析与推荐，不代订、不支付；价格库存以下单页为准。",
    }
