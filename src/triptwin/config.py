"""Stage 4 configuration loaded from a local, ignored ``.env`` file."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr


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

    @classmethod
    def from_env(cls, path: str | Path = ".env") -> "Settings":
        env_path = Path(path)
        if not env_path.is_file():
            raise FileNotFoundError(
                f"未找到配置文件：{env_path.resolve()}。请复制 .env.example 为 .env。"
            )
        values: Mapping[str, str | None] = dotenv_values(env_path)
        expected = {
            "DASHSCOPE_API_KEY": "dashscope_api_key",
            "FLYAI_API_KEY": "flyai_api_key",
            "BAILIAN_WORKSPACE_ID": "bailian_workspace_id",
            "BAILIAN_AGENT_ID": "bailian_agent_id",
            "BAILIAN_ENVIRONMENT_ID": "bailian_environment_id",
        }
        missing = [name for name in expected if not (values.get(name) or "").strip()]
        if missing:
            raise ValueError(".env 缺少有效配置：" + ", ".join(missing))
        return cls(
            **{
                field: (values[name] or "").strip()
                for name, field in expected.items()
            }
        )

    @property
    def managed_agents_base_url(self) -> str:
        return (
            f"https://{self.bailian_workspace_id}.cn-beijing.maas.aliyuncs.com"
            "/api/v1/agentstudio"
        )

