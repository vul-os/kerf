# PLC — IEC 61131-3 Programmable Logic Controllers

`kerf-plc` adds IEC 61131-3 Structured Text (ST) authoring and linting to
Kerf projects. Write PLC programs alongside your machine designs, lint them
offline via MATIEC, and keep control logic version-controlled with the rest
of the project.

For the canonical ST language reference (data types, control flow, standard
function blocks, variable sections) see the LLM authoring guide at
`packages/kerf-plc/llm_docs/plc.md`.

---

## Overview

| Property | Value |
|---|---|
| Package | `kerf-plc` |
| Plugin entry-point | `kerf_plc.plugin:register` |
| Capability tag | `plc.lint` |
| Source | `packages/kerf-plc/` |

---

## File types

| Extension | Kind | Description |
|---|---|---|
| `.plc.st` | `plc_st` | IEC 61131-3 Structured Text source file |

Files are edited in Monaco with a custom `iec61131-st` language definition
(syntax highlighting, bracket matching, keyword completion). Lint markers are
supplied by the `run_plc_lint` LLM tool or the `POST /lint-plc` route.

---

## Language primer

Structured Text is Pascal-shaped. The three Program Organisation Units (POUs)
are:

| POU | Keyword pair | Stateful? |
|---|---|---|
| Function | `FUNCTION … END_FUNCTION` | No |
| Function Block | `FUNCTION_BLOCK … END_FUNCTION_BLOCK` | Yes |
| Program | `PROGRAM … END_PROGRAM` | Yes (scan-cycle root) |

Variable sections:

```st
VAR            (* local *)
VAR_INPUT      (* caller-supplied — read-only inside the POU *)
VAR_OUTPUT     (* written by the POU, readable by caller *)
VAR_IN_OUT     (* read-write by both *)
VAR_GLOBAL     (* global scope *)
END_VAR
```

Scalar types: `BOOL`, `INT`, `DINT`, `LINT`, `REAL`, `LREAL`, `TIME`, `STRING`.

See `packages/kerf-plc/llm_docs/plc.md` for the full type table, operators,
control-flow constructs, and IEC stdlib function blocks (`TON`, `TOF`, `TP`,
`SR`, `CTU`, `R_TRIG`, …).

---

## Minimal example

```st
PROGRAM StartStopLatch

VAR_INPUT
  start_pb  : BOOL;   (* Start pushbutton — momentary NO *)
  stop_pb   : BOOL;   (* Stop pushbutton  — momentary NC, inverted *)
  fault     : BOOL;   (* Overload relay input *)
END_VAR

VAR_OUTPUT
  motor_run : BOOL;   (* Motor contactor coil *)
END_VAR

IF (start_pb AND NOT stop_pb AND NOT fault) THEN
  motor_run := TRUE;
END_IF

IF (stop_pb OR fault) THEN
  motor_run := FALSE;
END_IF

END_PROGRAM
```

---

## LLM tools

### `run_plc_lint`

Lint a Structured Text source string via the MATIEC `iec2c` parser.

```json
{
  "source": "PROGRAM MyPLC\nVAR_INPUT x : BOOL; END_VAR\n...\nEND_PROGRAM"
}
```

Returns:

```json
{
  "diagnostics": [
    {
      "severity": "error",
      "message": "undefined variable 'y'",
      "line": 5,
      "column": 3,
      "source": "matiec"
    }
  ],
  "warnings": []
}
```

`diagnostics` are forwarded to the Monaco marker layer. `warnings` carry
top-level informational messages (for example, `"MATIEC not installed — lint
disabled"`). When MATIEC is absent the route returns HTTP 200 with an empty
`diagnostics` array and a single advisory `warning`; no exception is raised.

Source: `packages/kerf-plc/src/kerf_plc/tools/run_plc_lint.py`

---

## HTTP routes

| Method | Path | Description |
|---|---|---|
| `POST` | `/lint-plc` | Lint a `.plc.st` source string; returns Monaco-ready diagnostics |

Request body:

```json
{ "source": "<Structured Text source string>" }
```

Response:

```json
{
  "diagnostics": [{ "severity", "message", "line", "column", "source" }],
  "warnings": ["..."]
}
```

Source: `packages/kerf-plc/src/kerf_plc/routes.py`

---

## MATIEC dependency

MATIEC (`iec2c`) is the open-source IEC 61131-3 compiler shipped with
OpenPLC. It is licensed **GPLv3**. Kerf invokes it as a **separate subprocess**
— no in-process linking — so the hosted service and local install remain
MIT-licensed.

```bash
# Debian / Ubuntu
apt install matiec

# Build from source
git clone https://github.com/thiagoralves/OpenPLC_v3.git
cd OpenPLC_v3/utils/matiec_src && make
sudo cp iec2c /usr/local/bin/
```

Lint is gracefully disabled (single `warning`, empty `diagnostics`) when
`iec2c` is not found on `$PATH`. The subprocess timeout defaults to 5 s;
override with `MATIEC_TIMEOUT`.

Source: `packages/kerf-plc/src/kerf_plc/matiec_lint.py`

---

## Subpackage structure

```
packages/kerf-plc/
  src/kerf_plc/
    plugin.py          — register() entry point; wires router + LLM tools
    routes.py          — POST /lint-plc FastAPI route
    matiec_lint.py     — subprocess wrapper around iec2c
    tools/
      run_plc_lint.py  — LLM tool spec + handler
  llm_docs/
    plc.md             — full ST language reference for LLM context
  tests/
```

---

## Related documentation

| Topic | Path |
|---|---|
| ST language reference (LLM) | `packages/kerf-plc/llm_docs/plc.md` |
| Firmware / embedded C | `docs/firmware.md` |
| Electronics workflow | `docs/electronics.md` |
| Plugin development | `docs/plugins-development.md` |
