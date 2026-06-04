# arch_check_slab_on_grade

*Module: `kerf_cad_core.arch.slab_on_grade_tools` · Domain: cad*

## Description

Check concrete slab-on-grade thickness adequacy under a concentrated point or wheel load per ACI 360R-10 / Westergaard (1948) interior load model.

Theory (PCA EB119 simplified Westergaard):
  l = [E·h³/(12·(1−ν²)·k)]^0.25   [radius of relative stiffness, mm]
  σ_max = 3·P·(1+ν)/(2·π·h²)·(log₁₀(l/b)+0.5)   [interior load, MPa]
  MR = 0.62·√f'c   [modulus of rupture, MPa]
  DCR = σ_max / MR;   joint_spacing ≤ 30·h (PCA 30×h rule)

Returns: radius_of_relative_stiffness_l_mm, max_bending_stress_MPa, modulus_of_rupture_MR_MPa, dcr, adequate (bool), recommended_joint_spacing_m, honest_caveat.

SCOPE: Interior load only — edge / corner positions have higher stress (Westergaard 1948); thermal curling not modelled; single load; unreinforced/crack-control slab only. All inputs in mm and MPa; load in kN; k in MPa/m.

## Input schema

```json
{
  "type": "object",
  "required": [
    "slab_thickness_mm",
    "fc_MPa",
    "subgrade_modulus_k_MPa_per_m",
    "point_load_kN",
    "contact_radius_mm",
    "slab_long_dimension_m"
  ],
  "properties": {
    "slab_thickness_mm": {
      "type": "number",
      "description": "Slab thickness h (mm).  Must be > 0.  Typical warehouse floors: 100\u2013200 mm."
    },
    "fc_MPa": {
      "type": "number",
      "description": "Specified compressive strength f'c (MPa).  Must be > 0.  Typical slab-on-grade: 25\u201335 MPa."
    },
    "subgrade_modulus_k_MPa_per_m": {
      "type": "number",
      "description": "Modulus of subgrade reaction k (MPa/m = kN/m\u00b3).  Must be > 0.  Typical values: very soft \u2248 13\u201327 MPa/m; medium \u2248 27\u201355 MPa/m; dense/stiff \u2248 55\u2013110 MPa/m; rock \u2265 140 MPa/m.  Obtained from ASTM D1196 plate-bearing test."
    },
    "point_load_kN": {
      "type": "number",
      "description": "Applied concentrated or wheel load P (kN).  Must be > 0.  For a multi-axle vehicle use the heaviest single wheel load."
    },
    "contact_radius_mm": {
      "type": "number",
      "description": "Radius of load contact area (mm).  Must be > 0.  For a circular tyre load: b = sqrt(P / (\u03c0\u00b7p_tyre)) where p_tyre is tyre inflation pressure.  For a square rigid pad of side a: b = sqrt(a\u00b2/\u03c0)."
    },
    "slab_long_dimension_m": {
      "type": "number",
      "description": "Longer plan dimension of the slab panel (m).  Must be > 0.  Used to contextualise the joint spacing recommendation."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_slab_on_grade",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
