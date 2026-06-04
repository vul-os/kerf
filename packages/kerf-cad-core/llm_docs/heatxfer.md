# heatxfer

*Module: `kerf_cad_core.heatxfer.tools` · Domain: cad*

This module registers **17** LLM tool(s):

- [`hx_composite_wall`](#hx-composite-wall)
- [`hx_cylindrical_shell`](#hx-cylindrical-shell)
- [`hx_spherical_shell`](#hx-spherical-shell)
- [`hx_nusselt_flat_plate`](#hx-nusselt-flat-plate)
- [`hx_nusselt_pipe_dittus`](#hx-nusselt-pipe-dittus)
- [`hx_nusselt_pipe_laminar`](#hx-nusselt-pipe-laminar)
- [`hx_nusselt_cylinder_cb`](#hx-nusselt-cylinder-cb)
- [`hx_nusselt_natural_vplate`](#hx-nusselt-natural-vplate)
- [`hx_radiation_two_surface`](#hx-radiation-two-surface)
- [`hx_fin_straight`](#hx-fin-straight)
- [`hx_fin_pin`](#hx-fin-pin)
- [`hx_fin_array_resistance`](#hx-fin-array-resistance)
- [`hx_lmtd`](#hx-lmtd)
- [`hx_effectiveness_ntu`](#hx-effectiveness-ntu)
- [`hx_lumped_capacitance`](#hx-lumped-capacitance)
- [`hx_tube_count`](#hx-tube-count)
- [`hx_shell_tube_bell_delaware`](#hx-shell-tube-bell-delaware)

---

## `hx_composite_wall`

1D steady-state conduction through a plane composite wall.

Computes total thermal resistance, per-layer resistances, interface temperatures, and heat flux Q (W) for a series of planar layers (material layers and/or contact resistances) under fixed surface temperatures.

Returns Q_W, R_total, layer_resistances, T_interfaces.
Errors: {ok:false, reason} for missing/invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "layers": {
      "type": "array",
      "description": "Ordered list of layer dicts from hot side to cold side. Material layer: {\"k\": W/mK, \"t\": m, \"A\": m\u00b2(optional, default 1)}. Contact layer: {\"R_contact\": m\u00b2K/W, \"A\": m\u00b2(optional)}.",
      "items": {
        "type": "object"
      }
    },
    "T_hot": {
      "type": "number",
      "description": "Hot-side surface temperature (K). Must be > 0."
    },
    "T_cold": {
      "type": "number",
      "description": "Cold-side surface temperature (K). Must be > 0."
    }
  },
  "required": [
    "layers",
    "T_hot",
    "T_cold"
  ]
}
```

---

## `hx_cylindrical_shell`

1D radial conduction through a cylindrical shell.

Q = 2π k L (T_inner - T_outer) / ln(r_outer / r_inner)

Returns Q_W (total W), q_per_m (W/m), R_cond (K/W).
Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_inner": {
      "type": "number",
      "description": "Inner radius (m). Must be > 0."
    },
    "r_outer": {
      "type": "number",
      "description": "Outer radius (m). Must be > r_inner."
    },
    "k": {
      "type": "number",
      "description": "Thermal conductivity (W/m\u00b7K). Must be > 0."
    },
    "T_inner": {
      "type": "number",
      "description": "Inner surface temperature (K)."
    },
    "T_outer": {
      "type": "number",
      "description": "Outer surface temperature (K)."
    },
    "L": {
      "type": "number",
      "description": "Cylinder length (m). Default 1.0."
    }
  },
  "required": [
    "r_inner",
    "r_outer",
    "k",
    "T_inner",
    "T_outer"
  ]
}
```

---

## `hx_spherical_shell`

1D radial conduction through a spherical shell.

Q = 4π k r_i r_o (T_inner - T_outer) / (r_outer - r_inner)

Returns Q_W, R_cond.
Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_inner": {
      "type": "number",
      "description": "Inner radius (m). Must be > 0."
    },
    "r_outer": {
      "type": "number",
      "description": "Outer radius (m). Must be > r_inner."
    },
    "k": {
      "type": "number",
      "description": "Thermal conductivity (W/m\u00b7K). Must be > 0."
    },
    "T_inner": {
      "type": "number",
      "description": "Inner surface temperature (K)."
    },
    "T_outer": {
      "type": "number",
      "description": "Outer surface temperature (K)."
    }
  },
  "required": [
    "r_inner",
    "r_outer",
    "k",
    "T_inner",
    "T_outer"
  ]
}
```

---

## `hx_nusselt_flat_plate`

Average Nusselt number for forced convection over a flat plate.

Laminar  (Re <= 5e5): Nu = 0.664 Re^0.5 Pr^(1/3)
Turbulent (Re > 5e5): Nu = 0.037 Re^(4/5) Pr^(1/3)
Mixed (full plate):   Nu = (0.037 Re^(4/5) - 871) Pr^(1/3)
'auto' selects laminar or mixed based on Re.

Returns Nu, regime. Validity: 0.6 <= Pr <= 60; warning issued outside this range.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Re_L": {
      "type": "number",
      "description": "Reynolds number based on plate length. Must be > 0."
    },
    "Pr": {
      "type": "number",
      "description": "Prandtl number. Must be > 0."
    },
    "regime": {
      "type": "string",
      "enum": [
        "auto",
        "laminar",
        "turbulent",
        "mixed"
      ],
      "description": "Flow regime. Default 'auto'."
    }
  },
  "required": [
    "Re_L",
    "Pr"
  ]
}
```

---

## `hx_nusselt_pipe_dittus`

Dittus-Boelter Nusselt correlation for fully developed turbulent pipe flow.

Nu = 0.023 Re^0.8 Pr^n
  n = 0.4 (fluid heated, T_s > T_m)
  n = 0.3 (fluid cooled, T_s < T_m)

Validity: Re > 10 000, 0.6 < Pr < 160, L/D > 10. Warning issued if Re <= 10 000.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Re_D": {
      "type": "number",
      "description": "Reynolds number (pipe diameter). Must be > 0."
    },
    "Pr": {
      "type": "number",
      "description": "Prandtl number. Must be > 0."
    },
    "heating": {
      "type": "boolean",
      "description": "True = fluid heated (n=0.4, default); False = cooled (n=0.3)."
    }
  },
  "required": [
    "Re_D",
    "Pr"
  ]
}
```

---

## `hx_nusselt_pipe_laminar`

Average Nusselt number for laminar internal pipe flow (Hausen correlation).

Nu = 3.66 + 0.065 Gz / (1 + 0.04 Gz^(2/3))
where Gz = (D/L) Re Pr (Graetz number)

Valid for Re_D < 2300. Warning issued if Re >= 2300.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Re_D": {
      "type": "number",
      "description": "Reynolds number. Must be > 0."
    },
    "Pr": {
      "type": "number",
      "description": "Prandtl number. Must be > 0."
    },
    "L_D": {
      "type": "number",
      "description": "L/D ratio (length/diameter). Must be > 0."
    }
  },
  "required": [
    "Re_D",
    "Pr",
    "L_D"
  ]
}
```

---

## `hx_nusselt_cylinder_cb`

Average Nusselt number for external cross-flow over a cylinder.

Churchill & Bernstein (1977) correlation (Incropera 7.54):
Nu = 0.3 + [0.62 Re^(1/2) Pr^(1/3)] / [1+(0.4/Pr)^(2/3)]^(1/4)
          × [1 + (Re/282000)^(5/8)]^(4/5)

Valid for Re·Pr > 0.2. Warning issued otherwise.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Re_D": {
      "type": "number",
      "description": "Reynolds number (cylinder diameter). Must be > 0."
    },
    "Pr": {
      "type": "number",
      "description": "Prandtl number. Must be > 0."
    }
  },
  "required": [
    "Re_D",
    "Pr"
  ]
}
```

---

## `hx_nusselt_natural_vplate`

Average Nusselt number for natural convection on a vertical plate.

Churchill & Chu (1975) correlations:
  'laminar' (Ra <= 1e9): Nu = 0.68 + 0.670 Ra^(1/4) / psi^(4/9)
  'all' (composite):     Nu = [0.825 + 0.387 Ra^(1/6) / psi^(8/27)]²
  where psi = [1 + (0.492/Pr)^(9/16)]

Returns Nu. Warning for Ra > 1e9 in 'laminar' mode.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Ra_L": {
      "type": "number",
      "description": "Rayleigh number (= Gr\u00b7Pr). Must be > 0."
    },
    "Pr": {
      "type": "number",
      "description": "Prandtl number. Must be > 0."
    },
    "regime": {
      "type": "string",
      "enum": [
        "all",
        "laminar"
      ],
      "description": "Correlation variant: 'all' (default) or 'laminar'."
    }
  },
  "required": [
    "Ra_L",
    "Pr"
  ]
}
```

---

## `hx_radiation_two_surface`

Net radiation heat transfer between two gray, diffuse surfaces.

Uses electrical analogy with surface and space resistances:
Q_12 = (σT1⁴ - σT2⁴) / (R_surf1 + R_space + R_surf2)
  R_surf = (1-ε)/(εA),  R_space = 1/(A1·F12)

Returns Q_12_W (positive = net heat from 1 to 2), R_total, Eb1, Eb2.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T1": {
      "type": "number",
      "description": "Surface 1 temperature (K). Must be > 0."
    },
    "T2": {
      "type": "number",
      "description": "Surface 2 temperature (K). Must be > 0."
    },
    "eps1": {
      "type": "number",
      "description": "Emissivity of surface 1 (0, 1]."
    },
    "eps2": {
      "type": "number",
      "description": "Emissivity of surface 2 (0, 1]."
    },
    "A1": {
      "type": "number",
      "description": "Area of surface 1 (m\u00b2). Must be > 0."
    },
    "A2": {
      "type": "number",
      "description": "Area of surface 2 (m\u00b2). Must be > 0."
    },
    "F12": {
      "type": "number",
      "description": "View factor from surface 1 to 2. [0, 1]."
    }
  },
  "required": [
    "T1",
    "T2",
    "eps1",
    "eps2",
    "A1",
    "A2",
    "F12"
  ]
}
```

---

## `hx_fin_straight`

Efficiency and effectiveness of a straight rectangular fin.

m = sqrt(2h / (k·t)),  L_c = L (adiabatic) or L+t/2 (convective)
η_f = tanh(m·L_c) / (m·L_c)
ε_f = η_f × 2L_c / t

Returns eta_f, eps_f, mL_c, L_c, m.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "L": {
      "type": "number",
      "description": "Fin length/height (m). Must be > 0."
    },
    "t": {
      "type": "number",
      "description": "Fin thickness (m). Must be > 0."
    },
    "k": {
      "type": "number",
      "description": "Fin thermal conductivity (W/m\u00b7K). Must be > 0."
    },
    "h": {
      "type": "number",
      "description": "Convective coefficient (W/m\u00b2\u00b7K). Must be > 0."
    },
    "tip": {
      "type": "string",
      "enum": [
        "adiabatic",
        "convective"
      ],
      "description": "Tip condition: 'adiabatic' (default) or 'convective'."
    }
  },
  "required": [
    "L",
    "t",
    "k",
    "h"
  ]
}
```

---

## `hx_fin_pin`

Efficiency and effectiveness of a cylindrical pin fin.

m = sqrt(4h / (k·D)),  L_c = L + D/4
η_f = tanh(m·L_c) / (m·L_c)
ε_f = η_f × 4L_c / D

Returns eta_f, eps_f, mL_c, L_c, m.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "L": {
      "type": "number",
      "description": "Pin fin length (m). Must be > 0."
    },
    "D": {
      "type": "number",
      "description": "Pin fin diameter (m). Must be > 0."
    },
    "k": {
      "type": "number",
      "description": "Thermal conductivity (W/m\u00b7K). Must be > 0."
    },
    "h": {
      "type": "number",
      "description": "Convective coefficient (W/m\u00b2\u00b7K). Must be > 0."
    }
  },
  "required": [
    "L",
    "D",
    "k",
    "h"
  ]
}
```

---

## `hx_fin_array_resistance`

Overall thermal resistance of a fin array (Incropera 3.108).

η_overall = 1 - N·A_fin/A_total × (1 - η_f)
R_array = 1 / (η_overall · h · A_total)

Returns R_array (K/W), eta_overall.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "N": {
      "type": "integer",
      "description": "Number of fins. Must be >= 1."
    },
    "eta_f": {
      "type": "number",
      "description": "Individual fin efficiency [0, 1]."
    },
    "A_fin": {
      "type": "number",
      "description": "Total surface area of one fin (m\u00b2). Must be > 0."
    },
    "A_base": {
      "type": "number",
      "description": "Base area between fins per pitch (m\u00b2). Must be > 0."
    },
    "h": {
      "type": "number",
      "description": "Convective coefficient (W/m\u00b2\u00b7K). Must be > 0."
    },
    "A_total": {
      "type": "number",
      "description": "Total heat transfer area = N\u00b7A_fin + unfinned base (m\u00b2). Must be > 0."
    }
  },
  "required": [
    "N",
    "eta_f",
    "A_fin",
    "A_base",
    "h",
    "A_total"
  ]
}
```

---

## `hx_lmtd`

Heat exchanger sizing via the LMTD method.

Q = U · A · F · ΔT_lm

Supports counter-flow (F=1), parallel-flow (F=1), and cross-flow with both fluids unmixed (F from TEMA charts).

Returns Q_W, LMTD_K, F, ΔT1, ΔT2.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T_h_in": {
      "type": "number",
      "description": "Hot inlet temperature (K). Must be > 0."
    },
    "T_h_out": {
      "type": "number",
      "description": "Hot outlet temperature (K). Must be > 0."
    },
    "T_c_in": {
      "type": "number",
      "description": "Cold inlet temperature (K). Must be > 0."
    },
    "T_c_out": {
      "type": "number",
      "description": "Cold outlet temperature (K). Must be > 0."
    },
    "U": {
      "type": "number",
      "description": "Overall heat-transfer coefficient (W/m\u00b2\u00b7K). Must be > 0."
    },
    "A": {
      "type": "number",
      "description": "Heat exchanger area (m\u00b2). Must be > 0."
    },
    "flow": {
      "type": "string",
      "enum": [
        "counter",
        "parallel",
        "crossflow_unmixed"
      ],
      "description": "Flow arrangement. Default 'counter'."
    }
  },
  "required": [
    "T_h_in",
    "T_h_out",
    "T_c_in",
    "T_c_out",
    "U",
    "A"
  ]
}
```

---

## `hx_effectiveness_ntu`

Heat exchanger effectiveness via the ε-NTU method.

Counter-flow: ε = (1 - exp(-NTU(1-Cr))) / (1 - Cr·exp(-NTU(1-Cr)))
  Special case Cr=1: ε = NTU/(NTU+1)
Parallel-flow: ε = (1 - exp(-NTU(1+Cr))) / (1+Cr)
Cross-flow (unmixed): ε = 1 - exp[(NTU^0.22/Cr)(exp(-Cr·NTU^0.78)-1)]

Returns epsilon (effectiveness [0,1]), C_r, NTU, C_min, C_max.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "C_min": {
      "type": "number",
      "description": "Minimum heat capacity rate (W/K). Must be > 0."
    },
    "C_max": {
      "type": "number",
      "description": "Maximum heat capacity rate (W/K). Must be >= C_min."
    },
    "NTU": {
      "type": "number",
      "description": "Number of transfer units. Must be > 0."
    },
    "flow": {
      "type": "string",
      "enum": [
        "counter",
        "parallel",
        "crossflow_unmixed"
      ],
      "description": "Flow arrangement. Default 'counter'."
    }
  },
  "required": [
    "C_min",
    "C_max",
    "NTU"
  ]
}
```

---

## `hx_lumped_capacitance`

Transient temperature response using the lumped-capacitance model.

τ = ρ V c_p / (h A_s)    [time constant, s]
T(t) = T_inf + (T_i - T_inf) × exp(-t/τ)

Optional Biot number check: Bi = h·L_c/k (L_c = V/A_s).
A WARNING is issued (not an error) if Bi > 0.1.

Returns T_t_K, tau_s, Bi (None if k not provided), theta, Q_total_J.
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T_i": {
      "type": "number",
      "description": "Initial body temperature (K). Must be > 0."
    },
    "T_inf": {
      "type": "number",
      "description": "Ambient/fluid temperature (K). Must be > 0."
    },
    "h": {
      "type": "number",
      "description": "Convective coefficient (W/m\u00b2\u00b7K). Must be > 0."
    },
    "A_s": {
      "type": "number",
      "description": "Surface area (m\u00b2). Must be > 0."
    },
    "rho": {
      "type": "number",
      "description": "Density (kg/m\u00b3). Must be > 0."
    },
    "V": {
      "type": "number",
      "description": "Volume (m\u00b3). Must be > 0."
    },
    "c_p": {
      "type": "number",
      "description": "Specific heat capacity (J/kg\u00b7K). Must be > 0."
    },
    "t": {
      "type": "number",
      "description": "Time (s). Must be >= 0."
    },
    "Lc": {
      "type": "number",
      "description": "Characteristic length L_c (m). Optional; default V/A_s."
    },
    "k": {
      "type": "number",
      "description": "Body thermal conductivity (W/m\u00b7K). Optional; required for Bi check."
    }
  },
  "required": [
    "T_i",
    "T_inf",
    "h",
    "A_s",
    "rho",
    "V",
    "c_p",
    "t"
  ]
}
```

---

## `hx_tube_count`

Estimate TEMA tube count for a shell-and-tube heat exchanger.

Uses the TEMA tube-layout formula:
  N_t = (CTP/CL) * (π/4) * (D_s / P_t)²
where CL is the layout packing factor and CTP is the tube-count
correction for multiple passes.

Supported layouts: triangular_30, rotated_60, square_90, rotated_45.
TEMA minimum pitch = 1.25 × tube_od.

Returns N_tubes (int).
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "shell_id": {
      "type": "number",
      "description": "Shell inner diameter (m). Must be > 0."
    },
    "tube_od": {
      "type": "number",
      "description": "Tube outer diameter (m). Must be > 0."
    },
    "pitch": {
      "type": "number",
      "description": "Tube pitch centre-to-centre (m). Must be >= 1.25*tube_od."
    },
    "layout": {
      "type": "string",
      "enum": [
        "triangular_30",
        "rotated_60",
        "square_90",
        "rotated_45"
      ],
      "description": "TEMA tube layout pattern."
    },
    "n_passes": {
      "type": "integer",
      "description": "Number of tube passes (1, 2, 4, or 6). Default 1."
    }
  },
  "required": [
    "shell_id",
    "tube_od",
    "pitch",
    "layout"
  ]
}
```

---

## `hx_shell_tube_bell_delaware`

Full Bell-Delaware shell-and-tube heat exchanger design.

Computes shell-side h_s with Bell-Delaware correction factors
(Jc baffle-cut, Jl leakage, Jb bypass, Jr laminar, Js uneven spacing),
tube-side h_t (Dittus-Boelter / Hausen), overall U, required area A_req,
tube count, baffle count, and ΔP (tube-side + shell-side).

Validated against Kern (1950) kerosene cooler example:
  h_s ~500 W/m²·K, h_t ~3000 W/m²·K, U ~400 W/m²·K, A ~50 m² @ 1 MW.

Returns: U_W_m2K, A_req_m2, A_actual_m2, overdesign, N_tubes, N_baffles,
         h_t_W_m2K, h_s_W_m2K, Re_t, Re_s, LMTD_K, dP_tube_Pa, dP_shell_Pa,
         factors (Jc/Jl/Jb/Jr/Js).
Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "duty_W": {
      "type": "number",
      "description": "Heat duty (W). Must be > 0."
    },
    "t_hot_in": {
      "type": "number",
      "description": "Hot-fluid inlet temperature (\u00b0C or K)."
    },
    "t_hot_out": {
      "type": "number",
      "description": "Hot-fluid outlet temperature."
    },
    "t_cold_in": {
      "type": "number",
      "description": "Cold-fluid inlet temperature."
    },
    "t_cold_out": {
      "type": "number",
      "description": "Cold-fluid outlet temperature."
    },
    "shell_props": {
      "type": "object",
      "description": "Shell-side fluid properties: {rho: kg/m\u00b3, mu: Pa\u00b7s, cp: J/kg\u00b7K, k: W/m\u00b7K, Pr: (opt), m_dot: kg/s (opt)}."
    },
    "tube_props": {
      "type": "object",
      "description": "Tube-side fluid properties: {rho: kg/m\u00b3, mu: Pa\u00b7s, cp: J/kg\u00b7K, k: W/m\u00b7K, Pr: (opt), m_dot: kg/s (opt)}."
    },
    "geometry": {
      "type": "object",
      "description": "HX geometry: {D_s, tube_od, tube_id, pitch, layout, L_tube, N_t, n_passes, N_b, B, baffle_cut, k_wall, R_foul_t, R_foul_s, D_tb, D_sb, n_ss (all optional except D_s/tube_od/tube_id/pitch/L_tube/N_t/N_b/B)}."
    }
  },
  "required": [
    "duty_W",
    "t_hot_in",
    "t_hot_out",
    "t_cold_in",
    "t_cold_out",
    "shell_props",
    "tube_props",
    "geometry"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
