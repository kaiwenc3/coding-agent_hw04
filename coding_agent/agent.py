"""Agent core: a handwritten ReAct loop using LangChain models, tools, and messages.

User message -> LLM -> tool calls?
    Yes: execute tools, append ToolMessages, and call the LLM again.
    No: return the final response."""
from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Callable

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from .config import Config
from .prompts import SYSTEM_PROMPT
from .sandbox import ConfirmFn, Sandbox
from .tools import build_tools


@dataclass
class Events:
    """UI callbacks: the agent emits events and the CLI controls their presentation."""
    on_token: Callable[[str], None] = lambda s: None
    on_tool_call: Callable[[str, dict], None] = lambda name, args: None
    on_tool_result: Callable[[str, str], None] = lambda name, out: None
    on_step_end: Callable[[], None] = lambda: None


class CodingAgent:
    def __init__(self, cfg: Config, confirm: ConfirmFn):
        self.cfg = cfg
        self.sandbox = Sandbox(cfg.workspace, confirm, cfg.auto_approve)
        self.tools = build_tools(self.sandbox, cfg)
        self.tool_map = {t.name: t for t in self.tools}
        # bind_tools sends tool JSON schemas with each request so the model can return tool_calls
        self.llm = ChatOpenAI(model=cfg.model, temperature=cfg.temperature, streaming=True).bind_tools(self.tools)
        self.messages: list[BaseMessage] = []
        self.reset()

    # ------------------------------------------------------------ Session management
    def reset(self) -> None:
        sys_prompt = SYSTEM_PROMPT.format(workspace=self.cfg.workspace, os_name=platform.platform())
        self.messages = [SystemMessage(content=sys_prompt)]

    def set_auto_approve(self, value: bool) -> None:
        self.sandbox.auto_approve = value

    # ------------------------------------------------------------ Main loop
    def run(self, user_input: str, ev: Events | None = None) -> str:
        ev = ev or Events()
        self.messages.append(HumanMessage(content=user_input))
        final = ""
        for _ in range(self.cfg.max_steps):
            self._compact_history()
            ai = self._call_llm(ev)
            self.messages.append(ai)
            if not ai.tool_calls:          # No tool calls means this is the final response
                final = ai.content if isinstance(ai.content, str) else str(ai.content)
                break
            for call in ai.tool_calls:     # Respond to every tool call returned in the round
                ev.on_tool_call(call["name"], call["args"])
                out = self._exec_tool(call["name"], call["args"])
                ev.on_tool_result(call["name"], out)
                # Match tool_call_id to avoid an OpenAI 400 error
                self.messages.append(ToolMessage(content=out, tool_call_id=call["id"], name=call["name"]))
        else:
            final = f"（已达到最大步数 {self.cfg.max_steps}，任务可能未完成。可以输入“继续”让我接着做。）"
            self.messages.append(AIMessage(content=final))
            ev.on_token(final)
        return final

    def _call_llm(self, ev: Events) -> AIMessage:
        """Stream text while accumulating chunks into a complete AIMessage with tool calls."""
        full: AIMessageChunk | None = None
        for chunk in self.llm.stream(self.messages):
            if isinstance(chunk.content, str) and chunk.content:
                ev.on_token(chunk.content)
            full = chunk if full is None else full + chunk   # Chunks support merging with +
        ev.on_step_end()
        if full is None:
            return AIMessage(content="")
        # Convert to a regular AIMessage for history
        return AIMessage(content=full.content, tool_calls=full.tool_calls, additional_kwargs=full.additional_kwargs)

    def _exec_tool(self, name: str, args: dict) -> str:
        tool = self.tool_map.get(name)
        if tool is None:
            return f"ERROR: 未知工具 {name}，可用工具：{', '.join(self.tool_map)}"
        try:
            return str(tool.invoke(args))
        except Exception as e:  # Including argument validation failures
            return f"ERROR: 调用 {name} 失败：{type(e).__name__}: {e}"

    # ------------------------------------------------------------ Context compression
    def _compact_history(self) -> None:
        """Compress older tool outputs while preserving message structure and tool-call pairs."""
        def size() -> int:
            return sum(len(str(m.content)) for m in self.messages)

        if size() <= self.cfg.max_context_chars:
            return
        tool_idx = [i for i, m in enumerate(self.messages) if isinstance(m, ToolMessage)]
        for i in tool_idx[:-6]:                      # Keep the six most recent tool outputs unchanged
            m = self.messages[i]
            if len(str(m.content)) > 200:
                self.messages[i] = ToolMessage(
                    content="[旧工具输出已压缩以节省上下文，如需请重新调用工具]",
                    tool_call_id=m.tool_call_id, name=m.name)
            if size() <= self.cfg.max_context_chars:
                break
