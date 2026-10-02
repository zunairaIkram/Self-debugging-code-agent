# Self-debugging code agent

A small Python agent that takes a **single-function** coding problem, plans a solution, critiques that plan, writes code, and repairs it until generated tests pass.

The web UI streams each stage live. Generated code is executed in an [E2B](https://e2b.dev/) sandbox through an MCP tool, not on your machine.

## What it does

1. Makes a plan (pseudocode, a function name, and test cases).
2. A critic loop checks the plan for bugs, missing tests, and scope violations.
3. If the critic finds flaws, the agent replans (up to three times).
4. It generates a single Python function from the approved plan.
5. It calls `test_code` until the cases pass or the iteration budget is used up.
6. It returns the final function to the UI (or CLI).

The agent refuses multi-file projects and multi-function solutions.

## Requirements

- Python 3.11+ recommended
- An [OpenAI](https://platform.openai.com/) API key (`gpt-4o-mini`)
- An [E2B](https://e2b.dev/) API key for sandboxed test execution

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
openai_api_key=sk-...
e2b_api_key=e2b_...
```

Do not commit `.env`. It is already listed in `.gitignore`.

## Run the web UI

```powershell
python server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Describe a one-function problem, or use the example chips (palindrome, two sum, FizzBuzz, factorial).

The UI posts to `/api/run` and reads Server-Sent Events for planning, critique, code generation, tool calls, and test results.

## Run from the command line

```powershell
python agent.py
```

That runs a built-in palindrome prompt. To use your own prompt, call `agent()` from Python:

```python
from agent import agent

print(agent("Write a Python function factorial(n) that returns n!."))
```

## Project layout

| Path | Role |
|------|------|
| `server.py` | Starlette app: UI, `/health`, streaming `/api/run` |
| `agent.py` | Plan → critique → replan → generate → test loop |
| `pydanticBlueprints.py` | Structured schemas for plans, tests, and critic output |
| `mcp_client.py` | Stdio MCP client that talks to the test server |
| `tools.py` | MCP server exposing `test_code` (E2B sandbox) |
| `static/` | Front-end (`index.html`, `app.js`, `styles.css`) |

## Limits

- One function, one file, Python only.
- Plan critique has a small replan budget; code repair has a small iteration budget.
- Tests run remotely in E2B with a short timeout.
