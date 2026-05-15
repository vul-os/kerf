# ODB++ Fab Export

## `export_odbpp`

Exports a CircuitJSON board as an **ODB++ fab archive** (`.tgz`).

ODB++ (ISO/IEC 13052, originally Mentor/Valor) is one of the two primary
"intelligent fab" delivery formats — alongside IPC-2581 — accepted by leading
PCB contract manufacturers (Sanmina, TTM, Jabil, Foxconn, etc.).

**When to use:** User asks to export ODB++, generate an ODB++ package, or
wants to send the board to a fab that requires ODB++ format.

**Input:**
- `circuit_json` (required) — the parsed CircuitJSON array from the active
  `.circuit.tsx` file.
- `stem` (optional) — base name used as the top-level directory and step name
  inside the archive. Default `"board"`.

**Output:**
- `tgz_filename` — e.g. `board-odbpp.tgz`
- `tgz_b64` — base64-encoded `.tgz` bytes; offer as a download link.
- `manifest` — list of all paths inside the archive.
- `layer_count` — number of layer `features` files in the archive.
- `message` — human-readable summary.

## Archive layout

```
<stem>/
  misc/
    info              EDA tool name, ODB++ version, units, creation date
  steps/
    pcb/
      stephdr         board dimensions, datum, layer list
      layers/
        top_copper/
          attrlist    layer type=signal, context=board, polarity=positive
          components  component placement records (CMP x y rot mir ref fp val)
          features    pads (P), lines/traces (L), surfaces/pours (S/OB/OS/OE)
        bottom_copper/  (same structure)
        top_silk/       (lines and text approximations)
        bottom_silk/
        top_mask/       (pad openings with 0.1 mm expansion)
        bottom_mask/
        drill/          (via + PTH pad hole centres as round pads)
        outline/        (board outline as line segments)
```

## Feature-record syntax

| Record | Format |
|--------|--------|
| Line   | `L x1 y1 x2 y2 <sym_idx> P 0;` |
| Pad    | `P x y <sym_idx> P <orient> <mirror>;` |
| Surface open | `S P;` → `OB x0 y0 I;` → `OS xi yi;`… → `OE;` |

Symbol names: `r<diam>` (circle), `rect<w>x<h>`, `oval<w>x<h>`.

## Format details

- Units: millimetres throughout.
- Coordinates: floating-point, 6 decimal places.
- Archive: gzip-compressed tar (`.tgz`), pure Python `tarfile` — no Mentor
  binary or proprietary SDK required.
- Soldermask layers use `polarity=negative` (openings are positive features).
