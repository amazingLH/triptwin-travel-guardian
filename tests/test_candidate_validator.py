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

