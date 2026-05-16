# Steel Connection Design (AISC 360)

Pure-Python AISC 360-22 steel connection calculations. No OCC dependency. All
tools are stateless — they compute and return results; no DB write. Units: SI
(mm for dimensions, N for forces, Pa for stresses), LRFD or ASD.

References: AISC 360-22 — Specification for Structural Steel Buildings;
AISC Steel Construction Manual, 16th edition.

---

## When to use

Trigger on: bolt shear, bolt capacity, bearing capacity, bolt tension, slip-
critical, pre-tensioned bolt, block shear, bolt group, eccentric bolt group,
instantaneous center, fillet weld, weld capacity, weld group, electrode
strength, E70, E60, base plate, column base plate, bearing pressure, AISC,
LRFD, ASD, steel connection, bolted connection, welded connection, J3, J4,
J2, J8.

---

## Tools

### `electrode_strength`

Return Fexx (electrode classification strength) for a standard SMAW/FCAW
electrode designation.

**Key inputs:** `designation` — one of `E60`, `E70`, `E80`, `E90`, `E100`, `E110`.

**Returns:** `Fexx_Pa`, `Fexx_ksi`.

---

### `bolt_shear_capacity`

Compute bolt shear strength per AISC 360-22 J3.6.

**Key inputs:** `Ab` (gross bolt area, mm²), `Fnv` (nominal shear stress, Pa),
`n_bolts`. Optional: `shear_planes` (1 or 2), `Vu` (applied force, N),
`method` (`'LRFD'` or `'ASD'`).

**Returns:** `Rn_N`, design capacity, utilization ratio.

---

### `bolt_bearing_capacity`

Compute bolt bearing strength on connected material per AISC J3.10.

**Key inputs:** `Fu` (ultimate stress of material, Pa), `t` (thickness, mm),
`d` (bolt diameter, mm), `n_bolts`. Optional: `lc` (clear distance, mm),
`Vu`, `method`.

**Returns:** governing capacity (deformation-controlled or clear-distance, lesser),
utilization ratio.

---

### `bolt_tension_capacity`

Compute bolt tension strength per AISC J3.6.

**Key inputs:** `Ab` (mm²), `Fnt` (nominal tensile stress, Pa; A325=621 MPa,
A490=780 MPa), `n_bolts`. Optional: `Tu` (applied tension, N), `method`.

**Returns:** `Rn_N`, design capacity, utilization ratio.

---

### `slip_critical_capacity`

Compute slip-critical connection capacity per AISC J3.8.

**Key inputs:** `mu` (slip coefficient; Class A=0.35, Class B=0.50), `Pt`
(minimum fastener tension, N), `n_bolts`. Optional: `n_faying` (faying
surfaces), `hole_factor` (hf; STD=1.0, oversized=0.85, slotted=0.70),
`Vu`, `method`.

**Returns:** `Rn_N`, design capacity, utilization ratio.

---

### `block_shear_capacity`

Compute block shear rupture capacity per AISC J4.3.

**Key inputs:** `Fu` (Pa), `Fy` (Pa), `Agv` (gross shear area, mm²), `Anv`
(net shear area, mm²), `Ant` (net tension area, mm²). Optional: `Ubs`
(1.0 uniform, 0.5 non-uniform), `Vu`, `method`.

**Returns:** governing Rn (shear rupture + tension rupture vs shear yield +
tension rupture), utilization ratio.

---

### `bolt_group_eccentric`

Compute eccentric bolt group capacity ratio.

**Key inputs:** `bolt_coords` (list of [x_mm, y_mm] per bolt), `P` (applied
shear, N), `e` (eccentricity from bolt-group centroid, mm). Optional:
`method` (`'IC'` default or `'elastic'`), `bolt_capacity_N`.

**Returns:** utilization ratio, governing bolt index, method used.

---

### `fillet_weld_capacity`

Compute fillet weld group capacity per AISC J2.4.

**Key inputs:** `weld_size_mm` (throat-forming leg, mm), `total_length_mm`,
`Fexx_Pa` (electrode strength). Optional: `theta_deg` (load angle from weld
axis, default 0), `method`.

**Returns:** `phi_Rn_N` (LRFD capacity) or `Rn_over_Omega_N` (ASD), utilization.

---

### `weld_group_elastic_vector`

Elastic vector method for an eccentrically loaded weld group.

**Key inputs:** `weld_segments` (list of `{x1,y1,x2,y2,size_mm}` per segment),
`P` (N), `ex` (eccentricity x, mm), `ey` (eccentricity y, mm), `Fexx_Pa`.
Optional: `method`.

**Returns:** max resultant stress at governing segment, utilization ratio.

---

### `base_plate_bearing`

AISC J8 column base plate bearing check.

**Key inputs:** `P` (axial column load, N), `B` (plate width, mm), `N`
(plate length, mm), `f_prime_c` (concrete compressive strength, Pa). Optional:
`method`.

**Returns:** bearing stress, allowable bearing stress, utilization, pass/fail.

---

## Example

**User:** "Check a single-shear bolted connection: four 3/4-inch A325N bolts,
applied shear 150 kN. Use LRFD."

**Tools:**
1. `bolt_shear_capacity` Ab:284.9 Fnv:372e6 n_bolts:4 shear_planes:1 Vu:150000
   method:'LRFD' → utilization ratio and capacity.
2. `bolt_bearing_capacity` Fu:414e6 t:12 d:19.05 n_bolts:4 Vu:150000 → bearing check.
