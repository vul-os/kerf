# kerf-sdk — Python SDK (`kerf` on PyPI)

`kerf-sdk` is the Python client library for scripting against a running Kerf server. It is published to PyPI as `kerf` and is the primary integration path for automation, parametric scripting, and external tooling. It communicates with the server over HTTP using JSON-RPC 2.0 on a single endpoint (`/v1/rpc`).

The SDK runs on the user's own machine. No code is sent to a remote agent — calls go directly to the configured Kerf server URL via HTTP.

---

## Installation

```bash
pip install kerf
```

Requires Python 3.10+. The only runtime dependency is `httpx`.

---

## Authentication

The SDK authenticates with a long-lived opaque API token (`kerf_sk_*`). Generate a token from workspace settings in the Kerf UI or via `POST /api/api-tokens`.

```bash
export KERF_API_TOKEN="kerf_sk_yourtokenhere"
export KERF_API_URL="https://kerf.sh"   # default; omit for cloud
```

`load_token()` and `load_url()` in `kerf.auth` read these environment variables. `KERF_API_URL` defaults to `https://kerf.sh` if unset.

---

## Client instantiation

```python
from kerf import Kerf
from kerf.auth import load_token, load_url

client = Kerf(token=load_token(), base_url=load_url())

# Or explicitly:
client = Kerf(token="kerf_sk_...", base_url="http://localhost:8000")
```

The client is a context manager:

```python
with Kerf(token=..., base_url=...) as kerf:
    files = kerf.files.list(project_id="...")
```

Call `client.close()` to release the underlying `httpx` connection pool when not using the context manager.

---

## Low-level RPC

All namespaced methods delegate to `client.invoke`:

```python
result = client.invoke("files.list", {"project_id": "uuid"})
```

Envelope format:
```json
{"jsonrpc": "2.0", "method": "files.list", "params": {"project_id": "..."}, "id": "<uuid>"}
```

`invoke` raises `kerf.client.KerfError(code, message)` on a JSON-RPC error response and `httpx.HTTPStatusError` on a non-2xx HTTP status.

---

## Namespaced method reference

### `kerf.files` — file CRUD

| Method | RPC method | Description |
|---|---|---|
| `files.list(project_id)` | `files.list` | List all files in a project |
| `files.read(project_id, file_id)` | `files.read` | Read file content + metadata |
| `files.write(project_id, file_id, content)` | `files.write` | Overwrite file content |
| `files.edit(project_id, file_id, old_string, new_string)` | `files.edit` | Exact-string replace in a file |
| `files.create(project_id, name, kind, content, parent_id?)` | `files.create` | Create a new file or folder |
| `files.delete(project_id, file_id)` | `files.delete` | Soft-delete a file |
| `files.search(project_id, query)` | `files.search` | Full-text search within a project |

### `kerf.equations` — parametric equations

| Method | RPC method | Description |
|---|---|---|
| `equations.read(project_id, file_id)` | `equations.read` | Read all equations in a file |
| `equations.set(project_id, file_id, name, expression)` | `equations.set` | Set or update a named equation |

### `kerf.configurations` — design variants

| Method | RPC method | Description |
|---|---|---|
| `configurations.add(project_id, file_id, label, params)` | `configurations.add` | Add a named configuration with parameter overrides |
| `configurations.set_active(project_id, file_id, config_id)` | `configurations.set_active` | Switch the active configuration |

### `kerf.revisions` — fine-grained undo

| Method | RPC method | Description |
|---|---|---|
| `revisions.list(project_id, file_id)` | `revisions.list` | List all revisions for a file |
| `revisions.restore(project_id, file_id, revision_id)` | `revisions.restore` | Restore a historical revision (non-destructive) |

### `kerf.docs` — documentation search

| Method | RPC method | Description |
|---|---|---|
| `docs.search(query)` | `docs.search` | Keyword search across LLM docs corpus |

---

## Error handling

```python
from kerf.client import KerfError

try:
    result = client.files.read(project_id="p", file_id="nonexistent")
except KerfError as e:
    print(e.code, e.message)   # e.g. -32000, "file not found"
```

`KerfError.code` follows JSON-RPC 2.0 error codes. Application-level error codes are in the negative range (`-32000` to `-32099`).

---

## Usage examples

### List all files in a project and print their paths

```python
from kerf import Kerf
from kerf.auth import load_token, load_url

with Kerf(token=load_token(), base_url=load_url()) as kerf:
    project_id = "your-project-uuid"
    files = kerf.files.list(project_id)
    for f in files:
        print(f["path"], f["kind"])
```

### Read and update an equation

```python
with Kerf(token=load_token(), base_url=load_url()) as kerf:
    eqs = kerf.equations.read(project_id="...", file_id="...")
    print(eqs)   # {"wall_thickness": "200", "floor_height": "3000"}

    kerf.equations.set(
        project_id="...",
        file_id="...",
        name="floor_height",
        expression="3500",
    )
```

### Add a configuration variant

```python
with Kerf(token=load_token(), base_url=load_url()) as kerf:
    kerf.configurations.add(
        project_id="...",
        file_id="...",
        label="M6",
        params={"diameter": "6", "thread_pitch": "1"},
    )
    kerf.configurations.set_active(project_id="...", file_id="...", config_id="M6")
```

---

## Integration points

- **API tokens** (`kerf-auth`): the SDK token authenticates through `require_auth` — same dependency as all other protected routes.
- **Billing** (`kerf-billing`): SDK tokens on paid paths can carry a `max_spend_per_day_usd` cap. Exceeding the cap returns `ApiTokenDailyCapExceeded` as a `KerfError`.
- **RPC endpoint**: `/v1/rpc` is mounted by `kerf-api` and dispatches to the same tool handlers used by the chat agent.

---

## Future namespaces (not yet wired)

Heavy-operation namespaces (`kerf.fem`, `kerf.cam`, `kerf.topo`) are reserved for future wiring. They will follow the same `invoke` pattern with job-status polling. Until the `/v1/rpc` methods exist server-side, calling them raises `KerfError`.
