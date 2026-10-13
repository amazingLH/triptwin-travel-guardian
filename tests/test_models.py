from __future__ import annotations

import json
from pathlib import Path

from triptwin.models import Trip
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_golden_json_round_trip_preserves_identity() -> None:
    payload = json.loads(
        (ROOT / "examples" / "hangzhou_golden_trip.json").read_text(
            encoding="utf-8"
        )
    )

    trip = Trip.model_validate(payload)
    restored = Trip.model_validate_json(trip.model_dump_json())

    assert restored.trip_id == "hangzhou-golden-001"
    assert restored.version == "1.0"
    assert len(restored.events) == 5


def test_dependency_cycle_is_rejected() -> None:
    payload = json.loads(
        (ROOT / "examples" / "hangzhou_golden_trip.json").read_text(encoding="utf-8")
    )
    payload["events"][0]["depends_on"] = ["west-lake-boat"]

    with pytest.raises(ValueError, match="contains a cycle"):
        Trip.model_validate(payload)

