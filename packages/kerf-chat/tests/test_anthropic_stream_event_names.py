"""Regression: AnthropicProvider.stream() must match real SDK event class names.

The Anthropic SDK (>= 0.39 — version on dev is 0.103) emits events as
`RawMessageStartEvent`, `RawContentBlockStartEvent`, `RawContentBlockDeltaEvent`,
`ParsedContentBlockStopEvent`, `RawMessageDeltaEvent`, `ParsedMessageStopEvent` —
NOT the un-prefixed names that AnthropicProvider.stream() used to check
against. The previous code silently dropped every event because no `elif`
branch matched, surfacing as:

    Chat sends → "blank chat head"
    e2e probe → stop_reason=tool_use, events=2, tool_calls=0

This test pins the matching behaviour so a SDK upgrade or a refactor
can't break it again.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from kerf_chat.llm import AnthropicProvider, CompleteRequest, ToolSpec


# ── Tiny SDK-shape fakes ───────────────────────────────────────────────────


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _MessageEnv:
    usage: _Usage


@dataclass
class _TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class _ToolUseBlock:
    type: str = "tool_use"
    id: str = "tu_1"
    name: str = "read_file"


@dataclass
class _TextDelta:
    type: str = "text_delta"
    text: str = ""


@dataclass
class _InputJsonDelta:
    type: str = "input_json_delta"
    partial_json: str = ""


# Real SDK class names. We construct fake instances whose class name matches.

def _make_event(class_name: str, **attrs):
    cls = type(class_name, (object,), {})
    obj = cls()
    for k, v in attrs.items():
        setattr(obj, k, v)
    return obj


def _final_message(stop_reason: str = "end_turn") -> object:
    fm = _make_event("FakeFinalMessage")
    fm.stop_reason = stop_reason
    fm.usage = _Usage(input_tokens=10, output_tokens=20)
    fm.content = []
    return fm


def _fake_stream_ctx(raw_events: list):
    """Build a fake `client.messages.stream(**kw)` context manager."""

    class _Stream:
        def __iter__(self):
            return iter(raw_events)

        def get_final_message(self):
            return _final_message()

    class _CM:
        def __enter__(self):
            return _Stream()

        def __exit__(self, *exc):
            return False

    return _CM()


def _fake_client(raw_events: list):
    class _Messages:
        def stream(self, **kw):
            return _fake_stream_ctx(raw_events)

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    return _Client


# ── Tests ──────────────────────────────────────────────────────────────────


def _drive(raw_events: list, tools: list[ToolSpec] | None = None):
    req = CompleteRequest(
        model="claude-opus-4-7",
        system="test",
        tools=tools or [],
    )
    provider = AnthropicProvider(api_key="k", prompt_cache=False)

    async def _collect():
        out = []
        with patch("anthropic.Anthropic", _fake_client(raw_events)):
            async for ev in provider.stream(req):
                out.append(ev)
        return out

    return asyncio.get_event_loop().run_until_complete(_collect())


def test_raw_text_delta_emits_assistant_text_delta():
    """A RawContentBlockDeltaEvent with text_delta → assistant_text_delta."""
    raw = [
        _make_event("RawMessageStartEvent", message=_MessageEnv(_Usage(input_tokens=10))),
        _make_event("RawContentBlockStartEvent", content_block=_TextBlock()),
        _make_event("RawContentBlockDeltaEvent", delta=_TextDelta(text="hello")),
        _make_event("RawContentBlockStopEvent"),
        _make_event("RawMessageStopEvent"),
    ]
    out = _drive(raw)
    texts = [e for e in out if e.type == "assistant_text_delta"]
    assert len(texts) == 1, f"expected 1 text delta, got events={[e.type for e in out]}"
    assert texts[0].data == {"text": "hello"}


def test_raw_tool_use_emits_start_and_complete():
    """A tool_use block must emit tool_use_start AND tool_use_complete.

    This is the exact path that was broken: the previous code matched
    against `ContentBlockStartEvent` (no `Raw` prefix), so no events
    fired, and the route's turn_tool_calls list stayed empty, and the
    agent loop emitted assistant_done with stop_reason=tool_use AND
    zero tools — surface symptom: 'blank chat head'.
    """
    tools = [ToolSpec(name="read_file", description="x", input_schema={})]
    raw = [
        _make_event("RawMessageStartEvent", message=_MessageEnv(_Usage(input_tokens=20))),
        _make_event(
            "RawContentBlockStartEvent",
            content_block=_ToolUseBlock(id="tu_42", name="read_file"),
        ),
        _make_event(
            "RawContentBlockDeltaEvent",
            delta=_InputJsonDelta(partial_json='{"path":"/main.jscad"}'),
        ),
        _make_event("ParsedContentBlockStopEvent"),
        _make_event("RawMessageStopEvent"),
    ]
    out = _drive(raw, tools=tools)
    types = [e.type for e in out]
    assert "tool_use_start" in types, f"missing tool_use_start; got {types}"
    assert "tool_use_complete" in types, f"missing tool_use_complete; got {types}"

    start = next(e for e in out if e.type == "tool_use_start")
    complete = next(e for e in out if e.type == "tool_use_complete")

    assert start.data == {"tool_use_id": "tu_42", "name": "read_file"}
    assert complete.data["tool_use_id"] == "tu_42"
    assert complete.data["name"] == "read_file"
    assert complete.data["input"] == {"path": "/main.jscad"}


def test_input_json_delta_emits_tool_use_input_delta():
    tools = [ToolSpec(name="x", description="", input_schema={})]
    raw = [
        _make_event(
            "RawContentBlockStartEvent",
            content_block=_ToolUseBlock(id="tu_a", name="x"),
        ),
        _make_event(
            "RawContentBlockDeltaEvent",
            delta=_InputJsonDelta(partial_json='{"k":'),
        ),
        _make_event(
            "RawContentBlockDeltaEvent",
            delta=_InputJsonDelta(partial_json='"v"}'),
        ),
        _make_event("RawContentBlockStopEvent"),
    ]
    out = _drive(raw, tools=tools)
    deltas = [e for e in out if e.type == "tool_use_input_delta"]
    assert len(deltas) == 2
    assert deltas[0].data == {"tool_use_id": "tu_a", "partial_json": '{"k":'}
    assert deltas[1].data == {"tool_use_id": "tu_a", "partial_json": '"v"}'}

    complete = next(e for e in out if e.type == "tool_use_complete")
    assert complete.data["input"] == {"k": "v"}


def test_legacy_unprefixed_names_still_match():
    """If an older SDK (without `Raw` prefix) is somehow in use, the
    matching should still work — we accept both naming conventions."""
    raw = [
        _make_event("MessageStartEvent", message=_MessageEnv(_Usage(input_tokens=5))),
        _make_event("ContentBlockStartEvent", content_block=_TextBlock()),
        _make_event("ContentBlockDeltaEvent", delta=_TextDelta(text="hi")),
        _make_event("ContentBlockStopEvent"),
        _make_event("MessageStopEvent"),
    ]
    out = _drive(raw)
    texts = [e for e in out if e.type == "assistant_text_delta"]
    assert len(texts) == 1
    assert texts[0].data == {"text": "hi"}


def test_text_event_helpers_are_ignored():
    """The SDK emits TextEvent / InputJsonEvent helpers alongside the
    Raw deltas. We already forwarded the Raw delta, so the helpers
    must NOT produce duplicate StreamEvents."""
    raw = [
        _make_event("RawContentBlockStartEvent", content_block=_TextBlock()),
        _make_event("RawContentBlockDeltaEvent", delta=_TextDelta(text="x")),
        _make_event("TextEvent", type="text", text="x"),  # higher-level helper
        _make_event("RawContentBlockStopEvent"),
    ]
    out = _drive(raw)
    texts = [e for e in out if e.type == "assistant_text_delta"]
    assert len(texts) == 1, f"TextEvent helper should be ignored; got {[e.type for e in out]}"
