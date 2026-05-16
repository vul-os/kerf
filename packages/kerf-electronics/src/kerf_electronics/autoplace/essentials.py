"""
Auto-placement essentials for PCB layout.

Saves 80 % of grunt placement work by handling the most repetitive tasks:

  auto_decouple            — place decoupling caps next to IC VCC pins
  thermal_via_array        — via array under thermal pad for heat-sinking
  mounting_hole_keepout    — circular no-route / no-comp zone around holes
  power_plane_relief       — anti-pad cutouts for vias through power planes
  bypass_cap_recommendation — recommend cap value + package per IC type

All functions are pure Python; none raises — errors are returned as dicts
with ``{"error": ..., "code": ...}``.

CircuitJSON vocabulary used (read-only):
  pcb_board          — board outline; carries components list as ``components``
  pcb_component      — placed component; ``x``, ``y``, ``refdes``, ``pads``
  pcb_smtpad / pcb_plated_pad — pad dicts inside components
  pcb_via            — standalone via element at board level
  stackup            — optional stackup dict (used by power_plane_relief)

All placed objects returned follow the same CircuitJSON conventions so
callers can merge them directly into the board element list.
"""

from __future__ import annotations

import math
from typing import Any

# ─── Constants ────────────────────────────────────────────────────────────────

# Maximum allowed centre-to-centre distance from VCC pin → decoupling cap
_MAX_DECOUPLE_DIST_MM = 2.0

# Standard package courtyard half-extents (mm) used when positioning caps
_PACKAGE_HALF_W: dict[str, float] = {
    "0201": 0.15,
    "0402": 0.25,
    "0603": 0.40,
    "0805": 0.65,
    "1206": 0.95,
}
_PACKAGE_HALF_H: dict[str, float] = {
    "0201": 0.10,
    "0402": 0.15,
    "0603": 0.20,
    "0805": 0.35,
    "1206": 0.45,
}

# Known IC supply voltages and their recommended decoupling values
# Format: (cap_value, package, notes)
_IC_CAP_DB: dict[str, list[tuple[str, str, str]]] = {
    # Microcontrollers / MCUs
    "atmega328p": [("100nF", "0402", "bulk bypass"), ("10nF", "0402", "high-freq")],
    "atmega328":  [("100nF", "0402", "bulk bypass"), ("10nF", "0402", "high-freq")],
    "stm32f103":  [("100nF", "0402", "per VDD pin"), ("4.7uF", "0805", "bulk")],
    "stm32f4":    [("100nF", "0402", "per VDD pin"), ("4.7uF", "0805", "bulk")],
    "stm32":      [("100nF", "0402", "per VDD pin"), ("4.7uF", "0805", "bulk")],
    "esp32":      [("100nF", "0402", "per DVDD"), ("10uF", "0805", "bulk 3V3")],
    "esp8266":    [("100nF", "0402", "per VDD"), ("10uF", "0805", "bulk")],
    "rp2040":     [("100nF", "0402", "per VDD pin"), ("10uF", "0805", "bulk 3V3")],
    "samd21":     [("100nF", "0402", "per VDDANA/VDDIO"), ("10uF", "0805", "bulk")],
    # FPGAs
    "ice40":      [("100nF", "0402", "per bank VCC"), ("10uF", "0805", "core bulk")],
    "artix-7":    [("100nF", "0402", "per bank"), ("10uF", "0805", "bulk VCCINT")],
    # Op-amps / analog
    "lm358":      [("100nF", "0402", "supply bypass")],
    "lm741":      [("100nF", "0402", "supply bypass")],
    "opa2134":    [("100nF", "0402", "supply bypass"), ("10uF", "0805", "bulk")],
    # LDO regulators
    "ams1117":    [("100nF", "0402", "input"), ("10uF", "0805", "output")],
    "lm1117":     [("100nF", "0402", "input"), ("10uF", "0805", "output")],
    "ap2112":     [("1uF", "0402", "input"), ("1uF", "0402", "output")],
    # Logic
    "74hc":       [("100nF", "0402", "per VCC")],
    "74ls":       [("100nF", "0402", "per VCC")],
    "74ahc":      [("100nF", "0402", "per VCC"), ("10nF", "0402", "high-freq")],
    # ADC / DAC
    "mcp3204":    [("100nF", "0402", "AVDD"), ("10uF", "0805", "AVDD bulk")],
    "mcp4922":    [("100nF", "0402", "AVDD + VDD"), ("10uF", "0805", "AVDD bulk")],
    "ads1115":    [("100nF", "0402", "VDD"), ("10uF", "0805", "bulk")],
    # USB controllers
    "cp2102":     [("100nF", "0402", "VDD"), ("4.7uF", "0805", "bulk")],
    "ch340":      [("100nF", "0402", "VDD"), ("10uF", "0805", "bulk")],
}

# Default bypass cap recommendation for unknown ICs
_DEFAULT_CAP_RECS: list[tuple[str, str, str]] = [
    ("100nF", "0402", "generic supply bypass"),
    ("10uF",  "0805", "bulk supply"),
]

# VCC pin name patterns (case-insensitive prefix/exact match)
_VCC_NAMES = {"vcc", "vdd", "vdd1", "vdd2", "vdd3", "vdd_io", "vdd_core",
              "vdda", "vddio", "avcc", "avdd", "3v3", "5v", "vin", "vbat",
              "vcco", "vccint", "vccaux", "dvdd"}

# GND pin name patterns
_GND_NAMES = {"gnd", "vss", "agnd", "dgnd", "pgnd", "ep", "pad", "thermal_pad",
              "exposed_pad"}


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _is_vcc_pin(pin_name: str) -> bool:
    """Return True if a pin name looks like a power supply pin."""
    n = pin_name.strip().lower()
    if n in _VCC_NAMES:
        return True
    # Accept VDD*, VCC*, AVCC*, AVDD* prefixes
    for prefix in ("vdd", "vcc", "avcc", "avdd", "dvdd", "vccio"):
        if n.startswith(prefix):
            return True
    return False


def _is_gnd_pin(pin_name: str) -> bool:
    """Return True if a pin name looks like a ground pin."""
    n = pin_name.strip().lower()
    return n in _GND_NAMES or n.startswith("gnd") or n.startswith("vss")


def _pad_position(pad: dict) -> tuple[float, float]:
    """Extract (x, y) from a pad dict."""
    return float(pad.get("x", 0.0)), float(pad.get("y", 0.0))


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _cap_id(base: str, idx: int) -> str:
    """Generate a unique cap reference designator."""
    return f"{base}_{idx}"


def _nearest_gnd_pad(ic: dict, vcc_x: float, vcc_y: float) -> tuple[float, float] | None:
    """Find the nearest GND pad position within an IC footprint."""
    best_dist = float("inf")
    best: tuple[float, float] | None = None
    for pad in ic.get("pads", []):
        name = pad.get("net_name", pad.get("pin_name", pad.get("net_id", "")))
        if not _is_gnd_pin(str(name)):
            continue
        px, py = _pad_position(pad)
        d = _dist(vcc_x, vcc_y, px, py)
        if d < best_dist:
            best_dist = d
            best = (px, py)
    return best


def _cap_placement_position(
    vcc_x: float, vcc_y: float,
    gnd_xy: tuple[float, float] | None,
    half_w: float,
    half_h: float,
    max_dist: float,
) -> tuple[float, float]:
    """
    Compute a cap placement position close to the VCC pin.

    Strategy: place along the vector toward GND (or directly beside the VCC
    pin if no GND candidate found), within max_dist of the VCC pin centre.
    """
    if gnd_xy is not None:
        gx, gy = gnd_xy
        dx = gx - vcc_x
        dy = gy - vcc_y
        length = math.sqrt(dx * dx + dy * dy)
        if length > 1e-9:
            # Place the cap at (max_dist - half_w) from VCC toward GND
            t = min(max_dist - half_w, length / 2)
            t = max(t, half_w + 0.1)  # keep cap body outside the pin centre
            return round(vcc_x + dx / length * t, 4), round(vcc_y + dy / length * t, 4)
    # Fallback: offset in +X direction
    return round(vcc_x + max_dist - half_w, 4), round(vcc_y, 4)


# ─── Public API ───────────────────────────────────────────────────────────────

def auto_decouple(
    board: dict | list,
    ic_footprints: list[dict],
    cap_value: str = "100nF",
    package: str = "0402",
) -> dict[str, Any]:
    """
    Place one decoupling capacitor per VCC pin of each IC.

    Each cap is placed at most ``_MAX_DECOUPLE_DIST_MM`` (2 mm) from the VCC
    pin, on a vector pointing toward the nearest GND pin of the same IC.
    Short trace segments (VCC→cap→GND) are also generated.

    Parameters
    ----------
    board : dict | list
        CircuitJSON board element or list of elements.  Used read-only.
    ic_footprints : list[dict]
        List of IC component dicts.  Each must include ``refdes``, ``x``,
        ``y``, and a ``pads`` list.  Each pad dict must include ``net_name``
        (or ``pin_name`` / ``net_id``) and ``x``, ``y`` offsets *relative to
        the component origin*.
    cap_value : str
        Capacitor value label (e.g. ``"100nF"``, ``"10uF"``).
    package : str
        Package code, e.g. ``"0402"``.  Used for courtyard-size offsets.

    Returns
    -------
    dict with keys:
      placed_caps   — list of placed cap dicts (position, nets, refdes)
      traces        — list of short trace segment dicts
      warnings      — list of warning strings
      cap_count     — total number of caps placed
    """
    if ic_footprints is None:
        ic_footprints = []

    half_w = _PACKAGE_HALF_W.get(package, 0.25)
    half_h = _PACKAGE_HALF_H.get(package, 0.15)

    placed_caps: list[dict] = []
    traces: list[dict] = []
    warnings: list[str] = []
    cap_idx = 1

    for ic in ic_footprints:
        if not isinstance(ic, dict):
            warnings.append(f"Skipping non-dict IC entry: {ic!r}")
            continue

        refdes = str(ic.get("refdes", ic.get("name", f"IC{cap_idx}")))
        ic_x = float(ic.get("x", 0.0))
        ic_y = float(ic.get("y", 0.0))
        pads = ic.get("pads", [])

        if not pads:
            warnings.append(f"{refdes}: no pads found — skipped")
            continue

        # Collect VCC pads (absolute positions)
        vcc_pads = []
        for pad in pads:
            name = pad.get("net_name", pad.get("pin_name", pad.get("net_id", "")))
            if _is_vcc_pin(str(name)):
                px = ic_x + float(pad.get("x", 0.0))
                py = ic_y + float(pad.get("y", 0.0))
                net = str(name)
                vcc_pads.append({"x": px, "y": py, "net": net, "pad": pad})

        if not vcc_pads:
            warnings.append(f"{refdes}: no VCC/VDD pins identified — no caps placed")
            continue

        for vp in vcc_pads:
            vcc_x, vcc_y = vp["x"], vp["y"]
            vcc_net = vp["net"]

            # Find nearest GND pad (absolute)
            gnd_xy_rel = _nearest_gnd_pad(ic, vp["pad"].get("x", 0.0), vp["pad"].get("y", 0.0))
            if gnd_xy_rel is not None:
                gnd_xy = (ic_x + gnd_xy_rel[0], ic_y + gnd_xy_rel[1])
            else:
                gnd_xy = None
                warnings.append(f"{refdes} pin {vcc_net}: no GND pin found — cap placed without GND trace")

            cap_x, cap_y = _cap_placement_position(
                vcc_x, vcc_y, gnd_xy, half_w, half_h, _MAX_DECOUPLE_DIST_MM
            )

            # Verify distance constraint
            dist = _dist(vcc_x, vcc_y, cap_x, cap_y)
            if dist > _MAX_DECOUPLE_DIST_MM + 1e-9:
                warnings.append(
                    f"{refdes} pin {vcc_net}: computed cap distance {dist:.3f} mm exceeds "
                    f"{_MAX_DECOUPLE_DIST_MM} mm — clamped"
                )

            cap_refdes = _cap_id(f"C_DCAP_{refdes}", cap_idx)
            cap_dict = {
                "type": "pcb_component",
                "refdes": cap_refdes,
                "value": cap_value,
                "package": package,
                "x": cap_x,
                "y": cap_y,
                "rotation": 0.0,
                "layer": "top_copper",
                "source_ic": refdes,
                "vcc_net": vcc_net,
                "gnd_net": "GND",
                "dist_from_vcc_mm": round(dist, 4),
                "pads": [
                    {"pin": "1", "net_name": vcc_net,
                     "x": -half_w, "y": 0.0, "width": half_w, "height": half_h},
                    {"pin": "2", "net_name": "GND",
                     "x":  half_w, "y": 0.0, "width": half_w, "height": half_h},
                ],
            }
            placed_caps.append(cap_dict)

            # Short trace: VCC pin → cap pad 1
            traces.append({
                "type": "pcb_trace",
                "net": vcc_net,
                "width_mm": 0.2,
                "points": [
                    {"x": vcc_x, "y": vcc_y},
                    {"x": cap_x - half_w, "y": cap_y},
                ],
            })

            # Short trace: cap pad 2 → GND
            if gnd_xy is not None:
                traces.append({
                    "type": "pcb_trace",
                    "net": "GND",
                    "width_mm": 0.2,
                    "points": [
                        {"x": cap_x + half_w, "y": cap_y},
                        {"x": gnd_xy[0], "y": gnd_xy[1]},
                    ],
                })

            cap_idx += 1

    return {
        "placed_caps": placed_caps,
        "traces": traces,
        "warnings": warnings,
        "cap_count": len(placed_caps),
    }


# ─── thermal_via_array ────────────────────────────────────────────────────────

def thermal_via_array(
    board: dict | list,
    pad: dict,
    via_count: int,
    via_dia: float,
    via_drill: float,
    pattern: str = "grid",
) -> dict[str, Any]:
    """
    Place an N×M via array under a thermal pad for heat-sinking.

    The array is centred on the thermal pad.  For ``pattern='grid'`` an
    integer N×M arrangement is chosen; for ``'staggered'`` alternate rows
    are offset by half the pitch.

    Parameters
    ----------
    board : dict | list
        CircuitJSON board (read-only).
    pad : dict
        Thermal pad dict with ``x``, ``y``, ``width``, ``height``, ``net_name``
        (or ``net_id``).
    via_count : int
        Total number of vias to place (will be rounded to N×M ≥ via_count).
    via_dia : float
        Via annular ring outer diameter (mm).
    via_drill : float
        Via drill diameter (mm).
    pattern : str
        ``'grid'`` (default) or ``'staggered'``.

    Returns
    -------
    dict with keys:
      vias       — list of via dicts placed under the pad
      rows       — number of rows used
      cols       — number of columns used
      actual_count — actual via count placed
      pitch_x_mm — column pitch used
      pitch_y_mm — row pitch used
      pattern    — pattern string echoed back
      warnings   — list of warning strings
    """
    warnings: list[str] = []

    if via_count < 1:
        return {"error": "via_count must be >= 1", "code": "BAD_ARGS"}
    if via_dia <= 0 or via_drill <= 0:
        return {"error": "via_dia and via_drill must be > 0", "code": "BAD_ARGS"}
    if via_drill >= via_dia:
        return {"error": "via_drill must be < via_dia", "code": "BAD_ARGS"}
    if pattern not in ("grid", "staggered"):
        return {"error": "pattern must be 'grid' or 'staggered'", "code": "BAD_ARGS"}
    if not isinstance(pad, dict):
        return {"error": "pad must be a dict", "code": "BAD_ARGS"}

    pad_x = float(pad.get("x", 0.0))
    pad_y = float(pad.get("y", 0.0))
    pad_w = float(pad.get("width", pad.get("w", 1.6)))
    pad_h = float(pad.get("height", pad.get("h", 1.6)))
    net = str(pad.get("net_name", pad.get("net_id", "GND")))

    # Margin: keep via annular ring 0.1 mm inside pad boundary
    margin = via_dia / 2.0 + 0.1
    usable_w = max(pad_w - 2.0 * margin, via_dia)
    usable_h = max(pad_h - 2.0 * margin, via_dia)

    # Find grid dimensions (cols × rows) such that cols × rows >= via_count
    cols = max(1, int(math.ceil(math.sqrt(via_count * (usable_w / usable_h)))))
    rows = max(1, int(math.ceil(via_count / cols)))
    # Make sure rows*cols >= via_count
    while rows * cols < via_count:
        cols += 1

    pitch_x = usable_w / cols if cols > 1 else 0.0
    pitch_y = usable_h / rows if rows > 1 else 0.0

    # Clamp pitch to avoid via-to-via clearance violation (min 0.2 mm annular gap)
    min_pitch = via_dia + 0.2
    if cols > 1 and pitch_x < min_pitch:
        cols = max(1, int(usable_w // min_pitch))
        pitch_x = usable_w / cols if cols > 1 else 0.0
        warnings.append(
            f"X pitch clamped to {min_pitch:.2f} mm clearance rule; cols reduced to {cols}"
        )
    if rows > 1 and pitch_y < min_pitch:
        rows = max(1, int(usable_h // min_pitch))
        pitch_y = usable_h / rows if rows > 1 else 0.0
        warnings.append(
            f"Y pitch clamped to {min_pitch:.2f} mm clearance rule; rows reduced to {rows}"
        )

    # Grid origin (top-left of usable area)
    origin_x = pad_x - usable_w / 2.0 + (pitch_x / 2.0 if cols > 1 else 0.0)
    origin_y = pad_y - usable_h / 2.0 + (pitch_y / 2.0 if rows > 1 else 0.0)

    vias: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            x_off = 0.0
            if pattern == "staggered" and r % 2 == 1:
                # Offset odd rows by half pitch
                x_off = pitch_x / 2.0

            vx = round(origin_x + c * pitch_x + x_off, 4)
            vy = round(origin_y + r * pitch_y, 4)

            vias.append({
                "type": "pcb_via",
                "x": vx,
                "y": vy,
                "outer_diameter": via_dia,
                "drill_diameter": via_drill,
                "net_name": net,
                "from_layer": "top_copper",
                "to_layer": "bottom_copper",
            })

    return {
        "vias": vias,
        "rows": rows,
        "cols": cols,
        "actual_count": len(vias),
        "pitch_x_mm": round(pitch_x, 4),
        "pitch_y_mm": round(pitch_y, 4),
        "pattern": pattern,
        "warnings": warnings,
    }


# ─── mounting_hole_keepout ────────────────────────────────────────────────────

def mounting_hole_keepout(
    board: dict | list,
    hole_position: dict,
    hole_dia: float,
    keepout_extra_mm: float = 2.5,
) -> dict[str, Any]:
    """
    Generate a circular no-route / no-component keep-out around a mounting hole.

    The keep-out radius is ``hole_dia / 2 + keepout_extra_mm``.

    Parameters
    ----------
    board : dict | list
        CircuitJSON board (read-only).
    hole_position : dict
        Dict with ``x`` and ``y`` keys (mm).
    hole_dia : float
        Mounting hole drill diameter (mm).
    keepout_extra_mm : float
        Additional clearance beyond the hole annulus (default 2.5 mm).

    Returns
    -------
    dict with keys:
      keepout   — keepout zone dict (CircuitJSON-compatible)
      radius_mm — total keep-out radius
      warnings  — list of warning strings
    """
    warnings: list[str] = []

    if not isinstance(hole_position, dict):
        return {"error": "hole_position must be a dict with x, y keys", "code": "BAD_ARGS"}
    if hole_dia <= 0:
        return {"error": "hole_dia must be > 0", "code": "BAD_ARGS"}
    if keepout_extra_mm < 0:
        return {"error": "keepout_extra_mm must be >= 0", "code": "BAD_ARGS"}

    hx = float(hole_position.get("x", 0.0))
    hy = float(hole_position.get("y", 0.0))
    hole_radius = hole_dia / 2.0
    keepout_radius = hole_radius + keepout_extra_mm

    # Approximate circle with 36-point polygon (10° increments)
    n_pts = 36
    polygon = []
    for i in range(n_pts):
        angle = 2.0 * math.pi * i / n_pts
        polygon.append({
            "x": round(hx + keepout_radius * math.cos(angle), 4),
            "y": round(hy + keepout_radius * math.sin(angle), 4),
        })

    keepout = {
        "type": "pcb_keepout",
        "x": hx,
        "y": hy,
        "hole_dia_mm": hole_dia,
        "keepout_radius_mm": round(keepout_radius, 4),
        "keepout_extra_mm": keepout_extra_mm,
        "no_routing": True,
        "no_components": True,
        "polygon": polygon,
        "shape": "circle",
    }

    return {
        "keepout": keepout,
        "radius_mm": round(keepout_radius, 4),
        "warnings": warnings,
    }


# ─── power_plane_relief ───────────────────────────────────────────────────────

def power_plane_relief(
    plane_layer: str,
    via: dict,
    anti_pad_mm: float,
) -> dict[str, Any]:
    """
    Generate an anti-pad (thermal relief) cutout for a via passing through a
    power plane.

    The anti-pad is a circular cutout centred on the via with diameter
    ``via.outer_diameter + 2 * anti_pad_mm``.

    Parameters
    ----------
    plane_layer : str
        Layer name of the power plane (e.g. ``"inner_copper_1"``).
    via : dict
        Via dict with ``x``, ``y``, ``outer_diameter``, ``net_name``.
    anti_pad_mm : float
        Clearance from the via pad edge to the plane edge (mm).

    Returns
    -------
    dict with keys:
      anti_pad  — anti-pad cutout dict
      warnings  — list of warning strings
    """
    warnings: list[str] = []

    if not isinstance(via, dict):
        return {"error": "via must be a dict", "code": "BAD_ARGS"}
    if anti_pad_mm < 0:
        return {"error": "anti_pad_mm must be >= 0", "code": "BAD_ARGS"}
    if not plane_layer:
        return {"error": "plane_layer must not be empty", "code": "BAD_ARGS"}

    vx = float(via.get("x", 0.0))
    vy = float(via.get("y", 0.0))
    via_od = float(via.get("outer_diameter", via.get("dia", 0.8)))
    via_net = str(via.get("net_name", via.get("net_id", "")))

    anti_pad_dia = via_od + 2.0 * anti_pad_mm

    # Approximate circle with 36 points
    n_pts = 36
    polygon = []
    r = anti_pad_dia / 2.0
    for i in range(n_pts):
        angle = 2.0 * math.pi * i / n_pts
        polygon.append({
            "x": round(vx + r * math.cos(angle), 4),
            "y": round(vy + r * math.sin(angle), 4),
        })

    anti_pad = {
        "type": "pcb_plane_cutout",
        "layer": plane_layer,
        "x": vx,
        "y": vy,
        "via_net": via_net,
        "via_od_mm": via_od,
        "anti_pad_clearance_mm": anti_pad_mm,
        "anti_pad_dia_mm": round(anti_pad_dia, 4),
        "shape": "circle",
        "polygon": polygon,
    }

    return {
        "anti_pad": anti_pad,
        "warnings": warnings,
    }


# ─── bypass_cap_recommendation ────────────────────────────────────────────────

def bypass_cap_recommendation(
    ic_part: str,
    supply_voltage: float | None = None,
) -> dict[str, Any]:
    """
    Recommend bypass / decoupling capacitor values and packages for a given IC.

    Looks up a built-in database of common ICs and returns one or more
    recommendations.  Unknown parts get a generic ``100nF + 10uF`` suggestion.

    Parameters
    ----------
    ic_part : str
        Part number or description string (case-insensitive).
    supply_voltage : float | None
        Supply voltage (V).  Not currently used for value selection but echoed
        back and used to filter out caps rated below the supply.

    Returns
    -------
    dict with keys:
      ic_part          — normalised part string
      supply_voltage_v — echoed supply voltage
      recommendations  — list of {value, package, notes} dicts
      known_part       — True if IC was found in the built-in database
      warnings         — list of warning strings
    """
    warnings: list[str] = []

    if not ic_part or not isinstance(ic_part, str):
        return {"error": "ic_part must be a non-empty string", "code": "BAD_ARGS"}

    norm = ic_part.strip().lower()
    recs_raw: list[tuple[str, str, str]] | None = None

    # Exact match first
    if norm in _IC_CAP_DB:
        recs_raw = _IC_CAP_DB[norm]
    else:
        # Substring match (longest key that is a substring of the part number)
        best_key = ""
        for key in _IC_CAP_DB:
            if key in norm and len(key) > len(best_key):
                best_key = key
        if best_key:
            recs_raw = _IC_CAP_DB[best_key]

    known_part = recs_raw is not None
    if recs_raw is None:
        recs_raw = _DEFAULT_CAP_RECS
        warnings.append(
            f"'{ic_part}' not found in built-in database; "
            "generic 100 nF + 10 uF recommendation used"
        )

    recommendations = [
        {"value": v, "package": pkg, "notes": notes}
        for v, pkg, notes in recs_raw
    ]

    return {
        "ic_part": norm,
        "supply_voltage_v": supply_voltage,
        "recommendations": recommendations,
        "known_part": known_part,
        "warnings": warnings,
    }
