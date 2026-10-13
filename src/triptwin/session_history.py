"""Browser-local session history for the Gradio demo."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from triptwin.usage_guard import normalize_browser_usage
from triptwin.history_media import sanitize_previews


STORE_VERSION = 1
MAX_SESSIONS = 20


def ensure_store(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != STORE_VERSION:
        return {"version": STORE_VERSION, "active_id": None, "sessions": []}
    sessions = value.get("sessions")
    if not isinstance(sessions, list):
        sessions = []
    safe_sessions = [item for item in sessions if _valid_session(item)][-MAX_SESSIONS:]
    active_id = value.get("active_id")
    if not any(item["id"] == active_id for item in safe_sessions):
        active_id = safe_sessions[-1]["id"] if safe_sessions else None
    return {
        "version": STORE_VERSION,
        "active_id": active_id,
        "sessions": copy.deepcopy(safe_sessions),
        "usage": normalize_browser_usage(value.get("usage")),
        "answer_cache": _sanitize_answer_cache(value.get("answer_cache")),
    }


def ensure_active_session(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    store = ensure_store(value)
    session = _find_in_store(store, store.get("active_id"))
    if session is None:
        store, session = create_session(store)
    return store, session


def create_session(
    value: Any, *, current_snapshot: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    store = ensure_store(value)
    if current_snapshot is not None and store.get("active_id"):
        store = save_active_session(store, current_snapshot)
    now = datetime.now(UTC).isoformat()
    session = {
        "id": "tts_" + uuid4().hex,
        "title": "新旅行会话",
        "created_at": now,
        "updated_at": now,
        "snapshot": blank_snapshot(),
    }
    store["sessions"].append(session)
    store["sessions"] = store["sessions"][-MAX_SESSIONS:]
    store["active_id"] = session["id"]
    return store, copy.deepcopy(session)


def save_active_session(value: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    store = ensure_store(value)
    session = _find_in_store(store, store.get("active_id"))
    if session is None:
        store, created = create_session(store)
        session = _find_in_store(store, created["id"])
    session["snapshot"] = _sanitize_snapshot(snapshot)
    session["updated_at"] = datetime.now(UTC).isoformat()
    trip_state = session["snapshot"].get("trip_state")
    trip = (trip_state.get("trip") or trip_state.get("draft_trip")) if isinstance(trip_state, dict) else None
    title = trip.get("title") if isinstance(trip, dict) else None
    if isinstance(title, str) and title.strip():
        session["title"] = title.strip()[:60]
    elif session["snapshot"].get("image_previews"):
        session["title"] = session["snapshot"]["image_previews"][0]["name"][:60]
    return store


def switch_session(
    value: Any,
    target_id: str,
    *,
    current_snapshot: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    store = ensure_store(value)
    if current_snapshot is not None and target_id != store.get("active_id"):
        store = save_active_session(store, current_snapshot)
    target = _find_in_store(store, target_id)
    if target is None:
        raise ValueError("所选历史会话不存在或已过期。")
    store["active_id"] = target_id
    return store, copy.deepcopy(target)


def delete_session(value: Any, session_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Delete one browser-local session and select/create a safe replacement."""

    store = ensure_store(value)
    store["sessions"] = [
        session for session in store["sessions"] if session["id"] != session_id
    ]
    if store["sessions"]:
        store["active_id"] = store["sessions"][-1]["id"]
        return store, copy.deepcopy(store["sessions"][-1])
    store["active_id"] = None
    return create_session(store)


def clear_sessions(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Clear all browser-local history and start a fresh isolated session."""

    store = ensure_store(value)
    store["sessions"] = []
    store["active_id"] = None
    store["answer_cache"] = {}
    return create_session(store)


def find_session(value: Any, session_id: Any) -> dict[str, Any] | None:
    store = ensure_store(value)
    return _find_in_store(store, session_id)


def _find_in_store(
    store: dict[str, Any], session_id: Any
) -> dict[str, Any] | None:
    for session in store["sessions"]:
        if session["id"] == session_id:
            return session
    return None


def history_choices(value: Any) -> list[tuple[str, str]]:
    store = ensure_store(value)
    choices: list[tuple[str, str]] = []
    for session in reversed(store["sessions"]):
        timestamp = str(session.get("updated_at") or "")
        stamp = timestamp[5:16].replace("T", " ") if len(timestamp) >= 16 else ""
        short_id = str(session["id"])[-8:]
        choices.append((f"{session['title']} · {stamp} · {short_id}", session["id"]))
    return choices


def blank_snapshot() -> dict[str, Any]:
    return {
        "trip_state": {},
        "status": "等待载入图片。",
        "confirmed": False,
        "risks": "### 风险卡片\n\n等待检查。",
        "plan_b": "### 原方案 / Plan B\n\n等待生成。",
        "trace": "### Agent 工具执行轨迹摘要\n\n等待生成。",
        "chat_history": [],
        "amap_status": "",
        "inspection_status": "",
        "image_previews": [],
        "editor_text": None,
        "question_text": "",
    }


def _sanitize_snapshot(value: Any) -> dict[str, Any]:
    base = blank_snapshot()
    if not isinstance(value, dict):
        return base
    for key in base:
        if key in value:
            base[key] = copy.deepcopy(value[key])
    base["image_previews"] = sanitize_previews(base.get("image_previews"))
    if not isinstance(base.get("editor_text"), str):
        base["editor_text"] = None
    base["question_text"] = str(base.get("question_text") or "")[:500]
    history = base.get("chat_history")
    if not isinstance(history, list):
        base["chat_history"] = []
    else:
        messages = []
        for item in history:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = item.get("content")
            if isinstance(content, list):
                content = "\n".join(
                    block["text"] for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                )
            if isinstance(content, str) and content:
                messages.append({"role": item["role"], "content": content})
        base["chat_history"] = messages[-100:]
    return base


def _valid_session(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and value["id"].startswith("tts_")
        and isinstance(value.get("snapshot"), dict)
    )


def _sanitize_answer_cache(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    items = [
        (str(key), str(answer))
        for key, answer in value.items()
        if isinstance(key, str)
        and len(key) == 64
        and isinstance(answer, str)
        and answer.strip()
    ]
    return dict(items[-50:])
