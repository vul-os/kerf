"""LiteLLMProvider — the single implementation behind all four providers.

This replaces six test modules that each mocked a vendor's own SDK
(``anthropic.Anthropic``, ``openai.OpenAI``, ``google.genai.Client``) to pin
that vendor's call shape. Those shapes are LiteLLM's problem now, and mocking
an SDK that is no longer in the request path is worse than not testing at all:
when the providers were folded, those mocks silently stopped intercepting and
the suite began making real calls to api.anthropic.com. The root conftest now
blocks that outright, and everything here patches ``litellm.completion`` /
``litellm.acompletion``, which is the real boundary.

The behaviours below are not new — they are the regressions the deleted modules
existed to prevent, restated against the one code path that now serves every
provider:

  * Anthropic prompt-cache breakpoints on the system block and the last tool
  * temperature omitted rather than sent as 0 or null
  * tool_choice as a string for auto/none and an object for a named tool
  * Gemini 3's thought_signature surviving a full round trip
  * the streaming event vocabulary the SSE route and the frontend decode

Plus one that could not have been written before, because it was the bug:
every provider must receive the system prompt.
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
    GeminiProvider,
    LiteLLMProvider,
    Message,
    MoonshotProvider,
    OpenAIProvider,
    ToolCall,
    ToolSpec,
)


# ── fakes ───────────────────────────────────────────────────────────────────

def _tool_call(id="t1", name="read_file", arguments='{"path":"/a"}', fields=None):
    return SimpleNamespace(
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
        provider_specific_fields=fields,
    )


def _response(content="", tool_calls=None, finish_reason="stop",
              model="anthropic/claude-opus-4-7", prompt=11, completion=7):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, tool_calls=tool_calls or []),
            finish_reason=finish_reason,
        )],
        model=model,
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion),
    )


def _chunk(text=None, tool_calls=None, finish_reason=None, usage=None, model=None):
    delta = SimpleNamespace(content=text, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=usage,
        model=model,
    )


def _delta_tool(index=0, id=None, name=None, arguments=None, fields=None):
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
        provider_specific_fields=fields,
    )


def _capture(provider, req, response=None):
    """Run complete() against a stubbed litellm and return (kwargs, result)."""
    seen = {}

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return response if response is not None else _response(content="ok")

    with patch("litellm.completion", fake_completion):
        result = provider.complete(req)
    return seen, result


async def _drain(provider, req, chunks):
    """Run stream() against a stubbed litellm and collect the events."""
    class _Stream:
        def __aiter__(self):
            async def gen():
                for c in chunks:
                    yield c
            return gen()

    async def fake_acompletion(**kwargs):
        return _Stream()

    with patch("litellm.acompletion", fake_acompletion):
        return [ev async for ev in provider.stream(req)]


def _req(**overrides) -> CompleteRequest:
    base = dict(
        model="claude-opus-4-7",
        system="CAD system prompt",
        messages=[Message(role="user", content="make it 6mm taller")],
        max_tokens=4096,
        temperature=0.0,
    )
    base.update(overrides)
    return CompleteRequest(**base)


def _tools(n=2):
    return [
        ToolSpec(name=f"tool_{i}", description=f"d{i}", input_schema={"type": "object"})
        for i in range(n)
    ]


# ── routing ─────────────────────────────────────────────────────────────────

def test_catalogue_ids_are_prefixed_with_the_provider():
    """CATALOG stores bare vendor ids; LiteLLM routes on a prefix."""
    kwargs, _ = _capture(AnthropicProvider("k"), _req())
    assert kwargs["model"] == "anthropic/claude-opus-4-7"

    kwargs, _ = _capture(GeminiProvider("k"), _req(model="gemini-3-pro-preview"))
    assert kwargs["model"] == "gemini/gemini-3-pro-preview"


def test_an_already_prefixed_model_is_left_alone():
    """A gateway can serve models the catalogue has never heard of."""
    kwargs, _ = _capture(OpenAIProvider("k"), _req(model="openrouter/meta/llama-4"))
    assert kwargs["model"] == "openrouter/meta/llama-4"


def test_unsupported_params_are_dropped_rather_than_400ing():
    """o3-mini and friends reject parameters the chat models require."""
    kwargs, _ = _capture(OpenAIProvider("k"), _req())
    assert kwargs["drop_params"] is True


# ── the system prompt ───────────────────────────────────────────────────────

@pytest.mark.parametrize("provider", [
    AnthropicProvider("k"),
    OpenAIProvider("k"),
    MoonshotProvider("k"),
    GeminiProvider("k"),
])
def test_every_provider_receives_the_system_prompt(provider):
    """The bug this fold fixed.

    OpenAIProvider built its message list from req.messages alone and never
    read req.system, so choosing GPT-4o or Kimi ran the model with no CAD
    instructions whatsoever. Anthropic and Gemini sent it; nothing tested that
    the other two did.
    """
    kwargs, _ = _capture(provider, _req())
    system = [m for m in kwargs["messages"] if m["role"] == "system"]

    assert len(system) == 1, f"{provider.name()} got no system message"
    content = system[0]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    assert text == "CAD system prompt"


def test_an_empty_system_prompt_adds_no_message():
    kwargs, _ = _capture(AnthropicProvider("k"), _req(system=""))
    assert not [m for m in kwargs["messages"] if m["role"] == "system"]


# ── Anthropic prompt caching ────────────────────────────────────────────────

def test_system_block_carries_a_cache_breakpoint():
    """~7KB of CAD prompt goes out on every turn; it has to be cacheable."""
    kwargs, _ = _capture(AnthropicProvider("k", prompt_cache=True), _req())
    system = kwargs["messages"][0]["content"]

    assert isinstance(system, list), "cache_control needs a block, not a bare string"
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_system_is_a_plain_string_when_caching_is_off():
    kwargs, _ = _capture(AnthropicProvider("k", prompt_cache=False), _req())
    assert kwargs["messages"][0]["content"] == "CAD system prompt"


def test_only_the_last_tool_gets_the_breakpoint():
    """Anthropic caches the prefix up to the marked entry, so one suffices."""
    kwargs, _ = _capture(AnthropicProvider("k"), _req(tools=_tools(4)))
    marked = [i for i, t in enumerate(kwargs["tools"]) if "cache_control" in t]

    assert marked == [3]


def test_a_single_tool_still_gets_the_breakpoint():
    kwargs, _ = _capture(AnthropicProvider("k"), _req(tools=_tools(1)))
    assert "cache_control" in kwargs["tools"][0]


def test_tools_have_no_breakpoint_when_caching_is_off():
    kwargs, _ = _capture(AnthropicProvider("k", prompt_cache=False), _req(tools=_tools(3)))
    assert not any("cache_control" in t for t in kwargs["tools"])


def test_rolling_messages_never_carry_a_breakpoint():
    """Only the stable prefix is worth caching; conversation turns are not."""
    kwargs, _ = _capture(AnthropicProvider("k"), _req(messages=[
        Message(role="user", content="a"),
        Message(role="assistant", content="b"),
        Message(role="user", content="c"),
    ]))
    for m in kwargs["messages"][1:]:
        assert "cache_control" not in json.dumps(m)


@pytest.mark.parametrize("provider", [OpenAIProvider("k"), MoonshotProvider("k"), GeminiProvider("k")])
def test_non_anthropic_providers_get_no_cache_control(provider):
    """cache_control is Anthropic's; sending it elsewhere is a 400 waiting."""
    kwargs, _ = _capture(provider, _req(tools=_tools(2)))
    assert "cache_control" not in json.dumps(kwargs["messages"])
    assert "cache_control" not in json.dumps(kwargs["tools"])


# ── request parameters ──────────────────────────────────────────────────────

def test_default_temperature_is_omitted_entirely():
    """Some models reject an explicit null, some reject the parameter at all."""
    kwargs, _ = _capture(AnthropicProvider("k"), _req(temperature=0.0))
    assert "temperature" not in kwargs


def test_an_explicit_temperature_is_forwarded():
    kwargs, _ = _capture(AnthropicProvider("k"), _req(temperature=0.7))
    assert kwargs["temperature"] == 0.7


def test_no_tools_means_no_tool_keys():
    kwargs, _ = _capture(AnthropicProvider("k"), _req(tools=[]))
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs


@pytest.mark.parametrize("choice", ["auto", "none"])
def test_string_tool_choices_pass_through(choice):
    kwargs, _ = _capture(AnthropicProvider("k"), _req(tools=_tools(2), tool_choice=choice))
    assert kwargs["tool_choice"] == choice


def test_a_named_tool_choice_becomes_an_object():
    kwargs, _ = _capture(AnthropicProvider("k"), _req(tools=_tools(2), tool_choice="tool_1"))
    assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "tool_1"}}


def test_max_tokens_is_omitted_when_unset():
    kwargs, _ = _capture(AnthropicProvider("k"), _req(max_tokens=0))
    assert "max_tokens" not in kwargs


# ── base_url ────────────────────────────────────────────────────────────────

def test_a_configured_base_url_reaches_litellm():
    kwargs, _ = _capture(OpenAIProvider("k", base_url="https://gateway.internal/v1"), _req())
    assert kwargs["base_url"] == "https://gateway.internal/v1"


def test_base_url_is_omitted_when_unset():
    """Sending an empty string would override LiteLLM's own default."""
    kwargs, _ = _capture(OpenAIProvider("k"), _req())
    assert "base_url" not in kwargs


def test_moonshot_supplies_its_own_endpoint():
    kwargs, _ = _capture(MoonshotProvider("k"), _req(model="kimi-k2-0905-preview"))
    assert kwargs["base_url"] == "https://api.moonshot.cn/v1"


def test_a_configured_base_url_beats_the_moonshot_default():
    kwargs, _ = _capture(MoonshotProvider("k", base_url="https://gw/v1"), _req())
    assert kwargs["base_url"] == "https://gw/v1"


# ── responses ───────────────────────────────────────────────────────────────

def test_a_text_response_is_returned_with_its_token_counts():
    _, result = _capture(AnthropicProvider("k"), _req(),
                         _response(content="Raised the base to 16mm.", prompt=1234, completion=56))

    assert result.content == "Raised the base to 16mm."
    assert result.tool_calls == []
    assert result.stop_reason == "stop"
    assert (result.input_tokens, result.output_tokens) == (1234, 56)
    assert result.model_used == "anthropic/claude-opus-4-7"


def test_tool_calls_are_decoded():
    _, result = _capture(
        AnthropicProvider("k"), _req(),
        _response(tool_calls=[_tool_call(id="tu_1", name="edit_file", arguments='{"path":"/m.jscad"}')],
                  finish_reason="tool_calls"),
    )

    assert len(result.tool_calls) == 1
    assert (result.tool_calls[0].id, result.tool_calls[0].name) == ("tu_1", "edit_file")
    assert result.tool_calls[0].arguments_json == '{"path":"/m.jscad"}'


@pytest.mark.parametrize("finish,expected", [
    ("tool_calls", "tool_use"),
    ("function_call", "tool_use"),
    ("length", "max_tokens"),
    ("stop", "stop"),
    ("content_filter", "content_filter"),
])
def test_finish_reasons_map_to_the_vocabulary_the_routes_read(finish, expected):
    """routes.py branches on both "stop" and "tool_use"; keep both working."""
    _, result = _capture(AnthropicProvider("k"), _req(), _response(finish_reason=finish))
    assert result.stop_reason == expected


def test_a_tool_call_with_no_arguments_yields_valid_json():
    """`json.loads("")` further down the chain would take out the whole turn."""
    _, result = _capture(AnthropicProvider("k"), _req(),
                         _response(tool_calls=[_tool_call(arguments=None)]))
    assert json.loads(result.tool_calls[0].arguments_json) == {}


# ── Gemini 3 thought signatures ─────────────────────────────────────────────

def test_a_thought_signature_is_captured_off_the_response():
    """Without it, the next request is rejected with HTTP 400 INVALID_ARGUMENT."""
    _, result = _capture(
        GeminiProvider("k"), _req(model="gemini-3-pro-preview"),
        _response(tool_calls=[_tool_call(fields={"thought_signature": "AbC123=="})]),
    )
    assert result.tool_calls[0].provider_metadata == {"thought_signature": "AbC123=="}


def test_a_thought_signature_on_the_function_is_also_found():
    """Providers hang it in either of two places depending on the code path."""
    tc = SimpleNamespace(
        id="t1",
        function=SimpleNamespace(
            name="read_file", arguments="{}",
            provider_specific_fields={"thought_signature": "deep"},
        ),
        provider_specific_fields=None,
    )
    _, result = _capture(GeminiProvider("k"), _req(), _response(tool_calls=[tc]))
    assert result.tool_calls[0].provider_metadata == {"thought_signature": "deep"}


def test_a_thought_signature_is_echoed_back_on_the_next_turn():
    kwargs, _ = _capture(GeminiProvider("k"), _req(messages=[
        Message(role="user", content="hi"),
        Message(role="assistant", content="", tool_calls=[
            ToolCall(id="t1", name="read_file", arguments_json="{}",
                     provider_metadata={"thought_signature": "AbC123=="}),
        ]),
        Message(role="tool", content="body", tool_call_id="t1"),
    ]))

    assistant = next(m for m in kwargs["messages"] if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["provider_specific_fields"] == {
        "thought_signature": "AbC123=="
    }


def test_a_tool_call_without_metadata_sends_no_empty_field():
    """An empty provider_specific_fields is not the same as omitting it."""
    kwargs, _ = _capture(OpenAIProvider("k"), _req(messages=[
        Message(role="assistant", content="", tool_calls=[
            ToolCall(id="t1", name="read_file", arguments_json="{}"),
        ]),
    ]))
    assert "provider_specific_fields" not in kwargs["messages"][-1]["tool_calls"][0]


def test_tool_results_are_bound_to_their_call():
    kwargs, _ = _capture(OpenAIProvider("k"), _req(messages=[
        Message(role="tool", content="file body", tool_call_id="t1"),
    ]))
    tool_msg = kwargs["messages"][-1]
    assert (tool_msg["role"], tool_msg["tool_call_id"]) == ("tool", "t1")


# ── streaming ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_deltas_stream_then_close_with_usage():
    events = await _drain(AnthropicProvider("k"), _req(), [
        _chunk(text="Rais", model="anthropic/claude-opus-4-7"),
        _chunk(text="ed the base."),
        _chunk(finish_reason="stop"),
        _chunk(usage=SimpleNamespace(prompt_tokens=900, completion_tokens=12)),
    ])

    assert [e.type for e in events] == [
        "assistant_text_delta", "assistant_text_delta", "assistant_done",
    ]
    assert "".join(e.data["text"] for e in events[:2]) == "Raised the base."
    done = events[-1].data
    assert (done["input_tokens"], done["output_tokens"]) == (900, 12)
    assert done["stop_reason"] == "stop"


@pytest.mark.asyncio
async def test_streaming_asks_for_usage_explicitly():
    """Without stream_options every streamed turn records zero tokens, which is
    exactly what the Settings usage panel reads back."""
    seen = {}

    class _Empty:
        def __aiter__(self):
            async def gen():
                if False:
                    yield None
            return gen()

    async def fake(**kwargs):
        seen.update(kwargs)
        return _Empty()

    with patch("litellm.acompletion", fake):
        [ev async for ev in AnthropicProvider("k").stream(_req())]

    assert seen["stream"] is True
    assert seen["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_a_tool_call_streams_start_deltas_and_completion():
    events = await _drain(AnthropicProvider("k"), _req(tools=_tools(2)), [
        _chunk(tool_calls=[_delta_tool(id="tu_1", name="edit_file", arguments='{"pa')]),
        _chunk(tool_calls=[_delta_tool(arguments='th":"/m.jscad"}')]),
        _chunk(finish_reason="tool_calls"),
    ])

    assert [e.type for e in events] == [
        "tool_use_start", "tool_use_input_delta", "tool_use_input_delta",
        "tool_use_complete", "assistant_done",
    ]
    start = events[0].data
    assert (start["tool_use_id"], start["name"]) == ("tu_1", "edit_file")
    assert events[3].data["input"] == {"path": "/m.jscad"}
    assert events[-1].data["stop_reason"] == "tool_use"


@pytest.mark.asyncio
async def test_a_call_whose_id_and_name_arrive_apart_is_announced_once():
    """OpenAI splits identity across fragments; Anthropic-via-LiteLLM may not."""
    events = await _drain(AnthropicProvider("k"), _req(tools=_tools(1)), [
        _chunk(tool_calls=[_delta_tool(id="tu_1")]),
        _chunk(tool_calls=[_delta_tool(name="read_file")]),
        _chunk(tool_calls=[_delta_tool(arguments="{}")]),
        _chunk(finish_reason="tool_calls"),
    ])

    starts = [e for e in events if e.type == "tool_use_start"]
    assert len(starts) == 1
    assert (starts[0].data["tool_use_id"], starts[0].data["name"]) == ("tu_1", "read_file")


@pytest.mark.asyncio
async def test_parallel_tool_calls_are_kept_apart_by_index():
    events = await _drain(AnthropicProvider("k"), _req(tools=_tools(2)), [
        _chunk(tool_calls=[
            _delta_tool(index=0, id="a", name="read_file", arguments='{"p":1}'),
            _delta_tool(index=1, id="b", name="write_file", arguments='{"p":2}'),
        ]),
        _chunk(finish_reason="tool_calls"),
    ])

    completes = [e for e in events if e.type == "tool_use_complete"]
    assert [(c.data["tool_use_id"], c.data["input"]) for c in completes] == [
        ("a", {"p": 1}), ("b", {"p": 2}),
    ]


@pytest.mark.asyncio
async def test_truncated_tool_arguments_yield_empty_input_not_a_crash():
    """A dropped connection leaves half an object mid-stream. Empty input is a
    call the executor rejects cleanly; raising here kills the whole turn."""
    events = await _drain(AnthropicProvider("k"), _req(tools=_tools(1)), [
        _chunk(tool_calls=[_delta_tool(id="tu_1", name="edit_file", arguments='{"path": "/m')]),
        _chunk(finish_reason="tool_calls"),
    ])

    complete = next(e for e in events if e.type == "tool_use_complete")
    assert complete.data["input"] == {}


@pytest.mark.asyncio
async def test_a_streamed_thought_signature_survives_to_completion():
    events = await _drain(GeminiProvider("k"), _req(model="gemini-3-pro-preview", tools=_tools(1)), [
        _chunk(tool_calls=[_delta_tool(id="tu_1", name="read_file", arguments="{}",
                                       fields={"thought_signature": "AbC="})]),
        _chunk(finish_reason="tool_calls"),
    ])

    complete = next(e for e in events if e.type == "tool_use_complete")
    assert complete.data["provider_metadata"] == {"thought_signature": "AbC="}


@pytest.mark.asyncio
async def test_a_usage_only_final_chunk_does_not_crash_the_decoder():
    """LiteLLM's include_usage chunk carries no choices at all."""
    events = await _drain(AnthropicProvider("k"), _req(), [
        _chunk(text="hi"),
        SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=5, completion_tokens=1), model="m"),
    ])

    assert events[-1].type == "assistant_done"
    assert events[-1].data["input_tokens"] == 5


# ── the named providers ─────────────────────────────────────────────────────

@pytest.mark.parametrize("cls,expected", [
    (AnthropicProvider, "anthropic"),
    (OpenAIProvider, "openai"),
    (MoonshotProvider, "moonshot"),
    (GeminiProvider, "gemini"),
])
def test_provider_names_are_unchanged(cls, expected):
    """The registry, the BYO-key swap and every usage row key on this string."""
    provider = cls("k")
    assert provider.name() == expected
    assert isinstance(provider, LiteLLMProvider)
