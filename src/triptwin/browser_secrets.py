"""Keep unconfigured local browser encryption keys stable across restarts."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def persistent_secret(configured: str | None, directory: Path, name: str) -> str:
    if configured:
        return configured
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) < 32:
            raise RuntimeError("本地历史密钥文件不完整，请配置 TRIPTWIN_BROWSER_STATE_SECRET 和 TRIPTWIN_RATE_LIMIT_SALT 后重启。")
        return value
    value = secrets.token_urlsafe(32)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(value)
    return value
