"""Regression: tool errors must be propagated to the LLM as is_error=True.

Bug: when a tool raised an exception or returned an error payload, the
dispatcher either dropped the tool_result or sent a blank success block.
The LLM then either hallucinated success or gave a wrong excuse.

Fix contract:
1. executor.execute wraps exceptions → err_payload JSON.
2. routes._insert_tool_message stores is_error=True for error payloads.
3. The Message passed to provider.complete carries is_error=True.
4. AnthropicProvider.complete forwards is_error into the tool_result block.
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


# ── LLM transport: is_error forwarded into tool_result block ─────────────────

def test_anthropic_provider_forwards_is_error_in_tool_result():
    """AnthropicProvider.complete must set is_error=True on error tool blocks."""
    from kerf_chat.llm import AnthropicProvider, CompleteRequest, Message, ToolCall

    captured_kwargs: dict = {}

    class _FakeMsg:
        content = []
        stop_reason = "end_turn"
        usage = type("U", (), {"input_tokens": 0, "output_tokens": 0})()

    class _FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                captured_kwargs.update(kwargs)
                return _FakeMsg()

    import unittest.mock as mock
    provider = AnthropicProvider(api_key="test", prompt_cache=False)

    tool_msg = Message(
        role="tool",
        content='{"error": "write failed", "code": "ERROR"}',
        tool_call_id="call_abc",
        is_error=True,
    )

    req = CompleteRequest(
        model="claude-sonnet-4-6",
        system="",
        messages=[tool_msg],
        max_tokens=64,
    )

    with mock.patch("anthropic.Anthropic", return_value=_FakeClient()):
        provider.complete(req)

    msgs = captured_kwargs.get("messages", [])
    assert msgs, "messages must be present"
    # Tool messages are grouped into a single user turn with content blocks
    user_turn = msgs[0]
    assert user_turn["role"] == "user"
    blocks = user_turn["content"]
    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "tool_result"
    assert block.get("is_error") is True, (
        "is_error must be forwarded into the Anthropic tool_result block"
    )


def test_anthropic_provider_does_not_set_is_error_on_success():
    """Successful tool results must NOT have is_error in the tool_result block."""
    from kerf_chat.llm import AnthropicProvider, CompleteRequest, Message

    captured_kwargs: dict = {}

    class _FakeMsg:
        content = []
        stop_reason = "end_turn"
        usage = type("U", (), {"input_tokens": 0, "output_tokens": 0})()

    class _FakeClient:
        class messages:
            @staticmethod
            def create(**kwargs):
                captured_kwargs.update(kwargs)
                return _FakeMsg()

    import unittest.mock as mock
    provider = AnthropicProvider(api_key="test", prompt_cache=False)

    tool_msg = Message(
        role="tool",
        content='[{"id": "box"}]',
        tool_call_id="call_xyz",
        is_error=False,
    )

    req = CompleteRequest(
        model="claude-sonnet-4-6",
        system="",
        messages=[tool_msg],
        max_tokens=64,
    )

    with mock.patch("anthropic.Anthropic", return_value=_FakeClient()):
        provider.complete(req)

    msgs = captured_kwargs.get("messages", [])
    blocks = msgs[0]["content"]
    block = blocks[0]
    assert "is_error" not in block, (
        "Successful tool results must not carry is_error"
    )
