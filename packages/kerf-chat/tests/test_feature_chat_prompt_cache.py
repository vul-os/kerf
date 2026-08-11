"""Prompt caching has to hold across turns, not just on the first request.

Anthropic's cache is keyed on an exact prefix match. A breakpoint on turn one
is worth nothing if turn two sends the system block with different whitespace,
marks a different tool, or lets a cache_control leak onto a rolling message and
shift the prefix. So the invariant under test is *stability*: three turns of a
growing conversation must present a byte-identical cached prefix.

Single-turn placement (which block, which tool, off when disabled) lives in
test_litellm_provider.py alongside the rest of the provider contract. What is
here is only what a single request cannot show.

Rewritten when the four hand-written providers were folded into LiteLLM: this
module used to stub the anthropic SDK and feature-detect its cache_control
support, neither of which is in the request path any more.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from kerf_chat.llm import (  # noqa: E402
    AnthropicProvider,
    CompleteRequest,
    LLMConfig,
    Message,
    Registry,
    ToolSpec,
)

_EPHEMERAL = {"type": "ephemeral"}
_SYSTEM = "You are an expert CAD assistant.\n" * 40  # ~1.5KB, cache-worthy


def _tools(n: int) -> list[ToolSpec]:
    return [
        ToolSpec(name=f"tool_{i}", description=f"desc {i}",
                 input_schema={"type": "object", "properties": {}})
        for i in range(n)
    ]


class _Conversation:
    """Drives N turns through a provider, recording each outbound request."""

    def __init__(self, provider: AnthropicProvider):
        self.provider = provider
        self.requests: list[dict] = []

    def turn(self, messages: list[Message], tools: list[ToolSpec]) -> None:
        def fake_completion(**kwargs):
            self.requests.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="done", tool_calls=[]),
                    finish_reason="stop",
                )],
                model="anthropic/claude-opus-4-7",
                usage=SimpleNamespace(prompt_tokens=1500, completion_tokens=20),
            )

        req = CompleteRequest(
            model="claude-opus-4-7", system=_SYSTEM, messages=messages, tools=tools)
        with patch("litellm.completion", fake_completion):
            self.provider.complete(req)

    def system_blocks(self) -> list:
        return [r["messages"][0]["content"] for r in self.requests]

    def marked_tool_indices(self) -> list[list[int]]:
        return [
            [i for i, t in enumerate(r.get("tools") or []) if "cache_control" in t]
            for r in self.requests
        ]


@pytest.fixture()
def three_turns() -> _Conversation:
    """A conversation that grows the way a real one does — history accumulates."""
    convo = _Conversation(AnthropicProvider("k", prompt_cache=True))
    history: list[Message] = []
    for turn in range(3):
        history.append(Message(role="user", content=f"request {turn}"))
        convo.turn(list(history), _tools(4))
        history.append(Message(role="assistant", content=f"reply {turn}"))
    return convo


def test_the_system_block_is_byte_identical_on_every_turn(three_turns):
    """Anthropic matches the cached prefix exactly; drift is a silent miss."""
    blocks = three_turns.system_blocks()

    assert len(blocks) == 3
    assert blocks[0] == blocks[1] == blocks[2]
    assert blocks[0][0]["text"] == _SYSTEM


def test_every_turn_carries_the_system_breakpoint(three_turns):
    """Not just the priming call — a later turn without it stops reading."""
    for block in three_turns.system_blocks():
        assert block[0]["cache_control"] == _EPHEMERAL


def test_the_same_single_tool_is_marked_on_every_turn(three_turns):
    assert three_turns.marked_tool_indices() == [[3], [3], [3]]


def test_growing_history_never_leaks_a_breakpoint_onto_a_message(three_turns):
    """A cache_control on a rolling message moves the prefix every turn."""
    for request in three_turns.requests:
        for message in request["messages"][1:]:
            assert "cache_control" not in json.dumps(message)


def test_the_last_tool_is_still_the_marked_one_when_the_list_grows():
    """Tool availability is per-project, so the list changes between turns."""
    convo = _Conversation(AnthropicProvider("k", prompt_cache=True))
    convo.turn([Message(role="user", content="a")], _tools(2))
    convo.turn([Message(role="user", content="b")], _tools(5))

    assert convo.marked_tool_indices() == [[1], [4]]


def test_the_last_tool_is_still_the_marked_one_when_the_list_shrinks():
    convo = _Conversation(AnthropicProvider("k", prompt_cache=True))
    convo.turn([Message(role="user", content="a")], _tools(5))
    convo.turn([Message(role="user", content="b")], _tools(2))

    assert convo.marked_tool_indices() == [[4], [1]]


def test_nothing_is_marked_across_turns_when_caching_is_disabled():
    convo = _Conversation(AnthropicProvider("k", prompt_cache=False))
    for turn in range(3):
        convo.turn([Message(role="user", content=str(turn))], _tools(3))

    assert convo.marked_tool_indices() == [[], [], []]
    for block in convo.system_blocks():
        assert isinstance(block, str), "an uncached system prompt stays a bare string"


def test_the_registry_leaves_caching_on_by_default():
    """A config that never mentions caching must still get it."""
    registry = Registry(LLMConfig(anthropic_api_key="k"))
    assert registry.providers["anthropic"].prompt_cache is True


def test_the_registry_honours_caching_being_turned_off():
    registry = Registry(LLMConfig(anthropic_api_key="k", anthropic_prompt_cache=False))
    assert registry.providers["anthropic"].prompt_cache is False
