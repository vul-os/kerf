# Netlist Export + Extended ERC Report

Two LLM tools for exporting a CircuitJSON schematic to standard EDA netlist
formats and running an extended Electrical Rules Check.

Both tools derive net topology purely from the `source_component` /
`source_port` / `source_trace` / `source_net` element model — the same model
used by `run_erc`.

---

## `export_netlist`

Exports the schematic netlist in one of three standard formats.

**When to use:** User asks to export a netlist, generate a `.net` file for
a layout tool (KiCad, PADS, Altium import), or produce a spreadsheet of net
connections.  Run `erc_report` first to catch wiring errors before exporting.

**Input:**
- `circuit_json` (required) — flat array of CircuitJSON `source_*` elements.
- `format` (required) — one of `"kicad"`, `"orcad_pads"`, or `"csv"`.
- `stem` (optional) — board/job name used in the file header and filename
  (default: `"board"`).

**Output:**
- `filename` — suggested file name including extension.
- `format` — the format that was used.
- `content_b64` — base64-encoded UTF-8 netlist text; decode and save as the
  returned `filename`.
- `line_count` — total lines in the output file.
- `preview` — first 25 lines as plain text.
- `message` — human-readable summary.

---

### Format: `kicad` — KiCad S-expression (.net)

KiCad 5/6 compatible `(export …)` S-expression format.  This is the format
produced by KiCad's *File → Export → Netlist* function and consumed by KiCad
PCB layout, Freerouting, and many third-party tools.

**File extension:** `.net`

**Structure:**

```
(export (version "1")
  (design
    (source <board-name>)
    (date <ISO-8601 timestamp>)
    (tool "Kerf Electronics"))
  (components
    (comp (ref <REFDES>) (value <value>) (footprint <fp>))
    ...)
  (nets
    (net (code "1") (name <net-name>)
      (node (ref <REFDES>) (pin <pin-name>))
      ...)
    ...))
```

Strings containing spaces or special characters are double-quoted.
Parentheses are always balanced.

---

### Format: `orcad_pads` — OrCAD/PADS ASCII (.net)

PADS Layout ASCII netlist format.  Accepted by PADS Layout, CADSTAR, and many
legacy place-and-route and back-annotation tools.

**File extension:** `.net`

**Structure:**

```
!<board-name> <ISO-8601 timestamp>
*PART*
<REFDES> <footprint>
...
*NET*
*SIGNAL* <net-name>
<REFDES>.<pin> [<REFDES>.<pin> ...]
...
*END*
```

Nodes within a `*SIGNAL*` section are wrapped at 8 nodes per line.

---

### Format: `csv` — Generic CSV

One row per `(net, component, pin)` tuple.  Easy to import into spreadsheets,
BOM tools, or custom scripts.

**File extension:** `.csv`

**Columns:** `net_name`, `refdes`, `pin`, `pin_type`

`pin_type` reflects the `pin_type` field from the `source_port` element
(e.g. `passive`, `input`, `output`, `power_in`, `power_out`).

---

### Net name resolution

Net names are resolved from `source_net` elements whose IDs are connected
(via traces) to the relevant ports.  When no `source_net` label is available
for a merged net, the union-find root port ID is used as the net name.

---

## `erc_report`

Extended ERC that wraps the core `run_erc` checks and adds three more.

**When to use:** User asks for a detailed ERC, wants to know about power
sourcing problems, conflicting drivers, or isolated net stubs — or whenever
`run_erc` output is not detailed enough for diagnosis.

**Input:** `circuit_json` (required) — flat array of CircuitJSON
`source_*` elements.

**Output:**
- `errors` — list of error entries (see below).
- `warnings` — list of warning entries (see below).
- `summary.total_errors` — count of errors.
- `summary.total_warnings` — count of warnings.
- `summary.checks_run` — list of all check names executed.

Each entry has at minimum: `kind`, `severity`, `message`.
Optional fields: `component_id`, `port_id`, `net_id`, `net_root`, `drivers`.

---

### Checks from core `run_erc` (unchanged)

| kind | severity | trigger |
|------|----------|---------|
| `unconnected_pin` | error | `source_port` appears in no trace |
| `duplicate_refdes` | error | two `source_component` share the same `name` |
| `conflicting_net_label` | error | two `source_net` labels resolve to same net |
| `output_to_output` | error | two output pins on the same trace (per-trace) |
| `missing_power` | error | power-named net has no power/supply-type pin |
| `pin_direction_mismatch` | warning | input-only pins wired with no driver |
| `floating_net` | warning | a trace connects only one port |
| `bidirectional_promiscuity` | warning | > 3 bidirectional pins on one net |

---

### Extended checks (new in `erc_report`)

#### `single_node_net` — warning

A merged net (after union-find across all traces) touches exactly one port.
The signal can never reach a second pin — it is an isolated stub.

Differs from `floating_net`: `floating_net` fires per-trace; `single_node_net`
fires per merged net root.  Both can fire for the same dangling wire.

**Common cause:** Output pin connected to a trace that was never routed to a
receiver; partially modelled bus where one side was not yet added.

Entry includes `port_id` (the isolated port) and `net_root`.

---

#### `power_pin_no_driver` — error

A `power_in`-typed pin is on a merged net that has no `power_out` / `supply`
pin anywhere.  The power rail is referenced but nothing sources it.

More specific than `missing_power`: `missing_power` works from
`source_net.is_power` flags and name patterns; this check works from pin types
and flags missing sourcing pins directly.

**Common cause:** MCU VDD pin connected to a VCC net but no regulator or
power flag component drives it; schematic power hierarchy incomplete.

Entry includes `port_id`, `component_id`, and `net_root`.

---

#### `conflicting_outputs` — error

All output-driver pins on the same merged net are listed together in a single
structured entry per net, with a `drivers` array.

Complements `output_to_output` (which fires per-trace): this fires once per
net and gives the full picture when more than two drivers are involved.

Open-collector and open-drain pins are excluded (wired-OR is valid).

**Common cause:** Multiple TX lines accidentally shorted; copy-paste error
connecting two MCU output pins to the same bus line.

Entry includes `net_root` and `drivers: [{refdes, pin, port_id}, ...]`.

---

### Example

```json
[
  { "type": "source_component", "source_component_id": "c1", "name": "U1" },
  { "type": "source_port", "source_port_id": "p1",
    "source_component_id": "c1", "name": "VDD", "pin_type": "power_in" },
  { "type": "source_port", "source_port_id": "p2",
    "source_component_id": "c1", "name": "TX",  "pin_type": "output" },
  { "type": "source_trace", "source_trace_id": "t1",
    "connected_source_port_ids": ["p1"] },
  { "type": "source_trace", "source_trace_id": "t2",
    "connected_source_port_ids": ["p2"] }
]
```

Expected `erc_report` output includes:

```json
{
  "errors": [
    { "kind": "power_pin_no_driver", "severity": "error",
      "message": "Power-in pin \"VDD\" on component \"c1\" is on a net with no power-out/supply driver …",
      "port_id": "p1", "component_id": "c1" }
  ],
  "warnings": [
    { "kind": "single_node_net", "severity": "warning",
      "message": "Net (root \"p1\") has exactly one connected port \"VDD\" — single-node net …",
      "port_id": "p1" },
    { "kind": "single_node_net", "severity": "warning",
      "message": "Net (root \"p2\") has exactly one connected port \"TX\" — single-node net …",
      "port_id": "p2" }
  ],
  "summary": {
    "total_errors": 1,
    "total_warnings": 2,
    "checks_run": ["unconnected_pin", "duplicate_refdes", …, "single_node_net", "power_pin_no_driver", "conflicting_outputs"]
  }
}
```
