# protection

*Module: `kerf_electronics.protection.tools` · Domain: electronics*

This module registers **9** LLM tool(s):

- [`protection_fuse_select`](#protection-fuse-select)
- [`protection_inrush_ntc_size`](#protection-inrush-ntc-size)
- [`protection_tvs_mov_clamp`](#protection-tvs-mov-clamp)
- [`protection_reverse_polarity`](#protection-reverse-polarity)
- [`protection_efuse_trip`](#protection-efuse-trip)
- [`protection_ptc_resettable`](#protection-ptc-resettable)
- [`protection_breaker_coordination`](#protection-breaker-coordination)
- [`protection_onderdonk_trace_fuse`](#protection-onderdonk-trace-fuse)
- [`protection_wire_ampacity`](#protection-wire-ampacity)

---

## `protection_fuse_select`

Select and validate a fuse for a given load and supply.

Checks:
  • Continuous-current derating vs temperature
  • I²t let-through vs downstream device withstand
  • Voltage rating ≥ supply voltage
  • Interrupt rating (short-circuit)

Warnings issued for: UNDERSIZED, VOLTAGE_RATING_LOW, INTERRUPT_RATING_LOW, I2T_EXCEEDED.

Input: { load_current_a, supply_voltage_v, ambient_temp_c, fuse_rating_a, fuse_voltage_v, fuse_interrupt_a, fuse_i2t_as2, downstream_i2t_withstand_as2, derating_factor?, temp_derating_ref_c?, temp_derating_coefficient? }
Returns: { ok, derated_current_a, current_ok, voltage_ok, interrupt_ok, i2t_ok, all_ok, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "load_current_a": {
      "type": "number",
      "description": "Continuous load current [A]."
    },
    "supply_voltage_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "ambient_temp_c": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C]."
    },
    "fuse_rating_a": {
      "type": "number",
      "description": "Fuse continuous rating [A] at reference temperature."
    },
    "fuse_voltage_v": {
      "type": "number",
      "description": "Fuse voltage rating [V]."
    },
    "fuse_interrupt_a": {
      "type": "number",
      "description": "Fuse interrupt (short-circuit) rating [A]."
    },
    "fuse_i2t_as2": {
      "type": "number",
      "description": "Fuse let-through I\u00b2t [A\u00b2s]."
    },
    "downstream_i2t_withstand_as2": {
      "type": "number",
      "description": "Downstream device I\u00b2t withstand [A\u00b2s]."
    },
    "derating_factor": {
      "type": "number",
      "description": "Safety derating multiplier (default 0.75)."
    },
    "temp_derating_ref_c": {
      "type": "number",
      "description": "Reference temperature for derating [\u00b0C] (default 25)."
    },
    "temp_derating_coefficient": {
      "type": "number",
      "description": "Linear derating coefficient [/\u00b0C] (default 0.005)."
    }
  },
  "required": [
    "load_current_a",
    "supply_voltage_v",
    "ambient_temp_c",
    "fuse_rating_a",
    "fuse_voltage_v",
    "fuse_interrupt_a",
    "fuse_i2t_as2",
    "downstream_i2t_withstand_as2"
  ]
}
```

---

## `protection_inrush_ntc_size`

Estimate inrush energy and size an NTC inrush-limiter thermistor.

Model: peak inrush I = V / R_cold; energy E = 0.5×C×V²; steady-state P = I_ss²×R_hot.

Warnings: NTC_OVERLOADED, EXCESSIVE_DROP (>5% of supply).

Input: { supply_voltage_v, bulk_capacitance_uf, ntc_resistance_cold_ohm, ntc_resistance_hot_ohm, ntc_max_power_w, steady_state_current_a, ambient_temp_c? }
Returns: { ok, inrush_peak_a, inrush_energy_j, steady_state_power_w, ntc_voltage_drop_v, power_ok, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "supply_voltage_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "bulk_capacitance_uf": {
      "type": "number",
      "description": "Bulk capacitance [\u03bcF]."
    },
    "ntc_resistance_cold_ohm": {
      "type": "number",
      "description": "NTC resistance at ambient (cold) [\u03a9]."
    },
    "ntc_resistance_hot_ohm": {
      "type": "number",
      "description": "NTC resistance at operating temperature (hot) [\u03a9]."
    },
    "ntc_max_power_w": {
      "type": "number",
      "description": "NTC rated continuous power dissipation [W]."
    },
    "steady_state_current_a": {
      "type": "number",
      "description": "Steady-state load current [A]."
    },
    "ambient_temp_c": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C] (default 25)."
    }
  },
  "required": [
    "supply_voltage_v",
    "bulk_capacitance_uf",
    "ntc_resistance_cold_ohm",
    "ntc_resistance_hot_ohm",
    "ntc_max_power_w",
    "steady_state_current_a"
  ]
}
```

---

## `protection_tvs_mov_clamp`

Check TVS / MOV clamp device adequacy for a surge event.

Checks: standoff ≥ working voltage, clamping voltage ≤ 1.5× standoff, pulse power ≤ rated power, surge energy ≤ 8/20 μs energy capacity, I_pp ≥ surge current, IEC 61000-4-5 level compliance.

Warnings: STANDOFF_TOO_LOW, CLAMP_TOO_HIGH, POWER_EXCEEDED, ENERGY_EXCEEDED, IPP_UNDERSIZED, IEC_LEVEL_NOT_MET.

Input: { working_voltage_v, tvs_standoff_v, tvs_clamping_v_at_ipp, tvs_ipp_a, tvs_peak_power_w, surge_current_a, surge_energy_j, iec_level? }
Returns: { ok, standoff_ok, clamping_v_ok, power_ok, energy_ok, ipp_ok, iec_compliance, pulse_power_w, all_ok, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "working_voltage_v": {
      "type": "number",
      "description": "Circuit working voltage [V]."
    },
    "tvs_standoff_v": {
      "type": "number",
      "description": "TVS/MOV standoff voltage [V]."
    },
    "tvs_clamping_v_at_ipp": {
      "type": "number",
      "description": "Clamping voltage at I_pp [V]."
    },
    "tvs_ipp_a": {
      "type": "number",
      "description": "TVS/MOV peak pulse current rating [A]."
    },
    "tvs_peak_power_w": {
      "type": "number",
      "description": "TVS/MOV peak pulse power rating [W]."
    },
    "surge_current_a": {
      "type": "number",
      "description": "Applied surge peak current [A]."
    },
    "surge_energy_j": {
      "type": "number",
      "description": "Applied surge energy [J]."
    },
    "iec_level": {
      "type": "string",
      "enum": [
        "1",
        "2",
        "3",
        "4"
      ],
      "description": "IEC 61000-4-5 immunity level '1'..'4' (optional)."
    }
  },
  "required": [
    "working_voltage_v",
    "tvs_standoff_v",
    "tvs_clamping_v_at_ipp",
    "tvs_ipp_a",
    "tvs_peak_power_w",
    "surge_current_a",
    "surge_energy_j"
  ]
}
```

---

## `protection_reverse_polarity`

Compare series diode vs P-channel MOSFET reverse-polarity protection.

Calculates conduction loss and load voltage for each approach and recommends the lower-loss option.

Warnings: DIODE_VF_EXCEEDS_SUPPLY, RDS_ON_HIGH (>10% drop).

Input: { supply_voltage_v, load_current_a, diode_vf_v, pfet_rds_on_ohm }
Returns: { ok, diode_power_w, diode_vload_v, pfet_power_w, pfet_vload_v, preferred, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "supply_voltage_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "load_current_a": {
      "type": "number",
      "description": "Load current [A]."
    },
    "diode_vf_v": {
      "type": "number",
      "description": "Diode forward voltage at load current [V]."
    },
    "pfet_rds_on_ohm": {
      "type": "number",
      "description": "P-FET RDS(on) at operating conditions [\u03a9]."
    }
  },
  "required": [
    "supply_voltage_v",
    "load_current_a",
    "diode_vf_v",
    "pfet_rds_on_ohm"
  ]
}
```

---

## `protection_efuse_trip`

eFuse overcurrent-trip threshold check and SOA (Safe Operating Area) note.

Checks conduction loss at normal current and fault energy during trip delay against the eFuse's thermal capacity.

Warnings: CONDUCTION_OVERLOAD, SOA_EXCEEDED, WILL_TRIP.

Input: { current_limit_a, load_current_a, supply_voltage_v, efuse_rds_on_ohm, efuse_max_power_w, trip_delay_us? }
Returns: { ok, conduction_power_w, fault_energy_j, soa_ok, conduction_ok, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "current_limit_a": {
      "type": "number",
      "description": "eFuse overcurrent trip threshold [A]."
    },
    "load_current_a": {
      "type": "number",
      "description": "Normal load current [A]."
    },
    "supply_voltage_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "efuse_rds_on_ohm": {
      "type": "number",
      "description": "eFuse internal FET RDS(on) [\u03a9]."
    },
    "efuse_max_power_w": {
      "type": "number",
      "description": "eFuse continuous power rating [W]."
    },
    "trip_delay_us": {
      "type": "number",
      "description": "Overcurrent-to-trip delay [\u03bcs] (default 1.0)."
    }
  },
  "required": [
    "current_limit_a",
    "load_current_a",
    "supply_voltage_v",
    "efuse_rds_on_ohm",
    "efuse_max_power_w"
  ]
}
```

---

## `protection_ptc_resettable`

PTC resettable fuse hold/trip current check at operating temperature.

Applies linear temperature derating to the hold and trip currents and checks whether the load current is safely within the hold zone.

Warnings: PTC_WILL_TRIP, PTC_MARGINAL.

Input: { ptc_hold_current_a, ptc_trip_current_a, load_current_a, ptc_resistance_ohm, supply_voltage_v, ambient_temp_c?, ptc_hold_temp_ref_c?, ptc_temp_derating_pct_per_c? }
Returns: { ok, hold_current_derated_a, trip_current_derated_a, load_within_hold, will_trip, steady_state_power_w, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ptc_hold_current_a": {
      "type": "number",
      "description": "Hold current at reference temperature [A]."
    },
    "ptc_trip_current_a": {
      "type": "number",
      "description": "Trip current at reference temperature [A]."
    },
    "load_current_a": {
      "type": "number",
      "description": "Normal load current [A]."
    },
    "ptc_resistance_ohm": {
      "type": "number",
      "description": "PTC resistance at hold condition [\u03a9]."
    },
    "supply_voltage_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "ambient_temp_c": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C] (default 25)."
    },
    "ptc_hold_temp_ref_c": {
      "type": "number",
      "description": "Reference temperature for hold/trip spec [\u00b0C] (default 25)."
    },
    "ptc_temp_derating_pct_per_c": {
      "type": "number",
      "description": "Derating rate [%/\u00b0C] (default 0.5)."
    }
  },
  "required": [
    "ptc_hold_current_a",
    "ptc_trip_current_a",
    "load_current_a",
    "ptc_resistance_ohm",
    "supply_voltage_v"
  ]
}
```

---

## `protection_breaker_coordination`

Fuse / breaker time-current coordination — selectivity ratio check.

For discrimination: upstream trip current / downstream trip current must be ≥ selectivity_ratio_min (default 1.6) AND the downstream device must clear before the upstream device.

Warnings: UNCOORDINATED, PARTIAL_COORDINATION.

Input: { upstream_trip_current_a, downstream_trip_current_a, upstream_trip_time_s, downstream_trip_time_s, selectivity_ratio_min? }
Returns: { ok, selectivity_ratio, ratio_ok, time_ok, coordinated, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "upstream_trip_current_a": {
      "type": "number",
      "description": "Upstream device trip current [A]."
    },
    "downstream_trip_current_a": {
      "type": "number",
      "description": "Downstream device trip current [A]."
    },
    "upstream_trip_time_s": {
      "type": "number",
      "description": "Upstream device trip time at fault [s]."
    },
    "downstream_trip_time_s": {
      "type": "number",
      "description": "Downstream device trip time at fault [s]."
    },
    "selectivity_ratio_min": {
      "type": "number",
      "description": "Minimum selectivity ratio (default 1.6)."
    }
  },
  "required": [
    "upstream_trip_current_a",
    "downstream_trip_current_a",
    "upstream_trip_time_s",
    "downstream_trip_time_s"
  ]
}
```

---

## `protection_onderdonk_trace_fuse`

PCB copper trace fusing current from Onderdonk's equation.

Formula: I_fuse = A[cmil] × sqrt(ΔT / (33 × t))
where A = cross-sectional area [circular mils], ΔT = melting − ambient [°C], t = fusing time [s].

Typical copper thicknesses: 35 μm = 1 oz, 70 μm = 2 oz, 105 μm = 3 oz.

Input: { trace_width_mm, trace_thickness_um, fusing_time_s, ambient_temp_c?, melting_temp_c? }
Returns: { ok, cross_section_mm2, cross_section_cmil, fusing_current_a }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "trace_width_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "trace_thickness_um": {
      "type": "number",
      "description": "Copper thickness [\u03bcm] (35=1oz, 70=2oz)."
    },
    "fusing_time_s": {
      "type": "number",
      "description": "Time from fault onset to fuse [s]."
    },
    "ambient_temp_c": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C] (default 25)."
    },
    "melting_temp_c": {
      "type": "number",
      "description": "Copper melting point [\u00b0C] (default 1085)."
    }
  },
  "required": [
    "trace_width_mm",
    "trace_thickness_um",
    "fusing_time_s"
  ]
}
```

---

## `protection_wire_ampacity`

Wire ampacity protection check per NEC 310.16 copper table.

Applies ambient-temperature correction factor and optionally checks that the overcurrent device rating does not exceed the derated wire ampacity.

Supported AWG: 30, 28, 26, 24, 22, 20, 18, 16, 14, 12, 10, 8, 6, 4, 2, 0.

Warnings: WIRE_UNDERSIZED, FUSE_OVERSIZED_FOR_WIRE.

Input: { awg, load_current_a, wire_length_m, ambient_temp_c?, insulation_temp_c?, fuse_rating_a? }
Returns: { ok, base_ampacity_a, derated_ampacity_a, ampacity_ok, voltage_drop_v, fuse_ok, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "awg": {
      "type": "integer",
      "description": "AWG wire gauge."
    },
    "load_current_a": {
      "type": "number",
      "description": "Load current [A]."
    },
    "wire_length_m": {
      "type": "number",
      "description": "One-way wire run length [m]."
    },
    "ambient_temp_c": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C] (default 30)."
    },
    "insulation_temp_c": {
      "type": "number",
      "description": "Insulation temperature rating [\u00b0C] (default 60)."
    },
    "fuse_rating_a": {
      "type": "number",
      "description": "Overcurrent device rating [A] (optional)."
    }
  },
  "required": [
    "awg",
    "load_current_a",
    "wire_length_m"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
