"""Validate FlyAI candidate evidence before it can become a final Plan B."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from triptwin.models import Trip, TripAnalysis


class CandidateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    name: str
    source_url: str
    extra_cost_cny: Decimal = Field(ge=0)
    covered_risk_ids: list[str]


class CandidateValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    flyai_evidence_valid: bool
    protected_event_ids_untouched: bool
    selections: list[CandidateSelection]
    unresolved_risk_ids: list[str]
    rejection_reasons: list[str]


def validate_candidate_artifact(
    trip: Trip, analysis: TripAnalysis, artifact: dict[str, Any]
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
        if event_id in protected or not isinstance(group, dict):
            continue
        risk_ids = [
            str(risk_id)
            for risk_id in group.get("risk_ids", [])
            if isinstance(risk_id, str)
        ]
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

    expected_risks = {risk.id for risk in analysis.risks}
    unresolved = sorted(expected_risks - covered_risks)
    if unresolved:
        rejections.append("仍有确定性风险未覆盖：" + ", ".join(unresolved))

    return CandidateValidation(
        valid=evidence_valid
        and protected_untouched
        and bool(selections)
        and not unresolved,
        flyai_evidence_valid=evidence_valid,
        protected_event_ids_untouched=protected_untouched,
        selections=selections,
        unresolved_risk_ids=unresolved,
        rejection_reasons=rejections,
    )


def _validate_option(
    event_id: str,
    risk_ids: list[str],
    option: Any,
    max_extra_cost: Decimal,
) -> CandidateSelection | None:
    if not isinstance(option, dict):
        return None
    name = option.get("name")
    source_url = option.get("jumpUrl")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(source_url, str) or not source_url.startswith(
        "https://router.feizhu.com/"
    ):
        return None
    try:
        extra_cost = Decimal(str(option.get("extra_cost_cny", 0)))
    except (InvalidOperation, ValueError):
        return None
    if extra_cost < 0 or extra_cost > max_extra_cost:
        return None
    return CandidateSelection(
        event_id=event_id,
        name=name,
        source_url=source_url,
        extra_cost_cny=extra_cost,
        covered_risk_ids=risk_ids,
    )

