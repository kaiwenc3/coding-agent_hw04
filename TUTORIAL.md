# LangChain + OpenAI Coding Agent 手把手教程

## 1. 安装与运行（Windows PowerShell）

```powershell
cd coding-agent
python -m venv .venv
.venv\Scripts\Activate.ps1          # 若报执行策略错误：Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt

copy .env.example .env              # 然后用记事本打开 .env，填入 OPENAI_API_KEY
python tests\test_offline.py        # 离线自检（不花钱），应打印 tools ok / deny ok / loop ok
```

macOS / Linux：`source .venv/bin/activate`，`cp .env.example .env`。

在一个**练习目录**里启动（agent 只能操作这个目录）：

```powershell
mkdir C:\playground
python main.py -w C:\playground
```

## 2. 第一次使用：三个递进任务

1. `在当前目录创建 fib.py，实现 fib(n)，并写 test_fib.py 用 pytest 测试，运行并确保通过`
   → 看它依次 write_file → run_shell(pytest) → 报错就自己修。每次写/执行都会弹确认，输入 `y`。
2. `读一下 fib.py，把递归改成带缓存的版本，改完重新跑测试`
   → 看它用 `edit_file`（局部替换，而不是重写整个文件）。
3. `项目里哪里定义了 fib？列出所有调用处`
   → 看它用 grep_search，不改任何东西，不会弹确认。

常用命令：`/help` `/clear` `/auto on|off` `/cwd` `/exit`。
一次性模式：`python main.py -w C:\playground -p "给 README 加一段使用说明"`。
换模型：`python main.py -m gpt-4o-mini` 或改 `.env` 里的 `AGENT_MODEL`。

## 3. 架构：一张图

```
你输入 ─► CodingAgent.run()
            │   messages = [System, Human, AI, Tool, AI, Tool, ...]
            ▼
        llm.stream(messages)  ◄── bind_tools(工具 Schema)
            │
   有 tool_calls? ── 否 ─► 最终答复，结束
            │是
            ▼
   Sandbox 检查路径/命令 ─► 人工确认 ─► 执行工具 ─► ToolMessage 追加 ─► 回到 llm
```

文件职责（共约 600 行）：

| 文件 | 行数 | 作用 |
|---|---|---|
| `config.py` | 31 | 读环境变量、默认参数 |
| `sandbox.py` | 69 | 路径沙箱、危险命令黑名单、确认机制 |
| `tools.py` | 224 | 8 个工具：list_dir / read_file / glob_files / grep_search / write_file / edit_file / run_shell / run_python |
| `prompts.py` | 14 | 系统提示词 |
| `agent.py` | 113 | ReAct 循环、流式输出、上下文压缩 |
| `cli.py` | 146 | REPL、确认弹窗、彩色输出 |

## 4. 关键代码逐点讲解

**① 工具 = 带 docstring 的函数。** `tools.py` 里 `@tool` 自动把函数名、参数类型、docstring 变成 JSON Schema。模型“看得见”的只有这些，所以 docstring 要写清用途和注意事项（例如 `edit_file` 说明 old_str 必须唯一）。

**② 工具不抛异常，返回 `ERROR: ...`。** `safe` 装饰器统一兜底。模型读到错误信息会自己修正——这就是 agent 能“自愈”的原因。

**③ `bind_tools` + `stream`。** `agent.py` 中 `ChatOpenAI(...).bind_tools(tools)` 把工具 Schema 随每次请求发出；`stream()` 返回的 chunk 可以用 `+` 合并，合并后的 `full.tool_calls` 就是完整的工具调用。

**④ 消息配对规则。** assistant 发出的每个 `tool_call` 必须有一条 `ToolMessage(tool_call_id=...)` 回应，否则 OpenAI 返回 400。`cli.py` 的 `_repair_history` 就是为中断时修复这一点。

**⑤ 三道安全闸。** 路径必须在工作目录内（`resolve()` 会展开 `..` 与符号链接）；黑名单命令直接拒绝；其余写/执行操作需要你确认。拒绝后返回给模型的是“用户拒绝”，它会停下来问你。

**⑥ 防失控。** `max_steps` 限制循环轮数；`shell_timeout` 限制命令时长；`max_output_chars` 截断超长输出；`_compact_history` 在上下文超预算时压缩旧工具输出。

## 5. 动手扩展（建议顺序）

1. **加一个工具**：在 `build_tools` 里仿照 `list_dir` 写 `@tool @safe def delete_file(...)`，加进返回列表，并在里面调用 `sb.approve(...)`。重启即生效，不需要改别处。
2. **改系统提示词**：在 `prompts.py` 加规则，例如“Python 项目用 pytest、遵循 PEP8”，观察行为变化。
3. **调试**：`.env` 加 `LANGSMITH_TRACING=true` 与 `LANGSMITH_API_KEY` 可在 LangSmith 看到每一步；或在 `_call_llm` 里 `print(self.messages)`。
4. **进阶**：改用 `langchain.agents.create_agent` 重写 `agent.py`（约 20 行），对比手写循环的差别——手写版的价值是你完全掌控确认、压缩、中断。

## 6. 常见问题

- **401 / invalid_api_key**：`.env` 的 key 有误或没保存；确认在 `main.py` 所在目录启动。
- **模型不调用工具**：换更强的模型（gpt-4.1 / gpt-4o），`gpt-4o-mini` 对复杂任务容易偷懒。
- **400 “tool_call_id did not have response”**：历史配对被破坏，输入 `/clear` 重来。
- **命令超时**：不要让它启动常驻服务（如 `flask run`）；超时会被终止。
- **费用**：`temperature=0`，且长任务上下文会增长；用 `/clear` 开新任务可省 token。
- **安全提醒**：黑名单只是兜底，不是真正的隔离。不信任的项目请在 Docker/虚拟机里跑，且别用 `--auto`。
