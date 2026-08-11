# Terminal

Kerf ships a real terminal. It runs a login shell as the OS user that started
the server, with the `kerf` CLI already on its `PATH`, so you can drive Kerf
from a command line without leaving the app — or point an agent like Claude
Code or Cursor at it and let *it* drive.

## Read this before enabling it on a server

**There is no sandbox.** A terminal session has the full authority of the
server process:

- the entire filesystem, as that user
- the process environment
- `kerf.toml` — which holds your JWT secret, your database DSN, and any
  provider API keys

Anyone who can open a terminal can read all of that. Authentication does not
change it: authentication decides *who gets a shell*, not *what the shell can
reach*.

That is fine in the case Kerf is built for — a node bound to loopback, running
as you, on your own machine. A shell there grants you nothing you did not
already have; it is no more privileged than opening Terminal.app. It is **not**
fine on a host reachable by people you would not hand an SSH key to.

So the terminal is gated on the **listen address**, not on a role:

| Bind | Terminal |
|------|----------|
| `127.0.0.1` / `::1` (default, and always in the desktop app) | available |
| anything else | refused, unless you opt in below |

```toml
[terminal]
enabled = true   # only on a bind you have thought about
```

The app asks the server whether a terminal is possible before offering one, so
a node where the answer is no never shows a control that would fail.

## Sandboxing it anyway

If you want a terminal on a shared or exposed host, put the sandbox *outside*
Kerf. Kerf cannot sandbox itself — the server process holds the secrets, so a
shell spawned by that process can always read them. The recipes below all work
by making the whole Kerf process less privileged.

### Run Kerf in a container

The most reliable option, and you may already be doing it — Kerf publishes
images to `ghcr.io/vul-os/kerf`. A shell inside the container reaches only the
container:

```sh
docker run --rm -p 127.0.0.1:8080:8080 \
  -v kerf-data:/data \
  -e KERF_DATA_DIR=/data \
  -e RATE_LIMIT_OVERRIDES='{}' \
  --read-only --tmpfs /tmp \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --pids-limit=512 --memory=4g \
  ghcr.io/vul-os/kerf:latest
```

Note what this does and does not buy you. It contains the *filesystem* blast
radius. It does **not** protect the secrets in that container's `kerf.toml`
from a shell in that same container — nothing can. Treat one container as one
trust domain: one team, or one person.

Do **not** bind-mount `/var/run/docker.sock` into it. That socket is equivalent
to root on the host, so a shell that can reach it escapes the container
immediately, and you have built a sandbox with a door in it.

### Run it as a dedicated unprivileged user

Cheaper, and worth doing even with a container:

```sh
useradd --system --create-home --shell /usr/sbin/nologin kerf
sudo -u kerf kerf-server --host 127.0.0.1
```

The shell then runs as `kerf`, which owns only its own data directory. Combine
with a reverse proxy that terminates TLS and authenticates, so the port is
never directly reachable.

### Restrict it with systemd

If you run Kerf under systemd, the unit can do most of a container's work:

```ini
[Service]
User=kerf
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/kerf
PrivateTmp=yes
PrivateDevices=yes
NoNewPrivileges=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryMax=4G
TasksMax=512
```

### What none of these fix

A shell can always read the configuration of the process that spawned it. If
the people who can reach your Kerf node are not people you would give an SSH
key on that box, do not enable the terminal — sandbox or no sandbox. Give them
their own node instead; that is what the Workshop is for.

## Using it

The `kerf` CLI is on `PATH` inside every session, resolved to the same install
serving the page — you do not need to activate a virtualenv or add anything to
your profile. Sessions are identified by `KERF_TERMINAL=1` in the environment,
so a script or an agent can detect that it is running inside Kerf.

Sessions outlive their connection. Closing the tab, sleeping the laptop or
losing wifi does not kill a running build: reconnecting re-attaches to the same
shell and replays the last 256 KB of output. A session with nothing attached is
reaped after an hour.

See [cli.md](./cli.md) for the command surface, including the JSON output and
the tool-calling interface that make Kerf drivable by an agent.
