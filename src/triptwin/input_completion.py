"""Human confirmation between image extraction and a usable TripGraph."""
from __future__ import annotations

import copy
import json
from datetime import datetime
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
    "event_type": "行程类型（transport 交通、accommodation 住宿、activity 活动、meal 餐饮、transfer 换乘）",
    "id": "内部行程编号（如 event-1）", "mobility_limitations": "行动限制（列表；无则填写 []）",
    "depends_on": "前置行程编号（列表，如 [\"event-1\"]；没有则 []）",
    "protected_event_ids": "必须保留的行程编号（列表；没有则 []）",
    "transfer_from_event_id": "上一段衔接行程编号（不衔接则 null）",
}


def validation_message(exc: ValidationError) -> str:
    error = exc.errors()[0]
    loc, message = error["loc"], error["msg"]
    translations = {
        "event end must be later": "结束时间必须晚于开始时间；跨日到达请填写次日日期。",
        "trip end must be later": "旅行结束时间必须晚于开始时间。",
        "event ids must be unique": "各项行程的内部编号不能重复，请在高级校对中修改重复编号。",
        "references unknown event ids": "前置或衔接行程编号不存在，请核对关联编号。",
        "cannot depend on itself": "行程不能将自己设为前置事件，请修正关联编号。",
        "contains a cycle": "行程关联形成循环，请删除错误的前置或衔接关系。",
        "同行总人数": "成人、儿童和老人合计至少为 1 人，请核对人数。",
        "受保护行程": "必须保留的行程编号不存在，请核对保护列表。",
        "366 天": "单次行程跨度超过 366 天，请核对年份或拆分行程。",
    }
    for marker, rendered in translations.items():
        if marker in message:
            return rendered
    prefix = f"第 {loc[1] + 1} 项" if len(loc) > 1 and loc[0] == "events" and isinstance(loc[1], int) else ""
    key = str(loc[-1]) if loc else ""
    if key == "budget_cny":
        return "请输入有效的总预算：金额必须大于 0，只填数字，例如 2000。"
    return f"请检查{prefix}{LABELS.get(key, '行程信息')}：填写值的格式或范围不正确。日期时间请带 +08:00 时区；数量和金额只填数字。"


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
            if loc and error["type"] != "extra_forbidden" and not isinstance(read_value(payload, loc), (dict, list)):
                fields.append((loc, LABELS.get(str(loc[-1]), "需修正：" + error["msg"])))
            if not loc and any(marker in error["msg"] for marker in ("references unknown", "contains a cycle", "cannot depend")):
                for index, event in enumerate(payload.get("events", [])):
                    fields.append((("events", index, "depends_on"), LABELS["depends_on"]))
                    if event.get("transfer_from_event_id"):
                        fields.append((("events", index, "transfer_from_event_id"), LABELS["transfer_from_event_id"]))
            if not loc and "受保护行程" in error["msg"]:
                fields.append((("constraints", "protected_event_ids"), LABELS["protected_event_ids"]))
    for index, event in enumerate(payload.get("events", [])):
        if not isinstance(event, dict):
            continue
        for key in ("start", "end", "cost_cny"):
            if event.get(key) is None:
                fields.append((("events", index, key), LABELS[key]))
        # Invalid windows need two editable timestamps, not a whole JSON object.
        try:
            if datetime.fromisoformat(str(event.get("end"))) <= datetime.fromisoformat(str(event.get("start"))):
                for key in ("start", "end"):
                    fields.append((("events", index, key), LABELS[key]))
        except (ValueError, TypeError):
            pass
        for key in ("origin", "destination") if event.get("event_type") == "transport" else ("location",):
            place = event.get(key)
            for prop in ("name", "city"):
                value = place.get(prop) if isinstance(place, dict) else None
                if not value or value == "待确认":
                    fields.append((("events", index, key, prop), LABELS[prop]))
    result = []
    for parts, label in dict(fields).items():
        if len(parts) > 2 and parts[0] == "events" and isinstance(parts[1], int):
            title = str(payload["events"][parts[1]].get("title") or "未命名行程")
            label = f"第 {parts[1] + 1} 项（{title}）：{label}"
        result.append((parts, label))
    return result


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
            if isinstance(event, dict) and isinstance(event.get("metadata"), dict) and event["metadata"].get("booking_status")
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
        optional_reference = path.endswith(".transfer_from_event_id")
        if (not value or value in {"null", "待确认"}) and not optional_reference:
            if path == "constraints.budget_cny":
                raise ValueError("请输入总预算：在表格第一行“总预算”的填写值中输入金额（例如 2000），然后再次点击确认。Plan B 最大新增费用是另一项，不能代替总预算。")
            label = str(row[1]).split("（", 1)[0]
            raise ValueError(f"请输入{label}：在对应行的“填写值”中补充信息，然后再次点击确认。")
        try:
            parsed = None if optional_reference and not value else json.loads(value)
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
        for index, event in enumerate(events):
            for key in ("start", "end"):
                try:
                    parsed_time = datetime.fromisoformat(str(event[key]))
                except (TypeError, ValueError):
                    raise ValueError(f"请输入有效的第 {index + 1} 项{LABELS[key]}，例如 2026-10-20T20:16:00+08:00。") from None
                if parsed_time.utcoffset() is None:
                    raise ValueError(f"第 {index + 1} 项{LABELS[key]}缺少时区，请在时间末尾加上 +08:00。")
            if datetime.fromisoformat(str(event["end"])) <= datetime.fromisoformat(str(event["start"])):
                raise ValueError(f"第 {index + 1} 项（{event.get('title', '行程')}）的结束时间必须晚于开始时间；跨日到达请填写次日日期。")
        result["start"] = min((e["start"] for e in events), key=datetime.fromisoformat)
        result["end"] = max((e["end"] for e in events), key=datetime.fromisoformat)
    try:
        trip = Trip.model_validate(result)
    except ValidationError as exc:
        raise ValueError(validation_message(exc)) from None
    if trip.constraints.budget_cny is None:
        raise ValueError("请填写总预算后再构建。")
    return trip
