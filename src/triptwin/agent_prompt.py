"""Build a bounded Managed Agent task from deterministic TripGraph findings."""

from __future__ import annotations

import json

from triptwin.models import Trip, TripAnalysis


def build_replanning_prompt(trip: Trip, analysis: TripAnalysis) -> str:
    """Ask the cloud agent for evidence, not for the final risk decision.

    The local deterministic engine remains the source of truth for whether a
    risk exists.  The cloud agent is limited to finding real FlyAI candidates
    for affected, non-protected nodes.
    """

    protected = sorted(trip.constraints.protected_event_ids)
    affected = sorted(
        {
            event_id
            for risk in analysis.risks
            for event_id in risk.affected_event_ids
            if event_id not in trip.constraints.protected_event_ids
        }
    )
    event_by_id = {event.id: event for event in trip.events}
    affected_events = [
        {
            "id": event_id,
            "title": event_by_id[event_id].title,
            "start": event_by_id[event_id].start.isoformat(),
            "end": event_by_id[event_id].end.isoformat(),
            "city": _event_city(event_by_id[event_id]),
        }
        for event_id in affected
        if event_id in event_by_id
    ]
    risk_payload = [
        {
            "id": risk.id,
            "severity": risk.severity,
            "description": risk.description,
            "affected_event_ids": risk.affected_event_ids,
            "recommendation": risk.recommendation,
        }
        for risk in analysis.risks
    ]
    additive_repairs = [
        {
            "risk_id": risk.id,
            "description": risk.description,
            "recommendation": risk.recommendation,
        }
        for risk in analysis.risks
        if risk.affected_event_ids
        and all(
            event_id in trip.constraints.protected_event_ids
            for event_id in risk.affected_event_ids
        )
    ]
    context = {
        "trip_id": trip.trip_id,
        "trip_window": [trip.start.isoformat(), trip.end.isoformat()],
        "protected_event_ids": protected,
        "affected_events": affected_events,
        "preferences": trip.constraints.preferences,
        "avoidances": trip.constraints.avoidances,
        "budget_cny": str(trip.constraints.budget_cny),
        "max_plan_b_extra_cost_cny": str(
            trip.constraints.max_plan_b_extra_cost_cny
        ),
        "risks": risk_payload,
        "additive_repairs": additive_repairs,
    }
    return (
        "你是 TripTwin 的候选检索执行器。风险是否成立已由本地确定性规则判定，"
        "不要自行改写风险结论。请激活已挂载的官方“飞猪旅行”Skill，先读取所需"
        "命令的参数文档，再通过 bash 实际执行 FlyAI CLI 查询。只为 affected_events"
        " 中的节点寻找真实候选；严禁更改 protected_event_ids 中的订单。对于"
        " additive_repairs，必须通过新增节点解决（例如缺少住宿晚数就执行 search-hotel），"
        "并把结果写入 additive_candidates。优先低步行、"
        "少换乘、室内和预算友好的杭州候选。至少执行一次 FlyAI 查询。最终仅返回"
        "一个 JSON 对象，字段为 status、flyai_commands、candidates、"
        "additive_candidates、notes；不得声称"
        "已预订或已支付。\n\nTripGraph context:\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


def build_missing_hotel_prompt(trip: Trip, risk_id: str) -> str:
    """Build a minimal recovery turn for the one uncovered hotel-night risk."""

    protected = sorted(trip.constraints.protected_event_ids)
    context = {
        "trip_id": trip.trip_id,
        "risk_id": risk_id,
        "city": "杭州",
        "check_in_date": "2026-10-19",
        "check_out_date": "2026-10-20",
        "preferred_area": "西湖",
        "protected_event_ids": protected,
        "budget_cny": str(trip.constraints.budget_cny),
        "max_plan_b_extra_cost_cny": str(
            trip.constraints.max_plan_b_extra_cost_cny
        ),
    }
    return (
        "这是 TripTwin 阶段 4 的增量修复任务，只处理第二晚住宿缺失，不要重复查询"
        "景点。请激活官方“飞猪旅行”Skill，读取 references/search-hotel.md，"
        "然后通过 bash 实际执行一次 flyai search-hotel：杭州、西湖附近、"
        "入住 2026-10-19、退房 2026-10-20。严禁改动 protected_event_ids 中"
        "已有订单；本任务只能新增第二晚住宿候选。至少返回 3 个带飞猪 jumpUrl 的"
        "真实酒店候选，价格未知时必须用 null，不得编造。不得预订或支付。把最终"
        "JSON 写入 /mnt/session/outputs/hangzhou-golden-001-hotel-repair.json，"
        "结构必须包含 status、flyai_commands、candidates（空对象）、"
        "additive_candidates、notes。其中 additive_candidates 以 risk_id 为键，"
        "每项包含 risk_ids 和 options；每个 option 至少包含 name、jumpUrl、"
        "price_cny、extra_cost_cny、source='flyai'。\n\nRecovery context:\n"
        + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


def _event_city(event: object) -> str | None:
    for attr in ("location", "destination", "origin"):
        location = getattr(event, attr, None)
        if location is not None:
            return location.city
    return None

