"""Safety layer: workspace path checks, a command denylist, and user approval.

All tool side effects pass through this layer.
1. File paths must stay within the workspace, including resolved symlinks.
2. Denylisted commands are rejected without offering approval.
3. Writes, edits, and commands require y/n/a approval."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

# Callback signature: confirm(action, detail) -> "y" | "n" | "a"
ConfirmFn = Callable[[str, str], str]

BLOCKED_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rf][a-zA-Z]*\s+(/|~|\*|\.\.)",  # rm -rf / ~ * ..
    r"\bmkfs\b", r"\bdd\s+if=", r":\(\)\s*\{.*\};\s*:",                  # Formatting, disk writes, and fork bombs
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b",
    r"\bformat\s+[a-zA-Z]:", r"\bdel\s+/[sfq]", r"\brd\s+/s", r"Remove-Item\s+.*-Recurse.*[A-Za-z]:\\",
    r"(curl|wget|iwr|Invoke-WebRequest)[^|]*\|\s*(sh|bash|iex|powershell)",  # Download-and-execute pipelines
    r"\bchmod\s+-R\s+777\s+/", r"\breg\s+(delete|add)\b",
]


class SandboxError(Exception):
    """Safety violation returned to the model so it can choose another approach."""


class Sandbox:
    def __init__(self, root: Path, confirm: ConfirmFn, auto_approve: bool = False):
        self.root = root.resolve()
        self._confirm = confirm
        self.auto_approve = auto_approve

    # ---------- Paths ----------
    def resolve(self, path: str) -> Path:
        """Resolve a model-provided path and require it to stay within the workspace."""
        p = Path(path).expanduser()
        p = (p if p.is_absolute() else self.root / p).resolve()  # resolve expands .. and symlinks
        try:
            p.relative_to(self.root)
        except ValueError:
            raise SandboxError(f"路径越界：{path} 不在工作目录 {self.root} 内")
        return p

    def rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root)) or "."
        except ValueError:
            return str(p)

    # ---------- Commands ----------
    def check_command(self, cmd: str) -> None:
        for pat in BLOCKED_PATTERNS:
            if re.search(pat, cmd, flags=re.IGNORECASE):
                raise SandboxError(f"命令被安全策略拒绝（匹配 {pat!r}）：{cmd}")

    # ---------- Approval ----------
    def approve(self, action: str, detail: str) -> None:
        """Request approval before side effects; raise SandboxError if denied."""
        if self.auto_approve:
            return
        ans = self._confirm(action, detail)
        if ans == "a":
            self.auto_approve = True
        elif ans != "y":
            raise SandboxError("用户拒绝了该操作。请询问用户想怎么做，不要重复同样的操作。")
