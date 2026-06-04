# surfacing

*Module: `kerf_cad_core.surfacing` · Domain: cad*

This module registers **18** LLM tool(s):

- [`feature_sweep1`](#feature-sweep1)
- [`feature_sweep2`](#feature-sweep2)
- [`feature_network_srf`](#feature-network-srf)
- [`feature_blend_srf`](#feature-blend-srf)
- [`feature_to_solid`](#feature-to-solid)
- [`feature_boolean`](#feature-boolean)
- [`feature_surface_boolean`](#feature-surface-boolean)
- [`feature_trim_by_curve`](#feature-trim-by-curve)
- [`surface_continuity`](#surface-continuity)
- [`feature_surface_curvature_combs`](#feature-surface-curvature-combs)
- [`feature_blend_srf_g3`](#feature-blend-srf-g3)
- [`feature_zebra_analysis`](#feature-zebra-analysis)
- [`feature_class_a_check`](#feature-class-a-check)
- [`feature_global_continuity_audit`](#feature-global-continuity-audit)
- [`feature_g3_chain_blend`](#feature-g3-chain-blend)
- [`feature_fit_surface`](#feature-fit-surface)
- [`feature_isophote_analysis`](#feature-isophote-analysis)
- [`nurbs_extrude_variable`](#nurbs-extrude-variable)

---

## `feature_sweep1`

Append a `sweep1` node to a `.feature` file. Sweep1 sweeps a closed profile sketch along ONE open-curve path.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "profile_sketch_path": {
      "type": "string",
      "description": "Absolute path of the profile .sketch file."
    },
    "path_sketch_path": {
      "type": "string",
      "description": "Absolute path of the path .sketch file."
    },
    "scale": {
      "type": "number",
      "description": "Scale factor, default 1.0."
    },
    "twist_deg": {
      "type": "number",
      "description": "Twist along the sweep in degrees."
    },
    "mode": {
      "type": "string",
      "enum": [
        "auto",
        "frenet",
        "corrected_frenet"
      ],
      "description": "Frame mode for the sweep. 'auto' (default) \u2014 OCCT's built-in frame, no twist correction. 'frenet' \u2014 classic Frenet\u2013Serret frame; fast but can exhibit roll on near-inflection paths. 'corrected_frenet' \u2014 tangent-locked corrected Frenet frame (OCCT SetMode_5); eliminates roll artefacts on coils, jewellery shanks, and any path with high curvature variation. If the OpenCASCADE.js build lacks SetMode_5, the worker silently falls back to the default frame and sets degraded:true in the evaluation result."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "profile_sketch_path",
    "path_sketch_path"
  ]
}
```

---

## `feature_sweep2`

Append a `sweep2` node to a `.feature` file. Sweep2 sweeps a closed profile sketch along TWO open-curve rails.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "profile_sketch_path": {
      "type": "string",
      "description": "Absolute path of the profile .sketch (closed wire)."
    },
    "rail1_sketch_path": {
      "type": "string",
      "description": "Absolute path of the first rail .sketch (open curve)."
    },
    "rail2_sketch_path": {
      "type": "string",
      "description": "Absolute path of the second rail .sketch (open curve)."
    },
    "twist_deg": {
      "type": "number",
      "description": "Twist along the sweep, degrees."
    },
    "scale_end": {
      "type": "number",
      "description": "End-section scale, default 1."
    },
    "mode": {
      "type": "string",
      "enum": [
        "auto",
        "frenet",
        "corrected_frenet"
      ],
      "description": "Frame mode for the sweep; default auto."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "profile_sketch_path",
    "rail1_sketch_path",
    "rail2_sketch_path"
  ]
}
```

---

## `feature_network_srf`

Append a `network_srf` node to a `.feature` file. NetworkSrf fits a NURBS surface to a U/V grid of curves.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "u_paths": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Absolute paths of the U-direction .sketch files (\u22652)."
    },
    "v_paths": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Absolute paths of the V-direction .sketch files (\u22652)."
    },
    "options": {
      "type": "object",
      "properties": {
        "continuity": {
          "type": "string",
          "enum": [
            "C0",
            "C1",
            "C2"
          ],
          "description": "Continuity, default C1."
        },
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "u_paths",
    "v_paths"
  ]
}
```

---

## `feature_blend_srf`

Append a `blend_srf` node to a `.feature` file. BlendSrf builds a smooth G0/G1/G2 surface that bridges two existing edges of a body.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "target_id": {
      "type": "string",
      "description": "Existing feature node id whose edges these belong to."
    },
    "edge1_id": {
      "type": "integer",
      "description": "First edge id (post-evaluation)."
    },
    "edge2_id": {
      "type": "integer",
      "description": "Second edge id."
    },
    "options": {
      "type": "object",
      "properties": {
        "continuity": {
          "type": "string",
          "enum": [
            "G0",
            "G1",
            "G2"
          ],
          "description": "Continuity, default G1."
        },
        "id": {
          "type": "string"
        },
        "blend_dist": {
          "type": "number",
          "description": "Blend distance."
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_id",
    "edge1_id",
    "edge2_id"
  ]
}
```

---

## `feature_to_solid`

Append a `to_solid` node to a `.feature` file. Promotes the named feature's surface output (a TopoDS_Face / Shell / sewn-face collection) to a TopoDS_Solid via BRepBuilderAPI_Sewing + MakeSolid. Required as a preparatory step before `feature_boolean` can consume a surface body.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "target_id": {
      "type": "string",
      "description": "Existing feature node id whose output to promote."
    },
    "options": {
      "type": "object",
      "properties": {
        "tolerance": {
          "type": "number",
          "description": "Sewing tolerance in model units (default 1e-6, raise for noisy NURBS)."
        },
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_id"
  ]
}
```

---

## `feature_boolean`

Append a `boolean` node to a `.feature` file. Performs a CSG-style operation between two existing feature bodies. Both targets must resolve to TopoDS_Solid — if either is a surface, run `feature_to_solid` on it first.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "target_a_id": {
      "type": "string",
      "description": "First operand (the 'A' side; the one preserved on cut)."
    },
    "target_b_id": {
      "type": "string",
      "description": "Second operand (the 'B' side; the tool body on cut)."
    },
    "kind": {
      "type": "string",
      "enum": [
        "cut",
        "fuse",
        "common"
      ],
      "description": "cut = A \u2212 B, fuse = A \u222a B, common = A \u2229 B."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_a_id",
    "target_b_id",
    "kind"
  ]
}
```

---

## `feature_surface_boolean`

Append a `surface_boolean` node to a `.feature` file. Performs a surface-direct CSG operation between two feature bodies (`cut` = A − B, `fuse` = A ∪ B, `common` = A ∩ B). Unlike `feature_boolean`, operands do NOT need to be solids — Face, Shell, and Solid shapes are all accepted. Returns a compound of trimmed face fragments. Use when you want to intersect or subtract two NURBS surfaces without the solid round-trip imposed by `feature_to_solid`. If the worker logs a BOPAlgo error with a C1-T10 escalation note, the current WASM build does not support non-solid operands; use `feature_boolean` (with `feature_to_solid` pre-pass) as a fallback.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "target_a_id": {
      "type": "string",
      "description": "First operand (the 'A' side; preserved on cut)."
    },
    "target_b_id": {
      "type": "string",
      "description": "Second operand (the 'B' side; the tool body on cut)."
    },
    "kind": {
      "type": "string",
      "enum": [
        "cut",
        "fuse",
        "common"
      ],
      "description": "cut = A \u2212 B, fuse = A \u222a B, common = A \u2229 B."
    },
    "fuzziness": {
      "type": "number",
      "description": "Intersection tolerance in model units (default 1e-4). Raise to 1e-3 if tangent-intersection face fragments go missing."
    },
    "coarse_mode": {
      "type": "boolean",
      "description": "Opt-in performance flag (default false). When true, skips the ShapeFix_Shape pre-pass and ShapeUpgrade_UnifySameDomain cleanup. Faster (~30-50% on dense NURBS) but may produce non-watertight face fragments. Use for preview renders or topology-optimisation intermediates where topological cleanliness is not critical."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_a_id",
    "target_b_id",
    "kind"
  ]
}
```

---

## `feature_trim_by_curve`

Append a `trim_by_curve` node to a `.feature` file. Splits a NURBS face along the UV-space projection of a 3D curve, keeping one side as the new current shape. Use when you want to cut a window or remove a region from a NURBS face without a solid round-trip — for example, cutting a stone-setting window into a ring shoulder or removing a teardrop from a blend surface. The cutter (`trim_curve_ref`) must be a sketch path or an already-evaluated feature id. The face is identified by `target_face_name` (use the positional face-N id from the inspector; persistent face naming is not yet shipped). WARNING: trim invalidates positional face-N IDs — downstream ops referencing the trimmed face by id will break on re-evaluation until persistent-face-naming ships (see docs/plans/persistent-face-naming.md). If the worker logs a TrimByCurveUnsupportedError, BRepFeat_SplitShape is absent in this WASM build; escalate to C2-T12 (Section+prism fallback).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "target_feature_ref": {
      "type": "string",
      "description": "Feature node id whose output contains the face to trim. Must be an earlier node in the same .feature file."
    },
    "target_face_name": {
      "type": "string",
      "description": "Positional face identifier (e.g. 'face-1', 'face-3') from the inspector's face list.  Persistent face names are not yet supported."
    },
    "trim_curve_ref": {
      "type": "string",
      "description": "Absolute .sketch path OR id of an already-evaluated feature body whose shape acts as the 3D cutter curve/wire."
    },
    "keep_side": {
      "type": "string",
      "enum": [
        "positive",
        "negative"
      ],
      "description": "'positive' (default) keeps the BRepFeat_SplitShape Left() result; 'negative' keeps the Right() result.  If the wrong side is kept, swap this value."
    },
    "tolerance": {
      "type": "number",
      "description": "Projection + split tolerance in model units (default 1e-3). Raise to 1e-2 if the projected wire has C1 discontinuities."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_feature_ref",
    "target_face_name",
    "trim_curve_ref"
  ]
}
```

---

## `surface_continuity`

Query or enforce surface continuity on a NURBS surfacing feature node in a .feature file. C0=positional, C1=tangent, C2=curvature for sweep1/sweep2/network_srf. G0/G1/G2=geometric continuity for blend_srf. If set_continuity is omitted, the tool reports the current value.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id."
    },
    "node_id": {
      "type": "string",
      "description": "ID of the surfacing node to inspect or modify."
    },
    "set_continuity": {
      "type": "string",
      "enum": [
        "C0",
        "C1",
        "C2",
        "G0",
        "G1",
        "G2"
      ],
      "description": "If provided, update the node's continuity to this value. Omit to query only."
    }
  },
  "required": [
    "file_id",
    "node_id"
  ]
}
```

---

## `feature_surface_curvature_combs`

Append a `surface_curvature_combs` node to a `.feature` file. Samples principal curvatures (k1/k2, mean, Gaussian) on the target NURBS feature's faces via GeomLProp_SLProps and displays an interactive curvature-comb overlay in the viewport (Three.js LineSegments: blue=concave, red=convex, white=flat; comb length = curvature × scale_factor). Use this to verify G2/G3 continuity at face junctions visually — e.g. after a blend_srf between a shank sweep and a bezel, inspect the curvature combs to confirm the tangency match looks smooth. NOTE: This is visualisation-only on the OCCT path. Algorithmic G3 enforcement is structurally impossible in stock OCCT (GeomAbs_G3 absent from GeomAbs_Shape enum). When `include_g3_residuals=true` and the target is a pure-Python NurbsSurface (not an OCCT body), the node stores a `g3_residuals` column computed by the analytic `curvature_rate_continuity_residual` oracle (GK-62) — bypassing OCCT entirely.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_feature_ref": {
      "type": "string",
      "description": "Node id of the feature whose face(s) to sample (e.g. 'blend_srf-1', 'sweep1-2'). Must exist in the evaluated tree before this node."
    },
    "target_face_name": {
      "type": "string",
      "description": "Optional. If set, sample only the named face (positional id like 'face-0'); otherwise all faces on the target body are sampled."
    },
    "uv_density": {
      "type": "number",
      "description": "UV grid step as a fraction of the parameter range (default 0.1 \u2192 ~10\u00d710 sample grid per face). Smaller values produce finer combs but increase worker compute time. Range: 0.01\u20130.5."
    },
    "scale_factor": {
      "type": "number",
      "description": "Comb line length multiplier: line_length = max(|k1|, |k2|) \u00d7 scale_factor (default 10). Increase for nearly-flat surfaces; decrease for high-curvature surfaces where combs would overshoot."
    },
    "show_combs": {
      "type": "boolean",
      "description": "Initial overlay visibility toggle (default true). The overlay panel also exposes this as an on/off toggle so the user can hide combs without removing the node."
    },
    "include_g3_residuals": {
      "type": "boolean",
      "description": "When true, store a `g3_residuals` column in the node for pure-Python NurbsSurface targets (OCCT path cannot compute G3). The worker calls `curvature_rate_continuity_residual` (GK-62 oracle) and attaches the per-seam-sample residuals to the result. Has no effect when the target is an OCCT body. Default false."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_feature_ref"
  ]
}
```

---

## `feature_blend_srf_g3`

Append a `blend_srf_g3` node to a `.feature` file. Builds a **G3 (curvature-rate-continuous) degree-7 Bézier blend strip** between two existing NURBS surfaces (GK-62). G3 = positional + tangent + curvature + curvature-rate continuity at both seams — the highest analytic continuity class; required for automotive Class-A and fine jewellery surfacing. The oracle `curvature_rate_continuity_residual` is evaluated after construction; residual > 1e-5 is reported as a warning in the result. Set `trim_and_sew=true` to also call `g3_blend_trim_sew`, which trims the two support surfaces to the blend seam and sews all three into a closed Body (bounded to analytic carrier matrix: plane / world-axis cylinder / sphere). The `continuity` field is always 'G3' — this node does not accept G0/G1/G2.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_id": {
      "type": "string",
      "description": "Existing feature node id whose edges these belong to."
    },
    "edge1_id": {
      "type": "integer",
      "description": "First edge id (post-evaluation)."
    },
    "edge2_id": {
      "type": "integer",
      "description": "Second edge id."
    },
    "blend_dist": {
      "type": "number",
      "description": "Blend distance / strip width in model units (default 2.0)."
    },
    "samples": {
      "type": "integer",
      "description": "Seam sample count for the G3 strip (default 24, min 8)."
    },
    "trim_and_sew": {
      "type": "boolean",
      "description": "If true, also call g3_blend_trim_sew to trim support surfaces and sew all three into a closed Body. Requires analytic carrier (plane / world-axis cylinder / sphere); returns unsupported-input for arbitrary NURBS. Default false."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_id",
    "edge1_id",
    "edge2_id"
  ]
}
```

---

## `feature_zebra_analysis`

Append a `zebra_analysis` node to a `.feature` file. Runs the **zebra / reflection-line continuity analyser** (GK-38) on the shared edge between two NURBS feature surfaces and returns stripe-break flags for G0 (positional), G1 (tangent), and G2 (curvature) continuity. This is a **read-only analysis node** — it does not modify any geometry. Results include per-sample stripe intensities, a G1/G2 break boolean, and reflection-line data from `reflection_lines`. Use after a `blend_srf` or `blend_srf_g3` to verify the join quality matches the Class-A acceptance standard.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "surface_a_ref": {
      "type": "string",
      "description": "Feature node id of the first surface body."
    },
    "surface_b_ref": {
      "type": "string",
      "description": "Feature node id of the second surface body."
    },
    "shared_edge_pts": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "3-D polyline along the shared edge \u2014 list of [x, y, z] points (at least 2). Typically copied from an inspector face/edge report.",
      "minItems": 2
    },
    "num_samples": {
      "type": "integer",
      "description": "Stripe sample count along the edge (default 20, min 4)."
    },
    "n_stripes": {
      "type": "integer",
      "description": "Number of zebra stripes (default 8)."
    },
    "g1_tol": {
      "type": "number",
      "description": "G1 stripe-tangent break threshold (default 0.05)."
    },
    "g2_tol": {
      "type": "number",
      "description": "G2 stripe-curvature break threshold (default 0.5)."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "surface_a_ref",
    "surface_b_ref",
    "shared_edge_pts"
  ]
}
```

---

## `feature_class_a_check`

Append a `class_a_check` node to a `.feature` file. Runs the **Class-A acceptance harness** (GK-64) on the shared edge between two NURBS feature surfaces, and optionally also runs the **Class-A leading quality pass** (hot-spot detection) on each surface individually. The acceptance harness runs three passes: (1) curvature combs — flags inflection-free issues; (2) zebra / reflection-line — detects G0/G1/G2 stripe breaks; (3) G0/G1/G2/G3 gate — per-grade boolean pass/fail. The leading pass (when `run_leading=true`) flags comb-peak, zebra-break, and G3-dropout hot-spots on each surface. This is a **read-only analysis node** — does not modify geometry. Results include a per-gate verdict dict and any hot-spot list.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "surface_a_ref": {
      "type": "string",
      "description": "Feature node id of the first surface body."
    },
    "surface_b_ref": {
      "type": "string",
      "description": "Feature node id of the second surface body."
    },
    "shared_edge_pts": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "3-D polyline along the shared edge \u2014 list of [x, y, z] points (at least 2).",
      "minItems": 2
    },
    "num_samples": {
      "type": "integer",
      "description": "Sample count for the acceptance harness (default 20, min 4)."
    },
    "tolerance": {
      "type": "number",
      "description": "G0 positional tolerance (default 1e-4)."
    },
    "run_leading": {
      "type": "boolean",
      "description": "If true, also run the Class-A leading quality pass on each surface and include hot-spots in the result. Default false."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "surface_a_ref",
    "surface_b_ref",
    "shared_edge_pts"
  ]
}
```

---

## `feature_global_continuity_audit`

Append a `global_continuity_audit` node to a `.feature` file. Runs the **global continuity audit** (GK-138) on a feature body: walks every shared edge in the body and classifies each as G0 / G1 / G2 / G3 (or below_G0 for positional gaps). This is a **read-only analysis node** — does not modify geometry. Returns a per-edge continuity report and a summary count by grade. Useful for validating that a blend chain or complex surface assembly achieves the target continuity everywhere — not just at the last seam.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_feature_ref": {
      "type": "string",
      "description": "Feature node id whose Body to audit."
    },
    "tol": {
      "type": "number",
      "description": "G0 positional tolerance in model units (default 1e-4)."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_feature_ref"
  ]
}
```

---

## `feature_g3_chain_blend`

Append a `g3_chain_blend` node to a `.feature` file. Builds a **G3 (curvature-accel-continuous) blend along a multi-edge tangent chain** (GK-132). For each edge in the chain, constructs a degree-7 G3 NURBS blend strip with both adjacent support faces. Because every strip uses the same `radius`, the normal curvature κ=1/r is identical at all chain junctions — no G2 break across the chain. Single-edge input degenerates to a standard G3 edge blend with residual. The edge ids must form a tangent-continuous chain — use `tangent_edge_chain` (accessible via the geometry inspector) to build the list from a seed edge.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "target_id": {
      "type": "string",
      "description": "Existing feature node id whose Body these edges belong to."
    },
    "edge_ids": {
      "type": "array",
      "items": {
        "type": "integer"
      },
      "description": "Ordered list of Edge.id values forming a tangent-continuous chain (at least 1). A single element degenerates to a single G3 blend.",
      "minItems": 1
    },
    "radius": {
      "type": "number",
      "description": "Rolling-ball fillet radius > 0 (model units)."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "target_id",
    "edge_ids",
    "radius"
  ]
}
```

---

## `feature_fit_surface`

Append a `fit_surface` node to a `.feature` file. Fits a **NURBS surface to an ordered (m×n) point grid** (GK-34) using centripetal chord-length parametrisation + Piegl–Tiller knot placement (P&T §9.4.1). Equivalent to Rhino's 'Patch' command for regular grids. The U refinement loop runs first; then V is refined holding U fixed — control-point count increases until max_deviation ≤ tol or max_ctrl is reached (best-effort surface returned when tol is not met). Input is a JSON-serialisable m×n×3 array of 3-D data points. For unordered / scattered input, pre-sort into a grid before calling.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "points_grid": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "array",
          "items": {
            "type": "number"
          },
          "minItems": 3,
          "maxItems": 3
        }
      },
      "description": "Ordered m\u00d7n grid of 3-D data points: outer list = m rows, inner list = n columns, each point = [x, y, z]. m \u2265 degree_u+1, n \u2265 degree_v+1.",
      "minItems": 2
    },
    "degree_u": {
      "type": "integer",
      "description": "B-spline degree in U (1\u20135, default 3)."
    },
    "degree_v": {
      "type": "integer",
      "description": "B-spline degree in V (1\u20135, default 3)."
    },
    "tol": {
      "type": "number",
      "description": "Target maximum Euclidean deviation between input points and fitted surface (default 1e-3, same units as input)."
    },
    "max_ctrl_u": {
      "type": "integer",
      "description": "Max control-point count in U (default 32)."
    },
    "max_ctrl_v": {
      "type": "integer",
      "description": "Max control-point count in V (default 32)."
    },
    "options": {
      "type": "object",
      "properties": {
        "id": {
          "type": "string"
        }
      }
    }
  },
  "required": [
    "file_id",
    "points_grid"
  ]
}
```

---

## `feature_isophote_analysis`

Analyse isophote (environment-map) continuity of a NURBS surface feature node (GK-P11). 

Samples the illumination scalar μ = n̂·L̂ over a UV grid and discretises into `sphere_map_res` equal-angle bands. Detects **isophote breaks** — cells where the band index jumps by ≥ 2 across an adjacent cell — which are the visual signature of a G1 (tangent) discontinuity. 

**Read-only** — does NOT append a feature node. Returns analysis data: `has_break` (bool), `num_breaks` (int), `mu_grid`, `band_grid`, `gradient_grid`, `isophote_break_mask`, `normal_grid`, `us`, `vs`. 

Use to verify Class-A surface quality before committing to a blend or match-surface step. A surface with `has_break: false` is G1-smooth under the chosen light direction.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the .feature file containing the surface."
    },
    "target_id": {
      "type": "string",
      "description": "Id of the NURBS surface node to analyse."
    },
    "uv_grid": {
      "type": "array",
      "items": {
        "type": "integer",
        "minimum": 3,
        "maximum": 200
      },
      "minItems": 2,
      "maxItems": 2,
      "description": "Grid resolution [nu, nv] (default [48, 48]).",
      "default": [
        48,
        48
      ]
    },
    "sphere_map_res": {
      "type": "integer",
      "description": "Number of equal-angle isophote bands on the environment-map sphere (default 16, minimum 2).",
      "minimum": 2,
      "maximum": 64,
      "default": 16
    },
    "light_dir": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "minItems": 3,
      "maxItems": 3,
      "description": "Directional light vector [x, y, z] (need not be normalised). Defaults to world-up [0, 0, 1]."
    }
  },
  "required": [
    "file_id",
    "target_id"
  ]
}
```

---

## `nurbs_extrude_variable`

Append a `nurbs_extrude_variable` node to a `.feature` file. Sweeps a profile that morphs along the path — e.g. circle at the start transitioning to an ellipse and ending as a rectangle. 

Supports three interpolation modes:
- `linear`        — piecewise-linear profile blending (C0 at section knots).
- `cubic_hermite` — Catmull-Rom Hermite (C1); smooth profile evolution.
- `C2`            — alias for `cubic_hermite`.


Each `section` entry pairs a path parameter `t ∈ [0, 1]` with a profile sketch.  At least one section is required; two or more produce the morphing effect.  The profile is placed in a rotation-minimising frame (Wang 2008) at each path sample so the sweep is torsion-free.

Related tools: `feature_sweep1` (constant profile, one path), `feature_sweep2` (constant profile, two rails).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the target .feature file."
    },
    "path_sketch_path": {
      "type": "string",
      "description": "Absolute path of the spine / path .sketch file (3-D open curve)."
    },
    "sections": {
      "type": "array",
      "minItems": 1,
      "description": "List of {t, sketch_path} objects defining the profile at each path parameter. t=0 is the start, t=1 the end.",
      "items": {
        "type": "object",
        "properties": {
          "t": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Path parameter at which this profile is placed."
          },
          "sketch_path": {
            "type": "string",
            "description": "Absolute path of the profile .sketch file."
          }
        },
        "required": [
          "t",
          "sketch_path"
        ]
      }
    },
    "interp": {
      "type": "string",
      "enum": [
        "linear",
        "cubic_hermite",
        "C2"
      ],
      "description": "Profile interpolation scheme (default 'linear').",
      "default": "linear"
    },
    "n_path_samples": {
      "type": "integer",
      "minimum": 2,
      "description": "Number of cross-sections along the path (default 20).",
      "default": 20
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "path_sketch_path",
    "sections"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
