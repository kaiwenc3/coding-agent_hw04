"""Command-line REPL with Rich output."""
from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax

from .agent import CodingAgent, Events
from .config import Config

console = Console()

HELP = """[bold]命令[/bold]
  /help          显示帮助
  /clear         清空对话历史（重新开始）
  /auto on|off   开/关自动批准（跳过写文件、执行命令的确认）
  /cwd           显示当前工作目录
  /exit          退出（也可 Ctrl+D）
直接输入自然语言即可，例如：[italic]给 utils.py 里的 parse() 写单元测试并跑通[/italic]"""


def confirm(action: str, detail: str) -> str:
    """Request approval: y to allow, n to deny, a to allow all for this session."""
    console.print(Panel(Syntax(detail, "diff" if detail.startswith(("---", "覆盖", "@@")) else "text", word_wrap=True),
                        title=f"[yellow]需要确认：{action}[/yellow]", border_style="yellow"))
    while True:
        ans = console.input("[yellow]允许？ (y)是 / (n)否 / (a)本次会话全部允许 > [/yellow]").strip().lower()
        if ans in ("y", "n", "a"):
            return ans


def make_events() -> Events:
    state = {"streaming": False}

    def on_token(s: str) -> None:
        state["streaming"] = True
        console.print(escape(s), end="", soft_wrap=True, highlight=False)

    def on_step_end() -> None:
        if state["streaming"]:
            console.print()
            state["streaming"] = False

    def on_tool_call(name: str, args: dict) -> None:
        brief = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
        console.print(f"[cyan]⚙ {name}[/cyan]([dim]{escape(brief)}[/dim])")

    def on_tool_result(name: str, out: str) -> None:
        style = "red" if out.startswith("ERROR") else "dim"
        lines = out.splitlines()
        preview = "\n".join(lines[:6]) + (f"\n… (+{len(lines) - 6} 行)" if len(lines) > 6 else "")
        console.print(f"[{style}]{escape(preview)}[/{style}]")

    return Events(on_token, on_tool_call, on_tool_result, on_step_end)


def _short(v, n: int = 60) -> str:
    s = repr(v).replace("\\n", "⏎")
    return s if len(s) <= n else s[: n - 1] + "…"


def handle_command(line: str, agent: CodingAgent) -> bool:
    """Handle slash commands; return True to exit."""
    cmd, *rest = line.split()
    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/help":
        console.print(HELP)
    elif cmd == "/clear":
        agent.reset()
        console.print("[green]对话已清空[/green]")
    elif cmd == "/cwd":
        console.print(str(agent.cfg.workspace))
    elif cmd == "/auto":
        on = bool(rest) and rest[0] == "on"
        agent.set_auto_approve(on)
        console.print(f"自动批准：[bold]{'开（谨慎！）' if on else '关'}[/bold]")
    else:
        console.print(f"未知命令 {cmd}，输入 /help 查看")
    return False


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="LangChain + OpenAI coding agent")
    ap.add_argument("-w", "--workspace", help="工作目录（默认当前目录）")
    ap.add_argument("-m", "--model", help="模型名，覆盖 AGENT_MODEL")
    ap.add_argument("--auto", action="store_true", help="自动批准所有写/执行操作")
    ap.add_argument("--max-steps", type=int, help="单次任务最大步数")
    ap.add_argument("-p", "--prompt", help="一次性模式：执行这条任务后退出")
    args = ap.parse_args(argv)

    cfg = Config.load(args.workspace)
    if args.model:
        cfg.model = args.model
    if args.max_steps:
        cfg.max_steps = args.max_steps
    cfg.auto_approve = args.auto

    agent = CodingAgent(cfg, confirm)
    ev = make_events()
    console.print(Panel.fit(f"模型 [bold]{cfg.model}[/bold]\n工作目录 [bold]{cfg.workspace}[/bold]\n输入 /help 查看命令",
                            title="Coding Agent", border_style="green"))

    if args.prompt:
        agent.run(args.prompt, ev)
        return

    while True:
        try:
            line = console.input("\n[bold green]你 ›[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if handle_command(line, agent):
                break
            continue
        try:
            console.print("[bold magenta]Agent ›[/bold magenta]")
            agent.run(line, ev)
        except KeyboardInterrupt:
            console.print("\n[yellow]已中断当前任务[/yellow]")
            _repair_history(agent)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]出错：{type(e).__name__}: {escape(str(e))}[/red]")
            _repair_history(agent)


def _repair_history(agent: CodingAgent) -> None:
    """Interruptions or errors may leave tool calls without matching ToolMessages.
    Roll back to before the latest HumanMessage to restore valid history."""
    from langchain_core.messages import HumanMessage
    for i in range(len(agent.messages) - 1, 0, -1):
        if isinstance(agent.messages[i], HumanMessage):
            del agent.messages[i:]
            break


if __name__ == "__main__":
    main(sys.argv[1:])
