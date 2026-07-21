"""Tool registry and dispatch (design §2).

A tool is a schema (what the model sees, declared in agents/prompts.py) plus a
function (what we run, here). ``build_tool_registry`` binds each function to one
run's :class:`ToolContext`; ``dispatch`` runs the requested tool and never lets
a tool crash or time out kill the agent loop — errors are returned to the model.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..providers.base import ToolCall, ToolResult
from .files import ToolContext, read_file, write_file
from .foundry import run_foundry_test
from .slither import run_slither


def build_tool_registry(
    ctx: ToolContext, names: Iterable[str] | None = None
) -> dict[str, Callable[..., str]]:
    """Return {tool_name -> callable(**arguments) -> str} bound to ``ctx``.

    ``names`` restricts the registry to a subset — tool scope *is* role
    definition (design §2). Scoping the registry, and not just the schema list
    the model sees, means an agent that hallucinates a tool it was not granted
    gets an error result rather than the capability: the finder cannot write or
    execute a PoC even if it tries.
    """
    all_tools: dict[str, Callable[..., str]] = {
        "read_file": lambda **a: read_file(ctx, **a),
        "run_slither": lambda **a: run_slither(ctx, **a),
        "write_file": lambda **a: write_file(ctx, **a),
        "run_foundry_test": lambda **a: run_foundry_test(ctx, **a),
    }
    if names is None:
        return all_tools
    unknown = set(names) - set(all_tools)
    if unknown:
        raise KeyError(f"unknown tool(s): {sorted(unknown)}")
    return {name: all_tools[name] for name in names}


def dispatch(call: ToolCall, registry: dict[str, Callable[..., str]], max_chars: int) -> ToolResult:
    """Run the requested tool; convert any failure into an error result."""
    fn = registry.get(call.name)
    try:
        if fn is None:
            raise KeyError(f"unknown tool {call.name!r}")
        output, is_error = fn(**call.arguments), False
    except TypeError as exc:  # bad/missing arguments from the model
        output, is_error = f"Tool error: bad arguments for {call.name}: {exc}", True
    except Exception as exc:  # tool crashed / timed out / not found
        output, is_error = f"Tool error: {exc}", True

    return ToolResult(
        call_id=call.id,
        content=str(output)[:max_chars],
        is_error=is_error,
    )
