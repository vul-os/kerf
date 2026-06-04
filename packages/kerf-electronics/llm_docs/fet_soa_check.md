# electronics_check_fet_soa

*Module: `kerf_electronics.fet_soa_check` · Domain: electronics*

## Description

Check whether a power MOSFET operating point lies within its Safe Operating Area (SOA) using linearised SOA boundaries.

Three SOA boundary regions (IRF Hexfet Designer's Manual §5):
  1. Voltage limit   : V_DS <= V_DSS_max
  2. Current limit   : I_D <= I_D_continuous (DC) or I_D <= I_D_pulsed (pulsed)
  3. Thermal limit   : T_J = T_amb + P_diss×R_θJA <= T_J_max
                        P_diss = V_DS × I_D × duty_cycle
  4. Power limit     : P_diss <= P_D_max

Reports within_soa, P_diss_W, T_junction_estimate_C, soa_violation_modes, headroom_pct, honest_caveat.

HONEST: linearised SOA only (not curved datasheet boundaries); pulse-width SOA NOT interpolated; second-breakdown / UIS NOT modelled as separate boundary; thermal model is single-node steady-state JESD51 (not transient Z_θJC(t)); R_DS_on temperature dependence NOT corrected; switching losses NOT included.

Refs: IRF Hexfet Designer's Manual §5; IPC-9701A; Jedec JESD51-1.

Input: { part_number, V_DSS_max_V, I_D_continuous_A, I_D_pulsed_A, R_DS_on_mOhm, R_theta_JA_K_per_W, P_D_max_W, V_DS_V, I_D_A, [T_J_max_C=150], [pulse_duration_ms=1e6], [duty_cycle=1.0], [T_ambient_C=25] }

Returns: { ok, within_soa, P_diss_W, T_junction_estimate_C, soa_violation_modes, headroom_pct, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "part_number": {
      "type": "string",
      "description": "Device part number (e.g. IRFZ44N). Used in report text."
    },
    "V_DSS_max_V": {
      "type": "number",
      "description": "Drain-source breakdown voltage (absolute maximum) [V]. Must be > 0."
    },
    "I_D_continuous_A": {
      "type": "number",
      "description": "Continuous drain current (DC) rating at T_case=25\u00b0C [A]. Must be > 0."
    },
    "I_D_pulsed_A": {
      "type": "number",
      "description": "Pulsed drain current rating (peak) [A]. Must be >= I_D_continuous_A."
    },
    "R_DS_on_mOhm": {
      "type": "number",
      "description": "On-state drain-source resistance at specified V_GS [m\u03a9]. Must be > 0."
    },
    "T_J_max_C": {
      "type": "number",
      "description": "Maximum rated junction temperature [\u00b0C]. Default 150. Typical values: 150 or 175 for power MOSFETs."
    },
    "R_theta_JA_K_per_W": {
      "type": "number",
      "description": "Thermal resistance junction-to-ambient [K/W or \u00b0C/W]. Must be > 0."
    },
    "P_D_max_W": {
      "type": "number",
      "description": "Maximum continuous power dissipation at T_case=25\u00b0C [W]. Must be > 0."
    },
    "V_DS_V": {
      "type": "number",
      "description": "Drain-source voltage at the operating point [V]. Must be >= 0."
    },
    "I_D_A": {
      "type": "number",
      "description": "Drain current at the operating point [A]. Must be >= 0."
    },
    "pulse_duration_ms": {
      "type": "number",
      "description": "Pulse duration [ms]. Use large value (e.g. 1e6) for DC steady state. Used in caveat context only; does NOT alter limits in this linearised model."
    },
    "duty_cycle": {
      "type": "number",
      "description": "Fraction of period device is conducting (0 < duty_cycle <= 1.0). Use 1.0 for DC. Affects average P_diss and current-limit selection."
    },
    "T_ambient_C": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C]. Default 25.0."
    }
  },
  "required": [
    "V_DSS_max_V",
    "I_D_continuous_A",
    "I_D_pulsed_A",
    "R_DS_on_mOhm",
    "R_theta_JA_K_per_W",
    "P_D_max_W",
    "V_DS_V",
    "I_D_A"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_check_fet_soa",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
