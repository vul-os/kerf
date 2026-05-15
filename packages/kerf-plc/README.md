# kerf-plc

IEC 61131-3 Structured Text plugin for Kerf.

Provides:
- `.plc.st` file kind (Monaco editor with custom `iec61131-st` syntax highlighting)
- Offline lint via the MATIEC parser (`POST /lint-plc`)
- `run_plc_lint` LLM tool

## Scope (v0.2 — Tier 1)

- Syntax-highlighted Monaco editor.
- Offline lint diagnostics via the MATIEC parser subprocess.
- File kind registration, file tree icon, create-menu entry.

## Out of scope (Tier 2 — deferred to v0.3+)

- `POST /run-plc-sim` simulated execution against synthetic inputs.
- OpenPLC runtime integration.
- Ladder Diagram / Function Block Diagram graphical editors.

## MATIEC

[MATIEC](https://github.com/thiagoralves/OpenPLC_v3/tree/master/utils/matiec_src)
is the open-source IEC 61131-3 compiler/linter shipped with
[OpenPLC](https://www.openplcproject.com/). It is licensed **GPLv3**.

Kerf invokes MATIEC as a **separate subprocess** (no in-process linking). This
subprocess boundary means the hosted service is not GPL-tainted. Local installs
are similarly unaffected — MATIEC is an optional system dependency; lint is
gracefully disabled when `iec2c` is absent.

### Installing MATIEC

**Debian / Ubuntu:**

```bash
apt install matiec
```

**Build from source (any platform):**

```bash
git clone https://github.com/thiagoralves/OpenPLC_v3.git
cd OpenPLC_v3/utils/matiec_src
make
# Copy 'iec2c' binary into your PATH
sudo cp iec2c /usr/local/bin/
```

The plugin looks for `iec2c` on `$PATH`. When it is absent, `POST /lint-plc`
returns a single `severity=warning` diagnostic explaining that lint is disabled.

### Subprocess timeout

Lint subprocess timeout is 5 seconds (configurable via env var `MATIEC_TIMEOUT`).
