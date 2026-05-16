# Lathe Turning CAM (CNC Turning Cycles)

Pure-Python CNC turning cycle generators and cutting-parameter calculators. No
OCC dependency. All tools are stateless — they compute ISO G-code lines and
pass metadata; no DB write. Units: mm, rpm, m/min, mm/rev.

References: ISO 6983-1:2009; Fanuc 0i-TF Operator's Manual (G71, G70, G76, G32);
Machinery's Handbook, 30th ed.

Profile convention: list of `[Z_mm, X_radius_mm]` pairs where Z is axial
position (positive towards tailstock) and X is the radius (not diameter).

---

## When to use

Trigger on: CNC turning, lathe, G-code turning, roughing pass, finishing pass,
facing, parting, cut-off, threading lathe, OD thread, ID thread, groove, grooving,
turning cycle, G71, G70, G76, constant surface speed, spindle RPM, feed per
revolution, depth of cut, stock removal, turning profile, turning toolpath.

---

## Tools

### `turning_cutting_params`

Compute spindle RPM and feed rate (mm/min) for each point in a turning profile.

**Key inputs:** `profile` (list of [Z, X] pairs). Optional: `css_m_per_min`
(default 180), `feed_mm_rev` (default 0.20), `rpm_min` (default 50),
`rpm_max` (default 3500).

**Returns:** per-point `{z_mm, x_mm, diameter_mm, rpm, feed_mm_min}`.

---

### `turning_roughing_passes`

Generate G71-equivalent OD roughing passes from a 2D turning profile.

**Key inputs:** `profile`, `stock_x_mm` (initial stock radius). Optional:
`doc_mm` (depth of cut, default 2.0), `css_m_per_min`, `feed_mm_rev`,
`finish_allowance_mm` (default 0.3).

**Returns:** `{ok, pass_count, passes:[...], gcode:[...], warnings:[]}`.

---

### `turning_finishing_pass`

Generate a G70-equivalent finishing pass that follows the exact profile.

**Key inputs:** `profile`. Optional: `css_m_per_min`, `feed_mm_rev`
(default 0.08 for finish), `doc_mm` (default 0.25).

**Returns:** `{ok, pass_count, passes:[...], gcode:[...], warnings:[]}`.

---

### `turning_facing`

Generate a facing cycle cutting the end face from OD inward.

**Key inputs:** `x_max_mm` (outer radius at face), `z_face_mm` (axial position
of face). Optional: `doc_mm` (axial DOC, default 2.0), `n_passes`, `css_m_per_min`,
`feed_mm_rev`, `bore_radius_mm` (stop radius for hollow parts, default 0).

**Returns:** `{ok, pass_count, passes:[...], gcode:[...], warnings:[]}`.

---

### `turning_parting`

Generate a parting (cut-off) cycle at a specified Z position.

**Key inputs:** `z_part_mm` (axial position of cut), `x_max_mm` (outer radius).
Optional: `css_m_per_min` (default 80 m/min), `feed_mm_rev` (default 0.05),
`peck_depth_mm` (for peck parting on deep/interrupted cuts), `bore_radius_mm`.

**Returns:** `{ok, pass_count, passes:[...], gcode:[...], warnings:[]}`.

---

### `turning_od_threading`

Generate an external (OD) threading cycle using G76-style degressive infeed.

**Key inputs:** `z_start_mm`, `z_end_mm` (thread extent), `pitch_mm`,
`x_major_mm` (major diameter radius). Optional: `infeed_deg` (default 29.5° for
60° thread form), `thread_depth_mm` (default 0.6495 × pitch).

**Returns:** `{ok, pass_count, passes:[...], gcode:[...], warnings:[]}`.

---

### `turning_id_threading`

Generate an internal (ID / bore) threading cycle using G76-style degressive infeed.

**Key inputs:** `z_start_mm`, `z_end_mm`, `pitch_mm`, `x_minor_mm` (minor radius
of bore). Optional: `infeed_deg`, `thread_depth_mm`.

**Returns:** `{ok, pass_count, passes:[...], gcode:[...], warnings:[]}`.

---

### `turning_grooving`

Generate a single or multi-step grooving cycle.

**Key inputs:** `z_groove_mm` (groove centre Z), `x_bottom_mm` (groove floor
radius), `x_top_mm` (groove OD radius). Optional: `width_mm`, `doc_mm`
(peck increment), `css_m_per_min`, `feed_mm_rev`.

**Returns:** `{ok, pass_count, passes:[...], gcode:[...], warnings:[]}`.

---

## Example

**User:** "I have a steel shaft profile: [(0, 25), (50, 25), (50, 15), (80, 15)] mm
(Z, radius). Stock radius 28 mm. Generate roughing and finishing G-code."

**Tools:**
1. `turning_roughing_passes` profile:[...] stock_x_mm:28 doc_mm:2.0 → roughing G-code.
2. `turning_finishing_pass` profile:[...] feed_mm_rev:0.08 → finishing G-code.
