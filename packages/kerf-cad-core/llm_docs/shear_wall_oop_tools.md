# arch_check_shear_wall_oop

*Module: `kerf_cad_core.arch.shear_wall_oop_tools` · Domain: cad*

## Description

Check out-of-plane (OOP) flexural capacity of a reinforced concrete shear wall under combined axial load and lateral (wind/seismic) moment.

Checks performed (per ACI 318-19):
  1. Slenderness: h/t ≤ 30 (ACI §11.5.3)
  2. Empirical axial: φPn = 0.55·φ·f'c·Ag·[1−(k·h/(32·t))²] (ACI §11.7.5.1; k=0.8 default fixed-fixed)
  3. OOP flexure: rectangular stress block, unit-strip (ACI §22.3; both faces of steel); a=(As_total·fy)/(0.85·f'c·b); φMn=φ·As_total·fy·(d−a/2)
  4. Bresler linear interaction: DCR = Pu/φPn + Mu/φMn ≤ 1.0

Returns slenderness_h_over_t, slenderness_ok, phi_Pn_kN_per_m, phi_Mn_kNm_per_m, interaction_dcr, adequate, governing_check, honest_caveat.

SCOPE: Empirical ACI §11.7.5 only — NOT the slender-wall moment-magnifier (ACI §11.8 / §6.7.3). No P-delta. No biaxial bending. No in-plane shear (ACI §11.6/§18.10). Bresler linear interaction approximation. All inputs in mm and MPa; force in kN/m; moment in kNm/m.

## Input schema

```json
{
  "type": "object",
  "required": [
    "wall_thickness_t_mm",
    "wall_height_h_mm",
    "wall_length_lw_mm",
    "fc_MPa",
    "fy_MPa",
    "As_each_face_mm2_per_m",
    "axial_load_Pu_kN_per_m",
    "oop_moment_Mu_kNm_per_m"
  ],
  "properties": {
    "wall_thickness_t_mm": {
      "type": "number",
      "description": "Wall thickness t (mm).  Must be > 0."
    },
    "wall_height_h_mm": {
      "type": "number",
      "description": "Clear storey height h between lateral supports (mm). Must be > 0.  Governs slenderness h/t and empirical \u03c6Pn."
    },
    "wall_length_lw_mm": {
      "type": "number",
      "description": "Horizontal plan length of wall lw (mm). Informational \u2014 in-plane shear not checked here. Must be > 0."
    },
    "fc_MPa": {
      "type": "number",
      "description": "Concrete compressive strength f'c (MPa).  Must be > 0."
    },
    "fy_MPa": {
      "type": "number",
      "description": "Steel yield strength (MPa), e.g. 420.  Must be > 0."
    },
    "As_each_face_mm2_per_m": {
      "type": "number",
      "description": "Vertical reinforcement area on each face (mm\u00b2/m of wall width). Total steel for OOP flexure = 2 \u00d7 this value. Must be \u2265 0."
    },
    "axial_load_Pu_kN_per_m": {
      "type": "number",
      "description": "Factored axial compressive load per unit wall width (kN/m). Must be \u2265 0.  Tensile uplift not supported."
    },
    "oop_moment_Mu_kNm_per_m": {
      "type": "number",
      "description": "Factored out-of-plane bending moment demand per unit width (kNm/m).  Must be \u2265 0."
    },
    "k_factor": {
      "type": "number",
      "description": "ACI \u00a711.7.5.1 effective-height factor k. Default 0.8 (restrained top + bottom against rotation). Use 1.0 for cantilever walls (free top)."
    },
    "cover_mm": {
      "type": "number",
      "description": "Clear concrete cover to reinforcement (mm). Default 25 mm.  Used to compute effective depth d."
    },
    "bar_spacing_mm": {
      "type": "number",
      "description": "Assumed vertical bar spacing for effective-depth back-calculation (mm). Default 200 mm."
    },
    "phi": {
      "type": "number",
      "description": "ACI strength-reduction factor \u03c6 for compression-controlled walls. Default 0.65 per ACI 318-19 Table 21.2.2."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_shear_wall_oop",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
