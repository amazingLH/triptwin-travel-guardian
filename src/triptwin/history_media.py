"""Bounded, browser-local JPEG previews; never persist server file paths."""

from __future__ import annotations

import base64
import re
from html import escape
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

MAX_PREVIEW_CHARS = 24_576
JPEG_PREFIX = "data:image/jpeg;base64,"


def sanitize_previews(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        name, url = item.get("name"), item.get("data_url")
        if (
            isinstance(name, str) and isinstance(url, str)
            and len(url) <= MAX_PREVIEW_CHARS
            and url.startswith(JPEG_PREFIX)
            and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", url[len(JPEG_PREFIX):])
        ):
            result.append({"name": name[:200], "data_url": url})
    return result


def capture_previews(paths: list[Path]) -> list[dict[str, str]]:
    result = []
    for path in paths[:5]:
        try:
            with Image.open(path) as image:
                if image.width * image.height > 25_000_000:
                    continue
                thumbnail = ImageOps.exif_transpose(image).convert("RGB")
                thumbnail.thumbnail((640, 1000))
            for _ in range(8):
                buffer = BytesIO()
                thumbnail.save(buffer, format="JPEG", quality=60, optimize=True)
                url = JPEG_PREFIX + base64.b64encode(buffer.getvalue()).decode("ascii")
                if len(url) <= MAX_PREVIEW_CHARS:
                    result.append({"name": path.name, "data_url": url})
                    break
                thumbnail.thumbnail((max(1, int(thumbnail.width * .8)), max(1, int(thumbnail.height * .8))))
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
    return result


def previews_html(value: object) -> str:
    photos = []
    for item in sanitize_previews(value):
        name = escape(item["name"], quote=True)
        photos.append(
            f'<figure title="{name}"><img src="{item["data_url"]}" alt="{name}" '
            f'title="{name}"><figcaption>{name}</figcaption></figure>'
        )
    return '<div class="import-photo-list" aria-label="已导入截图">' + "".join(photos) + "</div>" if photos else ""
