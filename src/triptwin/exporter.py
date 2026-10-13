"""Privacy-conscious exports for a validated TripGraph."""

from __future__ import annotations

import tempfile
from pathlib import Path

from triptwin.models import Trip


def export_trip_files(trip_payload: dict[str, object]) -> list[str]:
    trip = Trip.model_validate(trip_payload)
    directory = Path(tempfile.gettempdir()) / "triptwin-exports"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{trip.trip_id}.json"
    ics_path = directory / f"{trip.trip_id}.ics"
    json_path.write_text(trip.model_dump_json(indent=2), encoding="utf-8")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TripTwin//Travel Digital Twin//ZH-CN",
        "CALSCALE:GREGORIAN",
    ]
    for event in sorted(trip.events, key=lambda item: item.start):
        place = event.location or event.destination or event.origin
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{_escape(event.id)}@triptwin",
                f"DTSTART:{event.start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{event.end.strftime('%Y%m%dT%H%M%S')}",
                f"SUMMARY:{_escape(event.title)}",
                f"LOCATION:{_escape(place.name if place else '')}",
                "DESCRIPTION:TripTwin 仅分析与提醒，不代表预订或支付。",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    ics_path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return [str(json_path), str(ics_path)]


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )
