"""Offline tests using a fake model to check tools, path checks, and the agent loop.
Run: python tests/test_offline.py"""
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "sk-test")

from langchain_core.messages import AIMessageChunk
from coding_agent.agent import CodingAgent, Events
from coding_agent.config import Config


class FakeLLM:
    """Scripted model: request a file write, run it, check a path, then summarize."""
    def __init__(self):
        self.n = 0
    def stream(self, messages):
        self.n += 1
        if self.n == 1:
            yield AIMessageChunk(content="", tool_call_chunks=[
                {"name": "write_file", "args": '{"path": "hi.py", "content": "print(1+1)\\n"}', "id": "c1", "index": 0}])
        elif self.n == 2:
            yield AIMessageChunk(content="", tool_call_chunks=[
                {"name": "run_shell", "args": '{"command": "python hi.py"}', "id": "c2", "index": 0}])
        elif self.n == 3:
            yield AIMessageChunk(content="", tool_call_chunks=[
                {"name": "read_file", "args": '{"path": "../../etc/passwd"}', "id": "c3", "index": 0}])
        else:
            yield AIMessageChunk(content="完成：")
            yield AIMessageChunk(content="输出 2")


def make_agent(tmp, answers):
    cfg = Config.load(tmp)
    agent = CodingAgent(cfg, confirm=lambda a, d: answers.pop(0) if answers else "y")
    return agent


def test_loop():
    with tempfile.TemporaryDirectory() as tmp:
        agent = make_agent(tmp, ["y", "y"])
        agent.llm = FakeLLM()
        log = []
        ev = Events(on_tool_result=lambda n, o: log.append((n, o)))
        final = agent.run("写个脚本", ev)
        assert final == "完成：输出 2", final
        assert (Path(tmp) / "hi.py").exists()
        assert "exit_code=0" in log[1][1] and "2" in log[1][1], log[1]
        assert log[2][1].startswith("ERROR: 路径越界"), log[2]
    print("loop ok")


def test_tools():
    with tempfile.TemporaryDirectory() as tmp:
        agent = make_agent(tmp, [])
        t = agent.tool_map
        assert t["write_file"].invoke({"path": "a/b.py", "content": "x=1\ny=2\nx=1\n"}).startswith("OK")
        assert "ERROR" in t["edit_file"].invoke({"path": "a/b.py", "old_str": "x=1", "new_str": "x=9"})  # Occurs twice
        assert t["edit_file"].invoke({"path": "a/b.py", "old_str": "y=2", "new_str": "y=3"}).startswith("OK")
        assert "y=3" in t["read_file"].invoke({"path": "a/b.py"})
        assert "a/b.py:2" in t["grep_search"].invoke({"pattern": "y=3"})
        assert "a/b.py" in t["glob_files"].invoke({"pattern": "*.py"})
        assert "b.py" in t["list_dir"].invoke({})
        assert "拒绝" in t["run_shell"].invoke({"command": "rm -rf /"})
        assert "exit_code=0" in t["run_python"].invoke({"code": "print('ok')"})
    print("tools ok")


def test_deny():
    with tempfile.TemporaryDirectory() as tmp:
        agent = make_agent(tmp, ["n"])
        out = agent.tool_map["write_file"].invoke({"path": "x.txt", "content": "hi"})
        assert "用户拒绝" in out and not (Path(tmp) / "x.txt").exists()
    print("deny ok")


if __name__ == "__main__":
    test_tools(); test_deny(); test_loop()
