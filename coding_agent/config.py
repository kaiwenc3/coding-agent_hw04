"""Configuration from environment variables or .env, with CLI overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    model: str = "gpt-4.1"
    workspace: Path = Path.cwd()
    max_steps: int = 25            # Maximum reasoning/tool rounds per task to prevent endless loops
    auto_approve: bool = False     # True skips approval for writes and commands (dangerous)
    shell_timeout: int = 60        # Command timeout in seconds
    max_output_chars: int = 8000   # Maximum characters per tool output before truncation
    max_context_chars: int = 120_000  # History character budget before compressing older tool outputs
    temperature: float = 1

    @classmethod
    def load(cls, workspace: str | None = None) -> "Config":
        load_dotenv()
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("缺少 OPENAI_API_KEY：请在 .env 里设置，或 export / $env: 设置。")
        cfg = cls(model=os.getenv("AGENT_MODEL", "gpt-4.1"))
        cfg.workspace = Path(workspace or os.getcwd()).resolve()
        if not cfg.workspace.is_dir():
            raise SystemExit(f"工作目录不存在：{cfg.workspace}")
        return cfg
