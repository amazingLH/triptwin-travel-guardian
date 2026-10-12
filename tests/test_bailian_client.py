import json

import httpx

from triptwin.bailian_client import BailianManagedAgentClient
from triptwin.config import Settings


def _settings() -> Settings:
    return Settings(
        dashscope_api_key="dashscope-secret",
        flyai_api_key="flyai-secret",
        bailian_workspace_id="ws-demo",
        bailian_agent_id="agent_demo",
        bailian_environment_id="env_demo",
    )


def test_create_session_payload_and_redaction() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("authorization")
        observed["json"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "sesn_demo"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(
        transport=transport,
        base_url="https://ws-demo.cn-beijing.maas.aliyuncs.com/api/v1/agentstudio",
        headers={"Authorization": "Bearer dashscope-secret"},
    )
    client = BailianManagedAgentClient(_settings(), client=http_client)

    session_id = client.create_session(title="test", trip_id="trip-1")

    assert session_id == "sesn_demo"
    assert observed["authorization"] == "Bearer dashscope-secret"
    payload = observed["json"]
    assert isinstance(payload, dict)
    assert payload["environment_variables"]["FLYAI_API_KEY"] == "flyai-secret"
    redacted = client.redact(payload)
    assert "flyai-secret" not in json.dumps(redacted)
    assert redacted["environment_variables"]["FLYAI_API_KEY"] == "***REDACTED***"


def test_run_turn_collects_tool_trace_and_final_message() -> None:
    state = {"message_sent": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/events"):
            state["message_sent"] = True
            return httpx.Response(200, json={"id": "evt_user"})
        if request.method == "GET" and request.url.path.endswith("/events"):
            if not state["message_sent"]:
                return httpx.Response(200, json={"events": []})
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "id": "evt_tool",
                            "type": "tool_call",
                            "name": "bash",
                            "arguments": {"command": "flyai search-poi"},
                        },
                        {
                            "id": "evt_output",
                            "type": "tool_call_output",
                            "name": "bash",
                            "content": [
                                {"type": "text", "text": "flyai-secret hidden"}
                            ],
                        },
                        {
                            "id": "evt_answer",
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "完成"}],
                        },
                        {
                            "id": "evt_end",
                            "type": "session_status",
                            "content": [
                                {
                                    "type": "data",
                                    "data": {
                                        "session_status": "idle",
                                        "stop_reason": {"type": "end_turn"},
                                    },
                                }
                            ],
                        },
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://ws-demo.cn-beijing.maas.aliyuncs.com/api/v1/agentstudio",
    )
    client = BailianManagedAgentClient(_settings(), client=http_client)

    run = client.run_turn(
        "sesn_demo", "test", timeout_seconds=1, poll_interval_seconds=0
    )

    assert run.status == "end_turn"
    assert run.final_text == "完成"
    assert len(run.tool_calls) == 1
    assert len(run.tool_outputs) == 1
    assert "flyai-secret" not in run.model_dump_json()
    assert "***REDACTED***" in run.model_dump_json()

