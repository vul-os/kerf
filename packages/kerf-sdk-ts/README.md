# kerf-sdk

TypeScript SDK for [Kerf](https://kerf.app) — automate your CAD/EDA projects over HTTP/JSON-RPC.

## Install

```bash
npm install kerf-sdk
```

Requires Node 18+ (uses native `fetch` and `crypto.randomUUID`).

## Auth

Generate an API token from your workspace settings (`/w/<slug>/settings` → API Tokens), then:

```bash
export KERF_API_TOKEN=kerf_sk_...
export KERF_API_URL=https://kerf.app   # default; omit for cloud
```

## Quickstart

```ts
import { fromEnv } from 'kerf-sdk'

const k = fromEnv()

// list files in a project
const files = await k.files.list('<project-id>')
for (const f of files) {
  console.log(f.name, f.kind)
}

// read a script file
const content = await k.files.read('<project-id>', '<file-id>')

// search code across the project
const results = await k.files.search('<project-id>', 'extrude')

// read equations
const eqs = await k.equations.read('<project-id>', '<file-id>')
```

## Explicit connection

```ts
import { connect } from 'kerf-sdk'

const k = connect('kerf_sk_...', 'https://kerf.app')
```

## AsyncDisposable (TypeScript 5.2+)

```ts
await using k = fromEnv()
const files = await k.files.list('<project-id>')
// k is automatically disposed when the block exits
```

## API

All calls go through `POST /v1/rpc` as JSON-RPC 2.0 envelopes. The method names match Kerf's tool registry:

| Method | Wrapper | Description |
|--------|---------|-------------|
| `files.list` | `k.files.list(projectId)` | List project files |
| `files.read` | `k.files.read(projectId, fileId)` | Read file content |
| `files.write` | `k.files.write(projectId, fileId, content)` | Overwrite file content |
| `files.edit` | `k.files.edit(projectId, fileId, oldStr, newStr)` | Apply a diff-style edit |
| `files.create` | `k.files.create(projectId, name, kind?, content?, parentId?)` | Create a new file |
| `files.delete` | `k.files.delete(projectId, fileId)` | Delete a file |
| `files.search` | `k.files.search(projectId, query)` | Search code across files |
| `import_step` | `k.invoke("import_step", params)` | Import a STEP file |
| `equations.read` | `k.equations.read(projectId, fileId)` | Read project equations |
| `equations.set` | `k.equations.set(projectId, fileId, name, expr)` | Set an equation value |
| `configurations.add` | `k.configurations.add(projectId, fileId, label, params)` | Add a configuration variant |
| `configurations.set_active` | `k.configurations.setActive(projectId, fileId, configId)` | Switch active configuration |
| `revisions.list` | `k.revisions.list(projectId, fileId)` | List file revision history |
| `revisions.restore` | `k.revisions.restore(projectId, fileId, revisionId)` | Restore a previous revision |
| `docs.search` | `k.docs.search(query)` | Search Kerf documentation |

## Low-level access

```ts
const result = await k.invoke('files.list', { project_id: '...' })
```

## Error handling

```ts
import { KerfError } from 'kerf-sdk'

try {
  await k.files.read('<project-id>', 'bad-id')
} catch (err) {
  if (err instanceof KerfError) {
    console.error(err.code, err.message)
  }
}
```

## Source

Part of the [Kerf monorepo](https://github.com/kerf-sh/kerf). SDK lives at `packages/kerf-sdk-ts/`.

The Python SDK (`pip install kerf-sdk`) lives at `packages/kerf-sdk/` — both talk to the same `/v1/rpc` endpoint.

## License

MIT
