"""Per-trip live Amap/FlyAI orchestration for the public application.

No cached competition artifact is read here.  Every returned fact is derived
from the current TripGraph and the current Managed Agent turn.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from triptwin.agent_prompt import build_replanning_prompt
from triptwin.bailian_client import AgentRun, BailianManagedAgentClient
from triptwin.candidate_validator import CandidateValidation, validate_candidate_artifact
from triptwin.config import Settings
from triptwin.live_context import AmapInspection, apply_amap_evidence, parse_amap_events
from triptwin.models import Trip, TripAnalysis, TripEvent
from triptwin.risk_engine import RiskEngine


class LiveTripResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: str
    session_id_masked: str
    trip: dict[str, Any]
    analysis: TripAnalysis
    inspection: AmapInspection
    candidate_artifact: dict[str, Any]
    candidate_validation: CandidateValidation
    run_status: str
    tool_call_count: int = Field(ge=0)
    error_count: int = Field(ge=0)


def run_live_trip(
    trip_payload: dict[str, Any], *, timeout_seconds: float = 150
) -> LiveTripResult:
    """Run a fresh, bounded tool turn for exactly one user TripGraph."""

    settings = Settings.from_env()
    trip = Trip.model_validate(trip_payload)
    initial = RiskEngine().analyze(trip)
    origin_name, destination_name = _inspection_leg(trip)
    dates = {
        (trip.start.date() + timedelta(days=offset)).isoformat()
        for offset in range((trip.end.date() - trip.start.date()).days + 1)
    }
    prompt = _live_prompt(
        trip,
        initial,
        origin_name=origin_name,
        destination_name=destination_name,
    )
    with BailianManagedAgentClient(settings) as client:
        session_id = client.create_session(
            title=f"TripTwin live {trip.trip_id}", trip_id=trip.trip_id
        )
        run = client.run_turn(session_id, prompt, timeout_seconds=timeout_seconds)
        artifact = _extract_artifact(run)
        if artifact is None:
            marked_file_id = _extract_marked_file_id(run.tool_outputs)
            artifact = (
                client.download_json_file(marked_file_id) if marked_file_id else None
            )
    if artifact is None:
        raise RuntimeError("实时智能体没有返回可验证的候选 JSON，未生成 Plan B。")
    artifact = _compact_artifact(artifact)
    artifact["flyai_commands"] = _verified_flyai_commands(run)
    artifact["fetched_at"] = datetime.now(UTC).isoformat()

    inspection = parse_amap_events(
        session_id,
        run.events,
        origin_name=origin_name,
        destination_name=destination_name,
        trip_dates=dates,
    )
    inspection_payload = inspection.model_dump(mode="json")
    inspection_payload["session_id"] = _mask_id(session_id)
    inspection = AmapInspection.model_validate(inspection_payload)
    if inspection.route is None:
        raise RuntimeError("高德 MCP 未返回可解析的公交路线，实时核验未通过。")
    if inspection.route.warning:
        raise RuntimeError(
            "高德终点只匹配到行政区级坐标，请在 TripGraph 中改成更精确的 POI 后重试。"
        )
    if inspection.weather is None:
        raise RuntimeError("高德 MCP 未返回可解析的天气结果，实时核验未通过。")
    enriched_payload = apply_amap_evidence(trip.model_dump(mode="json"), inspection)
    enriched_trip = Trip.model_validate(enriched_payload)
    analysis = RiskEngine().analyze(enriched_trip)
    validation = validate_candidate_artifact(
        enriched_trip, analysis, artifact, require_simulation=True
    )
    return LiveTripResult(
        generated_at=datetime.now(UTC).isoformat(),
        session_id_masked=_mask_id(session_id),
        trip=enriched_trip.model_dump(mode="json"),
        analysis=analysis,
        inspection=inspection,
        candidate_artifact=artifact,
        candidate_validation=validation,
        run_status=run.status,
        tool_call_count=len(run.tool_calls),
        error_count=len(run.errors),
    )


def _inspection_leg(trip: Trip) -> tuple[str, str]:
    by_id = {event.id: event for event in trip.events}
    candidates: list[tuple[int, str, str]] = []
    for event in sorted(trip.events, key=lambda item: item.start):
        if not event.transfer_from_event_id:
            continue
        previous = by_id.get(event.transfer_from_event_id)
        if previous is None:
            continue
        origin = _place_name(previous, prefer_destination=True)
        destination = _place_name(event)
        if origin and destination:
            available = int((event.start - previous.end).total_seconds() // 60)
            required = (event.travel_minutes_from_previous or 0) + (
                event.connection_buffer_minutes
                if event.connection_buffer_minutes is not None
                else trip.constraints.minimum_connection_buffer_minutes
            )
            candidates.append((available - required, origin, destination))
    if candidates:
        _, origin, destination = min(candidates, key=lambda item: item[0])
        return origin, destination
    ordered = sorted(trip.events, key=lambda item: item.start)
    if len(ordered) >= 2:
        origin = _place_name(ordered[0], prefer_destination=True)
        destination = _place_name(ordered[1])
        if origin and destination:
            return origin, destination
    raise ValueError("当前行程缺少两个可核验的地点，无法执行高德路线查询。")


def _place_name(event: TripEvent, *, prefer_destination: bool = False) -> str | None:
    values = (
        (event.destination, event.location, event.origin)
        if prefer_destination
        else (event.location, event.destination, event.origin)
    )
    return next((value.name for value in values if value is not None), None)


def _live_prompt(
    trip: Trip,
    analysis: TripAnalysis,
    *,
    origin_name: str,
    destination_name: str,
) -> str:
    cities = [
        location.city
        for event in trip.events
        for location in (event.location, event.destination, event.origin)
        if location is not None
    ]
    city = max(set(cities), key=cities.count) if cities else ""
    amap_instruction = (
        "先使用高德地图 MCP 真实执行："
        f"(1) maps_geo 查询 {origin_name}；(2) maps_geo 查询 {destination_name}；"
        "(3) 用精确坐标调用 maps_direction_transit_integrated；"
        f"(4) maps_weather 查询 {city}。不得估算或编造。"
    )
    return amap_instruction + "\n\n" + build_replanning_prompt(trip, analysis)


def _extract_artifact(run: AgentRun) -> dict[str, Any] | None:
    for event in reversed(run.tool_calls):
        for data in _event_data_blocks(event):
            if data.get("name") != "write":
                continue
            arguments = _json_object(data.get("arguments"))
            candidate = _json_object(arguments.get("content"))
            if candidate:
                return candidate
    text = run.final_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    candidate = _json_object(text)
    return candidate or None


def _extract_marked_file_id(outputs: list[dict[str, Any]]) -> str | None:
    for event in reversed(outputs):
        for data in _event_data_blocks(event):
            if data.get("name") != "mark_artifacts":
                continue
            marked = _json_object(data.get("output")).get("marked")
            if isinstance(marked, list):
                for item in marked:
                    if isinstance(item, dict) and isinstance(item.get("file_id"), str):
                        return item["file_id"]
    return None


def _verified_flyai_commands(run: AgentRun) -> list[dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for event in run.tool_outputs:
        for data in _event_data_blocks(event):
            call_id = data.get("call_id")
            if isinstance(call_id, str):
                outputs[call_id] = _json_object(data.get("output"))
    verified: list[dict[str, Any]] = []
    for event in run.tool_calls:
        for data in _event_data_blocks(event):
            if data.get("name") != "bash":
                continue
            command = _json_object(data.get("arguments")).get("command")
            if not isinstance(command, str) or not re.search(
                r"(?:^|&&\s*)flyai\s+(?:search-[\w-]+|keyword-search)\b", command
            ):
                continue
            output = outputs.get(str(data.get("call_id")), {})
            stdout = _json_object(output.get("stdout"))
            raw_stdout = output.get("stdout")
            result_status = stdout.get("status")
            if result_status is None and isinstance(raw_stdout, str) and "EXIT:0" in raw_stdout:
                result_status = 0
            verified.append(
                {
                    "command": command[:1000],
                    "exit_code": output.get("exit_code"),
                    "result_status": result_status,
                    "result_message": stdout.get("message"),
                }
            )
    return verified


def _event_data_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    content = event.get("content")
    if not isinstance(content, list):
        return []
    return [
        block["data"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("data"), dict)
    ]


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_artifact(value: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields required for validation/display before persistence."""

    raw_notes = value.get("notes")
    notes = raw_notes if isinstance(raw_notes, list) else []
    result: dict[str, Any] = {
        "status": str(value.get("status") or "completed")[:40],
        "candidates": {},
        "additive_candidates": {},
        "notes": [str(note)[:300] for note in notes[:10]],
    }
    for container_name in ("candidates", "additive_candidates"):
        container = value.get(container_name)
        if not isinstance(container, dict):
            continue
        compact_container: dict[str, Any] = {}
        for key, group in list(container.items())[:30]:
            if not isinstance(key, str) or not isinstance(group, dict):
                continue
            options: list[dict[str, Any]] = []
            raw_options = group.get("options")
            option_items = raw_options if isinstance(raw_options, list) else []
            for option in option_items[:10]:
                if not isinstance(option, dict):
                    continue
                options.append(
                    {
                        field: option[field]
                        for field in (
                            "name",
                            "jumpUrl",
                            "extra_cost_cny",
                            "source",
                            "event_patch",
                            "new_event",
                        )
                        if field in option
                    }
                )
            compact_container[key[:128]] = {
                "risk_ids": [
                    str(item)[:200]
                    for item in (
                        group.get("risk_ids")
                        if isinstance(group.get("risk_ids"), list)
                        else []
                    )[:30]
                ],
                "options": options,
            }
        result[container_name] = compact_container
    return result


def _mask_id(value: str) -> str:
    return value[:8] + "…" + value[-4:] if len(value) > 12 else value[:3] + "***"
