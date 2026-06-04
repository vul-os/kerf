# arch_design_base_plate

*Module: `kerf_cad_core.arch.base_plate_aisc_tools` · Domain: cad*

## Description

Design a steel column base plate for concentric axial compressive load per AISC Design Guide 1, 2nd ed. §3.1 + AISC 360-22 §J8.

Concrete bearing strength (AISC 360-22 §J8 Eq J8-2):
  Pp = 0.85·f'c·A1·√(A2/A1)   with A2/A1 ≤ 4
  φ_c·Pp ≥ P_u   (φ_c = 0.65 default)

Plate sizing: N ≈ B ≥ √(P_u/(φ_c·0.85·f'c·√(A2/A1))), rounded up to nearest 5 mm; must also cover column footprint (0.95·d × 0.80·bf).

Cantilever dimensions (DG-1 §3.1.2):
  m = (N − 0.95·d) / 2        [Eq 3.1-1]
  n = (B − 0.80·bf) / 2       [Eq 3.1-2]
  n' = √(d·bf) / 4
  X = [4·d·bf/(d+bf)²]·[P_u/(φ_c·Pp)]
  λ = min(1, 2·√X/(1+√(1-X)))  [Eq 3.1-8]
  l = max(m, n, λ·n')

Plate thickness (Murray-Stockwell, DG-1 Eq 3.1-5):
  t = l · √(2·P_u / (0.9·Fy·B·N))

Returns plate_B_mm, plate_N_mm, plate_thickness_t_mm, m_mm, n_mm, X_factor, plate_phi_Pn_kN, demand_capacity_ratio, adequate, and an honest scope caveat.

SCOPE: concentric axial compressive load ONLY (DG-1 §3.1). NOT covered: moment transfer (DG-1 §3.2), anchor rod design (DG-1 §3.3–3.4), shear lug (DG-1 §3.5), biaxial bending, tensile uplift. All dimensions in mm; loads in kN; stress in MPa.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "column_d_mm": {
      "type": "number",
      "description": "Overall depth d of the W-section in mm. Example: W14x90 \u2192 d = 355.6 mm. Must be > 0."
    },
    "column_bf_mm": {
      "type": "number",
      "description": "Flange width bf of the W-section in mm. Example: W14x90 \u2192 bf = 368.3 mm. Must be > 0."
    },
    "axial_load_kN": {
      "type": "number",
      "description": "Factored axial compressive demand P_u in kN (LRFD). Must be > 0."
    },
    "fc_MPa": {
      "type": "number",
      "description": "Concrete compressive strength f'c in MPa. Typical: 21 MPa (3 000 psi), 28 MPa (4 000 psi), 35 MPa (5 000 psi). Must be > 0."
    },
    "support_width_B_mm": {
      "type": "number",
      "description": "Width of the concrete pedestal or footing in mm (direction parallel to plate B). Must be > 0."
    },
    "support_length_L_mm": {
      "type": "number",
      "description": "Length of the concrete pedestal or footing in mm (direction parallel to plate N). Must be > 0."
    },
    "phi_c": {
      "type": "number",
      "description": "Concrete bearing resistance factor \u03c6_c. AISC 360-22 \u00a7J8 default = 0.65."
    },
    "Fy_MPa": {
      "type": "number",
      "description": "Plate steel yield stress Fy in MPa. A36 = 250 MPa; A572 Gr 50 = 345 MPa (default)."
    }
  },
  "required": [
    "column_d_mm",
    "column_bf_mm",
    "axial_load_kN",
    "fc_MPa",
    "support_width_B_mm",
    "support_length_L_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="arch_design_base_plate",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
