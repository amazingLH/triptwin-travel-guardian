from pathlib import Path

import pytest

from triptwin.config import Settings


def _clear_cloud_environment(monkeypatch) -> None:
    for name in (
        "DASHSCOPE_API_KEY",
        "FLYAI_API_KEY",
        "BAILIAN_WORKSPACE_ID",
        "BAILIAN_AGENT_ID",
        "BAILIAN_ENVIRONMENT_ID",
        "DASHSCOPE_TEXT_MODEL",
        "DASHSCOPE_VISION_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_load_and_mask_secrets(monkeypatch, tmp_path: Path) -> None:
    _clear_cloud_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DASHSCOPE_API_KEY=secret-dashscope\n"
        "FLYAI_API_KEY=secret-flyai\n"
        "BAILIAN_WORKSPACE_ID=ws-demo\n"
        "BAILIAN_AGENT_ID=agent_demo\n"
        "BAILIAN_ENVIRONMENT_ID=env_demo\n",
        encoding="utf-8",
    )

    settings = Settings.from_env(env_file)

    assert settings.bailian_agent_id == "agent_demo"
    assert settings.dashscope_text_model == "qwen3.7-flash"
    assert settings.dashscope_vision_model == "qwen3.7-flash"
    assert "secret-dashscope" not in repr(settings)
    assert "secret-flyai" not in repr(settings)
    assert settings.managed_agents_base_url.startswith("https://ws-demo.")


def test_settings_reports_missing_names_without_values(monkeypatch, tmp_path: Path) -> None:
    _clear_cloud_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("DASHSCOPE_API_KEY=present\n", encoding="utf-8")

    with pytest.raises(ValueError, match="FLYAI_API_KEY"):
        Settings.from_env(env_file)


def test_settings_load_from_cloud_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "secret-dashscope")
    monkeypatch.setenv("FLYAI_API_KEY", "secret-flyai")
    monkeypatch.setenv("BAILIAN_WORKSPACE_ID", "ws-cloud")
    monkeypatch.setenv("BAILIAN_AGENT_ID", "agent-cloud")
    monkeypatch.setenv("BAILIAN_ENVIRONMENT_ID", "env-cloud")
    monkeypatch.setenv("DASHSCOPE_TEXT_MODEL", "qwen3.7-flash")
    monkeypatch.setenv("DASHSCOPE_VISION_MODEL", "qwen3.7-flash")

    settings = Settings.from_env(tmp_path / "missing.env")

    assert settings.bailian_workspace_id == "ws-cloud"
    assert settings.dashscope_text_model == "qwen3.7-flash"
    assert settings.dashscope_vision_model == "qwen3.7-flash"

