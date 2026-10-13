"""Bounded browser-local previews with authenticated temporary original references."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

MAX_PREVIEW_CHARS = 24_576
JPEG_PREFIX = "data:image/jpeg;base64,"


def sanitize_previews(value: object) -> list[dict[str, Any]]:
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
            photo = {"name": name[:200], "data_url": url}
            reference = item.get("original_ref")
            if isinstance(reference, dict) and all(isinstance(reference.get(key), str) for key in ("path", "digest", "signature")):
                photo["original_ref"] = {key: reference[key] for key in ("path", "digest", "signature")}
            result.append(photo)
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


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _signature(reference: dict, name: str, secret: str) -> str:
    value = json.dumps([name, reference["path"], reference["digest"]], ensure_ascii=False).encode()
    return hmac.new(secret.encode(), b"triptwin-history-file-v1\n" + value, hashlib.sha256).hexdigest()


def attach_original_reference(photo: dict, path: Path, secret: str) -> None:
    reference = {"path": str(path.resolve()), "digest": file_digest(path)}
    reference["signature"] = _signature(reference, photo["name"], secret)
    photo["original_ref"] = reference


def restore_original(photo: dict, secret: str, allowed_roots: list[Path]) -> Path | None:
    reference = photo.get("original_ref")
    if not isinstance(reference, dict):
        return None
    try:
        if not hmac.compare_digest(reference["signature"], _signature(reference, photo["name"], secret)):
            return None
        path = Path(reference["path"]).resolve()
        if not any(path.is_relative_to(root.resolve()) for root in allowed_roots):
            return None
        if not path.is_file() or path.stat().st_size > 12 * 1024 * 1024:
            return None
        return path if file_digest(path) == reference["digest"] else None
    except (OSError, KeyError, TypeError, ValueError):
        return None


def materialize_preview(photo: dict, directory: Path) -> Path:
    """Recover a display-only file, NEVER silently re-recognize this thumbnail."""
    data = base64.b64decode(photo["data_url"][len(JPEG_PREFIX):], validate=True)
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "JPEG" or image.width * image.height > 1_000_000:
                raise ValueError("历史截图预览格式无效。")
            image.verify()
    except Image.DecompressionBombError as exc:
        raise ValueError("历史截图预览尺寸无效。") from exc
    name = re.sub(r'[\\/:*?"<>|\r\n]', "_", photo["name"])[:180].strip(" .") or "历史截图.jpg"
    if name.startswith("."):
        name = "图片" + name
    target = directory / ("history-preview-" + hashlib.sha256(data + name.encode()).hexdigest()) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def previews_html(value: object) -> str:
    photos = []
    for item in sanitize_previews(value):
        name = escape(item["name"], quote=True)
        photos.append(
            f'<figure title="{name}"><img src="{item["data_url"]}" alt="{name}" '
            f'title="{name}"><figcaption>{name}</figcaption></figure>'
        )
    return '<div class="import-photo-list" aria-label="已导入截图">' + "".join(photos) + "</div>" if photos else ""
