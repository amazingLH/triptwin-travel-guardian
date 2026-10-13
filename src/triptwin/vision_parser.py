"""Multimodal itinerary extraction through Alibaba Cloud Model Studio."""

from __future__ import annotations

import base64
import copy
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from triptwin.config import Settings
from triptwin.models import Trip


class VisionExtraction(BaseModel):
    """Validated structured output returned by the vision model."""

    model_config = ConfigDict(extra="forbid")

    trip: Trip
    field_confidence: dict[str, float] = Field(default_factory=dict)
    low_confidence_fields: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def extract_trip_from_image(
    image_path: str | Path,
    *,
    settings: Settings | None = None,
    model: str | None = None,
    timeout_seconds: float = 120,
) -> tuple[VisionExtraction, dict[str, Any]]:
    """Read an itinerary image with Qwen and return a validated TripGraph."""

    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"未找到行程图片：{path}")
    resolved_settings = settings or Settings.from_env()
    resolved_model = model or resolved_settings.dashscope_vision_model
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    data_url = (
        f"data:{mime_type};base64,"
        + base64.b64encode(path.read_bytes()).decode("ascii")
    )
    endpoint = (
        f"https://{resolved_settings.bailian_workspace_id}.cn-beijing.maas.aliyuncs.com"
        "/compatible-mode/v1/chat/completions"
    )
    payload = {
        "model": resolved_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": _EXTRACTION_PROMPT},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 5000,
        "enable_thinking": False,
    }
    headers = {
        "Authorization": (
            "Bearer "
            + resolved_settings.dashscope_api_key.get_secret_value()
        ),
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    parsed = _normalize_extraction(_parse_json_object(content))
    extraction = VisionExtraction.model_validate(parsed)
    metadata = {
        "model": resolved_model,
        "request_id": response.headers.get("x-request-id")
        or body.get("request_id")
        or body.get("id"),
        "usage": body.get("usage", {}),
    }
    return extraction, metadata


def _normalize_extraction(payload: dict[str, Any]) -> dict[str, Any]:
    """Map harmless model naming variants into the strict TripGraph schema."""

    normalized = copy.deepcopy(payload)
    trip = normalized.get("trip")
    if not isinstance(trip, dict):
        return normalized

    travelers = trip.get("travelers")
    if isinstance(travelers, list):
        profile: dict[str, Any] = {
            "adults": 0,
            "children": 0,
            "seniors": 0,
            "mobility_limitations": [],
        }
        for traveler in travelers:
            if not isinstance(traveler, dict):
                continue
            traveler_type = str(traveler.get("type", "")).lower()
            count = int(traveler.get("count", 0))
            if "senior" in traveler_type or "老人" in traveler_type:
                profile["seniors"] += count
            elif "child" in traveler_type or "儿童" in traveler_type:
                profile["children"] += count
            else:
                profile["adults"] += count
            limitation = traveler.get("note") or traveler.get("mobility_limitation")
            if limitation:
                profile["mobility_limitations"].append(str(limitation))
        trip["travelers"] = profile
    elif isinstance(travelers, dict):
        limitations = travelers.get("mobility_limitations")
        if isinstance(limitations, str):
            travelers["mobility_limitations"] = [limitations]
        elif limitations is None:
            travelers["mobility_limitations"] = []

    constraints = trip.get("constraints")
    if isinstance(constraints, dict):
        aliases = {
            "plan_b_increment_limit_cny": "max_plan_b_extra_cost_cny",
            "min_buffer_minutes": "minimum_connection_buffer_minutes",
            "max_transfer_per_segment": "max_transfers_per_leg",
        }
        for source, target in aliases.items():
            if source in constraints and target not in constraints:
                constraints[target] = constraints.pop(source)
        if constraints.get("max_daily_activities") is None:
            constraints["max_daily_activities"] = 3
        for name in ("preferences", "avoidances", "protected_event_ids"):
            if constraints.get(name) is None:
                constraints[name] = []

    city = "杭州" if "杭州" in str(trip.get("title", "")) else "未知"
    events = trip.get("events")
    if isinstance(events, list):
        previous_event_id: str | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            aliases = {
                "walk_minutes": "walking_minutes",
                "transit_time_minutes": "travel_minutes_from_previous",
                "plan_b_increment_cny": "proposed_extra_cost_cny",
            }
            for source, target in aliases.items():
                if source in event and target not in event:
                    event[target] = event.pop(source)
            for name in ("walking_minutes", "transfer_count"):
                if event.get(name) is None:
                    event[name] = 0
            if event.get("proposed_extra_cost_cny") is None:
                event["proposed_extra_cost_cny"] = "0"
            if event.get("depends_on") is None:
                event["depends_on"] = []
            if isinstance(event.get("depends_on"), str):
                event["depends_on"] = [event["depends_on"]]
            if (
                event.get("travel_minutes_from_previous") is not None
                and not event.get("transfer_from_event_id")
            ):
                reference = (
                    event["depends_on"][0]
                    if event.get("depends_on")
                    else previous_event_id
                )
                if reference:
                    event["transfer_from_event_id"] = reference
                    if not event.get("depends_on"):
                        event["depends_on"] = [reference]
            if (
                event.get("transfer_from_event_id")
                and event.get("travel_minutes_from_previous") is None
            ):
                event.pop("transfer_from_event_id", None)
            location = event.get("location")
            if isinstance(location, str):
                if event.get("event_type") == "transport" and "->" in location:
                    origin, destination = [part.strip() for part in location.split("->", 1)]
                    event["origin"] = {
                        "name": origin,
                        "city": "上海" if "上海" in origin else city,
                    }
                    event["destination"] = {"name": destination, "city": city}
                    event.pop("location", None)
                else:
                    event["location"] = {"name": location, "city": city}
            metadata = event.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            if "nights" in event:
                metadata["nights"] = event.pop("nights")
            if event.pop("is_protected", False):
                metadata["booking_status"] = "protected"
            event["metadata"] = metadata
            if isinstance(event.get("id"), str):
                previous_event_id = event["id"]
    return normalized


def _parse_json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        raise ValueError("视觉模型没有返回文本 JSON。")
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("视觉模型返回内容中没有 JSON 对象。") from error
        result = json.loads(text[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("视觉模型返回的根节点不是 JSON 对象。")
    return result


_EXTRACTION_PROMPT = """
你是 TripTwin 的行程单结构化解析器。只依据图片中明确可见的信息，输出一个 JSON 对象，禁止 Markdown、解释或代码围栏。

根节点必须且只能有：trip、field_confidence、low_confidence_fields、notes。
trip 必须满足：
1. trip_id、version、title、start、end、travelers、constraints、events、risks。
2. 时间使用带 +08:00 时区的 ISO 8601。
3. event_type 只能是 transport/accommodation/activity/meal/transfer。
4. 图片中显示“受保护”的事件 ID 放入 constraints.protected_event_ids。
5. 金额只写数字字符串；未知金额写 null，绝不猜测。
6. travelers 必须是对象，字段名为 adults、children、seniors、mobility_limitations。
7. constraints 字段必须使用 budget_cny、max_plan_b_extra_cost_cny、minimum_connection_buffer_minutes、max_daily_walk_minutes、max_daily_activities、max_transfers_per_leg、protected_event_ids、preferences、avoidances。
8. 每个地点必须是 {"name":"地点名","city":"城市名"}；交通使用 origin 和 destination，其他事件使用 location。
9. 每个事件保留图片中的 id、event_type、title、start、end、cost_cny、walking_minutes、transfer_count、depends_on、transfer_from_event_id、travel_minutes_from_previous、proposed_extra_cost_cny、confidence、metadata；没有显示的可选字段可省略。
10. risks 固定输出空数组，风险由本地规则引擎计算。

field_confidence 是“字段路径: 0到1数值”的对象，至少覆盖行程起止、预算及每个事件的 title/start/end/cost_cny。
low_confidence_fields 列出置信度低于 0.8 的字段路径；没有则输出空数组。
notes 只记录图片缺失或模糊信息；不要输出任何身份证、手机号、票号或密钥。
""".strip()
