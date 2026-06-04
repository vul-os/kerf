# nurbs_fresnel_parameterize_curve

*Module: `kerf_cad_core.geom.fresnel_parameterize` · Domain: cad*

## Description

Re-parameterize a NURBS curve so that curvature grows linearly with arc-length: κ(s) ≈ target_kappa_rate · s — the Euler spiral (clothoid) law used for road/rail transition curves, drift-free CNC toolpaths, and smooth motion-control profiles.

Method: samples the input at arc-length–uniform points, evaluates Fresnel integrals C(s), S(s) (Abramowitz-Stegun §7.3) to build a Fresnel-shaped parameter sequence, then fits a degree-3 NURBS through the original geometric points with those parameters.

HONEST LIMITATIONS:
- Sampling-based (not closed-form): accuracy scales with num_samples.
- Degree-1 polylines return a caveat (curvature undefined).
- Fresnel monotone-blend kicks in when the spiral winds > 1.5 rad.

References: Walton & Meek (2009), Bertolazzi & Frego (2015).

Returns: {ok, control_points, knots, degree, max_curvature_residual, fresnel_C, fresnel_S, honest_caveat}
Errors: {ok:false, reason}.  Never raises.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "control_points": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        }
      },
      "description": "NURBS control points [[x,y,...], ...]."
    },
    "knots": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "NURBS knot vector."
    },
    "degree": {
      "type": "integer",
      "description": "Curve degree."
    },
    "weights": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Per-control-point weights (omit for non-rational)."
    },
    "num_samples": {
      "type": "integer",
      "description": "Number of arc-length uniform samples (default 200). More samples \u2192 better Fresnel approximation."
    },
    "target_kappa_rate": {
      "type": "number",
      "description": "Rate \u03b1 \u2265 0 such that target \u03ba(s) = \u03b1 \u00b7 s (default 1.0). Dimensionally: 1/length\u00b2 (if arc-length is in length units)."
    }
  },
  "required": [
    "control_points",
    "knots",
    "degree"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="nurbs_fresnel_parameterize_curve",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
