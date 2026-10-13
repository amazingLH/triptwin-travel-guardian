import json
from pathlib import Path

from triptwin.candidate_validator import validate_candidate_artifact
from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine


def _trip_and_analysis() -> tuple[Trip, object]:
    trip = Trip.model_validate_json(
        Path("examples/hangzhou_golden_trip.json").read_text(encoding="utf-8")
    )
    return trip, RiskEngine().analyze(trip)


def test_real_stage4_artifact_is_not_final_while_hotel_risk_unresolved() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = json.loads(
        Path("docs/evidence/stage4-api/candidates.json").read_text(encoding="utf-8")
    )
    artifact.pop("additive_candidates", None)

    validation = validate_candidate_artifact(trip, analysis, artifact)

    assert validation.flyai_evidence_valid
    assert validation.protected_event_ids_untouched
    assert len(validation.selections) == 3
    assert not validation.valid
    assert "date_consistency:missing_accommodation_nights" in (
        validation.unresolved_risk_ids
    )


def test_rejects_attempt_to_replace_protected_event() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = {
        "flyai_commands": [
            {"exit_code": 0, "result_status": 0, "items_returned": 1}
        ],
        "candidates": {"train-sh-hz": {"risk_ids": [], "options": []}},
    }

    validation = validate_candidate_artifact(trip, analysis, artifact)

    assert not validation.protected_event_ids_untouched
    assert not validation.valid


def test_rejects_lookalike_or_markdown_breaking_candidate_urls() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = json.loads(
        Path("docs/evidence/stage4-api/candidates.json").read_text(encoding="utf-8")
    )
    first_group = next(iter(artifact["candidates"].values()))
    first_group["options"] = [
        {
            "name": "恶意候选",
            "jumpUrl": "https://router.feizhu.com.evil.example/x)",
            "extra_cost_cny": 0,
        }
    ]

    validation = validate_candidate_artifact(trip, analysis, artifact)

    assert not validation.valid


def test_additive_hotel_candidate_covers_missing_night() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = json.loads(
        Path("docs/evidence/stage4-api/candidates.json").read_text(encoding="utf-8")
    )
    artifact["additive_candidates"] = {
        "date_consistency:missing_accommodation_nights": {
            "risk_ids": ["date_consistency:missing_accommodation_nights"],
            "options": [
                {
                    "name": "真实候选酒店",
                    "jumpUrl": "https://router.feizhu.com/example",
                    "extra_cost_cny": 100,
                }
            ],
        }
    }

    validation = validate_candidate_artifact(trip, analysis, artifact)

    assert validation.valid
    assert validation.unresolved_risk_ids == []


def test_replay_cost_cannot_be_understated() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = json.loads(
        Path("docs/evidence/stage4-api/candidates.json").read_text(encoding="utf-8")
    )
    repair = artifact["additive_candidates"][
        "date_consistency:missing_accommodation_nights"
    ]["options"][0]
    repair["extra_cost_cny"] = 1
    repair["new_event"] = {
        "id": "second-hotel",
        "event_type": "accommodation",
        "title": "第二晚酒店",
        "start": "2026-10-19T15:00:00+08:00",
        "end": "2026-10-20T11:00:00+08:00",
        "location": {"name": "候选酒店", "city": "杭州"},
        "cost_cny": 600,
    }

    validation = validate_candidate_artifact(trip, analysis, artifact)

    assert not validation.valid
    assert validation.total_extra_cost_cny > trip.constraints.max_plan_b_extra_cost_cny
    assert any("低于 TripGraph 回放值" in reason for reason in validation.rejection_reasons)


def test_rejects_candidates_for_another_trip() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = json.loads(
        Path("docs/evidence/stage4-api/candidates.json").read_text(encoding="utf-8")
    )
    artifact["candidates"]["beijing-foreign-event"] = artifact["candidates"].pop(
        next(iter(artifact["candidates"]))
    )

    validation = validate_candidate_artifact(trip, analysis, artifact)

    assert not validation.valid
    assert any("不存在的节点" in reason for reason in validation.rejection_reasons)


def test_rejects_aggregate_extra_cost_over_limit() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = json.loads(
        Path("docs/evidence/stage4-api/candidates.json").read_text(encoding="utf-8")
    )
    for group in [
        *artifact["candidates"].values(),
        *artifact["additive_candidates"].values(),
    ]:
        group["options"][0]["extra_cost_cny"] = 400

    validation = validate_candidate_artifact(trip, analysis, artifact)

    assert validation.total_extra_cost_cny > trip.constraints.max_plan_b_extra_cost_cny
    assert not validation.valid
    assert any("增量成本合计" in reason for reason in validation.rejection_reasons)


def test_live_validation_requires_replayable_event_patches() -> None:
    trip, analysis = _trip_and_analysis()
    artifact = json.loads(
        Path("docs/evidence/stage4-api/candidates.json").read_text(encoding="utf-8")
    )

    validation = validate_candidate_artifact(
        trip, analysis, artifact, require_simulation=True
    )

    assert not validation.valid
    assert validation.selections == []


def test_replayable_patch_must_actually_remove_the_risk() -> None:
    trip = Trip.model_validate(
        {
            "trip_id": "replay-case",
            "version": "1.0",
            "title": "回放校验",
            "start": "2026-10-13T08:00:00+08:00",
            "end": "2026-10-13T18:00:00+08:00",
            "travelers": {"adults": 1},
            "constraints": {"budget_cny": 1000},
            "events": [
                {
                    "id": "arrival",
                    "event_type": "transport",
                    "title": "到达",
                    "start": "2026-10-13T08:00:00+08:00",
                    "end": "2026-10-13T10:00:00+08:00",
                    "destination": {"name": "车站", "city": "北京"},
                    "cost_cny": 100,
                },
                {
                    "id": "museum",
                    "event_type": "activity",
                    "title": "博物馆",
                    "start": "2026-10-13T10:10:00+08:00",
                    "end": "2026-10-13T11:10:00+08:00",
                    "location": {"name": "博物馆", "city": "北京"},
                    "cost_cny": 0,
                    "depends_on": ["arrival"],
                    "transfer_from_event_id": "arrival",
                    "travel_minutes_from_previous": 20,
                },
            ],
        }
    )
    analysis = RiskEngine().analyze(trip)
    artifact = {
        "flyai_commands": [{"exit_code": 0, "result_status": 0}],
        "candidates": {
            "museum": {
                "risk_ids": ["time_connection:arrival:museum"],
                "options": [
                    {
                        "name": "顺延参观",
                        "jumpUrl": "https://router.feizhu.com/example",
                        "extra_cost_cny": 0,
                        "source": "flyai",
                        "event_patch": {
                            "start": "2026-10-13T10:45:00+08:00",
                            "end": "2026-10-13T11:45:00+08:00",
                        },
                    }
                ],
            }
        },
    }

    validation = validate_candidate_artifact(
        trip, analysis, artifact, require_simulation=True
    )

    assert validation.valid
    assert validation.unresolved_risk_ids == []

