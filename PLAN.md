# 动手写 Coding Agent：分阶段计划

原则：**每阶段只加一个能力，写完立刻能运行验证**。你写，我讲解和审代码。完整参考实现在 `coding_agent/`，卡住再看，别一开始就抄。

目标目录（从零自己建 `my-agent/`）：

```
my-agent/
├─ .env                 # OPENAI_API_KEY
├─ requirements.txt
├─ config.py            # 阶段1
├─ prompts.py           # 阶段1
├─ tools.py             # 阶段2→3→4→5 逐步长大
├─ sandbox.py           # 阶段4
├─ agent.py             # 阶段1→2→6
└─ cli.py               # 阶段1→6→7
```

## 路线总览

| 阶段 | 目标 | 新增/修改 | 验收（你亲眼看到的现象） | 约行数 |
|---|---|---|---|---|
| 0 | 环境就绪 | venv、依赖、.env | `python -c "import langchain_openai"` 无报错 | 0 |
| 1 | 能聊天 | config / prompts / agent / cli | 终端问答，且记得上文 | 90 |
| 2 | 会用第一个工具 | tools(read_file) + agent 循环 | 问"读 a.txt 讲了啥"，看到工具调用 | 90 |
| 3 | 会看项目 | list_dir / glob / grep | 问"哪里定义了 foo"，能定位 | 100 |
| 4 | 会改文件且安全 | sandbox + write_file / edit_file | 改文件前弹确认，`../` 越界被拒 | 130 |
| 5 | 会跑命令、自修复 | run_shell / run_python | 写代码→跑测试→失败→自己修到通过 | 60 |
| 6 | 体验 | 流式输出、rich、斜杠命令 | 逐字输出，/clear /auto 可用 | 80 |
| 7 | 稳健 | 最大步数、截断、上下文压缩、中断修复 | Ctrl+C 后能继续对话 | 50 |

合计约 600 行。

---

## 各文件框架（骨架，TODO 由我们逐阶段填）

### config.py（阶段1）
```python
@dataclass
class Config:
    model: str = "gpt-4.1"
    workspace: Path = ...
    max_steps: int = 25
    auto_approve: bool = False
    shell_timeout: int = 60
    max_output_chars: int = 8000

    @classmethod
    def load(cls, workspace=None) -> "Config": ...   # load_dotenv + 校验 key
```

### prompts.py（阶段1）
```python
SYSTEM_PROMPT = """你是...工作目录：{workspace}
工作方式：先理解再动手 / 小步修改 / 改完验证 / 报错换做法..."""
```

### agent.py（阶段1→2→6）
```python
class CodingAgent:
    def __init__(self, cfg, confirm):
        self.llm = ChatOpenAI(model=cfg.model)          # 阶段2 加 .bind_tools(tools)
        self.messages = [SystemMessage(...)]

    def run(self, user_input, ev=None) -> str:
        # 阶段1：append Human → llm.invoke → append AI → return
        # 阶段2：改成 for 循环：有 tool_calls 就执行并追加 ToolMessage，否则结束
        # 阶段6：invoke 换成 stream，逐 token 回调
    def _exec_tool(self, name, args) -> str: ...        # 阶段2
    def _compact_history(self): ...                      # 阶段7
    def reset(self): ...
```

### tools.py（阶段2→5）
```python
def build_tools(sb, cfg) -> list[BaseTool]:
    @tool
    def read_file(path, start_line=1, end_line=400): ...      # 阶段2
    @tool
    def list_dir(path=".", depth=2): ...                      # 阶段3
    @tool
    def glob_files(pattern): ...                              # 阶段3
    @tool
    def grep_search(pattern, glob="*"): ...                   # 阶段3
    @tool
    def write_file(path, content): ...                        # 阶段4
    @tool
    def edit_file(path, old_str, new_str): ...                # 阶段4
    @tool
    def run_shell(command): ...                               # 阶段5
    @tool
    def run_python(code): ...                                 # 阶段5
    return [...]
# 阶段2 先不加沙箱（sb 传 None 也行），阶段4 再补；统一的 safe 装饰器：错误→"ERROR: ..."
```

### sandbox.py（阶段4）
```python
class SandboxError(Exception): ...

class Sandbox:
    def __init__(self, root, confirm, auto_approve=False): ...
    def resolve(self, path) -> Path: ...       # 越界抛 SandboxError
    def check_command(self, cmd): ...          # 黑名单
    def approve(self, action, detail): ...     # y / n / a
```

### cli.py（阶段1→6→7）
```python
def confirm(action, detail) -> str: ...          # 阶段4 才需要
def main():
    # 阶段1：while True: input → agent.run → print
    # 阶段6：rich 输出、/help /clear /auto /exit、argparse(-w -m -p)
    # 阶段7：捕获 KeyboardInterrupt，修复 messages 配对
```

---

## 每阶段的学习重点

1. **阶段1**：LangChain 消息类型（System/Human/AI）；对话"记忆"就是把 `messages` 列表每次全发。
2. **阶段2**：`@tool` 如何由 docstring+类型生成 Schema；`bind_tools`；`tool_calls` → `ToolMessage(tool_call_id)` 配对；ReAct 循环。**最关键的一课。**
3. **阶段3**：只读工具设计（截断、跳过 `.git`/`node_modules`）；错误返回字符串而非抛异常。
4. **阶段4**：为什么 `edit_file` 要求 old_str 唯一；路径沙箱与人工确认；diff 预览。
5. **阶段5**：subprocess 超时、输出截断；让模型"跑测试→读报错→修"形成闭环。
6. **阶段6**：流式 chunk 用 `+` 合并出完整 `tool_calls`。
7. **阶段7**：防死循环、控制上下文增长、异常后恢复历史。

## 协作方式

- 每阶段我先给"要写什么+为什么"，你自己敲；贴代码或报错给我，我审。
- 每阶段结束都做一次验收任务，通过再进下一阶段。
- 你可随时说"这阶段太简单/太细"，我调整节奏。

**下一步：阶段 0 + 1。** 回复"开始"，我带你建环境并写 config / prompts / 最小聊天。
