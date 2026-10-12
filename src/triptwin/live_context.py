"""Parse and apply verified Amap MCP evidence to a TripGraph.

The parser only accepts facts found in ``mcp_call_output`` events.  Missing or
out-of-range weather data remains explicitly unverified; no LLM estimate is
used as a fallback.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class RouteEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_tool: str = "maps_direction_transit_integrated"
    fetched_at: AwareDatetime
    origin_name: str
    destination_name: str
    origin_coordinates: str
    destination_coordinates: str
    destination_precision: str
    distance_meters: int = Field(ge=0)
    duration_seconds: int = Field(ge=0)
    duration_minutes: float = Field(ge=0)
    walking_distance_meters: int = Field(ge=0)
    transfer_count: int = Field(ge=0)
    status: VerificationStatus
    warning: str | None = None


class WeatherForecast(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str
    dayweather: str
    nightweather: str
    daytemp: str
    nighttemp: str
    daywind: str = ""
    nightwind: str = ""
    daypower: str = ""
    nightpower: str = ""


class WeatherEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_tool: str = "maps_weather"
    fetched_at: AwareDatetime
    city: str
    forecasts: list[WeatherForecast]
    trip_dates_covered: bool
    status: VerificationStatus
    warning: str | None = None


class AmapInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    captured_at: AwareDatetime
    run_status: str
    event_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    tool_output_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    tool_names: list[str]
    route: RouteEvidence | None
    weather: WeatherEvidence | None


def parse_amap_events(
    session_id: str,
    events: list[dict[str, Any]],
    *,
    origin_name: str,
    destination_name: str,
    trip_dates: set[str],
) -> AmapInspection:
    """Build a compact, typed inspection from Managed Agent events."""

    calls: dict[str, dict[str, Any]] = {}
    outputs: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    errors = 0
    status = "unknown"
    timestamps: list[datetime] = []

    for event in events:
        created = _parse_datetime(event.get("created_at"))
        if created:
            timestamps.append(created)
        event_type = str(event.get("type") or "")
        if event_type == "mcp_call":
            data = _first_data(event)
            call_id = str(data.get("call_id") or "")
            if call_id:
                calls[call_id] = dict(data)
        elif event_type == "mcp_call_output":
            data = _first_data(event)
            outputs.append((event, data))
            if event.get("is_error") is True:
                errors += 1
        elif event_type == "error":
            errors += 1
        elif event_type == "session_status":
            data = _first_data(event)
            reason = data.get("stop_reason")
            if isinstance(reason, Mapping) and reason.get("type"):
                status = str(reason["type"])
            elif data.get("session_status"):
                status = str(data["session_status"])

    geo_by_call: dict[str, dict[str, Any]] = {}
    route_payload: dict[str, Any] | None = None
    route_event: dict[str, Any] | None = None
    weather_payload: dict[str, Any] | None = None
    weather_event: dict[str, Any] | None = None
    tool_names: list[str] = []

    for event, data in outputs:
        name = str(data.get("name") or "")
        if name:
            tool_names.append(name)
        payload = _decode_mcp_output(data.get("output"))
        if not payload:
            continue
        if name == "maps_geo":
            results = payload.get("results")
            if isinstance(results, list) and results and isinstance(results[0], dict):
                geo_by_call[str(data.get("call_id") or "")] = results[0]
        elif name == "maps_direction_transit_integrated":
            route_payload, route_event = payload, event
        elif name == "maps_weather":
            weather_payload, weather_event = payload, event

    geo_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for call_id, geo in geo_by_call.items():
        call = calls.get(call_id, {})
        geo_items.append((call, geo))
    origin_geo = _match_geo(geo_items, origin_name, index=0)
    destination_geo = _match_geo(geo_items, destination_name, index=1)

    route = _route_evidence(
        route_payload,
        route_event,
        origin_geo,
        destination_geo,
        origin_name,
        destination_name,
    )
    weather = _weather_evidence(weather_payload, weather_event, trip_dates)
    captured_at = max(timestamps) if timestamps else datetime.now(UTC)

    return AmapInspection(
        session_id=session_id,
        captured_at=captured_at,
        run_status=status,
        event_count=len(events),
        tool_call_count=sum(event.get("type") == "mcp_call" for event in events),
        tool_output_count=sum(
            event.get("type") == "mcp_call_output" for event in events
        ),
        error_count=errors,
        tool_names=list(dict.fromkeys(tool_names)),
        route=route,
        weather=weather,
    )


def apply_amap_evidence(
    trip_payload: dict[str, Any], inspection: AmapInspection
) -> dict[str, Any]:
    """Attach verified facts to matching TripGraph events."""

    result = copy.deepcopy(trip_payload)
    events = result.get("events")
    if not isinstance(events, list):
        return result

    route = inspection.route
    weather = inspection.weather
    for event in events:
        if not isinstance(event, dict):
            continue
        metadata = event.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            event["metadata"] = metadata

        location = event.get("location")
        location_name = (
            str(location.get("name") or "") if isinstance(location, dict) else ""
        )
        if (
            route
            and route.status is VerificationStatus.VERIFIED
            and route.destination_name in location_name
            and event.get("transfer_from_event_id")
        ):
            event["travel_minutes_from_previous"] = math.ceil(
                route.duration_seconds / 60
            )
            metadata["amap_route_evidence"] = route.model_dump(mode="json")

        if event.get("weather_sensitive") and weather:
            event_date = str(event.get("start") or "")[:10]
            forecast = next(
                (item for item in weather.forecasts if item.date == event_date), None
            )
            metadata["amap_weather_evidence"] = {
                "source_tool": weather.source_tool,
                "fetched_at": weather.fetched_at.isoformat(),
                "event_date": event_date,
                "status": "verified" if forecast else "unverified",
                "forecast": forecast.model_dump(mode="json") if forecast else None,
                "warning": None
                if forecast
                else "高德返回的预报日期未覆盖该活动日期，禁止估算天气。",
            }
    return result


def _route_evidence(
    payload: dict[str, Any] | None,
    event: dict[str, Any] | None,
    origin_geo: dict[str, Any] | None,
    destination_geo: dict[str, Any] | None,
    origin_name: str,
    destination_name: str,
) -> RouteEvidence | None:
    if not payload or not event:
        return None
    transits = payload.get("transits")
    valid = [item for item in transits or [] if isinstance(item, dict)]
    if not valid:
        return None
    fastest = min(valid, key=lambda item: _to_int(item.get("duration"), 10**12))
    duration = _to_int(fastest.get("duration"), 0)
    bus_legs = 0
    for segment in fastest.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        bus = segment.get("bus")
        lines = bus.get("buslines") if isinstance(bus, dict) else None
        if isinstance(lines, list) and lines:
            bus_legs += 1
    precision = str((destination_geo or {}).get("level") or "未知")
    warning = None
    if precision in {"区县", "市", "省"}:
        warning = "终点仅匹配到行政区级坐标，路线可作风险参考，但需再次确认精确 POI。"
    return RouteEvidence(
        fetched_at=_parse_datetime(event.get("created_at")) or datetime.now(UTC),
        origin_name=origin_name,
        destination_name=destination_name,
        origin_coordinates=str(
            payload.get("origin") or (origin_geo or {}).get("location") or ""
        ),
        destination_coordinates=str(
            payload.get("destination")
            or (destination_geo or {}).get("location")
            or ""
        ),
        destination_precision=precision,
        distance_meters=_to_int(payload.get("distance"), 0),
        duration_seconds=duration,
        duration_minutes=round(duration / 60, 1),
        walking_distance_meters=_to_int(fastest.get("walking_distance"), 0),
        transfer_count=max(bus_legs - 1, 0),
        status=VerificationStatus.VERIFIED,
        warning=warning,
    )


def _weather_evidence(
    payload: dict[str, Any] | None,
    event: dict[str, Any] | None,
    trip_dates: set[str],
) -> WeatherEvidence | None:
    if not payload or not event:
        return None
    forecasts = [
        WeatherForecast.model_validate(item)
        for item in payload.get("forecasts") or []
        if isinstance(item, dict)
    ]
    returned_dates = {item.date for item in forecasts}
    covered = bool(trip_dates) and trip_dates.issubset(returned_dates)
    warning = None
    if not covered:
        warning = "天气预报未覆盖完整行程日期，未覆盖日期保持未核验。"
    return WeatherEvidence(
        fetched_at=_parse_datetime(event.get("created_at")) or datetime.now(UTC),
        city=str(payload.get("city") or ""),
        forecasts=forecasts,
        trip_dates_covered=covered,
        status=(
            VerificationStatus.VERIFIED if forecasts else VerificationStatus.UNVERIFIED
        ),
        warning=warning,
    )


def _decode_mcp_output(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        envelope = json.loads(value)
    except json.JSONDecodeError:
        return None
    content = envelope.get("content") if isinstance(envelope, dict) else None
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    return None


def _first_data(event: Mapping[str, Any]) -> Mapping[str, Any]:
    content = event.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and isinstance(block.get("data"), Mapping):
                return block["data"]
    return {}


def _match_geo(
    items: list[tuple[dict[str, Any], dict[str, Any]]],
    name: str,
    *,
    index: int,
) -> dict[str, Any] | None:
    for call, geo in items:
        try:
            arguments = json.loads(str(call.get("arguments") or "{}"))
        except json.JSONDecodeError:
            arguments = {}
        if arguments.get("address") == name:
            return geo
    return items[index][1] if len(items) > index else None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
