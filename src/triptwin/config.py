"""Stage 4 configuration loaded from a local, ignored ``.env`` file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ModelSettings(BaseModel):
    """Credentials needed for direct text/vision model calls only."""

    model_config = ConfigDict(extra="forbid")

    dashscope_api_key: SecretStr = Field(min_length=1)
    bailian_workspace_id: str = Field(min_length=1)
    dashscope_text_model: str = Field(default="qwen3.7-flash", min_length=1)
    dashscope_vision_model: str = Field(default="qwen3.7-flash", min_length=1)

    @classmethod
    def from_env(cls, path: str | Path = ".env") -> "ModelSettings":
        env_path = Path(path)
        file_values: Mapping[str, str | None] = (
            dotenv_values(env_path) if env_path.is_file() else {}
        )
        required = ("DASHSCOPE_API_KEY", "BAILIAN_WORKSPACE_ID")
        values = {name: os.getenv(name) or file_values.get(name) for name in required}
        missing = [name for name in required if not (values.get(name) or "").strip()]
        if missing:
            raise ValueError("模型调用缺少有效配置：" + ", ".join(missing))
        return cls(
            dashscope_api_key=(values["DASHSCOPE_API_KEY"] or "").strip(),
            bailian_workspace_id=(values["BAILIAN_WORKSPACE_ID"] or "").strip(),
            dashscope_text_model=(
                os.getenv("DASHSCOPE_TEXT_MODEL")
                or file_values.get("DASHSCOPE_TEXT_MODEL")
                or "qwen3.7-flash"
            ).strip(),
            dashscope_vision_model=(
                os.getenv("DASHSCOPE_VISION_MODEL")
                or file_values.get("DASHSCOPE_VISION_MODEL")
                or "qwen3.7-flash"
            ).strip(),
        )


class Settings(BaseModel):
    """Secrets and resource identifiers required by Managed Agents.

    ``SecretStr`` keeps API keys masked in repr/log output.  Callers should only
    unwrap a secret immediately before constructing an authenticated request.
    """

    model_config = ConfigDict(extra="forbid")

    dashscope_api_key: SecretStr = Field(min_length=1)
    flyai_api_key: SecretStr = Field(min_length=1)
    bailian_workspace_id: str = Field(min_length=1)
    bailian_agent_id: str = Field(min_length=1)
    bailian_environment_id: str = Field(min_length=1)
    dashscope_text_model: str = Field(default="qwen3.7-flash", min_length=1)
    dashscope_vision_model: str = Field(default="qwen3.7-flash", min_length=1)

    @classmethod
    def from_env(cls, path: str | Path = ".env") -> "Settings":
        env_path = Path(path)
        file_values: Mapping[str, str | None] = (
            dotenv_values(env_path) if env_path.is_file() else {}
        )
        expected = {
            "DASHSCOPE_API_KEY": "dashscope_api_key",
            "FLYAI_API_KEY": "flyai_api_key",
            "BAILIAN_WORKSPACE_ID": "bailian_workspace_id",
            "BAILIAN_AGENT_ID": "bailian_agent_id",
            "BAILIAN_ENVIRONMENT_ID": "bailian_environment_id",
        }
        values = {
            name: os.getenv(name) or file_values.get(name) for name in expected
        }
        missing = [name for name in expected if not (values.get(name) or "").strip()]
        if missing:
            raise ValueError(".env 缺少有效配置：" + ", ".join(missing))
        return cls(
            **{
                field: (values[name] or "").strip()
                for name, field in expected.items()
            },
            dashscope_text_model=(
                os.getenv("DASHSCOPE_TEXT_MODEL")
                or file_values.get("DASHSCOPE_TEXT_MODEL")
                or "qwen3.7-flash"
            ).strip(),
            dashscope_vision_model=(
                os.getenv("DASHSCOPE_VISION_MODEL")
                or file_values.get("DASHSCOPE_VISION_MODEL")
                or "qwen3.7-flash"
            ).strip(),
        )

    @property
    def managed_agents_base_url(self) -> str:
        return (
            f"https://{self.bailian_workspace_id}.cn-beijing.maas.aliyuncs.com"
            "/api/v1/agentstudio"
        )

