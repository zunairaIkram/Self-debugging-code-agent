from openai import OpenAI
import json
from typing import Any, Generator, Optional

from mcp_client import MCPClient
from pydanticBlueprints import Plan, Critics
from dotenv import load_dotenv
import os

load_dotenv()
client = OpenAI(api_key=os.getenv("openai_api_key"))

role = "You are a self debugging code agent."
context = "When given a coding problem you analyze it check constraints, then generate a pseudocode and related test cases of it. Then on approval you generate code as per that pseudocode and call the required tools to test that code and when all test cases cleared you give the final code to user back."
constraints = "You can only solve single problems within one file, a single function, if user asks for a bigger problem like a multiple files project or requires multiple functions, you just say it's out of my scope."


def _schema_format(model, name: str) -> dict:
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "schema": model.model_json_schema(),
            "strict": False,
        }
    }


def _has_flaws(critic: Critics) -> bool:
    return bool(critic.flaws)


def _event(stage: str, message: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"stage": stage, "message": message}
    payload.update(extra)
    return payload


def _create_plan(prompt: str) -> Plan:
    plan_response = client.responses.create(
        model="gpt-4o-mini",
        input=[{"role": "user", "content": prompt}],
        instructions=(
            f"{role} {context} {constraints} "
            "Make a plan for this coding problem. Include pseudocode, a single function_name, "
            "and test cases whose args match that function's parameters."
        ),
        text=_schema_format(Plan, "plan"),
    )
    return Plan.model_validate_json(plan_response.output_text)


def _critique_plan(prompt: str, plan: Plan) -> Critics:
    critic_response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": plan.model_dump_json()},
        ],
        instructions=(
            f"Review this whole plan against the user prompt. Only consider flaws like bugs, "
            f"not fulfilling all test cases, against constraints {constraints}, more than one function. "
            "Do not give suggestions, just actual flaws, if none then null."
        ),
        text=_schema_format(Critics, "critics"),
    )
    return Critics.model_validate_json(critic_response.output_text)


def _replan(prompt: str, plan: Plan, flaws: list[str]) -> Plan:
    replan_response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": plan.model_dump_json()},
            {
                "role": "user",
                "content": (
                    "The critic rejected this plan. Flaws:\n"
                    + "\n".join(f"- {flaw}" for flaw in flaws)
                    + "\nProduce a revised plan that fixes every listed flaw. "
                    "Keep a single function, matching test-case args, and valid expected outputs."
                ),
            },
        ],
        instructions=(
            f"{role} {context} {constraints} "
            "Revise the previous plan. Do not repeat the rejected design."
        ),
        text=_schema_format(Plan, "plan"),
    )
    return Plan.model_validate_json(replan_response.output_text)


def run_agent(prompt: str, max_iterations: int = 5, max_replans: int = 3) -> Generator[dict[str, Any], None, Optional[str]]:
    previous_response_id = None

    yield _event("planning", "Analyzing the problem and drafting a plan…")
    plan = _create_plan(prompt)
    yield _event(
        "plan_ready",
        "Draft plan is ready. Sending it to the critic.",
        plan=plan.model_dump(),
    )
    print(f"PLAN: {plan.model_dump_json(indent=2)}")

    plan_approved = False
    critic = Critics(flaws=None)
    for replan_index in range(max_replans + 1):
        yield _event("critiquing", "Reviewing the plan for bugs and constraint issues…")
        critic = _critique_plan(prompt, plan)
        if not _has_flaws(critic):
            plan_approved = True
            yield _event("plan_approved", "Plan approved. Moving on to code generation.")
            break
        yield _event(
            "replanning",
            f"Critic found issues. Replanning ({replan_index + 1}/{max_replans + 1})…",
            flaws=critic.flaws,
        )
        print(f"CRITIC FLAWS: {critic.flaws}")
        plan = _replan(prompt, plan, critic.flaws)
        yield _event(
            "plan_ready",
            "Revised plan is ready.",
            plan=plan.model_dump(),
        )

    if not plan_approved:
        final = (
            "Could not approve a plan.\n"
            f"Last plan: {plan.model_dump_json()}\n"
            f"Remaining flaws: {critic.flaws}"
        )
        yield _event("error", "Could not approve a plan after the replan budget.", result=final)
        return final

    test_cases = plan.testCases
    coding_input = [
        {"role": "user", "content": prompt},
        {
            "role": "user",
            "content": (
                "Follow this approved plan. Write a single function, then call test_code "
                "with the full function source. After tests pass, return the final code.\n"
                f"{plan.model_dump_json()}"
            ),
        },
    ]

    mcp_client = MCPClient()
    mcp_client.connect()
    tools = mcp_client.get_tools_json()
    print(f"MCP TOOLS: {json.dumps(tools, indent=2)}")

    try:
        for iteration in range(max_iterations + 1):
            yield _event(
                "generating_code",
                f"Generating {'revised ' if iteration else ''}code from the approved plan…",
            )
            response = client.responses.create(
                model="gpt-4o-mini",
                input=coding_input,
                tools=tools,
                instructions=(
                    f"{role} {context} {constraints} "
                    "Follow the approved plan. Call test_code to run the planned test cases. "
                    "If any test fails, fix the function and call test_code again. "
                    "When all tests pass, return the final code to the user."
                ),
                previous_response_id=previous_response_id,
            )

            tool_calls = [item for item in response.output if item.type == "function_call"]
            if not tool_calls:
                result = response.output_text
                yield _event("done", "All tests passed. Final answer is ready.", result=result)
                return result

            print(f"TOOL CALLED: {[c.name for c in tool_calls]}")
            coding_input = []
            for call in tool_calls:
                yield _event(
                    "calling_tool",
                    f"Calling `{call.name}` to run the planned test cases…",
                    tool=call.name,
                )
                args = json.loads(call.arguments)
                if "code_block" not in args and "codeBlock" in args:
                    args["code_block"] = args["codeBlock"]
                args["function_name"] = plan.function_name
                args["test_cases"] = [tc.model_dump() for tc in test_cases]
                result = mcp_client.call_tool(call.name, args)
                print(f"TEST RESULTS: {result}")
                try:
                    parsed = json.loads(result)
                except json.JSONDecodeError:
                    parsed = {"raw": result}
                yield _event(
                    "tests_complete",
                    "Test runner returned results.",
                    tool=call.name,
                    tests=parsed,
                )
                coding_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": result,
                    }
                )

            previous_response_id = response.id

        final = "Maximum iterations reached"
        yield _event("error", "Stopped after the iteration budget.", result=final)
        return final
    finally:
        mcp_client.close()


def agent(prompt: str, max_iterations=5, max_replans=3):
    result = None
    for event in run_agent(prompt, max_iterations=max_iterations, max_replans=max_replans):
        result = event.get("result", result)
    return result


if __name__ == "__main__":
    response = agent("Write code in python which checks if the string is a palindrome or not.")
    print(response)
