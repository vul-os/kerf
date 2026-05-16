# Gear Train (Gearbox) Assembly

Pure-Python multi-stage gear-train analysis. No OCC dependency. All tools are
stateless — they compute and return results; no DB write. Units: mm, rpm, N·m.

References: Shigley §13-4 to §13-7; ISO 21771:2007.

---

## When to use

Trigger on: gearbox, gear train, speed reducer, speed increaser, multi-stage
gears, gear ratio, drivetrain, shaft speed, shaft torque, output rpm,
cumulative centre distance, gear efficiency, idler gear.

---

## Tools

### `gearbox_design`

Design a complete multi-stage gear train.

**Key inputs:** `stages` (ordered list of `{z1, z2, module}` pairs), `input_rpm`,
`input_torque`.

**Computes:** total ratio = ∏(z2/z1), per-shaft speed and torque, per-stage
centre distance, interference/undercut warnings, cumulative shaft layout, total
drivetrain efficiency = ∏η_i.

**Returns:** `{ok, total_ratio, efficiency, shafts:[...], stages:[...], warnings:[]}`.

---

### `gearbox_ratio`

Compute only the total gear ratio without full design analysis.

**Key inputs:** `stages` (ordered list of `{z1, z2, module}` pairs).

**Computes:** total_ratio = ∏(z2/z1) for non-idler stages.

**Returns:** `{ok, total_ratio, stage_ratios:[...]}`.

---

### `gearbox_shaft_table`

Return the shaft speed/torque table from a gear-train description.

**Key inputs:** `stages`, `input_rpm`, `input_torque`.

**Computes:** per-shaft speed, torque, and cumulative centre distance.

**Returns:** `{ok, shafts:[{shaft_id, rpm, torque_nm, cumulative_centre_distance_mm}]}`.

---

## Example

**User:** "I need a two-stage gearbox to reduce a 1450 rpm 50 N·m motor to
about 100 rpm. Stage 1: z1=18, z2=54, module=2. Stage 2: z1=15, z2=45, module=2."

**Tool:** `gearbox_design` with `stages=[{z1:18,z2:54,module:2},{z1:15,z2:45,module:2}]`,
`input_rpm:1450`, `input_torque:50`.

Returns total_ratio ≈ 9.0, output shaft ≈ 161 rpm, output torque ≈ 441 N·m,
plus stage centre distances and any undercut warnings.
