"""Tools implemented as typed Python functions with docstrings.

LangChain @tool builds JSON schemas from names, parameter types, and docstrings.
Docstrings therefore serve as tool instructions for the model.
Errors are returned as strings starting with ERROR: so the model can recover."""
from __future__ import annotations

import difflib
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from .config import Config
from .sandbox import Sandbox, SandboxError

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".mypy_cache", ".pytest_cache", "dist", "build"}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit * 2 // 3]
    tail = text[-limit // 3 :]
    return f"{head}\n...[已截断 {len(text) - limit} 字符]...\n{tail}"


def _iter_files(root: Path):
    """Walk files while skipping common irrelevant directories."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in sorted(filenames):
            yield Path(dirpath) / f


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(2048)
    except OSError:
        return True


def build_tools(sb: Sandbox, cfg: Config) -> list[BaseTool]:
    """Inject the sandbox and config via closures; expose only model-supplied arguments."""

    def safe(fn):
        """Convert SandboxError and other exceptions into ERROR: strings."""
        import functools

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            try:
                return _truncate(fn(*a, **kw), cfg.max_output_chars)
            except SandboxError as e:
                return f"ERROR: {e}"
            except Exception as e:  # noqa: BLE001 - intentional catch-all
                return f"ERROR: {type(e).__name__}: {e}"

        return wrapper

    # ------------------------------------------------------------------ Read-only tools
    @tool
    @safe
    def list_dir(path: str = ".", depth: int = 2) -> str:
        """List the directory tree. Paths are workspace-relative; depth defaults to 2 (maximum 5).
        Use this to understand the project layout before starting a task."""
        root = sb.resolve(path)
        if not root.is_dir():
            return f"ERROR: {path} 不是目录"
        depth = max(1, min(depth, 5))
        lines: list[str] = []

        def walk(d: Path, level: int):
            try:
                entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except PermissionError:
                return
            for e in entries:
                if e.name in SKIP_DIRS:
                    continue
                lines.append("  " * level + e.name + ("/" if e.is_dir() else ""))
                if e.is_dir() and level + 1 < depth:
                    walk(e, level + 1)

        walk(root, 0)
        return "\n".join(lines) or "(空目录)"

    @tool
    @safe
    def read_file(path: str, start_line: int = 1, end_line: int = 400) -> str:
        """Read a text file with line numbers, which are not part of the file content.
        Reads the first 400 lines by default; use start_line/end_line for larger files."""
        p = sb.resolve(path)
        if not p.is_file():
            return f"ERROR: 文件不存在：{path}"
        if _is_binary(p):
            return f"ERROR: {path} 看起来是二进制文件"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, start_line)
        end = min(len(lines), end_line)
        if start > len(lines):
            return f"ERROR: start_line 超出文件总行数 {len(lines)}"
        body = "\n".join(f"{i:>5}| {lines[i - 1]}" for i in range(start, end + 1))
        more = f"\n(共 {len(lines)} 行，当前显示 {start}-{end})" if end < len(lines) or start > 1 else ""
        return body + more

    @tool
    @safe
    def glob_files(pattern: str) -> str:
        """Find files using glob patterns such as '*.py', 'test_*.py', or 'src/**/*.ts'.
        Return workspace-relative paths."""
        out = []
        for f in _iter_files(sb.root):
            rel = sb.rel(f).replace("\\", "/")
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(f.name, pattern):
                out.append(rel)
            if len(out) >= 200:
                out.append("...(只显示前 200 个)")
                break
        return "\n".join(out) or "没有匹配的文件"

    @tool
    @safe
    def grep_search(pattern: str, glob: str = "*", ignore_case: bool = True) -> str:
        """Search workspace text files with a regular expression; return 'file:line: content'.
        Use glob to filter filenames, for example '*.py', and locate definitions or references."""
        try:
            rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error as e:
            return f"ERROR: 非法正则：{e}"
        hits = []
        for f in _iter_files(sb.root):
            if not fnmatch.fnmatch(f.name, glob) or _is_binary(f):
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{sb.rel(f)}:{i}: {line.strip()[:200]}")
                        if len(hits) >= 100:
                            return "\n".join(hits) + "\n...(命中过多，只显示前 100 条，请缩小范围)"
            except OSError:
                continue
        return "\n".join(hits) or "没有匹配"

    # ------------------------------------------------------------------ Write tools (approval required)
    @tool
    @safe
    def write_file(path: str, content: str) -> str:
        """Create a file or overwrite its entire contents. Use edit_file for partial changes.
        Missing parent directories are created automatically."""
        p = sb.resolve(path)
        old = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
        if old is None:
            detail = f"新建 {sb.rel(p)}（{len(content.splitlines())} 行）\n" + _truncate(content, 1500)
        else:
            detail = f"覆盖 {sb.rel(p)}\n" + _diff(old, content, sb.rel(p))
        sb.approve("写文件", detail)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        return f"OK: 已写入 {sb.rel(p)}（{len(content.splitlines())} 行）"

    @tool
    @safe
    def edit_file(path: str, old_str: str, new_str: str) -> str:
        """Replace old_str with new_str exactly once.
        Include enough context to make old_str unique and match whitespace exactly.
        Do not include the line-number prefixes shown by read_file."""
        p = sb.resolve(path)
        if not p.is_file():
            return f"ERROR: 文件不存在：{path}"
        text = p.read_text(encoding="utf-8", errors="replace")
        n = text.count(old_str)
        if n == 0:
            return "ERROR: 没找到 old_str。请先 read_file 确认原文（注意缩进/空白）。"
        if n > 1:
            return f"ERROR: old_str 出现了 {n} 次，请加入更多上下文使其唯一。"
        new_text = text.replace(old_str, new_str, 1)
        sb.approve("编辑文件", _diff(text, new_text, sb.rel(p)))
        p.write_text(new_text, encoding="utf-8", newline="\n")
        return f"OK: 已编辑 {sb.rel(p)}"

    @tool
    @safe
    def run_shell(command: str) -> str:
        """Run a shell command in the workspace (cmd.exe on Windows, sh elsewhere).
        Return the exit code, stdout, and stderr. Use for tests, dependencies, or git.
        Avoid interactive commands, which will time out."""
        sb.check_command(command)
        sb.approve("执行命令", command)
        try:
            r = subprocess.run(
                command, shell=True, cwd=sb.root, capture_output=True, text=True,
                timeout=cfg.shell_timeout, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: 命令超过 {cfg.shell_timeout}s 超时被终止（是否为交互式/常驻进程？）"
        return f"exit_code={r.returncode}\n--- stdout ---\n{r.stdout.strip()}\n--- stderr ---\n{r.stderr.strip()}"

    @tool
    @safe
    def run_python(code: str) -> str:
        """Run Python code in a separate process within the workspace and return its output.
        Useful for quick checks."""
        sb.approve("运行 Python", _truncate(code, 1500))
        try:
            r = subprocess.run(
                [sys.executable, "-c", code], cwd=sb.root, capture_output=True, text=True,
                timeout=cfg.shell_timeout, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: 超过 {cfg.shell_timeout}s 超时"
        return f"exit_code={r.returncode}\n--- stdout ---\n{r.stdout.strip()}\n--- stderr ---\n{r.stderr.strip()}"

    return [list_dir, read_file, glob_files, grep_search, write_file, edit_file, run_shell, run_python]


def _diff(old: str, new: str, name: str) -> str:
    d = difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm="", n=2)
    return _truncate("\n".join(d) or "(内容无变化)", 3000)
