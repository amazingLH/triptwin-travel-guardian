"""Deterministic, credential-free release evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from triptwin.models import Trip  # noqa: E402
from triptwin.risk_engine import RiskEngine  # noqa: E402


def main() -> int:
    cases = json.loads((ROOT / "evals" / "offline_cases.json").read_text(encoding="utf-8"))
    failures: list[str] = []
    for case in cases:
        trip = Trip.model_validate_json((ROOT / case["fixture"]).read_text(encoding="utf-8"))
        first = RiskEngine().analyze(trip)
        second = RiskEngine().analyze(trip)
        ids = [risk.id for risk in first.risks]
        if ids != [risk.id for risk in second.risks]:
            failures.append(f"{case['name']}: repeated analysis changed")
        expected = case.get("expected_risk_ids")
        if expected is not None and set(ids) != set(expected):
            failures.append(f"{case['name']}: expected {expected}, got {ids}")
        minimum = case.get("minimum_risk_count")
        if minimum is not None and len(ids) < minimum:
            failures.append(f"{case['name']}: risk count {len(ids)} < {minimum}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"offline evaluation passed: {len(cases)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
