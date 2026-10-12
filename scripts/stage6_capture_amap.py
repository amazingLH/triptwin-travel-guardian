"""Capture a real Amap MCP session as redacted Stage 6 evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from triptwin.bailian_client import BailianManagedAgentClient
from triptwin.config import Settings
from triptwin.live_context import apply_amap_evidence, parse_amap_events


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "evidence" / "stage6-amap"
TRIP_PATH = ROOT / "examples" / "hangzhou_golden_trip.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id")
    args = parser.parse_args()

    settings = Settings.from_env(ROOT / ".env")
    trip_payload = json.loads(TRIP_PATH.read_text(encoding="utf-8"))
    trip_dates = _trip_dates(trip_payload["start"][:10], trip_payload["end"][:10])

    with BailianManagedAgentClient(settings) as client:
        events = client.list_events(args.session_id)
        safe_events = client.redact(events)
    inspection = parse_amap_events(
        args.session_id,
        safe_events,
        origin_name="杭州东站",
        destination_name="西湖少年宫码头",
        trip_dates=trip_dates,
    )
    enriched = apply_amap_evidence(trip_payload, inspection)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_DIR / "events-redacted.json", safe_events)
    _write_json(
        OUTPUT_DIR / "inspection.json", inspection.model_dump(mode="json")
    )
    _write_json(OUTPUT_DIR / "enriched-trip.json", enriched)

    route = inspection.route
    weather = inspection.weather
    print(
        json.dumps(
            {
                "session_id": inspection.session_id,
                "run_status": inspection.run_status,
                "mcp_calls": inspection.tool_call_count,
                "mcp_outputs": inspection.tool_output_count,
                "errors": inspection.error_count,
                "route_minutes": route.duration_minutes if route else None,
                "route_distance_meters": route.distance_meters if route else None,
                "weather_forecast_dates": [f.date for f in weather.forecasts]
                if weather
                else [],
                "trip_dates_covered": weather.trip_dates_covered if weather else False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _trip_dates(start: str, end: str) -> set[str]:
    current = date.fromisoformat(start)
    finish = date.fromisoformat(end)
    values: set[str] = set()
    while current <= finish:
        values.add(current.isoformat())
        current += timedelta(days=1)
    return values


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
