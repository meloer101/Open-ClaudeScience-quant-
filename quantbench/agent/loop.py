import json
import threading
from collections.abc import Callable
from typing import Any

from quantbench.agent.llm import record_llm_usage
from quantbench.agent.run_context import RunCancelled, _RunContext
from quantbench.config import MAX_STEPS
from quantbench.skills.registry import SkillRegistry


def _message_to_dict(message: Any) -> dict:
    entry: dict[str, Any] = {"role": getattr(message, "role", "assistant"), "content": getattr(message, "content", None)}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        entry["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in tool_calls
        ]
    return entry


def run_agent_loop(
    llm,
    messages: list[dict],
    registry: SkillRegistry,
    run,
    ctx: _RunContext,
    emit: Callable[[dict[str, Any]], None],
    cancel_event: threading.Event | None,
) -> str:
    """Drives the MAX_STEPS tool-use loop shared by execute() and
    execute_fork(). Mutates `messages` in place and appends to ctx.warnings on
    step-limit exhaustion. Returns the final natural-language summary
    (possibly the step-limit message). Callers still emit their own
    {"type": "start", ...} event before calling this - the payload of that
    event differs between execute()/execute_fork() and is not this
    function's concern."""
    summary = ""
    for _ in range(MAX_STEPS):
        if cancel_event is not None and cancel_event.is_set():
            emit({"type": "cancelled"})
            raise RunCancelled(run.run_id)

        response = llm.chat(messages, tools=registry.schemas())
        record_llm_usage(response, getattr(llm, "model", "unknown"), ctx.llm_usage, step="coordinator")
        message = response.choices[0].message
        messages.append(_message_to_dict(message))

        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            summary = message.content or ""
            emit({"type": "final", "summary": summary})
            break

        for call in tool_calls:
            if cancel_event is not None and cancel_event.is_set():
                emit({"type": "cancelled"})
                raise RunCancelled(run.run_id)

            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                result: Any = {"error": f"invalid tool arguments JSON: {exc}"}
            else:
                emit({"type": "tool_start", "tool": name, "args": args})
                try:
                    result = registry.execute(name, args)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
            run.log_step(name, args, result)
            emit({"type": "tool_end", "tool": name, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
    else:
        summary = "Reached the step limit before the model produced a final answer."
        ctx.warnings.append("Coordinator hit MAX_STEPS without a final natural-language answer.")
        emit({"type": "final", "summary": summary})

    return summary
