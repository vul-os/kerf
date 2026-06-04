# Grain Direction Checking

> Validate that all cabinet panels have grain running in the structurally and aesthetically required direction.

**Module**: `packages/kerf-woodworking/src/kerf_woodworking/grain.py`
**Shipped**: Wave 10
**LLM tools**: `woodworking_grain_check`

---

## What it is

The grain direction module checks a panel joint against a rule set that encodes which grain orientations are acceptable for each joint type and panel role. For example, cabinet doors require face-grain horizontal (or vertical by design intent); shelves require grain along the span. Violations are reported as warnings with a severity level (info, warning, error) and a plain-language explanation.

## How to use it

### From chat

> "Check that all door panels in my cabinet have face grain running horizontally."

### From Python

```python
from kerf_woodworking.grain import check_grain, add_grain_meta, GrainDirection

# Annotate a panel with grain direction
panel = {"label": "door_panel", "width_mm": 450, "height_mm": 600}
panel_with_grain = add_grain_meta(panel, grain=GrainDirection.HORIZONTAL)

# Check a joint between panels
joint = {
    "label": "door_in_frame",
    "joint_type": "panel_in_groove",
    "grain": GrainDirection.HORIZONTAL,
}
warnings = check_grain(joint)
for w in warnings:
    print(w["severity"], w["message"])
```

### From an LLM tool spec

```json
{"tool": "woodworking_grain_check", "input": {"joint_type": "panel_in_groove", "grain_direction": "horizontal"}}
```

## How it works

`check_grain` applies a lookup table of (joint_type, grain_direction) → (severity, message) pairs. The rule set encodes industry standards: cross-grain glue joints are flagged as errors (differential shrinkage causes splitting), face-grain on structural members is a warning (reduced stiffness), and end-grain glue surfaces are errors (poor adhesion). `add_grain_meta` attaches a `grain` field to a panel dict for downstream cut-list layout.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `check_grain(joint)` | `list[dict]` | Warning list for a single joint |
| `add_grain_meta(panel, grain)` | `dict` | Attach grain annotation to panel dict |
| `GrainDirection` | enum | `HORIZONTAL`, `VERTICAL`, `CROSS`, `FACE`, `END` |

## Example

```python
warnings = check_grain({"joint_type": "cross_grain_glue", "grain": GrainDirection.CROSS})
# [{'severity': 'error', 'message': 'Cross-grain glue joint: differential
#   shrinkage will cause splitting along the grain.', ...}]
```

## Honest caveats

The rule set covers common solid-timber and veneered-panel scenarios. Engineered products (LVL, OSB, CLT) have their own grain-direction requirements that are not fully encoded. Finish grain matching (sequential veneer slicing for book-matched doors) is not checked. Exotic species with interlocked or irregular grain are not supported.

## References

- Hoadley, *Understanding Wood*, Taunton (2000), Ch. 4–5.
- AWI *Quality Standards Illustrated*, 8th ed., §5 (2017).
