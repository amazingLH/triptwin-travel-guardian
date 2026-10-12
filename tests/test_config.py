from pathlib import Path

import pytest

from triptwin.config import Settings


def test_settings_load_and_mask_secrets(tmp_path: Path) -> None:
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
    assert "secret-dashscope" not in repr(settings)
    assert "secret-flyai" not in repr(settings)
    assert settings.managed_agents_base_url.startswith("https://ws-demo.")


def test_settings_reports_missing_names_without_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DASHSCOPE_API_KEY=present\n", encoding="utf-8")

    with pytest.raises(ValueError, match="FLYAI_API_KEY"):
        Settings.from_env(env_file)

