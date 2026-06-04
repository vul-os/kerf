# Keyframe F-Curves and Animation Clips

> Animate any numeric property with Bezier F-curves; evaluate clips at arbitrary time.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/animation/keyframe.py`
**Shipped**: Wave 9B2
**LLM tools**: `animation_evaluate_clip`

---

## What it is

F-curves store a property's value over time as a sequence of `Keyframe` objects connected by Bezier handles. An `FCurve` evaluates to an interpolated value at any time `t`. `AnimClip` bundles multiple F-curves (one per animated property) into a named animation clip, mirroring Blender's Action / NLA workflow.

## How to use it

### From chat

> "Create a 2-second animation clip that rotates an object from 0° to 180° with an ease-in-out curve."

### From Python

```python
from kerf_cad_core.animation.keyframe import Keyframe, FCurve, AnimClip

k0 = Keyframe(time=0.0, value=0.0, handle_right=(0.5, 0.0))
k1 = Keyframe(time=2.0, value=180.0, handle_left=(1.5, 180.0))
curve = FCurve(property_path="rotation_z", keyframes=[k0, k1])

clip = AnimClip(name="spin", duration=2.0, fcurves={"rotation_z": curve})
angle_at_1s = clip.evaluate("rotation_z", t=1.0)
print(f"Angle at t=1s: {angle_at_1s:.2f}°")   # ≈ 90°
```

### From an LLM tool spec

```json
{"tool": "animation_evaluate_clip", "input": {"clip_name": "spin", "duration": 2.0, "fcurves": {"rotation_z": {"keyframes": [{"time": 0, "value": 0}, {"time": 2, "value": 180}]}}, "query_time": 1.0}}
```

## How it works

Each pair of consecutive keyframes is interpolated as a cubic Bezier curve parameterised by time. The Bezier `t` parameter (separate from animation time) is solved with a Newton-Raphson root-find on the x-component. The resulting `t` is used to evaluate the y-component (property value). Array-valued properties (XYZ translation, quaternion rotation) apply the same logic per-component.

## API reference

| Class / Function | Purpose |
|---|---|
| `Keyframe(time, value, handle_left, handle_right)` | Single keyframe with Bezier handles |
| `FCurve(property_path, keyframes)` | Animated property curve |
| `AnimClip(name, duration, fcurves)` | Multi-curve animation clip |
| `FCurve.evaluate(t)` | Interpolated value at time `t` |

## Example

```python
curve = FCurve("tx", [Keyframe(0, 0), Keyframe(1, 10), Keyframe(2, 0)])
print(curve.evaluate(0.5))   # ≈ 7.5 (Bezier ease)
print(curve.evaluate(1.5))   # ≈ 7.5
```

## Honest caveats

Bezier handle positions are in animation-time units, not normalised [0, 1]. Handles that cross adjacent keyframe times (overlapping tangents) produce non-monotone time curves and may cause the Newton-Raphson solver to diverge. Extrapolation beyond the first/last keyframe uses the constant value at the boundary keyframe. Euler rotation F-curves do not perform gimbal-lock correction; use quaternion channels for rotations > 180°.

## References

- Blender Foundation, *Blender 4.x — F-Curves and Drivers* documentation (2024).
- Shoemake, "Animating Rotation with Quaternion Curves," *SIGGRAPH* (1985).
