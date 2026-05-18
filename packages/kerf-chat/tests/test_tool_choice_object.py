"""Regression: Anthropic tool_choice must be an OBJECT, not a string.

Every opus chat turn failed with HTTP 400
"tool_choice: Input should be an object" because the Anthropic path
passed the bare strings "auto"/"none". Anthropic requires
{"type": "auto"} / {"type": "none"} / {"type": "tool", "name": ...}.
"""
import pathlib
import re

_LLM = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src/kerf_chat/llm.py"
).read_text()


def _anthropic_tool_choice_block() -> str:
    # The tool_choice mapping just before the Anthropic request.
    m = re.search(
        r"tool_choice = None\n.*?\n(?=\s*messages = \[\])",
        _LLM, re.S,
    )
    assert m, "could not locate the Anthropic tool_choice block"
    return m.group(0)


def test_no_bare_string_tool_choice():
    block = _anthropic_tool_choice_block()
    assert 'tool_choice = "auto"' not in block, (
        'tool_choice = "auto" (bare string) → Anthropic 400'
    )
    assert 'tool_choice = "none"' not in block


def test_uses_object_forms():
    block = _anthropic_tool_choice_block()
    assert '{"type": "auto"}' in block
    assert '{"type": "none"}' in block
    assert '{"type": "tool", "name": req.tool_choice}' in block
