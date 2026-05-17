# Toolpath Verification — `procsim/toolpath_verify.py`

Voxel/dexel-based G-code simulation for NC toolpath verification: material removal, gouging detection, remaining stock.

---

## Models

- **Voxel model** — cubic voxel grid representing the stock; tool subtracts material each move. Accurate for prismatic stock; memory proportional to `(nx × ny × nz)`.
- **Dexel model** — depth-pixel representation; efficient for 3-axis (Z-axis cutter); each XY cell stores a Z height. Faster and lower memory than voxel for typical milling.

---

## Public API

### `make_stock(dims_mm, *, model="dexel", resolution_mm=0.5) → StockModel`

Create a stock object from bounding dimensions `(x_mm, y_mm, z_mm)`.

`model`: `"voxel"` or `"dexel"`.

### `make_tool(tool_type, diameter_mm, *, flute_length_mm=None) → ToolModel`

`tool_type`: `"endmill_flat"`, `"endmill_ball"`, `"drill"`, `"face_mill"`.

### `simulate(gcode_text, stock, tool, *, feed_override=1.0, spindle_override=1.0) → SimResult`

Parse and simulate a G-code program against the stock.

`SimResult` fields:
```json
{
  "ok": true,
  "gouges": [],
  "remaining_volume_mm3": 4820.0,
  "material_removed_mm3": 18340.0,
  "line_count": 1842,
  "warnings": ["Rapid move at Z+5 crosses stock boundary (non-cutting — ok)"],
  "tool_path_length_mm": 12400.0
}
```

`gouges` is a list of `{"line": int, "xyz": [x,y,z], "depth_mm": float}` dicts.

### `remaining_stock_mesh(stock) → dict`

Returns a triangulated mesh dict `{"vertices": [...], "faces": [...]}` of the current stock state.

---

## Usage

```python
from kerf_cad_core.procsim.toolpath_verify import make_stock, make_tool, simulate

stock = make_stock((100, 80, 30), model="dexel", resolution_mm=0.5)
tool  = make_tool("endmill_flat", diameter_mm=10, flute_length_mm=25)

with open("program.nc") as f:
    gcode = f.read()

result = simulate(gcode, stock, tool)
if result["gouges"]:
    for g in result["gouges"]:
        print(f"Gouge at line {g['line']}: {g['xyz']}, depth {g['depth_mm']:.2f} mm")
```

---

## Notes

- Voxel model resolution: `resolution_mm=0.5` means 0.5 mm³ voxels. For 100×80×30 mm stock this is 100×80×30 / 0.125 ≈ 1.9M voxels — feasible.
- Dexel model is preferred for 3-axis operations; voxel is needed for 5-axis.
- G-code parser supports G00, G01, G02, G03, G17/18/19, G81–G83, M03/M05, tool changes (T/M06).
