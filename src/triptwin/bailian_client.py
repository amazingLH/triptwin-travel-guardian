"""Small, secret-safe client for the Alibaba Cloud Managed Agents REST API."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from triptwin.config import Settings


TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
TERMINAL_STOP_REASONS = {"end_turn", "retries_exhausted", "terminated"}


class BailianError(RuntimeError):
    """Base error that is safe to show without exposing request secrets."""


class BailianApiError(BailianError):
    pass


class BailianTimeoutError(BailianError):
    pass


class BailianApprovalRequired(BailianError):
    pass


class AgentRun(BaseModel):
    """Sanitized result of one agent turn."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    request_ids: list[str] = Field(default_factory=list)
    final_text: str = ""
    status: str = "unknown"
    event_count: int = Field(default=0, ge=0)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


class BailianManagedAgentClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        request_timeout_seconds: float = 30,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=settings.managed_agents_base_url,
            timeout=request_timeout_seconds,
            headers={
                "Authorization": (
                    "Bearer " + settings.dashscope_api_key.get_secret_value()
                ),
                "Content-Type": "application/json",
            },
        )
        self._secrets = (
            settings.dashscope_api_key.get_secret_value(),
            settings.flyai_api_key.get_secret_value(),
        )
        self._request_ids: list[str] = []

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "BailianManagedAgentClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def create_session(self, *, title: str, trip_id: str) -> str:
        response = self._request(
            "POST",
            "/sessions",
            json={
                "agent": self.settings.bailian_agent_id,
                "environment_id": self.settings.bailian_environment_id,
                "title": title,
                "environment_variables": {
                    "FLYAI_API_KEY": self.settings.flyai_api_key.get_secret_value()
                },
                "metadata": {"project": "triptwin", "trip_id": trip_id},
            },
        )
        payload = self._json(response)
        session_id = _first_string(
            payload,
            ("session_id",),
            ("id",),
            ("data", "session_id"),
            ("data", "id"),
        )
        if not session_id:
            raise BailianApiError("创建会话成功，但响应中没有 session_id。")
        return session_id

    def send_message(self, session_id: str, text: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/sessions/{session_id}/events",
            json={
                "input": [
                    {
                        "role": "user",
                        "type": "message",
                        "content": [{"type": "text", "text": text}],
                    }
                ]
            },
        )
        return self.redact(self._json(response))

    def list_sessions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        payload = self._json(
            self._request(
                "GET",
                "/sessions",
                params={"agent_id": self.settings.bailian_agent_id, "limit": limit},
            )
        )
        return [
            item
            for item in _extract_object_list(payload, ("data", "sessions", "items"))
            if isinstance(item, dict)
        ]

    def download_json_file(self, file_id: str) -> dict[str, Any]:
        """Download a marked JSON artifact produced by a session tool."""

        response = self._request("GET", f"/files/{file_id}/content")
        payload = self._json(response)
        if not isinstance(payload, dict):
            raise BailianApiError("百炼产物不是预期的 JSON 对象。")
        return payload

    def list_events(self, session_id: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        next_page: str | None = None
        for _ in range(50):
            params: dict[str, Any] = {"order": "asc", "limit": 100}
            if next_page:
                params["page"] = next_page
            payload = self._json(
                self._request(
                    "GET", f"/sessions/{session_id}/events", params=params
                )
            )
            page_events = _extract_event_list(payload)
            events.extend(event for event in page_events if isinstance(event, dict))
            next_page = _first_string(
                payload,
                ("next_page",),
                ("data", "next_page"),
                ("next_page_token",),
            )
            if not next_page:
                break
        return events

    def run_turn(
        self,
        session_id: str,
        text: str,
        *,
        timeout_seconds: float = 60,
        poll_interval_seconds: float = 1,
        cancel_on_failure: bool = False,
    ) -> AgentRun:
        baseline_ids = {_event_identity(event) for event in self.list_events(session_id)}
        try:
            self.send_message(session_id, text)
            return self.wait_for_completion(
                session_id,
                baseline_ids=baseline_ids,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        except BailianError as exc:
            if not cancel_on_failure:
                raise
            try:
                self.interrupt_session(session_id)
            except BailianError:
                note = " 自动中断请求未成功，请到百炼控制台确认并停止该会话，避免后台继续运行。"
            else:
                note = " 已提交中断请求，请在百炼控制台确认最终状态；已发生的费用不会退回。"
            raise type(exc)(str(exc) + note) from None

    def interrupt_session(self, session_id: str) -> None:
        """Best-effort stop for this run only; never approve tool requests."""
        self._request("POST", f"/sessions/{session_id}/events", json={
            "input": [{"role": "user", "type": "interrupt"}],
        })

    def wait_for_completion(
        self,
        session_id: str,
        *,
        baseline_ids: set[str] | None = None,
        timeout_seconds: float = 60,
        poll_interval_seconds: float = 1,
    ) -> AgentRun:
        """Wait for a previously submitted turn, including after a local timeout."""

        baseline_ids = baseline_ids or set()
        deadline = time.monotonic() + timeout_seconds
        new_events: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            all_events = self.list_events(session_id)
            new_events = [
                event
                for event in all_events
                if _event_identity(event) not in baseline_ids
            ]
            approval = next(
                (event for event in new_events if _needs_approval(event)), None
            )
            if approval is not None:
                raise BailianApprovalRequired(
                    "智能体暂停并请求人工批准工具调用；请在百炼会话中审核后重试。"
                )
            if any(_is_terminal(event) for event in new_events):
                return self._build_run(session_id, new_events)
            time.sleep(poll_interval_seconds)
        raise BailianTimeoutError(
            f"等待智能体完成超过 {timeout_seconds:g} 秒；会话仍可在百炼控制台查看。"
        )

    def _build_run(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> AgentRun:
        safe_events = [self.redact(event) for event in events]
        messages = [
            _event_text(event)
            for event in safe_events
            if _event_type(event) == "message" and _event_role(event) == "assistant"
        ]
        tool_calls = [
            event
            for event in safe_events
            if _event_type(event) in {"tool_call", "mcp_call"}
        ]
        tool_outputs = [
            event
            for event in safe_events
            if _event_type(event) in {"tool_call_output", "mcp_call_output"}
        ]
        errors = [event for event in safe_events if _event_type(event) == "error"]
        stop_reasons = [
            _stop_reason(event) for event in safe_events if _stop_reason(event)
        ]
        return AgentRun(
            session_id=session_id,
            request_ids=list(dict.fromkeys(self._request_ids)),
            final_text=next((text for text in reversed(messages) if text), ""),
            status=stop_reasons[-1] if stop_reasons else "completed",
            event_count=len(safe_events),
            tool_calls=tool_calls,
            tool_outputs=tool_outputs,
            errors=errors,
            events=safe_events,
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        # Retrying a non-idempotent message after a timeout can bill twice.
        attempts = 3 if method.upper() == "GET" else 1
        for attempt in range(attempts):
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code not in TRANSIENT_STATUS_CODES:
                    response.raise_for_status()
                    return response
                last_error = BailianApiError(
                    f"百炼接口暂时不可用（HTTP {response.status_code}）。"
                )
            except httpx.HTTPStatusError as exc:
                detail = self.redact(_safe_response_detail(exc.response))
                raise BailianApiError(
                    f"百炼接口请求失败（HTTP {exc.response.status_code}）：{detail}"
                ) from None
            except httpx.HTTPError as exc:
                last_error = exc
            if attempt < attempts - 1:
                time.sleep(0.5 * (2**attempt))
        raise BailianApiError(
            f"连接百炼接口失败，已尝试 {attempts} 次。请检查网络和资源配置。"
        ) from last_error

    def redact(self, value: Any) -> Any:
        """Recursively remove credentials from a value before persistence."""

        if isinstance(value, str):
            result = value
            for secret in self._secrets:
                if secret:
                    result = result.replace(secret, "***REDACTED***")
            return result
        if isinstance(value, Mapping):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized in {
                    "authorization",
                    "api_key",
                    "dashscope_api_key",
                    "flyai_api_key",
                }:
                    sanitized[str(key)] = "***REDACTED***"
                else:
                    sanitized[str(key)] = self.redact(item)
            return sanitized
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def _json(self, response: httpx.Response) -> dict[str, Any] | list[Any]:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise BailianApiError("百炼接口返回了无法解析的非 JSON 响应。") from exc
        if isinstance(payload, Mapping):
            request_id = payload.get("request_id")
            if isinstance(request_id, str) and request_id:
                self._request_ids.append(request_id)
        header_request_id = response.headers.get("x-request-id")
        if header_request_id:
            self._request_ids.append(header_request_id)
        return payload


def _extract_event_list(payload: dict[str, Any] | list[Any]) -> list[Any]:
    return _extract_object_list(payload, ("events", "items", "data"))


def _extract_object_list(
    payload: dict[str, Any] | list[Any], keys: tuple[str, ...]
) -> list[Any]:
    if isinstance(payload, list):
        return payload
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested_key in keys:
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested
    return []


def _first_string(payload: Any, *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        value = payload
        for part in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(part)
        if isinstance(value, str) and value:
            return value
    return None


def _event_type(event: Mapping[str, Any]) -> str:
    return str(event.get("type") or event.get("event_type") or "")


def _event_role(event: Mapping[str, Any]) -> str:
    role = event.get("role")
    if role:
        return str(role)
    message = event.get("message")
    return str(message.get("role") or "") if isinstance(message, Mapping) else ""


def _event_identity(event: Mapping[str, Any]) -> str:
    for key in ("id", "event_id", "request_id"):
        if event.get(key):
            return f"{key}:{event[key]}"
    return json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)


def _event_text(event: Mapping[str, Any]) -> str:
    message = event.get("message")
    if isinstance(message, Mapping):
        nested = _content_text(message.get("content"))
        if nested:
            return nested
    return _content_text(event.get("content"))


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, Mapping) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "\n".join(texts)
    return ""


def _stop_reason(event: Mapping[str, Any]) -> str:
    reason = event.get("stop_reason")
    if isinstance(reason, Mapping):
        return str(reason.get("type") or "")
    if isinstance(reason, str):
        return reason
    for data in _content_data(event):
        nested_reason = data.get("stop_reason")
        if isinstance(nested_reason, Mapping):
            nested_type = nested_reason.get("type")
            if nested_type:
                return str(nested_type)
        if isinstance(nested_reason, str):
            return nested_reason
    return ""


def _is_terminal(event: Mapping[str, Any]) -> bool:
    return _event_type(event) == "session_status" and (
        _stop_reason(event) in TERMINAL_STOP_REASONS
    )


def _needs_approval(event: Mapping[str, Any]) -> bool:
    if _event_type(event) == "tool_approval_request":
        return True
    status = str(event.get("session_status") or event.get("status") or "")
    if status == "requires_action":
        return True
    return any(
        str(data.get("session_status") or "") == "requires_action"
        or (
            isinstance(data.get("stop_reason"), Mapping)
            and data["stop_reason"].get("type") == "requires_action"
        )
        for data in _content_data(event)
    )


def _content_data(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    content = event.get("content")
    if not isinstance(content, list):
        return []
    return [
        block["data"]
        for block in content
        if isinstance(block, Mapping)
        and isinstance(block.get("data"), Mapping)
    ]


def _safe_response_detail(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text[:500]
    if isinstance(payload, Mapping):
        return {
            key: value
            for key, value in payload.items()
            if str(key).lower() not in {"environment_variables", "input"}
        }
    return str(payload)[:500]

