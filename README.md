# Coding Agent — HW04

A Python command-line coding agent built with LangChain and OpenAI. It can explore a workspace, read and edit files, run commands, and use tool results to continue a task.

## Features

- Directory listing, file reading, glob matching, and regular-expression search
- File creation and exact text replacement
- Shell commands and Python execution
- Streaming responses and an interactive CLI
- Workspace path checks, command denylist, and user approval
- Limits on task steps, command duration, output size, and history size

## Start on Windows (PowerShell)

Requires Python 3.10 or later and an OpenAI API key.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Replace the placeholder in `.env` with your API key. Keep `.env` local.

```powershell
New-Item -ItemType Directory -Force playground | Out-Null
.\.venv\Scripts\python.exe main.py -w .\playground
```

Example task: `Create a Python script that computes Fibonacci numbers and run it to verify the results.`

Approve a proposed write or command with `y`, reject with `n`, or approve all subsequent actions in the session with `a`.

CLI commands: `/help`, `/clear`, `/cwd`, `/auto on|off`, `/exit`.

## Offline checks

```powershell
.\.venv\Scripts\python.exe tests/test_offline.py
```

## Project files

- `coding_agent/`: implementation
- `tests/test_offline.py`: tool, approval, and loop checks with a fake model
- `playground/`: example workspace
- `TUTORIAL.md`: detailed tutorial
- `PLAN.md`: staged learning plan

## Execution limits

Path checks and a command denylist are not operating-system isolation. Shell and Python subprocesses run with the current user's permissions. Use a container or virtual machine for untrusted code.
