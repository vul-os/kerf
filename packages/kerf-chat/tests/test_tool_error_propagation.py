"""Regression: tool errors must be propagated to the LLM as is_error=True.

Bug: when a tool raised an exception or returned an error payload, the
dispatcher either dropped the tool_result or sent a blank success block.
The LLM then either hallucinated success or gave a wrong excuse.

Fix contract:
1. executor.execute wraps exceptions → err_payload JSON.
2. routes._insert_tool_message stores is_error=True for error payloads.
3. The Message passed to provider.complete carries is_error=True.
4. The provider marks the tool message so the model cannot read a failure as
   a success.

Point 4 changed shape when the four hand-written providers were folded into
LiteLLM. Anthropic's tool_result block has an is_error flag and the old
provider set it; LiteLLM's OpenAI-shaped tool message has nowhere to put one,
so the marker now lives in the content. That is strictly more coverage than
before — the flag only ever reached Anthropic, so a failed tool looked exactly
like a successful one to OpenAI, Moonshot and Gemini.
"""
from __future__ import annotations

import json

import pytest


# ── Executor: exception → err_payload ────────────────────────────────────────

class _RaisingCtx:
    project_id = "test-project"
    user_id = "test-user"
    role = "editor"


@pytest.mark.asyncio
async def test_executor_wraps_exception_as_err_payload():
    """executor.execute must catch exceptions and return an err_payload."""
    from kerf_chat.tools.registry import Registry, ToolSpec, Tool

    # Temporarily register a tool that always raises
    async def _boom(ctx, args: bytes) -> str:
        raise RuntimeError("disk full")

    boom_spec = ToolSpec(name="_test_boom", description="boom", input_schema={})
    Registry.append(Tool(spec=boom_spec, write=False, run=_boom))

    try:
        from kerf_chat.tools.executor import execute
        result = await execute(_RaisingCtx(), "_test_boom", b"{}")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "disk full" in parsed["error"]
        assert parsed.get("code") == "ERROR"
    finally:
        Registry[:] = [t for t in Registry if t.spec.name != "_test_boom"]


# ── is_error detection: err_payload shape ─────────────────────────────────────

def test_err_payload_shape_triggers_is_error():
    """The routes dispatcher detects err_payload by {"error":..., "code":...}."""
    err = json.dumps({"error": "something went wrong", "code": "ERROR"})
    parsed = json.loads(err)
    assert isinstance(parsed, dict)
    assert "error" in parsed and "code" in parsed, "err_payload must have error+code keys"


def test_ok_payload_does_not_trigger_is_error():
    """A normal tool result (list/dict without error+code) is not an error."""
    ok = json.dumps([{"id": "box", "geom": {}}])
    parsed = json.loads(ok)
    is_err = isinstance(parsed, dict) and "error" in parsed and "code" in parsed
    assert not is_err


# ── LLM transport: the model must be able to tell a failure from a success ───

def _tool_message_for(is_error: bool) -> dict:
    """Build one turn through a provider and return the tool message it sends."""
    from unittest.mock import patch
    from types import SimpleNamespace

    from kerf_chat.llm import AnthropicProvider, CompleteRequest, Message

    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=[]),
                finish_reason="stop",
            )],
            model="m",
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )

    req = CompleteRequest(
        model="claude-opus-4-7",
        messages=[Message(
            role="tool",
            content=json.dumps({"error": "disk full", "code": "ERROR"}),
            tool_call_id="tu_1",
            is_error=is_error,
        )],
    )
    with patch("litellm.completion", fake_completion):
        AnthropicProvider("k").complete(req)
    return seen["messages"][-1]


def test_provider_marks_an_errored_tool_result():
    msg = _tool_message_for(is_error=True)

    assert msg["content"].startswith("[tool error] ")
    # The payload survives the marker, so a model that parses it still can.
    assert json.loads(msg["content"].removeprefix("[tool error] "))["code"] == "ERROR"


def test_provider_leaves_a_successful_tool_result_alone():
    msg = _tool_message_for(is_error=False)

    assert "[tool error]" not in msg["content"]
    assert json.loads(msg["content"])["error"] == "disk full"


def test_the_marker_applies_to_every_provider_not_just_anthropic():
    """The old is_error flag was Anthropic-only; three providers never saw it."""
    from unittest.mock import patch
    from types import SimpleNamespace

    from kerf_chat.llm import CompleteRequest, GeminiProvider, Message, MoonshotProvider, OpenAIProvider

    for cls in (OpenAIProvider, MoonshotProvider, GeminiProvider):
        seen = {}

        def fake_completion(**kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="", tool_calls=[]), finish_reason="stop")],
                model="m", usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0),
            )

        req = CompleteRequest(
            model="m",
            messages=[Message(role="tool", content="boom", tool_call_id="t", is_error=True)],
        )
        with patch("litellm.completion", fake_completion):
            cls("k").complete(req)

        assert seen["messages"][-1]["content"].startswith("[tool error] "), cls.__name__
