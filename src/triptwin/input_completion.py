"""Human confirmation between image extraction and a usable TripGraph."""
from __future__ import annotations

import copy
import json
from typing import Any

from pydantic import ValidationError

from triptwin.models import Trip


LABELS = {
    "budget_cny": "总预算（元，必须填写）", "max_plan_b_extra_cost_cny": "Plan B 最大新增费用（元）",
    "minimum_connection_buffer_minutes": "最小衔接缓冲（分钟）",
    "max_daily_walk_minutes": "每天最多步行（分钟）", "max_daily_activities": "每天最多活动数",
    "max_transfers_per_leg": "每段最多换乘数", "adults": "成人数", "children": "儿童数",
    "seniors": "老人数", "start": "开始时间（如 2026-10-20T20:16:00+08:00）",
    "end": "结束时间（带 +08:00 时区）", "cost_cny": "订单/活动价格（元）",
    "city": "城市", "name": "站点或地点名称", "title": "行程名称",
}


def field_path(parts: tuple[Any, ...]) -> str:
    return ".".join(map(str, parts))


def read_value(payload: dict, parts: tuple[Any, ...]) -> Any:
    current: Any = payload
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and isinstance(part, int) and part < len(current):
            current = current[part]
        else:
            return None
    return current


def completion_fields(payload: dict) -> list[tuple[tuple[Any, ...], str]]:
    fields = [
        (("constraints", key), LABELS[key]) for key in (
            "budget_cny", "max_plan_b_extra_cost_cny", "minimum_connection_buffer_minutes",
            "max_daily_walk_minutes", "max_daily_activities", "max_transfers_per_leg",
        )
    ] + [(("travelers", key), LABELS[key]) for key in ("adults", "children", "seniors")]
    try:
        Trip.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors():
            loc = error["loc"]
            if loc and error["type"] != "extra_forbidden":
                fields.append((loc, LABELS.get(str(loc[-1]), "需修正：" + error["msg"])))
    for index, event in enumerate(payload.get("events", [])):
        if not isinstance(event, dict):
            continue
        for key in ("start", "end", "cost_cny"):
            if event.get(key) is None:
                fields.append((("events", index, key), LABELS[key]))
        for key in ("origin", "destination") if event.get("event_type") == "transport" else ("location",):
            place = event.get(key)
            for prop in ("name", "city"):
                value = place.get(prop) if isinstance(place, dict) else None
                if not value or value == "待确认":
                    fields.append((("events", index, key, prop), LABELS[prop]))
    return list(dict(fields).items())


def completion_rows(payload: dict) -> list[list[str]]:
    defaults = {
        "max_plan_b_extra_cost_cny": 500, "minimum_connection_buffer_minutes": 20,
        "max_daily_walk_minutes": 60, "max_daily_activities": 3, "max_transfers_per_leg": 1,
        "adults": 1, "children": 0, "seniors": 0,
    }
    rows = []
    for parts, label in completion_fields(payload):
        value = read_value(payload, parts)
        if value is None:
            value = defaults.get(str(parts[-1]))
            if value is not None:
                label += "（默认值，请确认）"
        rendered = "" if value is None else json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        rows.append([field_path(parts), label, rendered])
    return rows


def cancelled_orders(payload: dict) -> list[str]:
    return [str(event.get("title", "订单")) for event in payload.get("events", [])
            if isinstance(event, dict) and event.get("metadata", {}).get("booking_status")
            in {"refunded", "cancelled", "已退票", "已取消"}]


def confirm_draft(payload: dict, rows: list[list[Any]]) -> Trip:
    if cancelled_orders(payload):
        raise ValueError("已退票/取消订单：" + "、".join(cancelled_orders(payload)) +
                         "。该订单不能作为有效出行凭证；请清空并上传当前有效订单，不能通过补填预算恢复其有效性。")
    result = copy.deepcopy(payload)
    allowed = {field_path(parts): parts for parts, _ in completion_fields(payload)}
    seen = set()
    for row in rows:
        if len(row) != 3 or str(row[0]) not in allowed:
            raise ValueError("参数路径已被修改，请重新解析或恢复原参数路径，只编辑填写值列。")
        path = str(row[0])
        if path in seen:
            raise ValueError("参数重复，请保留每个参数一行。")
        seen.add(path)
        value = str(row[2]).strip() if row[2] is not None else ""
        if not value or value in {"null", "待确认"}:
            raise ValueError("请补充：" + str(row[1]))
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = value
        parts = allowed[path]
        if not parts:
            raise ValueError("行程结构需修正，请在结构化行程中校对，或上传更详细截图。")
        current = result
        for pos, part in enumerate(parts[:-1]):
            if isinstance(current, dict) and not isinstance(current.get(part), (dict, list)):
                current[part] = [] if isinstance(parts[pos + 1], int) else {}
            current = current[part]
        current[parts[-1]] = parsed
    if seen != set(allowed):
        raise ValueError("补充参数不完整，请保留表格所有行。")
    # Overall dates are derived from actual legs, never from an advertisement.
    events = result.get("events", [])
    if events and all(isinstance(e, dict) and e.get("start") and e.get("end") for e in events):
        from datetime import datetime
        result["start"] = min((e["start"] for e in events), key=datetime.fromisoformat)
        result["end"] = max((e["end"] for e in events), key=datetime.fromisoformat)
    trip = Trip.model_validate(result)
    if trip.constraints.budget_cny is None:
        raise ValueError("请填写总预算后再构建。")
    return trip
