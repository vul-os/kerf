# arch_check_lateral_bracing

*Module: `kerf_cad_core.arch.lateral_bracing_check_tools` · Domain: cad*

## Description

Check lateral-torsional buckling (LTB) for a compact doubly symmetric I-shaped steel member and compute LRFD design moment capacity per AISC 360-22 §F2.

Returns:
  • L_p_mm   — limiting unbraced length for plastic moment (Eq. F2-5)
  • L_r_mm   — limiting unbraced length for inelastic-to-elastic LTB boundary (Eq. F2-6)
  • Mp_kNm   — plastic moment capacity Fy·Zx
  • Mr_kNm   — moment at elastic LTB onset = 0.7·Fy·Sx
  • Mn_kNm   — nominal flexural strength for the supplied L_b
  • phi_Mn_kNm — LRFD design strength φ_b·Mn (φ_b = 0.90)
  • governing_mode — 'yielding' | 'inelastic_LTB' | 'elastic_LTB'
  • Lb_to_Lp_ratio — quick check ratio (< 1 → fully braced)
  • honest_caveat — code-compliance disclaimer

SCOPE: Doubly symmetric compact I-shaped members bent about the major axis only (AISC 360-22 §F2). Channels, tees, and built-up sections are out of scope. Cb (moment gradient factor) must be supplied — use Cb=1.0 for conservative (uniform moment) design.

All inputs in millimetres and MPa; moments returned in kN·m.

## Input schema

```json
{
  "type": "object",
  "required": [
    "section_label",
    "S_x_mm3",
    "Z_x_mm3",
    "r_y_mm",
    "J_mm4",
    "h_o_mm",
    "L_b_mm"
  ],
  "properties": {
    "section_label": {
      "type": "string",
      "description": "Section label for reporting, e.g. 'W14x90' or 'W360x134'."
    },
    "S_x_mm3": {
      "type": "number",
      "description": "Elastic section modulus about the strong axis (mm\u00b3)."
    },
    "Z_x_mm3": {
      "type": "number",
      "description": "Plastic section modulus about the strong axis (mm\u00b3)."
    },
    "r_y_mm": {
      "type": "number",
      "description": "Radius of gyration about the weak axis (mm). Used in Eq. F2-5 (Lp)."
    },
    "J_mm4": {
      "type": "number",
      "description": "Saint-Venant torsional constant (mm\u2074)."
    },
    "h_o_mm": {
      "type": "number",
      "description": "Distance between the centroids of the flanges (mm). For standard W-shapes h_o \u2248 d \u2212 t_f."
    },
    "L_b_mm": {
      "type": "number",
      "description": "Unbraced length of the compression flange (mm). Must be > 0."
    },
    "Fy_MPa": {
      "type": "number",
      "description": "Yield stress (MPa). Default 345 MPa (A992 / A572 Gr 50). Use 250 MPa for A36."
    },
    "E_MPa": {
      "type": "number",
      "description": "Elastic modulus (MPa). Default 200 000 MPa."
    },
    "ry_TS_mm": {
      "type": "number",
      "description": "Effective radius of gyration rts (mm) per AISC Eq. F2-7: rts = \u221a(\u221a(Iy\u00b7Cw)/Sx). Strongly recommended for accurate Lr/Fcr. Omit to use ry as a conservative fallback."
    },
    "Cb": {
      "type": "number",
      "description": "Moment gradient amplification factor (AISC \u00a7F1-1 / \u00a7C-F1-3). Default 1.0 (conservative uniform moment). Typical values: 1.14 (UDL, SS beam), 1.67 (midspan point load). Must be \u2265 1.0."
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_check_lateral_bracing",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
