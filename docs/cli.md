# The `kerf` CLI

Kerf's command surface. It exists so that a person — or an agent like Claude
Code or Cursor — can drive a Kerf node from a terminal instead of a chat box.

If you are an agent reading this to learn how to use Kerf: everything you need
is in [Driving Kerf from an agent](#driving-kerf-from-an-agent). The rest is
for humans.

## Where it runs

Inside Kerf's own terminal the CLI is already set up: `kerf` is on `PATH`
resolved to the same install serving the page, and `KERF_API_URL` points at
that node. Nothing to configure.

Outside it, either run `kerf login`, or set the two environment variables
yourself:

```sh
export KERF_API_URL=http://localhost:8080
export KERF_API_TOKEN=kerf_sk_...
```

A session inside the Kerf terminal is marked with `KERF_TERMINAL=1`, so a
script can tell where it is:

```sh
[ -n "$KERF_TERMINAL" ] && echo "running inside Kerf"
```

## Commands

| Command | What it does |
|---------|--------------|
| `kerf tools list` | Every registered tool, as `name description` |
| `kerf tools show <name>` | One tool's JSON input schema |
| `kerf tools call <name>` | Invoke a tool |
| `kerf mcp` | An MCP server over stdio exposing the same tools |
| `kerf serve` | Run a Kerf server |
| `kerf sync` | Two-way mirror between a local directory and a project |
| `kerf export` / `kerf import` | Materialise a project as files, and back |
| `kerf hydrate` | Fetch real bytes for LFS pointer stubs |
| `kerf admin set-password` | Set or change this node's password |
| `kerf login` | Store an API token and URL in `~/.config/kerf/credentials` |

`kerf <command> --help` prints the full options for any of them.

## Driving Kerf from an agent

Kerf exposes its whole modelling surface — 350+ tools spanning CAD, CAM, FEM,
CFD, PCB, BIM and the rest — through three commands. This is the same tool
registry the built-in chat uses, so anything the chat can do, you can do.

### The loop

**1. Find the tool.** `--json` gives you the machine-readable list.

```sh
kerf tools list --json
```

**2. Read its schema** before calling it, rather than guessing at argument
names:

```sh
kerf tools show run_fem
```

That prints the tool's JSON Schema — the same schema the server validates
against, so a call shaped to it will not be rejected for shape.

**3. Call it.** Arguments are JSON, inline or from a file:

```sh
kerf tools call read_file --args '{"path": "/main.jscad"}'
kerf tools call run_compute --args-file ./fem-run.json --project "$PROJECT_ID"
```

The result is printed as JSON on stdout.

### What you can rely on

- **stdout is the answer, stderr is the commentary.** Parse stdout; a
  progress line will never appear in it.
- **Exit code 0 means it worked.** Non-zero means it did not — do not parse
  output to decide whether a command succeeded.
- **`--json` output is stable**: it is the server's own payload, not a
  rendering of it.
- **No interactive prompts** unless you are on a TTY and have omitted a
  required value. In a script, pass everything explicitly and nothing will
  block.

### MCP, if your client speaks it

```sh
kerf mcp
```

Runs an MCP server over stdio exposing the same tools, for Claude Desktop,
Cursor, or anything else that speaks the protocol. Point your client's MCP
configuration at that command. Same registry, same schemas — the difference is
only whether your client prefers a protocol or a shell.

### A worked example

Read a part, change a dimension, and re-render it:

```sh
# What is in this project?
kerf tools call list_files --args '{}' --project "$PROJECT_ID"

# Read the file before editing it.
kerf tools call read_file --args '{"path": "/main.jscad"}' --project "$PROJECT_ID"

# Edit by unique substring, not by line number.
kerf tools call edit_file --args '{
  "path": "/main.jscad",
  "old_string": "size: [40, 40, 10]",
  "new_string": "size: [40, 40, 16]"
}' --project "$PROJECT_ID"

# Render it and wait for the job.
JOB=$(kerf tools call run_compute --args '{"engine":"render","file_id":"'"$FILE_ID"'"}' \
        --project "$PROJECT_ID" | jq -r .job_id)
kerf tools call poll_compute --args '{"job_id":"'"$JOB"'"}' --project "$PROJECT_ID"
```

### Conventions worth knowing

These are Kerf's own vocabulary, and getting them wrong produces confusing
errors:

- A **Part** is a whole `.jscad` / `.feature` / `.step` file. It returns an
  array of Objects.
- An **Object** is one entry in that array, identified by its `id`.
- A **Component** is an Assembly's placement of a single Object at a transform.

A `.jscad` file must export a default function taking one destructured
argument and returning `[{ id, geom }, ...]`. `jscad` is not a global; the
modelling modules arrive as that argument. `kerf tools call search_kerf_docs`
will find the authoring guide for any file kind.

## Recovering a node

There is no password-reset email — a self-hosted node has no mail transport.
The password is set on first load and changed from the machine:

```sh
kerf admin set-password              # prompts, or reads stdin
kerf admin set-password --generate   # generates one and prints it once
```

Reading from stdin keeps it out of your shell history:

```sh
kerf admin set-password < password.txt
```

See [terminal.md](./terminal.md) for what a terminal session can reach, and
when it is refused.
