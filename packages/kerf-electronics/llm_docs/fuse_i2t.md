# electronics_check_fuse_i2t

*Module: `kerf_electronics.tools.fuse_i2t` · Domain: electronics*

## Description

Verify that a fuse's pre-arcing I²t (melting energy) rating is consistent with a fault current waveform — does the fuse clear the fault, and is its breaking capacity adequate?

Algorithm (square-wave approximation):
  applied_I2t = peak_current_A² × (duration_ms / 1000)   [A²·s]
  clears_safely       = applied_I2t ≥ fuse_pre_arc_I2t
  breaking_cap_ok     = available_SCC_kA ≤ fuse.breaking_capacity_kA

References:
  • IEC 60269-1:2020 — Low-voltage fuses — General requirements
  • IEC 60269-2:2013 — Fuses for industrial applications
  • Cooper Bussmann 'Selecting Protective Devices' (SPD 2014 ed.) §2–§4
  • IEC 60909-0:2016 §11 — Short-circuit asymmetry correction

Fuse classes:
  F  — fast blow (ANSI/UL 248 class F, melts in <1s at 200% rated)
  FF — very fast blow (semiconductor protection)
  M  — medium / semi-time-delay
  T  — slow blow / time-delay (motor + transformer inrush)
  gG — IEC general-purpose full-range (cable protection)
  aR — IEC back-up current-limiting (semiconductor / motor protection)

Honest caveats:
  • Square-wave fault current only — sinusoidal AC or exponentially decaying DC NOT modelled; for AC apply I_rms² × t with IEC 60909 asymmetry correction.
  • Arcing I²t NOT included in applied I²t — total clearing I²t is higher; downstream equipment rating must account for the arcing phase.
  • Pre-arcing I²t is the 25°C rated value; derate for higher ambient per manufacturer temperature correction curve.
  • Fuse co-ordination (selectivity between series fuses) is NOT checked.

Input: { nominal_current_A, voltage_rating_V, I_squared_t_pre_arc_A2_s, breaking_capacity_kA, fuse_class, peak_current_A, duration_ms, available_short_circuit_current_kA }
Returns: { ok, applied_I2t_A2s, fuse_pre_arc_I2t_A2s, ratio_pct, clears_safely, breaking_capacity_adequate, recommended_fuse_class, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "nominal_current_A": {
      "type": "number",
      "description": "Fuse nominal (rated) current [A], e.g. 5, 10, 16, 32."
    },
    "voltage_rating_V": {
      "type": "number",
      "description": "Fuse maximum voltage rating [V], e.g. 250, 400, 690."
    },
    "I_squared_t_pre_arc_A2_s": {
      "type": "number",
      "description": "Fuse pre-arcing I\u00b2t rating [A\u00b2\u00b7s] from the manufacturer datasheet (IEC 60269-1 Table II).  Example: a 5 A gG fuse may have ~10 A\u00b2\u00b7s; a 32 A gG fuse ~800 A\u00b2\u00b7s."
    },
    "breaking_capacity_kA": {
      "type": "number",
      "description": "Maximum prospective short-circuit current the fuse can safely interrupt [kA rms symmetrical].  Common values: 1.5, 6, 10, 16, 20, 50, 100, 200 kA."
    },
    "fuse_class": {
      "type": "string",
      "enum": [
        "F",
        "M",
        "T",
        "FF",
        "gG",
        "aR"
      ],
      "description": "Fuse utilisation class per IEC 60269-1 / ANSI UL 248: F=fast, M=medium, T=slow/time-delay, FF=very fast, gG=IEC general-purpose, aR=IEC back-up semiconductor."
    },
    "peak_current_A": {
      "type": "number",
      "description": "Peak fault current amplitude [A] (or RMS for a rectangular approximation).  Applied I\u00b2t = peak_current_A\u00b2 \u00d7 (duration_ms/1000)."
    },
    "duration_ms": {
      "type": "number",
      "description": "Duration of the fault current pulse [ms].  Must be > 0. Example: 1 ms for a very fast short-circuit, 100 ms for a sustained overload event."
    },
    "available_short_circuit_current_kA": {
      "type": "number",
      "description": "Maximum prospective short-circuit current available at the fuse installation point [kA rms symmetrical].  Must not exceed the fuse's breaking_capacity_kA for safe operation."
    }
  },
  "required": [
    "nominal_current_A",
    "voltage_rating_V",
    "I_squared_t_pre_arc_A2_s",
    "breaking_capacity_kA",
    "fuse_class",
    "peak_current_A",
    "duration_ms",
    "available_short_circuit_current_kA"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_check_fuse_i2t",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
