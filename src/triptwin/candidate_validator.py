"""Validate FlyAI candidate evidence before it can become a final Plan B."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from triptwin.models import Trip, TripAnalysis
from triptwin.risk_engine import RiskEngine


class CandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    name: str
    source_url: str
    extra_cost_cny: Decimal = Field(ge=0)
    covered_risk_ids: list[str]
    proposed_event: dict[str, Any] | None = None


class CandidateValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    flyai_evidence_valid: bool
    protected_event_ids_untouched: bool
    selections: list[CandidateSelection]
    total_extra_cost_cny: Decimal = Field(ge=0)
    unresolved_risk_ids: list[str]
    rejection_reasons: list[str]


def validate_candidate_artifact(
    trip: Trip,
    analysis: TripAnalysis,
    artifact: dict[str, Any],
    *,
    require_simulation: bool = False,
) -> CandidateValidation:
    """Validate source, budget, protected nodes and risk coverage.

    This is intentionally conservative.  Candidate data can only become a
    final Plan B when every deterministic risk has at least one acceptable
    candidate or an explicit additive repair.
    """

    rejections: list[str] = []
    commands = artifact.get("flyai_commands")
    evidence_valid = bool(commands) and all(
        isinstance(command, dict)
        and command.get("exit_code") == 0
        and command.get("result_status") == 0
        for command in (commands or [])
    )
    if not evidence_valid:
        rejections.append("FlyAI 命令证据缺失，或至少一条命令未成功。")

    candidates = artifact.get("candidates")
    if not isinstance(candidates, dict):
        candidates = {}
        rejections.append("候选产物缺少 candidates 对象。")

    known_event_ids = {event.id for event in trip.events}
    expected_risks = {risk.id for risk in analysis.risks}
    protected = trip.constraints.protected_event_ids
    touched_protected = sorted(protected.intersection(candidates))
    protected_untouched = not touched_protected
    if touched_protected:
        rejections.append(
            "候选试图替换受保护节点：" + ", ".join(touched_protected)
        )

    selections: list[CandidateSelection] = []
    covered_risks: set[str] = set()
    for event_id, group in candidates.items():
        if event_id not in known_event_ids:
            rejections.append(f"候选引用了当前行程不存在的节点：{event_id}。")
            continue
        if event_id in protected or not isinstance(group, dict):
            continue
        risk_ids = [
            str(risk_id)
            for risk_id in group.get("risk_ids", [])
            if isinstance(risk_id, str)
        ]
        unknown_risks = sorted(set(risk_ids) - expected_risks)
        if unknown_risks:
            rejections.append(
                f"节点 {event_id} 声称覆盖当前分析不存在的风险："
                + ", ".join(unknown_risks)
            )
            continue
        options = group.get("options")
        if not isinstance(options, list):
            continue
        accepted = next(
            (
                selection
                for option in options
                if (
                    selection := _validate_option(
                        event_id,
                        risk_ids,
                        option,
                        trip.constraints.max_plan_b_extra_cost_cny,
                        require_simulation=require_simulation,
                        additive=False,
                    )
                )
                is not None
            ),
            None,
        )
        if accepted is None:
            rejections.append(f"节点 {event_id} 没有来源和预算均合格的候选。")
            continue
        selections.append(accepted)
        covered_risks.update(risk_ids)

    additive = artifact.get("additive_candidates")
    if isinstance(additive, dict):
        for repair_id, group in additive.items():
            if not isinstance(group, dict):
                continue
            risk_ids = [
                str(risk_id)
                for risk_id in group.get("risk_ids", [repair_id])
                if isinstance(risk_id, str)
            ]
            unknown_risks = sorted(set(risk_ids) - expected_risks)
            if unknown_risks:
                rejections.append(
                    f"增量修复 {repair_id} 引用了当前分析不存在的风险："
                    + ", ".join(unknown_risks)
                )
                continue
            options = group.get("options")
            if not isinstance(options, list):
                continue
            accepted = next(
                (
                    selection
                    for option in options
                    if (
                        selection := _validate_option(
                            f"additive:{repair_id}",
                            risk_ids,
                            option,
                            trip.constraints.max_plan_b_extra_cost_cny,
                            require_simulation=require_simulation,
                            additive=True,
                        )
                    )
                    is not None
                ),
                None,
            )
            if accepted is None:
                rejections.append(f"增量修复 {repair_id} 没有来源和预算均合格的候选。")
                continue
            selections.append(accepted)
            covered_risks.update(risk_ids)

    unresolved = sorted(expected_risks - covered_risks)
    if unresolved:
        rejections.append("仍有确定性风险未覆盖：" + ", ".join(unresolved))

    event_by_id = {event.id: event for event in trip.events}
    total_extra = Decimal("0")
    for selection in selections:
        effective_extra = selection.extra_cost_cny
        proposed = selection.proposed_event or {}
        proposed_extra = _decimal_or_zero(proposed.get("proposed_extra_cost_cny"))
        if selection.event_id.startswith("additive:"):
            effective_extra = max(
                effective_extra,
                proposed_extra,
                _decimal_or_zero(proposed.get("cost_cny")),
            )
        else:
            original = event_by_id.get(selection.event_id)
            old_cost = original.cost_cny if original and original.cost_cny is not None else Decimal("0")
            new_cost = (
                _decimal_or_zero(proposed.get("cost_cny"))
                if "cost_cny" in proposed
                else old_cost
            )
            effective_extra = max(
                effective_extra, proposed_extra, max(new_cost - old_cost, Decimal("0"))
            )
        if effective_extra > selection.extra_cost_cny:
            rejections.append(
                f"候选 {selection.name} 声明的增量成本低于 TripGraph 回放值 "
                f"¥{effective_extra}。"
            )
        total_extra += effective_extra
    if total_extra > trip.constraints.max_plan_b_extra_cost_cny:
        rejections.append(
            "入选候选的增量成本合计 "
            f"¥{total_extra} 超过 Plan B 上限 "
            f"¥{trip.constraints.max_plan_b_extra_cost_cny}。"
        )

    if require_simulation and selections:
        try:
            simulated_payload = trip.model_dump(mode="json")
            events = simulated_payload["events"]
            for selection in selections:
                proposed = selection.proposed_event
                if proposed is None:
                    continue
                if selection.event_id.startswith("additive:"):
                    events.append(proposed)
                    continue
                index = next(
                    i for i, event in enumerate(events) if event["id"] == selection.event_id
                )
                merged = {**events[index], **proposed, "id": selection.event_id}
                events[index] = merged
            simulated_trip = Trip.model_validate(simulated_payload)
            simulated_analysis = RiskEngine().analyze(simulated_trip)
            simulated_ids = {risk.id for risk in simulated_analysis.risks}
            remaining_after_simulation = sorted(expected_risks & simulated_ids)
            new_risks = sorted(simulated_ids - expected_risks)
            if remaining_after_simulation:
                unresolved = sorted(set(unresolved) | set(remaining_after_simulation))
                rejections.append(
                    "候选回放后原风险仍存在：" + ", ".join(remaining_after_simulation)
                )
            if new_risks:
                rejections.append("候选回放产生了新风险：" + ", ".join(new_risks))
        except (ValueError, StopIteration) as exc:
            rejections.append(f"候选无法回放为有效 TripGraph：{exc}")

    return CandidateValidation(
        valid=evidence_valid
        and protected_untouched
        and bool(selections)
        and not unresolved
        and not rejections,
        flyai_evidence_valid=evidence_valid,
        protected_event_ids_untouched=protected_untouched,
        selections=selections,
        total_extra_cost_cny=total_extra,
        unresolved_risk_ids=unresolved,
        rejection_reasons=rejections,
    )


def _validate_option(
    event_id: str,
    risk_ids: list[str],
    option: Any,
    max_extra_cost: Decimal,
    *,
    require_simulation: bool,
    additive: bool,
) -> CandidateSelection | None:
    if not isinstance(option, dict):
        return None
    name = option.get("name")
    source_url = option.get("jumpUrl")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(source_url, str) or len(source_url) > 2048:
        return None
    parsed_url = urlparse(source_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "router.feizhu.com"
        or any(character in source_url for character in "\r\n[]()<> ")
    ):
        return None
    try:
        extra_cost = Decimal(str(option.get("extra_cost_cny", 0)))
    except (InvalidOperation, ValueError):
        return None
    if extra_cost < 0 or extra_cost > max_extra_cost:
        return None
    if require_simulation and option.get("source") != "flyai":
        return None
    proposed_event = option.get("new_event" if additive else "event_patch")
    if proposed_event is not None and not isinstance(proposed_event, dict):
        return None
    if require_simulation and not isinstance(proposed_event, dict):
        return None
    return CandidateSelection(
        event_id=event_id,
        name=name,
        source_url=source_url,
        extra_cost_cny=extra_cost,
        covered_risk_ids=risk_ids,
        proposed_event=proposed_event,
    )


def _decimal_or_zero(value: Any) -> Decimal:
    try:
        return Decimal(str(value)) if value is not None else Decimal("0")
    except (InvalidOperation, ValueError):
        return Decimal("0")

