# Multi-Board 3D Assembly (MB3D)

> Combine multiple PCBs and their mechanical enclosures into a 3D assembly with connector alignment checks and board-to-board clearance validation.

**Module**: `packages/kerf-electronics/src/kerf_electronics/fab/board_step.py`
**Shipped**: Wave 10C1
**LLM tools**: `electronics_export_step`, `electronics_board_assembly`

---

## What it is

Complex electronics products contain multiple PCBs — a main board, a display daughtercard, a power module, a connector riser — all assembled in a shared enclosure. Multi-board 3D (MB3D) assembly validation ensures that boards fit within the housing, connectors on mating boards align, and no board-to-board or board-to-wall clearances are violated before committing to mechanical drawings. Kerf exports each board as a STEP file using its component 3D models and then places multiple boards in a common coordinate system.

## How to use it

### From chat

> "Generate the 3D assembly STEP for my two-board stack: main board at Z=0, daughtercard at Z=20 mm with a 20-pin 2 mm header connector. Check for clearance violations."

### From Python

```python
from kerf_electronics.fab.board_step import export_board_step

step_bytes = export_board_step(
    circuit_json=main_board,
    board_name="main_board",
    include_3d_models=True
)
with open("main_board.step", "wb") as f:
    f.write(step_bytes)
```

### From an LLM tool spec

```json
{"boards": [
  {"circuit_json_id": "<main>", "transform": {"z_mm": 0}},
  {"circuit_json_id": "<daughter>", "transform": {"z_mm": 20}}
], "check_clearance_mm": 1.0}
```

## How it works

`export_board_step` iterates the CircuitJSON `pcb_component` list, looks up the STEP model path from the component's `3d_model` attribute, applies the per-component placement transform (rotation, translation from the footprint origin), and assembles the result into a STEP AP214 compound solid using the OCCT `BRep_Builder`. For multi-board assembly, each board's STEP solid is transformed to the assembly coordinate frame. Clearance checking computes the minimum distance between bounding boxes of all component meshes across boards; pairs below the threshold are reported.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `export_board_step(circuit_json, board_name, include_3d_models)` | `bytes` | STEP AP214 board export |
| `assemble_boards(board_steps, transforms)` | `bytes` | Multi-board STEP assembly |
| `check_clearance(board_steps, min_clearance_mm)` | `list[dict]` | Clearance violation report |

## Example

```python
from kerf_electronics.fab.board_step import export_board_step
step = export_board_step(circuit_json, "demo_board", include_3d_models=False)
print(f"STEP file size: {len(step)/1024:.1f} kB")
```

## Honest caveats

Component 3D model lookup requires STEP files to be available at the paths stored in `3d_model` fields. If a model is missing, a placeholder bounding-box solid is used and a warning is emitted. The OCCT STEP writer requires `pythonocc-core`; without it the function falls back to IDF (simpler board-outline format). Flex/rigid-flex board topology is not handled — only rigid planar boards.

## References

- ISO 10303-214:2003 (STEP AP214) — Core data for automotive mechanical design processes.
- IPC-7351 (2011). *Land Pattern Naming Convention and Proportional Guidelines*, §3 (component 3D models).
