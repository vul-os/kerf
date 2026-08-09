# Kerf MCP server

`kerf mcp` runs a [Model Context Protocol](https://modelcontextprotocol.io)
server on stdio that exposes every tool Kerf registers for its own LLM
assistant — 350+ tools covering files, parametric sketches/features, CAM,
circuits, BOM, layers, and more — to any MCP client: Claude Desktop, other
MCP-aware editors/agents, or your own scripts via an MCP SDK.

It is a thin wrapper, not a second implementation: `kerf mcp` reads the
same `GET /api/tools` registry the [`kerf tools`](../packages/kerf-cli/README.md)
CLI reads, and every `tools/call` is forwarded to the same
`POST /api/tools/call` endpoint the web app's chat assistant uses. There is
one tool registry and one dispatch path; MCP and the CLI are just two ways
to reach it.

## What it exposes

- **`tools/list`** — one MCP tool per entry in `GET /api/tools`. Each tool's
  `name`, `description`, and `inputSchema` come straight from the server's
  `input_schema` — no re-authoring.
- **`tools/call`** — forwarded to `POST /api/tools/call` as
  `{"tool": name, "args": arguments, "project_id": ...}`. The tool's JSON
  result is returned as the call's text content. A tool error (unknown
  tool, a raised exception, an auth failure) comes back as an MCP error
  result (`isError: true`) carrying the server's message — never a raw
  traceback.

### Scoping calls to a project

Most tools need a `project_id` (anything that reads/writes files, runs CAM,
etc.); a few pure parsers/serializers work fine without one. `kerf mcp`
takes a default `--project` for the whole session:

```
kerf mcp --project <project-uuid>
```

A single call can override that default by including its own `project_id`
key in the call's arguments — it's popped off before the rest of the
arguments are sent as the tool's `args`, so it never collides with a tool's
own input schema.

## Auth and base URL

`kerf mcp` reuses exactly the same credential resolution as every other
`kerf` command (`kerf sync`, `kerf export`, ...) — there is only one auth
path in this CLI:

1. `KERF_API_URL` / `KERF_API_TOKEN` environment variables, if set.
2. Otherwise, whatever `kerf login` saved to `~/.config/kerf/credentials`.
3. `--url` / `--token` flags on `kerf mcp` itself override both.

Get a token from `https://<your-server>/settings#api-tokens` (or your
self-hosted node's equivalent), then either:

```
kerf login --token kerf_sk_... --api-url https://app.kerf.io
```

or export the environment variables directly:

```
export KERF_API_URL=https://app.kerf.io
export KERF_API_TOKEN=kerf_sk_...
```

`kerf mcp` does not touch the network until an MCP client actually calls
`tools/list` or `tools/call` — starting the process (e.g. by Claude Desktop,
on launch) is instant even offline. Once fetched, the tool list is cached
on disk for 5 minutes (`~/.config/kerf/tools_cache.json`) so repeated
`tools/list` calls in one session don't re-fetch the full registry.

## Install

`kerf mcp` needs the optional `mcp` dependency:

```
pip install 'kerf-cli[mcp]'
```

(A plain `pip install kerf-cli` stays a zero-dependency thin client — only
`kerf mcp` itself imports the `mcp` package, and only when you run it.)

## Claude Desktop configuration

Add a `kerf` entry to Claude Desktop's `claude_desktop_config.json`
(`~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS; `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "kerf": {
      "command": "kerf",
      "args": ["mcp"],
      "env": {
        "KERF_API_URL": "https://app.kerf.io",
        "KERF_API_TOKEN": "kerf_sk_..."
      }
    }
  }
}
```

If you'd rather scope the whole session to one project, add it as an
argument:

```json
{
  "mcpServers": {
    "kerf": {
      "command": "kerf",
      "args": ["mcp", "--project", "<project-uuid>"],
      "env": {
        "KERF_API_URL": "https://app.kerf.io",
        "KERF_API_TOKEN": "kerf_sk_..."
      }
    }
  }
}
```

Restart Claude Desktop after editing the config. It will list "kerf" among
its available tool servers, and every Kerf tool becomes callable from the
conversation.

If `kerf` is not on `PATH` where Claude Desktop launches it, use an
absolute path for `command` (e.g. the output of `which kerf`), or point it
at the interpreter directly: `"command": "/path/to/venv/bin/python3",
"args": ["-m", "kerf_cli.main", "mcp"]`.

## Debugging

Run it by hand to see what a client would see (type a `tools/list` request
or use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)):

```
kerf mcp
```

It logs a one-line startup message (`kerf mcp: serving Kerf tools over
stdio (server: ...)`) to stderr — stdout is reserved for the MCP protocol
itself, so nothing else should print there. If credentials are missing it
exits immediately with a message on stderr instead of starting a broken
session.
