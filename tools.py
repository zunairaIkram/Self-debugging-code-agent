import json
import os
import subprocess
import sys
import tempfile
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

mcp = MCPServer(
    name="test-code",
    instructions="Exposes test_code: run a Python function against test cases and return JSON pass/fail results.",
)


class TestCase(BaseModel):
    args: dict[str, Any] = Field(description="Keyword arguments to pass to the function.")
    expected: Any = Field(description="Expected return value for those arguments.")


def _strip_code_fences(code: str) -> str:
    stripped = code.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    return stripped


def _error_payload(message: str) -> str:
    return json.dumps({"all_passed": False, "error": message, "results": []}, default=str)


def run_test_code(code_block: str, test_cases: list[Any], function_name: str) -> str:
    try:
        if not str(function_name).isidentifier():
            return _error_payload(f"Invalid function_name: {function_name!r}")

        code_block = _strip_code_fences(code_block)
        serialized_cases = json.dumps(
            [tc if isinstance(tc, dict) else tc.model_dump() for tc in test_cases],
            default=str,
        )
        harness = f"""
import json
{code_block}

test_cases = json.loads({serialized_cases!r})
results = []
for i, tc in enumerate(test_cases):
    try:
        actual = {function_name}(**tc["args"])
        passed = actual == tc["expected"]
        results.append({{"index": i, "args": tc["args"], "expected": tc["expected"], "actual": actual, "passed": passed, "error": None}})
    except Exception as e:
        results.append({{"index": i, "args": tc["args"], "expected": tc["expected"], "actual": None, "passed": False, "error": f"{{type(e).__name__}}: {{e}}"}})

print(json.dumps({{"all_passed": all(r["passed"] for r in results), "results": results}}, default=str))
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(harness)
            temp_path = f.name
        try:
            proc = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return _error_payload("Execution timed out.")
        finally:
            os.remove(temp_path)

        if proc.returncode != 0:
            return _error_payload(proc.stderr.strip() or f"Process exited with code {proc.returncode}")
        stdout = proc.stdout.strip()
        if not stdout:
            return _error_payload(proc.stderr.strip() or "Harness produced no output.")
        return stdout
    except Exception as exc:
        return _error_payload(f"{type(exc).__name__}: {exc}")


@mcp.tool()
def test_code(
    code_block: Annotated[str, Field(description="Complete Python function source to execute.")],
    function_name: Annotated[str, Field(description="Exact name of the function to call after execution.")],
    test_cases: Annotated[list[TestCase], Field(description="Test cases to run against the function.")],
) -> str:
    """Execute a Python function against test cases in an isolated subprocess and return JSON pass/fail results."""
    return run_test_code(code_block, test_cases, function_name)


if __name__ == "__main__":
    mcp.run(transport="stdio")
