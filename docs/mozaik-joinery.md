# Cabinet Joinery

> Generate mortise-tenon, dovetail, finger, dowel, biscuit, and pocket-screw joint geometries for CNC or manual work.

**Module**: `packages/kerf-woodworking/src/kerf_woodworking/joinery.py`
**Shipped**: Wave 10
**LLM tools**: `woodworking_mortise_tenon`, `woodworking_dovetail`, `woodworking_finger_joint`, `woodworking_dowel`, `woodworking_biscuit`, `woodworking_pocket_screw`

---

## What it is

The joinery module generates precise joint geometry dictionaries for each classic woodworking joint type. Each function returns the cut dimensions, tool paths (as offset distances and depths), and recommended tolerances for a loose, medium, or tight fit. The output is feed-forward to a CAM tool path or CNC router.

## How to use it

### From chat

> "Generate a mortise-and-tenon joint for a 44 mm × 100 mm rail into a 70 mm leg, medium fit."

### From Python

```python
from kerf_woodworking.joinery import mortise_tenon, dovetail, finger_joint

joint = mortise_tenon(
    rail_thickness_mm=44,
    rail_width_mm=100,
    leg_depth_mm=70,
    fit="medium",
)
print(joint["tenon_length_mm"], joint["mortise_width_mm"])

pins = dovetail(
    board_thickness_mm=18,
    board_width_mm=300,
    pin_angle_deg=8,
    n_pins=5,
)
print(pins["pin_width_mm"], pins["tail_width_mm"])
```

### From an LLM tool spec

```json
{"tool": "woodworking_mortise_tenon", "input": {"rail_thickness_mm": 44, "rail_width_mm": 100, "leg_depth_mm": 70, "fit": "medium"}}
```

## How it works

Each joint function applies empirical proportioning rules from Taunton / Fine Woodworking standards. Mortise-tenon: tenon length = 2/3 of leg depth, tenon thickness = 1/3 of rail thickness, mortise depth = tenon length + 1 mm clearance. Dovetail: pin angle 1:6 softwood / 1:8 hardwood, tail width proportional to board width / (n_pins + 0.5). Fit tolerance is ±0.05 mm (tight), ±0.1 mm (medium), ±0.15 mm (loose).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `mortise_tenon(...)` | `dict` | Mortise and tenon dimensions |
| `dovetail(...)` | `dict` | Pin and tail geometry |
| `finger_joint(...)` | `dict` | Box-joint finger dimensions |
| `dowel(...)` | `dict` | Dowel diameter, depth, spacing |
| `biscuit(...)` | `dict` | Biscuit slot position and depth |
| `pocket_screw(...)` | `dict` | Pocket angle, pilot hole, screw spec |

## Example

```python
joint = mortise_tenon(44, 100, 70, "medium")
# {'tenon_length_mm': 46.7, 'tenon_thickness_mm': 14.6,
#  'mortise_width_mm': 14.7, 'mortise_depth_mm': 47.7}
```

## Honest caveats

Proportioning rules are based on traditional joinery standards and apply to solid timber. MDF and plywood may require wider tenons for adequate glue surface. The module does not simulate joint stiffness or failure loads; for structural calculations use the structural frame module. CNC machine offsets (router bit radius) are not applied — add them in the CAM step.

## References

- Taunton Press, *Complete Illustrated Guide to Joinery* (2002).
- Hoadley, *Understanding Wood*, Taunton (2000), Ch. 12.
