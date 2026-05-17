# Electronic workflow

End-to-end guide: schematic capture → netlist + ERC → autoplace → DRC →
fab bundle (Gerber/Excellon/PnP/IPC-2581) + pre-compliance (SI / EMC / PDN /
thermal).

All electronics logic lives in `packages/kerf-electronics/`. Schematic
capture uses the **tscircuit** TSX format (`.circuit.tsx`). PCB layout is
stored as a structured JSON document within the file's `content` field.

---

## 1. Schematic capture

Create a `.circuit.tsx` file (kind `circuit`):

```
POST /api/projects/{pid}/files
{ "name": "usb_power.circuit.tsx", "kind": "circuit", "content": "" }
```

Then use the LLM to populate it:

```
create_circuit    — scaffold a .circuit.tsx with version field and defaults
search_kerf_docs("circuit tscircuit")
→ read /docs/llm/circuit.md   — full JSX patterns + selector syntax
→ edit_file to add components and nets
```

The schematic is a React-like JSX tree. Example excerpt:

```tsx
<circuit>
  <resistor id="R1" resistance="10kohm" footprint="0402" />
  <capacitor id="C1" capacitance="100nf" footprint="0402" />
  <net id="VCC" />
  <trace from="R1.pin1" to="VCC" />
</circuit>
```

The `circuit.md` LLM doc (in `packages/kerf-electronics/src/kerf_electronics/llm_docs/`)
covers component primitives, net declarations, bus notation, and the full
selector syntax for accessing elements programmatically.

---

## 2. Hierarchical schematics

For multi-sheet designs, use the hierarchy tools:

```
add_sub_sheet           — add a child sheet; returns the new sheet file ID
add_global_label        — add a global net label visible across all sheets
add_hierarchical_label  — add a port on a sub-sheet's boundary
flatten_hierarchy       — merge all sheets into a single flat netlist
validate_hierarchy      — check: are all hierarchical labels connected?
add_bus / expand_bus    — bus notation for parallel nets (e.g. DATA[0:7])
add_differential_pair   — declare USB±, LVDS, HDMI pairs for length matching
```

These live in `kerf_electronics.tools.hier_schematic` and
`kerf_electronics.tools.buses`.

---

## 3. Electrical rules check (ERC)

```
run_erc   — runs all ERC rules on the active schematic file
```

Returns a list of violations:

```json
[
  { "kind": "unconnected_pin", "ref": "U1.pin3", "severity": "error" },
  { "kind": "net_not_driven", "net": "VOUT", "severity": "warning" }
]
```

ERC rules include: unconnected pins, nets with no driver, power pins shorted,
conflicting voltage levels. Custom rules can be added via the LLM doc at
`/docs/llm/erc_rules.md`.

---

## 4. Netlist export

After ERC is clean, export the netlist:

```
search_kerf_docs("netlist export")
→ use the export API or the IPC-D-356A tool
```

REST:
```
GET /api/projects/{pid}/export?format=netlist
```

The netlist is also consumed by the PCB autoplace and DRC steps internally.

---

## 5. PCB autoplace and routing

### Autoplace

```
autoroute_circuit   — runs the freerouting-based autoplacer + autorouter
                      on the active .circuit.tsx file
```

This calls `kerf_electronics.freerouting` which interfaces with the
FreeRouting engine. The result populates component positions and initial trace
routes back into the file.

### Manual routing

Trace and via tools:

```
route_trace_segments   — add trace segments between pads
delete_trace / split_trace / merge_traces / move_trace_vertex
add_via_stitching      — add via stitching to a copper pour
apply_teardrops        — add teardrops to pad entrances
route_with_shove       — shove-router: push existing traces out of the way
```

### Net classes

Set trace widths and clearances per net class:

```
define_net_class("Power", width_mils=40, clearance_mils=12)
assign_net_to_class("VCC", "Power")
assign_net_to_class("GND", "Power")
get_effective_net_rules   — verify which rules apply to a net
```

### Length matching

For high-speed signals:

```
set_trace_target_length("USB_DP", target_mm=45.0, tolerance_mm=0.5)
tune_trace_to_target      — meander the trace to hit the target length
match_diff_pair           — equalise length within a differential pair
report_diff_pair_skew     — report current skew of a diff pair
```

### Copper pours

```
add_copper_pour     — flood a net (usually GND) on a layer
delete_copper_pour
set_pour_net        — change the poured net
set_pour_clearance  — gap from other copper
```

---

## 6. PCB layer management

```
add_pcb_layer / remove_pcb_layer
set_pcb_layer_visibility / set_pcb_layer_color
reorder_pcb_layers
set_board_layer_count   — 2, 4, 6, 8 layer stackup
assign_to_layer         — move a copper object to a different layer
```

Layer tools live in `kerf_electronics.tools.pcb_layer_tools`.

---

## 7. Design rules check (DRC)

```
run_pcb_drc    — run all DRC rules on the board
set_drc_rule   — define a custom clearance, width, or via rule per net class
```

DRC rules check: minimum trace width, pad-to-pad clearance, annular ring,
drill-to-copper, board edge clearance, impedance violations (when stackup is
defined), and differential pair skew.

Manufacturing presets (JLC, OSH Park, PCBWay, generic 2-layer/4-layer) are
bundled in `kerf_electronics/dfm/` and applied via the DRC preset selector.

---

## 8. Pre-compliance analysis

Signal integrity, EMC, PDN, and thermal checks run before generating the fab
bundle. These are the analysis modules in `kerf_electronics/`:

### Signal integrity (`si/`)

```
run_simulation   — run a signal-integrity SPICE-based simulation
sim_job_status
import_touchstone — import a .s2p/.s4p Touchstone file for S-parameter analysis
```

The SI eye wizard (`si_eye_wizard.py`) generates eye diagrams from IBIS models.

### EMC (`emc/`, `emc_wizard.py`)

`emc_wizard.py` runs a pre-compliance EMC checklist:

- Decoupling capacitor placement and value selection
- Return path analysis (plane splits under high-speed traces)
- Common-mode filter insertion points
- ESD protection coverage

### PDN (`pdn/`, `pdn_wizard.py`)

`pdn_wizard.py` runs power delivery network analysis:

- DC voltage drop on power planes
- AC impedance profile vs. target impedance
- Decoupling capacitor resonance check
- Via inductance budget

### RF / microwave (`kerf_electronics.routes_rf`)

```
run_rf_study    — run an RF electromagnetic study
rf_job_status
```

RF study types: S-parameter extraction, antenna pattern, transmission-line
impedance, microstrip/stripline analysis via `kerf_electronics.si` and
`kerf_electronics.rfmatch`.

### Thermal (`thermal/`, `thermal_board.py`)

`thermal_board.py` runs a board-level thermal analysis: component junction
temperatures, copper fill thermal spreading, thermal via effectiveness.
Full FEA thermal is available via `kerf_electronics.thermal` and the
`kerf-fem` plugin.

---

## 9. Fabrication bundle

Once DRC is clean, generate the full fab bundle:

```
GET /api/projects/{pid}/export?format=fab_bundle
```

This calls `kerf_electronics.fab.bundle.build_bundle()` which assembles:

| Output file | Module | Standard |
|-------------|--------|----------|
| Gerber layers (copper, silk, mask, paste, outline) | `fab/gerber.py` | Gerber X2 |
| Excellon drill files | `fab/excellon.py` | Excellon 2 |
| Pick-and-place / centroid | `fab/pnp.py` | IPC-7351 |
| Bill of materials | `fab/fab_bom.py` | CSV + JSON |
| IPC-2581 assembly data | `fab/ipc2581.py` | IPC-2581B |
| IPC-D-356A netlist | (netlist tool) | IPC-D-356A |
| ODB++ (optional) | `fab/odbpp/writer.py` | ODB++ v8 |
| 3D STEP of board | `fab/board_step.py` | AP214 |
| IDF MCAD exchange | (IDF tool) | IDF v2/v3 |

The bundle is returned as a `.zip` download or stored as a derived artifact on
the file.

---

## 10. Differential pair workflow (example)

A complete USB 2.0 differential pair workflow from chat:

```
add_differential_pair("USB_DP", "USB_DM")
define_net_class("USB", width_mils=7, clearance_mils=7, diff_spacing_mils=7)
assign_net_to_class("USB_DP", "USB")
assign_net_to_class("USB_DM", "USB")
set_trace_target_length("USB_DP", 45.0, 0.5)
set_trace_target_length("USB_DM", 45.0, 0.5)
route_with_shove   (route the pair together)
match_diff_pair("USB_DP", "USB_DM")
report_diff_pair_skew("USB_DP", "USB_DM")
run_pcb_drc        (verify no impedance violations)
```

---

## Module map

| Module | Purpose |
|--------|---------|
| `schematic/` | Schematic document model |
| `tools/erc.py` | ERC rules |
| `tools/buses.py` | Bus / diff-pair declarations |
| `tools/hier_schematic.py` | Multi-sheet hierarchy |
| `tools/routing.py` | Trace routing |
| `tools/pour.py` | Copper pours |
| `tools/pcb_drc.py` | DRC |
| `tools/pcb_layer_tools.py` | Layer management |
| `tools/net_classes.py` | Net class rules |
| `tools/length_tuning.py` | Length matching + diff pair skew |
| `tools/via_stitching.py` | Via stitching + teardrops |
| `tools/shove_router.py` | Shove router |
| `tools/pad_overrides.py` | Mask / paste pad overrides |
| `tools/autoroute.py` | Autoroute via FreeRouting |
| `tools/rf.py` | RF study submission |
| `tools/sim.py` | SPICE / transient simulation |
| `freerouting/` | FreeRouting engine interface |
| `fab/gerber.py` | Gerber X2 output |
| `fab/excellon.py` | Excellon drill output |
| `fab/pnp.py` | Pick-and-place centroid |
| `fab/fab_bom.py` | Assembly BOM |
| `fab/ipc2581.py` | IPC-2581B output |
| `fab/bundle.py` | Full fab bundle assembler |
| `fab/board_step.py` | 3D STEP board export |
| `fab/odbpp/` | ODB++ writer |
| `si/` | Signal integrity |
| `si_eye_wizard.py` | Eye diagram from IBIS |
| `emc/`, `emc_wizard.py` | EMC pre-compliance |
| `pdn/`, `pdn_wizard.py` | PDN analysis |
| `thermal/`, `thermal_board.py` | Thermal analysis |
| `rfmatch/` | RF matching network |
| `stackup/` | Layer stackup impedance calculator |
| `dfm/` | DFM checks + manufacturing presets |
| `autoplace/` | Component placement |
| `sim_corner.py` | Corner simulation (process/voltage/temp) |

---

See also: [electronics.md](./electronics.md) · [llm-tools.md](./llm-tools.md) · [capabilities.md](./capabilities.md)
