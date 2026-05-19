"""Regression: GeminiProvider uses the modern `google.genai` SDK with
system_instruction on `types.GenerateContentConfig` (NOT a model
constructor or the generate_content() call).

Migrated 2026-05-19 from the deprecated `google-generativeai` package.

API contract pinned here:
  client = genai.Client(api_key=...)
  client.models.generate_content(
      model="...",
      contents=[types.Content(...)],
      config=types.GenerateContentConfig(
          system_instruction="...",
          tools=[types.Tool(...)],
          ...
      ),
  )

This test installs a fake `google.genai` module + types subpackage,
records the kwargs the provider passes, and asserts:
  1. genai.Client(api_key=...) is called with the key
  2. client.models.generate_content() is called
  3. system_instruction lives on the config object — NOT as a kwarg
     on generate_content() or generate_content_stream()
"""
from __future__ import annotations

import sys
import types as _types
from unittest.mock import MagicMock

from kerf_chat.llm import GeminiProvider, CompleteRequest


def _install_fake_genai():
    """Install a fake `google.genai` module that records the kwargs
    passed to Client + models.generate_content."""
    captured: dict = {"client_kwargs": None, "gen_kwargs": None, "config": None}

    # Fake types subpackage — only what GeminiProvider needs.
    fake_types = _types.ModuleType("google.genai.types")

    class _Part:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

        @classmethod
        def from_text(cls, text):
            p = cls()
            p.text = text
            return p

    class _Content:
        def __init__(self, role, parts):
            self.role = role
            self.parts = parts

    class _FunctionCall:
        def __init__(self, name, args):
            self.name = name
            self.args = args

    class _FunctionResponse:
        def __init__(self, name, response):
            self.name = name
            self.response = response

    class _FunctionDeclaration:
        def __init__(self, name, description, parameters):
            self.name = name
            self.description = description
            self.parameters = parameters

    class _Tool:
        def __init__(self, function_declarations):
            self.function_declarations = function_declarations

    class _GenerateContentConfig:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
            captured["config"] = self

    fake_types.Part = _Part
    fake_types.Content = _Content
    fake_types.FunctionCall = _FunctionCall
    fake_types.FunctionResponse = _FunctionResponse
    fake_types.FunctionDeclaration = _FunctionDeclaration
    fake_types.Tool = _Tool
    fake_types.GenerateContentConfig = _GenerateContentConfig

    class _Resp:
        candidates = []
        usage_metadata = _types.SimpleNamespace(
            prompt_token_count=0, candidates_token_count=0,
        )

    class _Models:
        def generate_content(self, **kwargs):
            captured["gen_kwargs"] = kwargs
            return _Resp()

        def generate_content_stream(self, **kwargs):
            captured["gen_kwargs"] = kwargs
            return iter([])

    class _Client:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = _Models()

    fake_genai = _types.ModuleType("google.genai")
    fake_genai.Client = _Client
    fake_genai.types = fake_types

    google_pkg = _types.ModuleType("google")
    google_pkg.genai = fake_genai

    sys.modules["google"] = google_pkg
    sys.modules["google.genai"] = fake_genai
    sys.modules["google.genai.types"] = fake_types

    return captured


def _restore(saved: dict):
    for k in ("google", "google.genai", "google.genai.types"):
        if saved.get(k) is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = saved[k]


def _saved():
    return {
        k: sys.modules.get(k)
        for k in ("google", "google.genai", "google.genai.types")
    }


def test_uses_new_genai_client_with_api_key():
    saved = _saved()
    captured = _install_fake_genai()
    try:
        GeminiProvider(api_key="test-key").complete(
            CompleteRequest(model="gemini-3-flash-preview", system="x", messages=[])
        )
    finally:
        _restore(saved)

    assert captured["client_kwargs"] == {"api_key": "test-key"}, (
        f"genai.Client must be called with api_key=...; got {captured['client_kwargs']}"
    )


def test_system_instruction_lives_on_config_not_generate_content():
    saved = _saved()
    captured = _install_fake_genai()
    try:
        GeminiProvider(api_key="k").complete(
            CompleteRequest(
                model="gemini-3-flash-preview",
                system="You are a CAD assistant.",
                messages=[],
            )
        )
    finally:
        _restore(saved)

    assert captured["config"] is not None, "GenerateContentConfig was never built"
    assert captured["config"].system_instruction == "You are a CAD assistant.", (
        "system_instruction MUST live on types.GenerateContentConfig"
    )

    gk = captured["gen_kwargs"] or {}
    assert "system_instruction" not in gk, (
        "system_instruction must NOT be a direct kwarg on generate_content()"
    )
    # The config object MUST be passed to generate_content() under `config=`.
    assert "config" in gk and gk["config"] is captured["config"], (
        "generate_content() must receive config=<GenerateContentConfig>"
    )


def test_blank_system_does_not_set_system_instruction_on_config():
    """If the request has no system prompt, we omit the field entirely
    rather than passing an empty string."""
    saved = _saved()
    captured = _install_fake_genai()
    try:
        GeminiProvider(api_key="k").complete(
            CompleteRequest(model="gemini-3-flash-preview", system="", messages=[])
        )
    finally:
        _restore(saved)

    # No system → config might be None entirely, or present without
    # system_instruction. Either is fine; the bad case is system="" on
    # the config (would override an inherited default).
    cfg = captured["config"]
    if cfg is not None:
        assert getattr(cfg, "system_instruction", None) is None


def test_tools_become_genai_tool_objects_on_config():
    from kerf_chat.llm import ToolSpec
    saved = _saved()
    captured = _install_fake_genai()
    try:
        GeminiProvider(api_key="k").complete(
            CompleteRequest(
                model="gemini-3-flash-preview",
                system="x",
                tools=[ToolSpec(
                    name="read_file",
                    description="read a file",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                )],
                messages=[],
            )
        )
    finally:
        _restore(saved)

    cfg = captured["config"]
    assert cfg is not None and getattr(cfg, "tools", None), (
        "tools list must live on GenerateContentConfig.tools"
    )
    tool = cfg.tools[0]
    assert hasattr(tool, "function_declarations")
    assert tool.function_declarations[0].name == "read_file"


def test_old_generativeai_module_is_not_imported():
    """Don't regress to the deprecated `google.generativeai` package."""
    saved = _saved()
    captured = _install_fake_genai()
    try:
        GeminiProvider(api_key="k").complete(
            CompleteRequest(model="gemini-3-flash-preview", system="x", messages=[])
        )
    finally:
        _restore(saved)
    # If the provider tried to import the old package it would have
    # raised a ModuleNotFoundError in this test env (we only installed
    # google.genai). The fact that we got here cleanly is the proof.
    assert captured["client_kwargs"] is not None
