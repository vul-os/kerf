# Trim By Curve Feature

Append a `trim_by_curve` node to a `.feature` file. Projects a 3D curve onto a
NURBS face and splits the face along that projection, keeping one side as the
new current shape. Requires no solid round-trip — operates directly on Face or
Shell topology.

Use this tool when the user wants to cut a window or remove a region from a NURBS
surface: for example, cutting a stone-setting window into a ring shoulder, removing
a teardrop from a blend surface, or punching an aperture into a swept hull.

---

## When to use

Reach for `feature_trim_by_curve` when the user asks about:

- cutting a hole or window into a NURBS face without converting to a solid
- trimming one side of a blend or sweep surface away using a sketch curve
- removing a region from a ring shoulder, hull panel, or architectural surface
- any surface-direct trim workflow (curve → face projection → split → keep side)

For solid-body cuts, use `feature_boolean` (`cut`) instead. For surface-direct
boolean operations between two bodies, use `feature_surface_boolean`.

---

## Tools

### `feature_trim_by_curve`

Append a `trim_by_curve` node. Projects `trim_curve_ref` onto `target_face_name`
of the body produced by `target_feature_ref` using `BRepProj_Projection` (primary)
with a `GeomAPI_ProjectPointOnSurf` fallback, then splits the face via
`BRepFeat_SplitShape`, keeping the `keep_side` half.

**Required:** `file_id`, `target_feature_ref`, `target_face_name`, `trim_curve_ref`

**Optional:**
- `keep_side` (`positive`/`negative`, default `positive`) — `positive` keeps
  `BRepFeat_SplitShape::Left()`; `negative` keeps `Right()`. If the wrong side
  is retained, flip this value.
- `tolerance` (positive number, default `1e-3`) — projection and split tolerance
  in model units (mm). Raise to `1e-2` if the projected wire has C1 discontinuities.
- `options.id` (string) — explicit node id; auto-generated if omitted.

**Returns:** `{file_id, id, op:"trim_by_curve", keep_side}`

**Warning — face-id invalidation:** trim invalidates positional `face-N` IDs on
the trimmed body. Downstream ops referencing the trimmed face by positional id
will break on re-evaluation until persistent-face-naming ships
(see `docs/plans/persistent-face-naming.md`). Use the inspector to re-identify
faces after each trim.

**Worker escalation:** if the worker logs a `TrimByCurveUnsupportedError`,
`BRepFeat_SplitShape` is absent in this WASM build. Escalate to the Section+prism
fallback (C2-T12).

---

## Example

**User ask:** "Cut a teardrop window into the shoulder of the ring sweep, keeping
the outer half."

```
1. feature_trim_by_curve
     file_id:"<uuid>"
     target_feature_ref:"sweep1-1"
     target_face_name:"face-2"
     trim_curve_ref:"/proj/window_outline.sketch"
     keep_side:"positive"
   → {id:"trim_by_curve-1", op:"trim_by_curve", keep_side:"positive"}
```

**User ask:** "Trim the blend surface to remove the region above the guide curve,
keeping the lower half."

```
1. feature_trim_by_curve
     file_id:"<uuid>"
     target_feature_ref:"blend_srf-1"
     target_face_name:"face-1"
     trim_curve_ref:"/proj/guide.sketch"
     keep_side:"negative"
     tolerance:0.01
   → {id:"trim_by_curve-1", op:"trim_by_curve", keep_side:"negative"}
```

---

## Notes

- The cutter (`trim_curve_ref`) must be a `.sketch` absolute path or the id of
  an already-evaluated feature body whose shape acts as the 3D cutter wire/curve.
- `target_face_name` uses the positional `face-N` id visible in the inspector
  (e.g. `face-1`, `face-3`). Persistent face names are not yet supported.
- Trim operates directly on Face/Shell topology — no `feature_to_solid` pre-step
  is needed or wanted.
- For the geometry back-end used by this op, see
  `kerf_cad_core.geom.trim_curve` (projection) and
  `kerf_cad_core.geom.trim_validation` (pre-flight checks).
- For the full surfacing toolkit overview, see `surfacing.md`.
