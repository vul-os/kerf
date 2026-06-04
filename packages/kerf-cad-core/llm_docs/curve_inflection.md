# nurbs_find_curve_inflections

*Module: `kerf_cad_core.geom.curve_inflection` · Domain: cad*

## Description

Find inflection points of a 2D NURBS curve — parameter values t* where the signed curvature κ(t) changes sign.  Used for fairness analysis and naval-architecture/automotive Class-A surface validation.

An inflection point is where the curve transitions from bending left (κ > 0) to bending right (κ < 0) or vice-versa — the osculating circle switches side (Piegl-Tiller §5.3; Farin §10.6; do Carmo §1.5).

κ(u) = (x'·y'' − y'·x'') / (x'² + y'²)^1.5  [signed 2D curvature]

Algorithm: sample κ(u) at num_samples uniform u-values → adjacent sign-change detection (|κ| < tol treated as zero) → 5-iteration bisection refinement per bracket.

Returns CurveInflectionReport:
  inflection_points  : [{parameter_u, xy_mm, curvature_left, curvature_right, sign_change}, ...]
  num_inflections    : count
  max_curvature      : max |κ| over samples
  min_curvature      : min |κ| over samples
  is_fair_class_a    : True iff ≤ 1 inflection AND no abrupt κ-jump
  warnings           : list of diagnostic strings
  honest_caveat      : scope / accuracy caveats

Applications: Class-A fairness QC, sketch QC, toolpath transitions, clothoid / fresnel-transition design.

HONEST: 2D only — 3D space-curve torsion not supported.  Sampling-based, not analytical root-finding.  Never raises — returns {ok:false, reason} for invalid inputs.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "degree": {
      "type": "integer",
      "description": "B-spline degree (>= 1; degree 2+ needed for curvature)."
    },
    "control_points": {
      "type": "array",
      "description": "List of 2D control points [[x,y], ...] or [[x,y,z], ...] (z is ignored; curve must lie in XY-plane).",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      }
    },
    "knots": {
      "type": "array",
      "description": "Knot vector (non-decreasing, clamped).",
      "items": {
        "type": "number"
      }
    },
    "weights": {
      "type": "array",
      "description": "Optional per-control-point weights for rational NURBS.",
      "items": {
        "type": "number"
      }
    },
    "num_samples": {
      "type": "integer",
      "description": "Number of uniform parameter samples for detection (default 200)."
    },
    "tol": {
      "type": "number",
      "description": "Near-zero curvature tolerance; samples with |\u03ba| < tol are treated as zero.  Default 1e-6.  Raise to suppress false positives in near-flat regions."
    }
  },
  "required": [
    "degree",
    "control_points",
    "knots"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="nurbs_find_curve_inflections",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
