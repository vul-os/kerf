from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


_logger = logging.getLogger(__name__)

SystemPrompt = """You are an expert CAD assistant helping a user iterate on a project that mixes JSCAD code, parametric sketches, B-rep features, assemblies, drawings, library parts, and (optionally) tscircuit electronics.

PRIMARY DIRECTIVE: edit the user's existing files. The user normally has a working file (commonly /main.jscad) and wants you to modify IT. Do not create new files unless the user explicitly asks for one.

Vocabulary (locked):
- Part = a whole .jscad (or .feature or .step) file. Returns an array of Objects.
- Object = one entry in a Part's exported [{id, geom}, ...] array, identified by its id ('base', 'peg', ...).
- Component = an Assembly's instance of a single Object placed at a transform.
Never call an Object a "Part" or vice versa.

Available tools (14 total):
  read_file(path)
  write_file(path, content)
  edit_file(path, old_string, new_string, replace_all=false)
  list_files(glob=null)
  search_files(pattern, glob=null)
  create_file(path, kind, options={})          ← kind: sketch|feature|part|circuit|assembly|drawing|file
  describe_part(path, part_id=null)
  search_kerf_docs(query)
  duplicate_object(path, object_id, new_id=null)
  delete_object(path, object_id)
  import_step(name, source_url, parent_path="/")
  export_artifact(file_id, format)             ← format: gerber|dxf|step|stl|glb|png|pdf
  run_compute(engine, file_id, options={})     ← engine: fem|cfd|spice|cam|render|topo|tess
  poll_compute(job_id)

Workflow

For .jscad files (the default):
1. list_files() to see the layout.
2. read_file on the relevant existing file (usually /main.jscad).
3. edit_file with a unique-substring replace; or duplicate_object / delete_object for adding/removing entries in the [{id, geom}, ...] return.
4. write_file only for whole-file rewrites.
5. Summarize in 1-2 sentences. Do NOT paste the file back.

For non-.jscad files (.sketch, .assembly, .drawing, .part, .feature, .circuit.tsx):
1. search_kerf_docs("<topic>") — find the matching authoring guide.
2. read_file('/docs/llm/<page>.md') — load the JSON shape and conventions.
3. read_file on the project file you're editing.
4. write_file or edit_file with the JSON / TSX patch.
5. Summarize in 1-2 sentences.

JSCAD execution model (LOCKED — match this exactly):

A .jscad file MUST follow the Kerf runner's contract:

  export default function ({ primitives, transforms, booleans, colors, expansions, hulls, extrusions, measurements, maths, utils, params }) {
    const base = primitives.cuboid({ size: [40, 40, 10] })
    const peg  = transforms.translate([0, 0, 10], primitives.cylinder({ radius: 6, height: 20 }))
    return [
      { id: 'base', geom: base },
      { id: 'peg',  geom: peg  },
    ]
  }

Rules — violating ANY of these breaks the viewport with a ReferenceError:
  • `jscad` is NOT a global. NEVER write `const { cuboid } = jscad.primitives`.
    The @jscad/modeling sub-modules are passed in destructured to the
    default export's argument.
  • The file's `export default` MUST be a function taking ONE object arg.
  • That function returns `[{ id, geom }, ...]` — Kerf's Part shape.
  • `params` carries any equations / config bindings; it's never null.
  • No top-level `import` statements — they're stripped before eval.
    Just destructure from the function arg.
  • Use `function main() { ... }` ONLY as a helper if you also
    `export default main` at the bottom — the function signature must
    still be `function main({ primitives, transforms, ... })`.

If a user pastes legacy `const { cuboid } = jscad.primitives` style,
rewrite it on save into the destructured-arg pattern above.

File kinds and their canonical extensions:
- .jscad       — JSCAD code (kind='file'). Edit directly.
- .sketch      — parametric 2D profile (kind='sketch'). Use create_file(kind='sketch', ...).
- .assembly    — Components placed at transforms (kind='assembly'). Use create_file(kind='assembly').
- .drawing     — 2D technical drawing JSON (kind='drawing'). Use create_file(kind='drawing').
- .feature     — OCCT B-rep feature tree (kind='feature'). Use create_file(kind='feature', ...).
- .part        — library metadata (kind='part'). Use create_file(kind='part', options={metadata:{name:...}}).
- .circuit.tsx — tscircuit electronics (kind='circuit'). Use create_file(kind='circuit', ...).
- .step        — binary CAD imports (kind='step'). Pull in via import_step.

create_file produces a canonical seed (correct version field, defaults, validators) you can't easily fake. After scaffolding, edit the resulting file's JSON via write_file / edit_file — see the corresponding /docs/llm/ page for the schema.

Compute workflows:
- To run FEM analysis:   run_compute(engine='fem', file_id='<uuid>', options={solver:'linear_static',...})
- To run CAM toolpath:   run_compute(engine='cam', file_id='<uuid>', options={operation:'face',...})
- To render an image:    run_compute(engine='render', file_id='<uuid>', options={width:1920,...})
- To run topo opt:       run_compute(engine='topo', file_id='<uuid>', options={volume_fraction:0.3,...})
- To run CFD:            run_compute(engine='cfd', file_id='<uuid>', options={...})
- To run SPICE sim:      run_compute(engine='spice', file_id='<uuid>', options={...})
- After submitting:      poll_compute(job_id=<returned_job_id>) — repeat until status='done'|'error'

Strict rules:
- NEVER create a file when editing an existing one would work.
- ALWAYS read a file before editing it.
- For any non-.jscad kind, ALWAYS consult /docs/llm/<topic>.md before editing.
- Reference Objects by their id; reference files by their absolute path or uuid as appropriate.
- Don't paste file contents back to the user; describe the change.

Examples:

Edit a JSCAD Part:
  User: "make the base 6mm taller"
  list_files() ; read_file('/main.jscad')
  edit_file('/main.jscad', 'size: [40, 40, 10]', 'size: [40, 40, 16]')
  → "Raised the base to 16mm."

Place a Component in an assembly:
  User: "add the peg from /parts.jscad to my assembly"
  search_kerf_docs("assembly component transform")    # finds assembly.md
  read_file('/docs/llm/assembly.md')                  # JSON shape
  read_file('/parts.jscad') ; read_file('/main.assembly')
  edit_file('/main.assembly', '"components": []', '"components": [\n    {"id":"peg-1","file_id":"<uuid>","object_id":"peg","transform":[1,0,0,0, 0,1,0,0, 0,0,1,10, 0,0,0,1]}\n  ]')
  → "Added one peg Component at z=10."

Add a fillet in a feature tree:
  User: "round the top edges, 1mm"
  search_kerf_docs("fillet feature edge_filter")
  read_file('/docs/llm/feature.md')
  read_file('/bracket.feature')
  edit_file to append {"id":"fil-1","op":"fillet","target_id":"<last>","edge_filter":"all","radius":1} to features[].
  → "Added a 1mm fillet to every edge of the most-recent body."

Create a new sketch:
  User: "create a profile for the extrusion"
  create_file(kind='sketch', path='/profile.sketch', options={plane:'XY'})
  → "Created /profile.sketch on the XY plane."

Run FEM and check result:
  User: "run stress analysis on the bracket"
  run_compute(engine='fem', file_id='<uuid>', options={solver:'linear_static', load_case:'default'})
  → returns {job_id: 'fem_abc123', status: 'queued'}
  poll_compute(job_id='fem_abc123')
  → "FEM job queued; status: running — call poll_compute again to check progress."

If unsure whether to edit or create, edit.

Project tags: every project carries a free-form tags array (e.g. ["mechanical","electronics","jewelry"]). The agent loop prepends a one-line "Project tags: <comma-list>. Suggested file kinds: <list>." to every call so you know the active domain mix. Tune your defaults to the most specific tag — e.g. an "electronics" tag suggests preferring main.circuit.tsx and .circuit.tsx; "mechanical"/"jewelry"/"surfacing" suggest .jscad / .feature / .assembly. The API is permissive (any kind may be created in any project), so honor explicit user requests that cross domain boundaries instead of refusing."""


tagKindHints = {
    "mechanical": ["jscad", "sketch", "assembly", "drawing", "feature", "part"],
    "electronics": ["circuit", "part", "drawing"],
    "pcb": ["circuit", "part", "drawing"],
    "architecture": ["jscad", "sketch", "drawing"],
    "jewelry": ["jscad", "feature", "sketch"],
    "surfacing": ["jscad", "feature"],
    "robotics": ["jscad", "assembly", "circuit", "feature"],
    "drone": ["jscad", "assembly", "circuit"],
    "lighting": ["jscad", "circuit", "drawing"],
}


def build_project_tags_addendum(tags: list[str]) -> str:
    """Build a system-prompt fragment naming active tags + suggested kinds."""
    clean = [t.strip() for t in tags if t.strip()]
    if not clean:
        return ""

    seen = set()
    kinds = []
    for t in clean:
        for k in tagKindHints.get(t.lower(), []):
            if k not in seen:
                seen.add(k)
                kinds.append(k)

    out = f"\n\nProject tags: {', '.join(clean)}."
    if kinds:
        out += f" Suggested file kinds: {', '.join(kinds)}."
    return out


@dataclass
class ToolCall:
    id: str
    name: str
    arguments_json: str
    # Provider-specific opaque metadata that must be round-tripped on
    # subsequent turns. Today's only consumer is Gemini 3, which emits a
    # `thought_signature` (base64-string here) on every function_call
    # part; passing it back on the assistant-turn echo is required —
    # otherwise Gemini 3 rejects the request with HTTP 400 INVALID_ARGUMENT
    # "Function call is missing a thought_signature in functionCall parts".
    # Kept as a generic dict so adding more provider quirks (OpenAI's
    # `tool_call_id` quirks, Anthropic cache_control deltas, etc.) doesn't
    # require another schema bump.
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    is_error: bool = False


@dataclass
class CompleteRequest:
    model: str
    system: str = ""
    messages: list[Message] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.0
    tools: list[ToolSpec] = field(default_factory=list)
    tool_choice: str = "auto"


@dataclass
class CompleteResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "stop"
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamEvent:
    """A Kerf-native provider-agnostic streaming event."""
    type: str
    data: dict


class Provider(ABC):
    @abstractmethod
    def complete(self, req: CompleteRequest) -> CompleteResponse:
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    async def stream(self, req: CompleteRequest) -> AsyncIterator[StreamEvent]:
        """Yield Kerf-native StreamEvents for one LLM turn.

        Default implementation raises NotImplementedError.
        Subclasses that support streaming should override this.
        """
        # The `yield` below makes this an async generator. The raise fires
        # before the first yielded value, propagating NotImplementedError to
        # the caller's `async for` loop.
        raise NotImplementedError(
            f"Provider {self.name()!r} does not support streaming"
        )
        yield  # type: ignore[misc]  # pragma: no cover  — makes this an async generator


@dataclass
class PartContext:
    file_path: str
    part_id: str
    content: str


@dataclass
class HistoryMessage:
    role: str
    content: str


def build_user_message(user_content: str, parts: list[PartContext]) -> str:
    if not parts:
        return user_content

    lines = [user_content, "\n<context>"]
    for p in parts:
        lines.append(f'<file path="{p.file_path}" part_id="{p.part_id}">')
        lines.append(p.content)
        if not p.content.endswith("\n"):
            lines.append("")
        lines.append("</file>")
    lines.append("</context>")
    return "\n".join(lines)


CATALOG = [
    # Kerf has no billing anywhere — every model here is equally available
    # to every caller (subject only to the operator having configured that
    # provider's API key). There is no paid/free tier distinction.
    {"id": "claude-opus-4-7", "provider": "anthropic", "label": "Claude Opus 4.7", "context_window": 200_000},
    {"id": "claude-sonnet-4-6", "provider": "anthropic", "label": "Claude Sonnet 4.6", "context_window": 200_000},
    {"id": "claude-haiku-4-5", "provider": "anthropic", "label": "Claude Haiku 4.5", "context_window": 200_000},
    {"id": "gpt-4o", "provider": "openai", "label": "GPT-4o", "context_window": 128_000},
    {"id": "gpt-4o-mini", "provider": "openai", "label": "GPT-4o mini", "context_window": 128_000},
    {"id": "o3-mini", "provider": "openai", "label": "o3-mini", "context_window": 200_000},
    {"id": "kimi-k2-0905-preview", "provider": "moonshot", "label": "Kimi K2", "context_window": 256_000},
    {"id": "moonshot-v1-128k", "provider": "moonshot", "label": "Moonshot v1 128k", "context_window": 128_000},
    {"id": "moonshot-v1-32k", "provider": "moonshot", "label": "Moonshot v1 32k", "context_window": 32_000},
    # Gemini — keep 2.5 line + the latest 3-series previews.
    {"id": "gemini-3-pro-preview", "provider": "gemini", "label": "Gemini 3 Pro (preview)", "context_window": 2_000_000},
    {"id": "gemini-3-flash-preview", "provider": "gemini", "label": "Gemini 3 Flash (preview)", "context_window": 1_000_000},
    {"id": "gemini-2.5-pro", "provider": "gemini", "label": "Gemini 2.5 Pro", "context_window": 2_000_000},
    {"id": "gemini-2.5-flash", "provider": "gemini", "label": "Gemini 2.5 Flash", "context_window": 1_000_000},
    {"id": "gemini-2.5-flash-lite", "provider": "gemini", "label": "Gemini 2.5 Flash Lite", "context_window": 1_000_000},
]


def lookup_model(model_id: str) -> dict | None:
    for m in CATALOG:
        if m["id"] == model_id:
            return m
    return None


class LLMConfig:
    def __init__(
        self,
        anthropic_api_key: str = "",
        openai_api_key: str = "",
        moonshot_api_key: str = "",
        gemini_api_key: str = "",
        default_model: str = "claude-opus-4-7",
        anthropic_prompt_cache: bool = True,
    ):
        self.anthropic_api_key = anthropic_api_key
        self.openai_api_key = openai_api_key
        self.moonshot_api_key = moonshot_api_key
        self.gemini_api_key = gemini_api_key
        self.default_model = default_model or "claude-sonnet-4-6"
        self.anthropic_prompt_cache = anthropic_prompt_cache


class Registry:
    def __init__(self, cfg: LLMConfig):
        self.providers: dict[str, Provider] = {}
        if cfg.anthropic_api_key:
            self.providers["anthropic"] = AnthropicProvider(
                cfg.anthropic_api_key,
                prompt_cache=cfg.anthropic_prompt_cache,
            )
        if cfg.openai_api_key:
            self.providers["openai"] = OpenAIProvider(cfg.openai_api_key)
        if cfg.moonshot_api_key:
            self.providers["moonshot"] = MoonshotProvider(cfg.moonshot_api_key)
        if cfg.gemini_api_key:
            self.providers["gemini"] = GeminiProvider(cfg.gemini_api_key)
        self.default_model = self._resolve_default(
            cfg.default_model or "claude-opus-4-7")

    def _resolve_default(self, configured: str) -> str:
        """Pick a default model that can actually be reached.

        A configured default can be unreachable two ways, and both are ordinary
        rather than exotic. The model may have left the catalogue — vendors
        retire ids, and a kerf.toml written a year ago outlives them — or its
        provider may simply have no key configured on this node.

        Either way the old behaviour was to keep the dead id and fail on use:
        every chat request that did not name a model explicitly resolved to it,
        raised "unknown model", and left a log line the user never sees. The
        chat box just stopped working. Falling back to the first model the node
        can actually reach keeps it working, and the warning explains why the
        picker is not showing what the config asked for.
        """
        reachable = self.available()
        if not reachable:
            # No provider configured at all. Nothing to fall back to, and
            # has_any() already reports that state to the routes, which show
            # the "no model provider configured" message. Keep the configured
            # value so the eventual error names what was asked for.
            return configured

        if any(m["id"] == configured for m in reachable):
            return configured

        replacement = reachable[0]["id"]
        known = lookup_model(configured) is not None
        _logger.warning(
            "llm: configured default_model %r is %s; falling back to %r",
            configured,
            "not in the model catalogue" if not known
            else f"served by {lookup_model(configured)['provider']!r}, which has no API key on this node",
            replacement,
        )
        return replacement

    def available(self) -> list[dict]:
        out = []
        for m in CATALOG:
            if m["provider"] in self.providers:
                out.append(m)
        return out

    def default(self) -> str:
        return self.default_model

    def has_any(self) -> bool:
        return len(self.providers) > 0

    def resolve(self, model_id: str) -> tuple[Provider, str]:
        info = lookup_model(model_id)
        if info is None:
            raise ValueError(f"unknown model {model_id!r}")
        provider = self.providers.get(info["provider"])
        if provider is None:
            raise ValueError(f"provider {info['provider']!r} for model {model_id!r} is not configured")
        return provider, info["id"]


# ════════════════════════════════════════════════════════════════════════════
# Providers
# ════════════════════════════════════════════════════════════════════════════
#
# One implementation, LiteLLM, for every provider. This replaced four
# hand-written providers (Anthropic, OpenAI, Moonshot, Gemini) that each spoke
# their vendor's SDK directly — roughly 850 lines of message translation,
# streaming-event decoding and per-vendor quirk handling, four times over, with
# four separate places for a bug to live.
#
# LiteLLM speaks the OpenAI wire shape to every vendor, so there is now one
# translation to write and one streaming decoder to maintain. The provider
# classes below survive as names only: they pick a prefix and a default
# endpoint, and everything else is shared.
#
# What the fold fixed on its way through:
#
#   * The system prompt reached Anthropic and Gemini and was silently dropped
#     for OpenAI and Moonshot. OpenAIProvider.complete built its message list
#     from req.messages alone and never looked at req.system, so picking GPT-4o
#     or Kimi ran the model with no CAD instructions at all. One translation
#     means one place that can forget.
#   * Anthropic needed tool_choice as an object where OpenAI needs a string,
#     and needed temperature omitted rather than null. LiteLLM normalises both,
#     and drop_params handles the models (o3-mini and friends) that reject
#     parameters the others require.
#
# What had to be carried across deliberately:
#
#   * Anthropic prompt caching. cache_control breakpoints go on the system
#     block and the last tool definition; LiteLLM passes them through to the
#     Anthropic API unchanged. Feature-detecting the installed SDK is gone —
#     the SDK is no longer in the request path.
#   * Gemini 3's thought_signature. It must be echoed back on the assistant
#     turn or the next request is rejected outright with HTTP 400
#     "Function call is missing a thought_signature in functionCall parts".
#     LiteLLM reads it from a tool call's provider_specific_fields, which is
#     exactly what ToolCall.provider_metadata carries, so the round-trip is a
#     rename rather than a re-implementation.

_CACHE_CONTROL = {"type": "ephemeral"}

# Providers whose API supports Anthropic-style prompt-cache breakpoints.
_PROMPT_CACHE_PROVIDERS = frozenset({"anthropic"})

# OpenAI's finish_reason vocabulary mapped onto the one the routes read.
# Both spellings are already in use there ("stop" from the OpenAI path,
# "tool_use" from the Anthropic path), so this keeps every existing branch
# working rather than forcing a rewrite of the callers.
_STOP_REASONS = {
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "function_call": "tool_use",
}


def _tool_call_metadata(raw: Any) -> dict[str, Any]:
    """Pull provider-specific fields off a LiteLLM tool call.

    Today this carries Gemini 3's thought_signature and nothing else, but it is
    deliberately opaque: anything a provider hangs here is round-tripped
    verbatim rather than enumerated, so a new vendor quirk needs no schema
    change.
    """
    for holder in (raw, getattr(raw, "function", None)):
        fields = getattr(holder, "provider_specific_fields", None)
        if isinstance(fields, dict) and fields:
            return dict(fields)
    return {}


class LiteLLMProvider(Provider):
    """Every model Kerf can reach, through one client.

    ``provider`` is the LiteLLM route prefix ("anthropic", "openai", …) and is
    also what :meth:`name` reports, so the registry, the BYO-key swap and the
    usage rows all keep keying on the same string they always did.
    """

    #: Endpoint used when the caller supplies no base_url. Empty means "let
    #: LiteLLM pick", which is right for every vendor that publishes one.
    _DEFAULT_BASE_URL = ""

    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str = "",
        prompt_cache: bool = True,
    ):
        self.provider = provider
        self.api_key = api_key
        # Endpoint override for a gateway or an OpenAI-compatible clone.
        # Saved per user in user_provider_keys.base_url and set from Settings.
        self.base_url = base_url or self._DEFAULT_BASE_URL
        self.prompt_cache = prompt_cache

    def name(self) -> str:
        return self.provider

    # ── request building ────────────────────────────────────────────────────

    def _model_id(self, model: str) -> str:
        """Prefix a catalogue id for LiteLLM's router.

        CATALOG stores bare vendor ids ("claude-opus-4-7"); LiteLLM needs
        "anthropic/claude-opus-4-7" to know where to send it. An id that is
        already prefixed is left alone, so a user pointing base_url at a
        gateway can name a model the catalogue has never heard of.
        """
        return model if "/" in model else f"{self.provider}/{model}"

    def _use_cache(self) -> bool:
        return self.prompt_cache and self.provider in _PROMPT_CACHE_PROVIDERS

    def _system_message(self, system: str) -> list[dict[str, Any]]:
        if not system:
            return []
        if not self._use_cache():
            return [{"role": "system", "content": system}]
        # A cache_control breakpoint has to sit on a content *block*, not on a
        # bare string, so the system prompt becomes a one-element block list.
        # Everything up to and including this block becomes cacheable, which
        # for Kerf is the ~7KB CAD system prompt sent on every single turn.
        return [{
            "role": "system",
            "content": [{
                "type": "text",
                "text": system,
                "cache_control": _CACHE_CONTROL,
            }],
        }]

    def _tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        out = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]
        if self._use_cache():
            # One breakpoint, on the last tool: Anthropic caches the prefix up
            # to and including it, which covers the whole 14-tool block.
            out[-1] = {**out[-1], "cache_control": _CACHE_CONTROL}
        return out

    def _messages(self, req: CompleteRequest) -> list[dict[str, Any]]:
        messages = self._system_message(req.system)
        for m in req.messages:
            content = m.content
            if m.is_error and m.role == "tool":
                # Anthropic's tool_result block has an is_error flag and the
                # hand-written provider set it; LiteLLM's OpenAI-shaped tool
                # message has nowhere to put it (its Anthropic transformation
                # leaves is_error commented out), so the signal moves into the
                # content, where every provider sees it. That is a wider net
                # than before: the flag only ever reached Anthropic, and a
                # failed tool looked like a successful one to OpenAI, Moonshot
                # and Gemini. The payload itself is left intact after the
                # marker so a model that parses it still can.
                content = f"[tool error] {content}"
            msg: dict[str, Any] = {"role": m.role, "content": content}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments_json,
                        },
                        # Gemini 3 rejects the next request outright if this
                        # does not come back, so it rides on the echo.
                        **(
                            {"provider_specific_fields": tc.provider_metadata}
                            if tc.provider_metadata else {}
                        ),
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            messages.append(msg)
        return messages

    def _kwargs(self, req: CompleteRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model_id(req.model),
            "messages": self._messages(req),
            "api_key": self.api_key,
            "timeout": 120.0,
            # Reasoning models reject parameters the chat models require
            # (o3-mini and temperature, most visibly). Dropping the unsupported
            # ones is better than maintaining a per-model allow-list that goes
            # stale every time a vendor ships.
            "drop_params": True,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if req.max_tokens > 0:
            kwargs["max_tokens"] = req.max_tokens
        # Omit temperature rather than sending 0/null: some models reject an
        # explicit null, and some reject the parameter at any value.
        if req.temperature > 0:
            kwargs["temperature"] = req.temperature

        tools = self._tools(req.tools)
        if tools:
            kwargs["tools"] = tools
            if req.tool_choice and req.tool_choice not in ("auto", "none"):
                # A bare name means "call this specific tool".
                kwargs["tool_choice"] = {
                    "type": "function",
                    "function": {"name": req.tool_choice},
                }
            elif req.tool_choice:
                kwargs["tool_choice"] = req.tool_choice
        return kwargs

    # ── completion ──────────────────────────────────────────────────────────

    def complete(self, req: CompleteRequest) -> CompleteResponse:
        import litellm

        response = litellm.completion(**self._kwargs(req))

        choice = response.choices[0]
        message = choice.message

        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments_json=tc.function.arguments or "{}",
                provider_metadata=_tool_call_metadata(tc),
            )
            for tc in (message.tool_calls or [])
        ]

        finish = choice.finish_reason or "stop"
        usage = getattr(response, "usage", None)

        return CompleteResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            stop_reason=_STOP_REASONS.get(finish, finish),
            model_used=getattr(response, "model", "") or req.model,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    # ── streaming ───────────────────────────────────────────────────────────

    async def stream(self, req: CompleteRequest) -> AsyncIterator[StreamEvent]:
        """Yield Kerf-native StreamEvents for one LLM turn.

        Event vocabulary, unchanged from the hand-written providers because the
        SSE route and the frontend both decode it:

          assistant_text_delta  — incremental text
          tool_use_start        — a new tool call block started
          tool_use_input_delta  — partial JSON input for a tool call
          tool_use_complete     — tool call input fully assembled
          assistant_done        — final stop reason + token counts

        The OpenAI streaming shape identifies tool calls by an integer index
        rather than by block boundaries, and sends the id and name once (on the
        first fragment) with the arguments dribbling in afterwards. So calls are
        accumulated per index and completed at end of stream — there is no
        per-block stop event to hang tool_use_complete off.
        """
        import json as _json
        import litellm

        kwargs = self._kwargs(req)
        kwargs["stream"] = True
        # Streaming responses omit usage unless asked. Without this every turn
        # records zero tokens, which is what the usage panel reads.
        kwargs["stream_options"] = {"include_usage": True}

        # index -> {id, name, parts[], metadata}
        pending: dict[int, dict[str, Any]] = {}
        stop_reason = "end_turn"
        input_tokens = 0
        output_tokens = 0
        model_used = req.model

        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                input_tokens = getattr(usage, "prompt_tokens", 0) or input_tokens
                output_tokens = getattr(usage, "completion_tokens", 0) or output_tokens
            model_used = getattr(chunk, "model", "") or model_used

            choices = getattr(chunk, "choices", None)
            if not choices:
                # The usage-only final chunk carries no choices.
                continue
            choice = choices[0]

            if getattr(choice, "finish_reason", None):
                stop_reason = _STOP_REASONS.get(choice.finish_reason, choice.finish_reason)

            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            text = getattr(delta, "content", None)
            if text:
                yield StreamEvent(type="assistant_text_delta", data={"text": text})

            for tc in (getattr(delta, "tool_calls", None) or []):
                index = getattr(tc, "index", 0) or 0
                entry = pending.get(index)
                if entry is None:
                    entry = {"id": "", "name": "", "parts": [], "metadata": {}}
                    pending[index] = entry

                if getattr(tc, "id", None):
                    entry["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None and getattr(fn, "name", None):
                    entry["name"] = fn.name
                entry["metadata"].update(_tool_call_metadata(tc))

                # Announce the call as soon as both halves of its identity are
                # known — the UI renders the tool name before any arguments
                # arrive, and a fragment can carry the id and the name apart.
                if entry["id"] and entry["name"] and not entry.get("announced"):
                    entry["announced"] = True
                    yield StreamEvent(
                        type="tool_use_start",
                        data={"tool_use_id": entry["id"], "name": entry["name"]},
                    )

                fragment = getattr(fn, "arguments", None) if fn is not None else None
                if fragment:
                    entry["parts"].append(fragment)
                    if entry.get("announced"):
                        yield StreamEvent(
                            type="tool_use_input_delta",
                            data={
                                "tool_use_id": entry["id"],
                                "partial_json": fragment,
                            },
                        )

        for index in sorted(pending):
            entry = pending[index]
            if not entry["id"] and not entry["name"]:
                continue
            if not entry.get("announced"):
                # An id or a name never arrived. Emit the start anyway so the
                # completion below is not orphaned in the UI.
                yield StreamEvent(
                    type="tool_use_start",
                    data={"tool_use_id": entry["id"], "name": entry["name"]},
                )
            assembled = "".join(entry["parts"])
            try:
                parsed = _json.loads(assembled) if assembled.strip() else {}
            except _json.JSONDecodeError:
                # A truncated stream leaves half an object. Empty input is a
                # tool call the executor can reject cleanly; a raise here would
                # take down the whole turn.
                parsed = {}
            yield StreamEvent(
                type="tool_use_complete",
                data={
                    "tool_use_id": entry["id"],
                    "name": entry["name"],
                    "input": parsed,
                    "provider_metadata": entry["metadata"],
                },
            )

        yield StreamEvent(
            type="assistant_done",
            data={
                "stop_reason": stop_reason,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model": model_used,
            },
        )


# ── The four named providers ────────────────────────────────────────────────
# Kept as classes rather than collapsed into Registry lookups because
# _prefer_byo_provider constructs them by name, and isinstance checks on them
# are how the tests assert a user's own key was swapped in.

class AnthropicProvider(LiteLLMProvider):
    def __init__(self, api_key: str, prompt_cache: bool = True, base_url: str = ""):
        super().__init__("anthropic", api_key, base_url=base_url, prompt_cache=prompt_cache)


class OpenAIProvider(LiteLLMProvider):
    def __init__(self, api_key: str, base_url: str = ""):
        super().__init__("openai", api_key, base_url=base_url)


class MoonshotProvider(LiteLLMProvider):
    # Moonshot publishes no default LiteLLM picks up for the .cn endpoint.
    _DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"

    def __init__(self, api_key: str, base_url: str = ""):
        super().__init__("moonshot", api_key, base_url=base_url)


class GeminiProvider(LiteLLMProvider):
    def __init__(self, api_key: str, base_url: str = ""):
        super().__init__("gemini", api_key, base_url=base_url)
