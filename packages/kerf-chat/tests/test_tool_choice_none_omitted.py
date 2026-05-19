"""Regression: tool_choice must be OMITTED when no tools are supplied.

The Anthropic kwargs dict used to always include `tool_choice=tool_choice`
even when tool_choice stayed at None (because the request had no tools —
auto-title, readme-gen, any provider.complete() without tools). The
Anthropic SDK serialises Python None as JSON null, and the API now
rejects that with HTTP 400 "tool_choice: Input should be an object".

This surfaced to users as the assistant saying:
  "There seems to be a temporary server-side issue preventing file reads
  and writes right now..."
…because every auto-title call (and every no-tool LLM hop) failed
silently with that 400, and any retry path that fed the error back into
the chat surfaced it to the user verbatim.

Same defensive omission pattern as test_temperature_omitted.py.
"""
import ast
import pathlib
from unittest.mock import patch

from kerf_chat.llm import AnthropicProvider, CompleteRequest, ToolSpec

_LLM = (
    pathlib.Path(__file__).resolve().parents[1] / "src/kerf_chat/llm.py"
).read_text()


# ── Source-level guard ──────────────────────────────────────────────────


def test_tool_choice_is_conditionally_included():
    """The kwargs dict must only set tool_choice when it's not None."""
    assert "if tool_choice is not None:" in _LLM, (
        "tool_choice must be conditionally added to the Anthropic kwargs dict"
    )
    assert '_kw["tool_choice"] = tool_choice' in _LLM


def test_tools_also_conditionally_included():
    """Same defensive treatment for tools — Anthropic rejects tools=None too."""
    assert "if tools:" in _LLM
    assert '_kw["tools"] = tools' in _LLM


def test_no_unconditional_tool_choice_in_kw_dict():
    """The buggy 'tool_choice=tool_choice,' inside dict(...) must be gone."""
    # The bug was:
    #   _kw = dict(
    #     ...
    #     tool_choice=tool_choice,
    #   )
    # which always serialised tool_choice (even when None) into the request.
    # The fix moves tool_choice out of the dict() literal and into a
    # conditional _kw["tool_choice"] = ... assignment after the dict is built.
    inside_dict = _LLM.split("_kw = dict(", 1)[1].split(")", 1)[0]
    assert "tool_choice" not in inside_dict, (
        "tool_choice must not appear inside the dict(...) literal — "
        "it must be conditionally assigned afterwards"
    )
    assert "tools=" not in inside_dict, (
        "tools must not appear inside the dict(...) literal either"
    )


def test_llm_module_still_parses():
    ast.parse(_LLM)


# ── Behavioural: invoke the provider with a mocked Anthropic client ────


class _Blk:
    type = "text"
    text = "Sketcher Tutorial"


class _Usage:
    input_tokens = 5
    output_tokens = 3


class _Resp:
    content = [_Blk()]
    stop_reason = "end_turn"
    usage = _Usage()


def _fake_anthropic(captured):
    class _Messages:
        def create(self, **kw):
            captured.update(kw)
            return _Resp()

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    return _Client


def _complete(tools=None):
    captured: dict = {}
    req = CompleteRequest(
        model="claude-opus-4-7",
        system="You name CAD chat threads succinctly.",
        tools=tools or [],
    )
    with patch("anthropic.Anthropic", _fake_anthropic(captured)):
        AnthropicProvider(api_key="k", prompt_cache=False).complete(req)
    return captured


def test_no_tools_means_no_tool_choice_in_request():
    """Auto-title path: tools=[] must NOT send tool_choice to Anthropic.

    This is the exact prod regression — the auto-title call passed
    tools=[] but tool_choice=None reached the API, triggering 400
    "tool_choice: Input should be an object".
    """
    captured = _complete(tools=None)
    assert "tool_choice" not in captured
    assert "tools" not in captured


def test_with_tools_includes_object_tool_choice():
    """Normal chat path: tools=[...] sends a proper tool_choice OBJECT."""
    tools = [ToolSpec(name="read_file", description="read a file", input_schema={})]
    captured = _complete(tools=tools)
    # tool_choice present, and is the OBJECT form.
    assert "tool_choice" in captured
    assert captured["tool_choice"] == {"type": "auto"}
    # tools present.
    assert "tools" in captured
    assert len(captured["tools"]) == 1
    assert captured["tools"][0]["name"] == "read_file"
