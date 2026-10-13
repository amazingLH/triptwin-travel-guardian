"""Run one real, bounded Managed Agent turn and save a sanitized trace."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from triptwin.agent_prompt import build_missing_hotel_prompt, build_replanning_prompt
from triptwin.bailian_client import BailianManagedAgentClient
from triptwin.candidate_validator import validate_candidate_artifact
from triptwin.config import Settings
from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine


ROOT = Path(__file__).resolve().parents[1]
TRIP_PATH = ROOT / "examples" / "hangzhou_golden_trip.json"
OUTPUT_PATH = ROOT / "docs" / "evidence" / "stage4-api" / "smoke-trace.json"
CANDIDATES_PATH = ROOT / "docs" / "evidence" / "stage4-api" / "candidates.json"
VALIDATION_PATH = (
    ROOT / "docs" / "evidence" / "stage4-api" / "candidate-validation.json"
)
LAST_SESSION_PATH = ROOT / ".stage4-last-session"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Ignore the saved session and submit a new cloud turn.",
    )
    args = parser.parse_args()
    settings = Settings.from_env(ROOT / ".env")
    trip = Trip.model_validate_json(TRIP_PATH.read_text(encoding="utf-8"))
    analysis = RiskEngine().analyze(trip)
    prior_candidates = _load_prior_candidates()
    prior_validation = (
        validate_candidate_artifact(trip, analysis, prior_candidates)
        if prior_candidates
        else None
    )
    missing_hotel_risk = "date_consistency:missing_accommodation_nights"
    incremental_repair = bool(
        args.new_session
        and prior_validation
        and prior_validation.unresolved_risk_ids == [missing_hotel_risk]
    )
    prompt = (
        build_missing_hotel_prompt(trip, missing_hotel_risk)
        if incremental_repair
        else build_replanning_prompt(trip, analysis)
    )

    print("[1/3] 本地 TripGraph 分析完成；未输出任何密钥。")
    with BailianManagedAgentClient(settings) as client:
        session_id = None if args.new_session else _recover_latest_session(
            client, trip.trip_id
        )
        if session_id:
            print(f"[2/3] 继续读取已有百炼会话：{_mask_id(session_id)}")
            run = client.wait_for_completion(session_id, timeout_seconds=120)
        else:
            session_id = client.create_session(
                title=f"途证哨 Stage 4 smoke {trip.trip_id}", trip_id=trip.trip_id
            )
            LAST_SESSION_PATH.write_text(session_id, encoding="utf-8")
            print(f"[2/3] 百炼会话已创建：{_mask_id(session_id)}")
            if incremental_repair:
                print("      本轮仅补查第二晚酒店，不重复查询已有景点。")
            run = client.run_turn(session_id, prompt, timeout_seconds=120)
        evidence = {
            "generated_at": datetime.now(UTC).isoformat(),
            "trip_id": trip.trip_id,
            "local_risk_count": analysis.risk_count,
            "local_total_risk_score": analysis.total_risk_score,
            "session_id": _mask_id(run.session_id),
            "status": run.status,
            "event_count": run.event_count,
            "request_id_count": len(run.request_ids),
            "tool_call_count": len(run.tool_calls),
            "tool_output_count": len(run.tool_outputs),
            "error_count": len(run.errors),
            "final_text": run.final_text,
            "tool_calls": [_compact_event(event) for event in run.tool_calls],
            "tool_outputs": [_compact_event(event) for event in run.tool_outputs],
            "errors": [_compact_event(event) for event in run.errors],
        }
        candidates = _extract_candidate_artifact(run.tool_calls)
        if candidates is None:
            candidates = _extract_json_message(run.final_text)
        if candidates is None:
            marked_file_id = _extract_marked_file_id(run.tool_outputs)
            if marked_file_id:
                candidates = client.download_json_file(marked_file_id)
        if candidates is not None:
            verified_commands = _verified_flyai_commands(
                run.tool_calls, run.tool_outputs
            )
            if verified_commands:
                candidates["flyai_commands"] = verified_commands
        is_repair_artifact = bool(
            candidates
            and candidates.get("additive_candidates")
            and not candidates.get("candidates")
        )
        if (
            candidates is not None
            and prior_candidates
            and (incremental_repair or is_repair_artifact)
        ):
            candidates = _merge_candidate_artifacts(prior_candidates, candidates)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if candidates is not None:
        CANDIDATES_PATH.write_text(
            json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        validation = validate_candidate_artifact(trip, analysis, candidates)
        VALIDATION_PATH.write_text(
            validation.model_dump_json(indent=2), encoding="utf-8"
        )
        if not validation.valid:
            print(
                "本地复核：候选尚不能成为最终 Plan B；未覆盖风险="
                + ", ".join(validation.unresolved_risk_ids)
            )
    print(f"[3/3] 脱敏联调证据已保存：{OUTPUT_PATH.relative_to(ROOT)}")
    print(
        "结果摘要："
        f"status={evidence['status']}, tool_calls={evidence['tool_call_count']}, "
        f"errors={evidence['error_count']}"
    )
    if (
        not evidence["tool_call_count"]
        or candidates is None
        or not validation.valid
    ):
        return 2
    return 0


def _recover_latest_session(
    client: BailianManagedAgentClient, trip_id: str
) -> str | None:
    if LAST_SESSION_PATH.is_file():
        session_id = LAST_SESSION_PATH.read_text(encoding="utf-8").strip()
        if session_id:
            return session_id
    expected_title = f"途证哨 Stage 4 smoke {trip_id}"
    for session in client.list_sessions():
        if session.get("title") == expected_title and isinstance(session.get("id"), str):
            session_id = str(session["id"])
            LAST_SESSION_PATH.write_text(session_id, encoding="utf-8")
            return session_id
    return None


def _load_prior_candidates() -> dict[str, object] | None:
    if not CANDIDATES_PATH.is_file():
        return None
    try:
        value = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _extract_json_message(text: str) -> dict[str, object] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```").strip()
    return _parse_json_object(stripped) or None


def _extract_marked_file_id(
    tool_outputs: list[dict[str, object]],
) -> str | None:
    for event in reversed(tool_outputs):
        content = event.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get("data"), dict):
                continue
            data = block["data"]
            if data.get("name") != "mark_artifacts":
                continue
            output = _parse_json_object(data.get("output"))
            marked = output.get("marked")
            if not isinstance(marked, list):
                continue
            for item in marked:
                if isinstance(item, dict) and isinstance(item.get("file_id"), str):
                    return str(item["file_id"])
    return None


def _verified_flyai_commands(
    tool_calls: list[dict[str, object]],
    tool_outputs: list[dict[str, object]],
) -> list[dict[str, object]]:
    outputs_by_call_id: dict[str, dict[str, object]] = {}
    for event in tool_outputs:
        for data in _event_data_blocks(event):
            call_id = data.get("call_id")
            output = _parse_json_object(data.get("output"))
            if isinstance(call_id, str) and output:
                outputs_by_call_id[call_id] = output

    verified: list[dict[str, object]] = []
    for event in tool_calls:
        for data in _event_data_blocks(event):
            if data.get("name") != "bash":
                continue
            arguments = _parse_json_object(data.get("arguments"))
            command = arguments.get("command")
            if not isinstance(command, str) or not re.search(
                r"(?:^|&&\s*)flyai\s+(?:search-[\w-]+|keyword-search)\b",
                command,
            ):
                continue
            call_id = data.get("call_id")
            output = outputs_by_call_id.get(str(call_id), {})
            stdout = _parse_json_object(output.get("stdout"))
            raw_stdout = output.get("stdout")
            result_status = stdout.get("status")
            if result_status is None and isinstance(raw_stdout, str):
                if "EXIT:0" in raw_stdout:
                    result_status = 0
            verified.append(
                {
                    "command": command,
                    "exit_code": output.get("exit_code"),
                    "result_status": result_status,
                    "result_message": stdout.get("message"),
                }
            )
    return verified


def _event_data_blocks(event: dict[str, object]) -> list[dict[str, object]]:
    content = event.get("content")
    if not isinstance(content, list):
        return []
    return [
        block["data"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("data"), dict)
    ]


def _merge_candidate_artifacts(
    original: dict[str, object], repair: dict[str, object]
) -> dict[str, object]:
    merged = dict(original)
    merged["status"] = repair.get("status", original.get("status", "completed"))
    successful_commands: list[dict[str, object]] = []
    seen_commands: set[str] = set()
    for command in [
        *(original.get("flyai_commands") or []),
        *(repair.get("flyai_commands") or []),
    ]:
        if (
            not isinstance(command, dict)
            or command.get("exit_code") != 0
            or command.get("result_status") != 0
        ):
            continue
        command_text = command.get("command")
        if not isinstance(command_text, str) or command_text in seen_commands:
            continue
        seen_commands.add(command_text)
        successful_commands.append(command)
    merged["flyai_commands"] = successful_commands
    merged["candidates"] = {
        **(original.get("candidates") or {}),
        **(repair.get("candidates") or {}),
    }
    merged["additive_candidates"] = {
        **(original.get("additive_candidates") or {}),
        **(repair.get("additive_candidates") or {}),
    }
    merged["notes"] = [
        *(original.get("notes") or []),
        *(repair.get("notes") or []),
    ]
    return merged


def _mask_id(value: str) -> str:
    if len(value) <= 10:
        return value[:3] + "***"
    return value[:8] + "…" + value[-4:]


def _compact_event(event: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {
        key: event[key]
        for key in ("type", "event_type", "role", "is_error", "error")
        if key in event
    }
    content = event.get("content")
    if not isinstance(content, list):
        return compact
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("data"), dict):
            continue
        data = block["data"]
        name = data.get("name")
        if name:
            compact["name"] = name
        arguments = _parse_json_object(data.get("arguments"))
        if arguments:
            if name == "bash":
                compact["command"] = arguments.get("command")
            elif name in {"activate_skill", "read_skill_file"}:
                compact["arguments"] = arguments
            elif name in {"write", "mark_artifacts"}:
                compact["artifact_action"] = name
        output = _parse_json_object(data.get("output"))
        if output:
            compact["exit_code"] = output.get("exit_code")
            compact["interrupted"] = output.get("interrupted")
            stderr = output.get("stderr")
            if stderr:
                compact["stderr"] = str(stderr)[:300]
            stdout = _parse_json_object(output.get("stdout"))
            if stdout:
                compact["result_status"] = stdout.get("status")
                compact["result_message"] = stdout.get("message")
    return compact


def _extract_candidate_artifact(
    tool_calls: list[dict[str, object]],
) -> dict[str, object] | None:
    for event in reversed(tool_calls):
        content = event.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get("data"), dict):
                continue
            data = block["data"]
            if data.get("name") != "write":
                continue
            arguments = _parse_json_object(data.get("arguments"))
            candidate = _parse_json_object(arguments.get("content"))
            if candidate and candidate.get("status") == "completed":
                return candidate
    return None


def _parse_json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())

