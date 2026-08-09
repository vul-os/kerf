# kerf-cli

Mode-agnostic Kerf command-line client.

- `kerf login` — save API token and server URL
- `kerf serve` — start a self-hosted Kerf server (requires Postgres)
- `kerf tools list / show / call` — drive Kerf's registered LLM tools from a
  terminal or a script (`GET /api/tools`, `POST /api/tools/call`)
- `kerf mcp` — run an MCP server on stdio exposing the same tools to Claude
  Desktop and other MCP clients (`pip install 'kerf-cli[mcp]'`; see
  [`docs/mcp.md`](../../docs/mcp.md))
