# LLM tool authoring

How to write a tool that the Kerf LLM agent can call. Tools are plain async
Python functions that read from or write to a project's files and database.

## The registry

`kerf-chat` owns a global `Registry` list in
`kerf_chat.tools.registry`. Every tool module registers into it by importing
`register` and decorating a handler function.

```python
from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
```

## ToolSpec

```python
@dataclass
class ToolSpec:
    name: str          # unique across all plugins; the LLM calls this name
    description: str   # shown to the LLM; be precise about what it does
    input_schema: dict # JSON Schema object describing the parameters
```

Example:

```python
read_widget_spec = ToolSpec(
    name="read_widget",
    description="Read a .widget file by absolute path and return its parsed JSON.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the .widget file, e.g. /parts/bracket.widget",
            },
        },
        "required": ["path"],
    },
)
```

## The @register decorator

```python
@register(spec, write=False)
async def run_read_widget(ctx: ProjectCtx, args: bytes) -> str:
    ...
```

| Parameter | Meaning |
|-----------|---------|
| `spec` | The `ToolSpec` declared above |
| `write=False` | Read-only tool — available to all roles including viewer. Set `write=True` for tools that mutate project state. |

`write=True` tools are filtered out for viewer-role users. The agent loop in
`kerf-chat` filters `ctx.tools` by the user's role before sending the tool
list to the LLM.

## Handler signature

```python
async def run_<base_name>(ctx: ProjectCtx, args: bytes) -> str:
```

`ctx` is a `ProjectCtx` (from `kerf_core.utils.context`) — a lightweight
context object carrying the asyncpg pool, project ID, user ID, and config. It
is NOT the same as `PluginContext`; `ProjectCtx` is per-request.

`args` is the raw bytes of the JSON object the LLM provided. Always parse it
defensively:

```python
import json

async def run_read_widget(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    path = a.get("path", "")
    if not path:
        return err_payload("path is required", "BAD_ARGS")
    ...
```

## Return contracts

All tools must return a JSON-encoded string. Use the helpers:

```python
ok_payload(value: Any) -> str
err_payload(msg: str, code: str) -> str
```

`ok_payload` JSON-encodes `value`. If encoding fails it returns an error
payload automatically.

`err_payload` returns `{"error": "<msg>", "code": "<code>"}`.

### Success

```python
return ok_payload({"path": path, "content": widget_data})
```

### Error

```python
return err_payload("file not found", "NOT_FOUND")
```

Common codes: `BAD_ARGS`, `NOT_FOUND`, `PERMISSION_DENIED`, `ERROR`.

Never raise exceptions from a handler — the LLM loop does not catch them and
the agent turn will be broken. Always return an `err_payload` string instead.

## Write tools and file revisions

Write tools must record a revision after mutating file content, so `Cmd+Z`
works:

```python
from kerf_core.revisions import write_revision

await write_revision(
    pool=ctx.pool,
    file_id=file_id,
    content=new_content,
    source="tool",      # "user" | "llm" | "tool" | "restore"
    user_id=ctx.user_id,
    cap=ctx.file_revisions_max or 200,
)
```

## The _TOOL_MODULES / tool_modules convention

Most plugins define `_TOOL_MODULES` at the top of `plugin.py` — a list of
dotted module paths. The `register()` function imports each module at plugin
load time, causing all `@register` decorators in those modules to fire.

```python
# plugin.py
_TOOL_MODULES = [
    "kerf_myplugin.tools.widget_ops",
    "kerf_myplugin.tools.widget_scaffold",
]

def _register_tools() -> None:
    import importlib
    for path in _TOOL_MODULES:
        try:
            importlib.import_module(path)
        except Exception as exc:
            logger.warning("failed to load %s: %s", path, exc)
```

Some plugins (like `kerf-api`) use a discovery pattern that reads `*_spec`
attributes from each module and matches them to `run_*` handler functions. Both
patterns are valid; the `@register` decorator pattern is simpler for new plugins.

## Full example

```python
# kerf_myplugin/tools/widget_ops.py

import json
from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx


read_widget_spec = ToolSpec(
    name="read_widget",
    description="Read a .widget file by absolute path. Returns the parsed JSON.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the .widget file."},
        },
        "required": ["path"],
    },
)


@register(read_widget_spec, write=False)
async def run_read_widget(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    path = a.get("path", "").rstrip("/")
    if not path.startswith("/"):
        return err_payload("path must be absolute", "BAD_ARGS")

    row = await ctx.pool.fetchrow(
        "SELECT id, content FROM files WHERE project_id = $1 AND path = $2 AND deleted_at IS NULL",
        ctx.project_id, path,
    )
    if not row:
        return err_payload(f"not found: {path}", "NOT_FOUND")

    try:
        data = json.loads(row["content"])
    except Exception:
        data = {"raw": row["content"]}

    return ok_payload({"path": path, "content": data})


write_widget_spec = ToolSpec(
    name="write_widget",
    description="Write or overwrite a .widget file at an absolute path.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path, e.g. /parts/sprocket.widget"},
            "content": {"type": "object", "description": "Widget JSON payload."},
        },
        "required": ["path", "content"],
    },
)


@register(write_widget_spec, write=True)
async def run_write_widget(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    path = a.get("path", "").rstrip("/")
    content_obj = a.get("content")

    if not path.startswith("/"):
        return err_payload("path must be absolute", "BAD_ARGS")
    if content_obj is None:
        return err_payload("content is required", "BAD_ARGS")

    content_str = json.dumps(content_obj)

    row = await ctx.pool.fetchrow(
        "SELECT id FROM files WHERE project_id = $1 AND path = $2 AND deleted_at IS NULL",
        ctx.project_id, path,
    )

    if row:
        file_id = row["id"]
        await ctx.pool.execute(
            "UPDATE files SET content = $1 WHERE id = $2",
            content_str, file_id,
        )
    else:
        import uuid
        name = path.rsplit("/", 1)[-1]
        file_id = await ctx.pool.fetchval(
            "INSERT INTO files(project_id, name, kind, content) VALUES ($1, $2, 'widget', $3) RETURNING id",
            ctx.project_id, name, content_str,
        )

    from kerf_core.revisions import write_revision
    await write_revision(
        pool=ctx.pool,
        file_id=file_id,
        content=content_str,
        source="tool",
        user_id=ctx.user_id,
        cap=ctx.file_revisions_max or 200,
    )

    return ok_payload({"ok": True, "path": path})
```

## Testing tools

```python
# tests/test_widget_ops.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from kerf_myplugin.tools.widget_ops import run_read_widget


@pytest.mark.asyncio
async def test_read_widget_not_found():
    ctx = MagicMock()
    ctx.pool.fetchrow = AsyncMock(return_value=None)
    ctx.project_id = "test-project"

    result = json.loads(await run_read_widget(ctx, b'{"path": "/missing.widget"}'))
    assert result["code"] == "NOT_FOUND"
```

## See also

- [plugins-development.md](./plugins-development.md) — plugin structure, entry-point, manifest
- [architecture.md](./architecture.md) — tool registry and the AI loop
