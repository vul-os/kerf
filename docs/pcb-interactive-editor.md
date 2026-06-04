# PCB Interactive Editor

> Push-and-shove routing, differential pair placement, copper pour, net-class assignment, and pad override tools for interactive PCB layout.

**Module**: `packages/kerf-electronics/src/kerf_electronics/routing/push_shove.py`, `tools/pour.py`, `tools/net_classes.py`
**Shipped**: Wave 9A2
**LLM tools**: `pcb_push_shove`, `pcb_route_diff_pair`, `pcb_pour`, `pcb_set_net_class`

---

## What it is

The PCB interactive editor provides the layout tools used after placement — routing, pours, and design intent constraints. Push-and-shove routing makes room for a new trace by temporarily displacing neighbouring tracks while respecting clearance rules. Differential pair routing keeps the positive and negative tracks coupled at a specified spacing. Copper pours fill unused copper with a net (typically GND) to reduce impedance and improve shielding.

## How to use it

### From chat

> "Route the USB D+ and D- signals as a differential pair with 0.1 mm spacing and 90Ω differential impedance. Then fill the GND pour on the top layer."

### From Python

```python
from kerf_electronics.routing.push_shove import route_diff_pair, validate_diff_pair
from kerf_electronics.tools.pour import pour_copper

dp_result = route_diff_pair(
    net_pos="USB_DP", net_neg="USB_DN",
    start={"x": 10, "y": 20}, end={"x": 80, "y": 20},
    spacing=0.1,
    board=circuit_json,
)
val = validate_diff_pair(dp_result["segs_pos"], dp_result["segs_neg"],
                          design_rules={"min_spacing_mm": 0.08})
print("Valid:", val["ok"])

poured = pour_copper(circuit_json, layer="F.Cu", net="GND", clearance=0.2)
```

### From an LLM tool spec

```json
{"action": "route_diff_pair",
 "net_pos": "USB_DP", "net_neg": "USB_DN",
 "start": [10,20], "end": [80,20],
 "spacing_mm": 0.1, "layer": "F.Cu"}
```

## How it works

Push-and-shove uses a vector-displacement algorithm: the new segment is extended until it would violate clearance with an existing segment; the obstructing segment is then displaced perpendicular to its path by the clearance amount, and its neighbours are dragged along. Differential pair routing extends push-and-shove with coupled parallel segments maintained at constant spacing; `tune_diff_pair_skew` adds serpentine meanders to the shorter trace to match lengths. Copper pour uses a point-in-polygon flood fill algorithm starting from the net's thermal-relief anchor points, respecting clearances.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `push_shove_segment(existing, new_seg, board, rules)` | `dict` | Push-and-shove placement |
| `route_diff_pair(net_pos, net_neg, start, end, spacing, board)` | `dict` | Coupled pair routing |
| `tune_diff_pair_skew(segs, target_length_diff_mm)` | `list` | Length-match serpentine |
| `validate_diff_pair(segs_pos, segs_neg, rules)` | `dict` | Coupling + length check |
| `pour_copper(circuit_json, layer, net, clearance)` | `dict` | GND/power plane fill |

## Example

```python
from kerf_electronics.routing.push_shove import tune_diff_pair_skew
tuned = tune_diff_pair_skew(dp_result["segs_pos"], target_length_diff_mm=0.0)
print("Length skew:", tuned["achieved_skew_mm"])
```

## Honest caveats

Push-and-shove is a local algorithm — it cannot resolve global routing conflicts that require rip-up-and-reroute. Differential pair routing assumes straight-line topology; curved traces around obstacles are not supported. Copper pour does not optimise via-stitch placement for maximum shielding effectiveness; vias must be added manually.

## References

- Wadell, B.C. (1991). *Transmission Line Design Handbook*. Artech House. §3.7 (diff pair impedance).
- IPC-2141A (2004). *Controlled Impedance Circuit Boards and High Speed Logic Design*. §3.
