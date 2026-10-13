"""Privacy-conscious exports for a validated TripGraph."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from triptwin.models import Trip


def export_trip_files(trip_payload: dict[str, object], *, directory_root: str | Path | None = None) -> list[str]:
    trip = Trip.model_validate(trip_payload)
    # Never overwrite another visitor's export, even for the same trip ID.
    if directory_root is not None:
        Path(directory_root).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="triptwin-export-", dir=directory_root))
    json_path = directory / f"{trip.trip_id}.json"
    ics_path = directory / f"{trip.trip_id}.ics"
    json_path.write_text(trip.model_dump_json(indent=2), encoding="utf-8")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TripTwin//Travel Digital Twin//ZH-CN",
        "CALSCALE:GREGORIAN",
    ]
    export_id = uuid4().hex
    timestamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    for event in sorted(trip.events, key=lambda item: item.start):
        place = event.location or event.destination or event.origin
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{trip.trip_id}-{event.id}-{export_id}@triptwin",
                f"DTSTAMP:{timestamp}",
                f"DTSTART:{event.start.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{event.end.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}",
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
        .replace("\r", "")
        .replace("\n", "\\n")
    )
