# arch_check_anchor_pullout

*Module: `kerf_cad_core.arch.anchor_bolt_pullout_tools` · Domain: cad*

## Description

Check cast-in-place headed anchor bolt(s) in pure tension per ACI 318-19 Chapter 17 + ACI 355.2.

Three ACI 318-19 §17.6 limit states are evaluated:
  1. Steel tensile strength (§17.6.1):
       A_se = 0.85·π·d²/4 (effective tensile area per ACI 355.2)
       φ·N_sa = φ_s · A_se · fy   (φ_s = 0.75 default)

  2. Concrete breakout in tension (§17.6.2):
       N_b = k_c · λ · √f'c · h_ef^1.5   [N, MPa, mm]  (k_c = 10 cracked / 14 uncracked, SI equivalent of ACI §17.6.2.2.1)
       A_Nco = 9·h_ef²
       A_Nc from projected cone geometry (clipped at edges / spacing)
       ψ_ed,N = 1.0 if c_a,min≥1.5·h_ef; else 0.7+0.3·c_a,min/(1.5·h_ef)  (§17.6.2.4.1)
       ψ_c,N = 1.0 cracked / 1.25 uncracked  (§17.6.2.5.1)
       φ·N_cb = φ_c · (A_Nc/A_Nco) · ψ_ed · ψ_c · N_b   (φ_c = 0.65 default)

  3. Concrete pullout — headed bolt (§17.6.3):
       N_p = 8 · A_brg · f'c  (§17.6.3.2)
       φ·N_pn = φ_c · N_p

Governing: min(φ·N_sa, φ·N_cb, φ·N_pn).

SCOPE: tension-only (no shear interaction §17.7); cracked concrete assumed by default (conservative); λ = 1.0 (normal-weight concrete); ψ_ec = 1.0 (concentric load); splitting / side-face blowout / adhesive bond NOT checked. One close edge assumed; multi-edge confinement requires full §17.6.2.1.2 geometry. All dimensions in mm; stresses in MPa; loads in kN.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "bolt_diameter_mm": {
      "type": "number",
      "description": "Nominal anchor bolt diameter d in mm. Must be > 0. Example: 16 for M16 bolt; 19 for 3/4\" bolt."
    },
    "embedment_depth_hef_mm": {
      "type": "number",
      "description": "Effective embedment depth h_ef in mm \u2014 from concrete surface to bearing face of anchor head (ACI 318-19 \u00a717.6.2.1). Must be > 0. Typical range: 75\u2013500 mm."
    },
    "edge_distance_min_mm": {
      "type": "number",
      "description": "Minimum edge distance c_a,min in mm \u2014 from anchor centreline to nearest free concrete edge (ACI 318-19 \u00a717.6.2.4.1). Must be \u2265 0. Values < 1.5\u00b7h_ef trigger the \u03c8_ed edge-effect factor."
    },
    "anchor_spacing_min_mm": {
      "type": "number",
      "description": "Centre-to-centre anchor spacing s in mm (for groups). Required if bolt_count > 1. Used to compute group projected breakout area A_Nc (\u00a717.6.2.1.2)."
    },
    "fc_MPa": {
      "type": "number",
      "description": "Specified compressive strength of concrete f'c in MPa. Must be > 0. Typical: 20\u201350 MPa (3000\u20137000 psi)."
    },
    "fy_steel_MPa": {
      "type": "number",
      "description": "Specified yield strength of anchor steel fy in MPa. Must be > 0. Typical: 250 (F1554 Gr36), 420 (A615 Gr60 / F1554 Gr55), 520 (ASTM A193 B7)."
    },
    "head_bearing_area_mm2": {
      "type": "number",
      "description": "Net bearing area of anchor head A_brg in mm\u00b2 \u2014 gross head area minus bolt shank area (ACI 318-19 \u00a717.6.3.2). Must be > 0. For a standard hex-head bolt: A_brg \u2248 A_head \u2212 \u03c0\u00b7d\u00b2/4. Typical: 200\u20132000 mm\u00b2 depending on bolt size and washer."
    },
    "N_factored_kN": {
      "type": "number",
      "description": "Factored tensile demand N_u in kN (LRFD combo, e.g. 1.2\u00b7DL+1.6\u00b7LL). Must be \u2265 0."
    },
    "bolt_count": {
      "type": "integer",
      "description": "Number of identical anchors in the group. Default 1. Must be \u2265 1. Groups assume equal load distribution."
    },
    "cracked_concrete": {
      "type": "boolean",
      "description": "If true (default/conservative), use k_c=10 (cracked) per ACI \u00a717.6.2.2.1 and \u03c8_c=1.0. If false, use k_c=14 (uncracked) and \u03c8_c=1.25 \u2014 only valid when concrete is verified uncracked throughout anchor service life."
    },
    "phi_steel": {
      "type": "number",
      "description": "Steel strength-reduction factor \u03c6_s. ACI 318-19 Table 17.5.3 ductile steel: 0.75 (default). Use 0.65 for non-ductile."
    },
    "phi_concrete": {
      "type": "number",
      "description": "Concrete strength-reduction factor \u03c6_c for breakout and pullout. ACI 318-19 Table 17.5.3: 0.65 Condition B (no supplementary reinforcement, default); 0.70 Condition A."
    }
  },
  "required": [
    "bolt_diameter_mm",
    "embedment_depth_hef_mm",
    "edge_distance_min_mm",
    "anchor_spacing_min_mm",
    "fc_MPa",
    "fy_steel_MPa",
    "head_bearing_area_mm2",
    "N_factored_kN"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_anchor_pullout",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
