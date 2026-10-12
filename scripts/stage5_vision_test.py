"""Run one real vision extraction and save redacted Stage 5 evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from triptwin.models import Trip
from triptwin.vision_parser import extract_trip_from_image


ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATH = ROOT / "assets" / "hangzhou-golden-itinerary.png"
EXPECTED_PATH = ROOT / "examples" / "hangzhou_golden_trip.json"
EVIDENCE_DIR = ROOT / "docs" / "evidence" / "stage5-vision"
EVIDENCE_PATH = EVIDENCE_DIR / "vision-result.json"


def _visible_fields(trip: Trip) -> dict[str, Any]:
    values: dict[str, Any] = {
        "trip_id": trip.trip_id,
        "version": trip.version,
        "start": trip.start.isoformat(),
        "end": trip.end.isoformat(),
        "travelers.adults": trip.travelers.adults,
        "travelers.seniors": trip.travelers.seniors,
        "constraints.budget_cny": str(trip.constraints.budget_cny),
        "constraints.max_plan_b_extra_cost_cny": str(
            trip.constraints.max_plan_b_extra_cost_cny
        ),
        "constraints.minimum_connection_buffer_minutes": (
            trip.constraints.minimum_connection_buffer_minutes
        ),
        "constraints.max_daily_walk_minutes": (
            trip.constraints.max_daily_walk_minutes
        ),
        "constraints.max_transfers_per_leg": trip.constraints.max_transfers_per_leg,
        "constraints.protected_event_ids": sorted(
            trip.constraints.protected_event_ids
        ),
    }
    for index, event in enumerate(trip.events):
        prefix = f"events[{index}]"
        values.update(
            {
                f"{prefix}.id": event.id,
                f"{prefix}.title": event.title,
                f"{prefix}.start": event.start.isoformat(),
                f"{prefix}.end": event.end.isoformat(),
                f"{prefix}.cost_cny": (
                    str(event.cost_cny) if event.cost_cny is not None else None
                ),
                f"{prefix}.walking_minutes": event.walking_minutes,
                f"{prefix}.transfer_count": event.transfer_count,
            }
        )
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if EVIDENCE_PATH.is_file() and not args.refresh:
        existing = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        print(
            "复用已有真实视觉证据："
            f"model={existing['model']}, accuracy={existing['field_accuracy']:.1%}"
        )
        return 0

    expected = Trip.model_validate_json(EXPECTED_PATH.read_text(encoding="utf-8"))
    extraction, metadata = extract_trip_from_image(IMAGE_PATH)
    expected_fields = _visible_fields(expected)
    actual_fields = _visible_fields(extraction.trip)
    mismatches = [
        {
            "field": name,
            "expected": expected_value,
            "actual": actual_fields.get(name),
        }
        for name, expected_value in expected_fields.items()
        if actual_fields.get(name) != expected_value
    ]
    accuracy = (len(expected_fields) - len(mismatches)) / len(expected_fields)
    evidence = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "model": metadata["model"],
        "request_id": metadata["request_id"],
        "usage": metadata["usage"],
        "image": str(IMAGE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "field_count": len(expected_fields),
        "field_accuracy": accuracy,
        "mismatches": mismatches,
        "field_confidence": extraction.field_confidence,
        "low_confidence_fields": extraction.low_confidence_fields,
        "notes": extraction.notes,
        "trip": extraction.trip.model_dump(mode="json"),
        "contains_real_personal_information": False,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"真实视觉解析完成：model={metadata['model']}, "
        f"accuracy={accuracy:.1%}, low_confidence={len(extraction.low_confidence_fields)}"
    )
    print(f"脱敏证据：{EVIDENCE_PATH.relative_to(ROOT)}")
    return 0 if accuracy >= 0.9 else 2


if __name__ == "__main__":
    raise SystemExit(main())
