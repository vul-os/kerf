# electronics_compute_pcb_trace_current

*Module: `kerf_electronics.tools.pcb_trace_current` · Domain: electronics*

## Description

Compute the maximum allowable DC current through a PCB copper trace per the IPC-2221B simplified formula (Equation 6-4):

  I [A] = k · ΔT^0.44 · A^0.725

  A  = cross-sectional area [mil²] = trace_width_mils × (copper_oz × 1.37)
  ΔT = allowed temperature rise above ambient [°C]
  k  = 0.048 for external (outer-layer) copper
       0.024 for internal (inner-layer / buried) copper

Copper weight → thickness: 0.5 oz ≈ 0.685 mil, 1 oz ≈ 1.37 mil, 2 oz ≈ 2.74 mil, 3 oz ≈ 4.11 mil.

Reference: IPC-2221B (2012) §6.2 Eq. 6-4 empirical power-law.

Honest caveats:
  • IPC-2221B simplified only. IPC-2152 (2009) has more detailed thermal curves with copper-weight correction (cf_cw), board thermal conductivity correction (cf_th), and plane-proximity correction (cf_pl) — not modelled here. Use tracecurrent_ipc2152 tool for the full IPC-2152 corrected model.
  • Formula assumes worst-case steady-state (no heat spreading from adjacent copper, vias, or pads).
  • Copper resistivity rise with temperature is not accounted for.

Input:  { trace_width_mils, copper_weight_oz?, temp_rise_C?, location? }
Returns: { ok, max_current_A, cross_section_mils2, formula_used, derate_factor, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "trace_width_mils": {
      "type": "number",
      "description": "Trace width [mils]. 1 mil = 0.0254 mm. Typical values: 10 mil (signal), 20\u201350 mil (power)."
    },
    "copper_weight_oz": {
      "type": "number",
      "description": "Copper weight [oz/ft\u00b2]. Common values: 0.5, 1, 2, 3. Default 1.0 oz (1 oz \u2248 34.8 \u00b5m \u2248 1.37 mils)."
    },
    "temp_rise_C": {
      "type": "number",
      "description": "Allowable temperature rise above ambient [\u00b0C]. Default 10 \u00b0C (IPC-2221B conservative guideline). Typical: 10 \u00b0C conservative, 20 \u00b0C moderate, 30 \u00b0C aggressive."
    },
    "location": {
      "type": "string",
      "enum": [
        "external",
        "internal"
      ],
      "description": "'external' (outer layer, default) or 'internal' (buried / inner layer). Internal traces have ~50% of the current capacity of external traces."
    }
  },
  "required": [
    "trace_width_mils"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_compute_pcb_trace_current",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
