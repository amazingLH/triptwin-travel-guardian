"""Command-line entry point for local TripGraph analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from triptwin.models import Trip
from triptwin.risk_engine import RiskEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a TripGraph JSON file and print deterministic risks."
    )
    parser.add_argument("trip_file", type=Path, help="Path to a TripGraph JSON file")
    parser.add_argument(
        "--compact", action="store_true", help="Print single-line JSON output"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = json.loads(args.trip_file.read_text(encoding="utf-8"))
        trip = Trip.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"TripGraph validation failed: {error}")
        return 2

    analysis = RiskEngine().analyze(trip)
    print(analysis.model_dump_json(indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

