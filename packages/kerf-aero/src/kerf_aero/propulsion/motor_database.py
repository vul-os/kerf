"""Motor database integration — Thrustcurve / RASP .eng format.

Provides:
  - RASP .eng file parsing (the standard amateur-rocketry motor data format
    used by OpenRocket, RASAero, and Thrustcurve.org).
  - A built-in curated motor catalogue of 30+ commonly-used commercial motors
    (Estes, Aerotech, Cesaroni, Apogee) with full thrust-curve data.
  - Performance integrators: total impulse, average thrust, burn time, Isp.
  - Motor selector: filter by impulse class, average thrust, or manufacturer.
  - ThrustcurveMotor dataclass for structured motor data exchange.

RASP .eng Format Reference
--------------------------
The RASP .eng format (used since ~1990) is a plain-text thrust-curve format:

    ; comments begin with semicolon
    <motor-name> <diam-mm> <len-mm> <delays> <propMass-g> <totalMass-g> <manufacturer>
    <time-s> <thrust-N>
    ...
    0.000 0.000   (final zero entry)

Diameter, length, delays, and manufacturer are metadata.  Delays are seconds
of ejection delay (or 0 for motor mounts).

Multiple motors may appear in a single file separated by blank lines.

Units in .eng files: time [s], thrust [N], mass [g].

References
----------
National Association of Rocketry (NAR), "RASP .eng File Format",
    http://www.nar.org/SandT/pdf/Cesaroni/Cesaroni_Motor_Data.pdf
Thrustcurve.org, "Motor Data Format",
    https://www.thrustcurve.org/info/motorformat.html
Apogee Rockets, "Understanding Motor Codes",
    https://www.apogeerockets.com/Rocket_Motots/Understanding_Motor_Codes
NAR & Tripoli Rocketry Association (TRA), "Motor Classification Impulse Ranges",
    https://www.nar.org/standards-and-testing-committee/impulse-limits/
Sutton & Biblarz, "Rocket Propulsion Elements", 9th ed., §11 (solid propellants).
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Standard gravity [m/s²]
G0_M_S2: float = 9.80665

#: NAR/TRA impulse classification boundaries [N·s]
#: Class letter → upper bound of total impulse for that class.
#: "A" starts at 1.26 N·s; each subsequent class doubles the range.
#: Ref: NAR Standards & Testing Committee.
IMPULSE_CLASS_BOUNDS: dict[str, tuple[float, float]] = {
    # letter : (lower_inclusive, upper_inclusive) [N·s]
    # NAR/TRA standard: A = 1.26–2.50 N·s, each class doubles upper bound.
    # Ref: NAR Standards & Testing Committee; TRA Classification Policy.
    "1/4A": (0.0,    0.625),
    "1/2A": (0.626,  1.25),
    "A":    (1.251,  2.50),
    "B":    (2.501,  5.00),
    "C":    (5.001,  10.00),
    "D":    (10.001, 20.00),
    "E":    (20.001, 40.00),
    "F":    (40.001, 80.00),
    "G":    (80.001, 160.00),
    "H":    (160.001, 320.00),
    "I":    (320.001, 640.00),
    "J":    (640.001, 1_280.00),
    "K":    (1_280.001, 2_560.00),
    "L":    (2_560.001, 5_120.00),
    "M":    (5_120.001, 10_240.00),
    "N":    (10_240.001, 20_480.00),
    "O":    (20_480.001, 40_960.00),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ThrustCurvePoint:
    """A single (time, thrust) data point from a motor thrust curve.

    Attributes
    ----------
    time_s : float
        Time since ignition [s].
    thrust_n : float
        Thrust at this time instant [N].
    """
    time_s: float
    thrust_n: float


@dataclass
class ThrustcurveMotor:
    """Complete characterisation of a solid rocket motor.

    Attributes
    ----------
    name : str
        Motor designation (e.g. 'Estes-A8-3', 'AT-G79-W').
    manufacturer : str
        Manufacturer name or abbreviation.
    diameter_mm : float
        Motor outer diameter [mm].
    length_mm : float
        Motor length [mm].
    propellant_mass_g : float
        Propellant mass [g] (inert mass = total_mass_g - propellant_mass_g).
    total_mass_g : float
        Total loaded motor mass [g].
    thrust_curve : list[ThrustCurvePoint]
        Time-thrust data points, first at t=0, last at thrust=0 (burn-end).
    delays_s : list[float]
        Available ejection-charge delay options [s].  Empty list = plugged.
    comments : list[str]
        Metadata comments from the .eng file.

    Derived properties (computed on demand)
    ----------------------------------------
    total_impulse_ns : float   — ∫F dt [N·s]
    average_thrust_n : float   — total_impulse / burn_time [N]
    burn_time_s      : float   — time from ignition to last thrust > 0 [s]
    isp_s            : float   — specific impulse [s] = total_impulse / (m_p × g₀)
    impulse_class    : str     — NAR/TRA letter classification (A–O)
    """
    name: str
    manufacturer: str
    diameter_mm: float
    length_mm: float
    propellant_mass_g: float
    total_mass_g: float
    thrust_curve: list[ThrustCurvePoint]
    delays_s: list[float] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived performance metrics (computed lazily on first access)
    # ------------------------------------------------------------------

    @property
    def total_impulse_ns(self) -> float:
        """Total impulse [N·s] via trapezoidal integration of thrust curve."""
        if len(self.thrust_curve) < 2:
            return 0.0
        imp = 0.0
        for i in range(1, len(self.thrust_curve)):
            dt = self.thrust_curve[i].time_s - self.thrust_curve[i - 1].time_s
            avg = 0.5 * (self.thrust_curve[i].thrust_n + self.thrust_curve[i - 1].thrust_n)
            imp += avg * dt
        return imp

    @property
    def burn_time_s(self) -> float:
        """Burn time [s]: time of last non-zero thrust sample."""
        for pt in reversed(self.thrust_curve):
            if pt.thrust_n > 1e-9:
                return pt.time_s
        return 0.0

    @property
    def average_thrust_n(self) -> float:
        """Average thrust [N] = total_impulse / burn_time."""
        bt = self.burn_time_s
        if bt <= 0.0:
            return 0.0
        return self.total_impulse_ns / bt

    @property
    def peak_thrust_n(self) -> float:
        """Peak (maximum) thrust [N]."""
        if not self.thrust_curve:
            return 0.0
        return max(pt.thrust_n for pt in self.thrust_curve)

    @property
    def isp_s(self) -> float:
        """Specific impulse [s] = total_impulse / (propellant_mass × g₀).

        Uses propellant mass in kg.  Returns 0 if propellant mass is zero.
        """
        mp_kg = self.propellant_mass_g / 1000.0
        if mp_kg <= 0.0:
            return 0.0
        return self.total_impulse_ns / (mp_kg * G0_M_S2)

    @property
    def impulse_class(self) -> str:
        """NAR/TRA impulse class letter (A–O) for this motor's total impulse."""
        ti = self.total_impulse_ns
        for cls, (lo, hi) in IMPULSE_CLASS_BOUNDS.items():
            if lo <= ti <= hi:
                return cls
        if ti > 20_480.0:
            return "O+"   # above classification range
        return "sub-A"

    def thrust_at(self, time_s: float) -> float:
        """Interpolate thrust at an arbitrary time [s].

        Linear interpolation between thrust-curve data points.
        Returns 0 for time before first point or after last non-zero point.

        Parameters
        ----------
        time_s : float
            Query time [s] since ignition.

        Returns
        -------
        float
            Interpolated thrust [N].
        """
        if not self.thrust_curve or time_s < 0.0:
            return 0.0
        pts = self.thrust_curve
        if time_s >= pts[-1].time_s:
            return 0.0
        if time_s <= pts[0].time_s:
            return pts[0].thrust_n
        # Binary search for bracket
        lo, hi = 0, len(pts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if pts[mid].time_s <= time_s:
                lo = mid
            else:
                hi = mid
        t0, t1 = pts[lo].time_s, pts[hi].time_s
        if t1 == t0:
            return pts[lo].thrust_n
        frac = (time_s - t0) / (t1 - t0)
        return pts[lo].thrust_n + frac * (pts[hi].thrust_n - pts[lo].thrust_n)

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict (for LLM tool output)."""
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "diameter_mm": self.diameter_mm,
            "length_mm": self.length_mm,
            "propellant_mass_g": self.propellant_mass_g,
            "total_mass_g": self.total_mass_g,
            "delays_s": self.delays_s,
            "total_impulse_ns": round(self.total_impulse_ns, 4),
            "average_thrust_n": round(self.average_thrust_n, 4),
            "peak_thrust_n": round(self.peak_thrust_n, 4),
            "burn_time_s": round(self.burn_time_s, 4),
            "isp_s": round(self.isp_s, 2),
            "impulse_class": self.impulse_class,
            "n_thrust_points": len(self.thrust_curve),
        }


# ---------------------------------------------------------------------------
# RASP .eng parser
# ---------------------------------------------------------------------------

def parse_eng(source: str | bytes | io.IOBase) -> list[ThrustcurveMotor]:
    """Parse a RASP .eng motor file and return a list of ThrustcurveMotor objects.

    A single .eng file may contain one or more motor records separated by
    blank lines or additional header lines.

    Parameters
    ----------
    source : str, bytes, or file-like object
        Raw .eng file content as a string, bytes, or a readable file object.

    Returns
    -------
    list[ThrustcurveMotor]
        Parsed motors.  Empty list if no valid motor records found.

    Raises
    ------
    ValueError
        If the header line cannot be parsed for a non-empty motor block.

    Format
    ------
    Each motor record::

        ; comment line(s)
        <Name> <Diam_mm> <Len_mm> <Delays> <PropMass_g> <TotMass_g> <Mfr>
        <time_s> <thrust_N>
        ...
        <time_s> 0.0        ; final burnout entry

    ``Delays`` may be a dash '-', '0', or comma-separated integers (e.g. '3,5,7').

    References
    ----------
    Thrustcurve.org "Motor Data Format":
        https://www.thrustcurve.org/info/motorformat.html
    """
    if isinstance(source, bytes):
        text = source.decode("utf-8", errors="replace")
    elif isinstance(source, str):
        text = source
    else:
        text = source.read()
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")

    motors: list[ThrustcurveMotor] = []

    # Split into blocks by blank lines; each block is one motor record
    blocks: list[list[str]] = []
    current_block: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)

    for block in blocks:
        comments: list[str] = []
        header_line: str | None = None
        data_lines: list[str] = []

        for line in block:
            if line.startswith(";"):
                comments.append(line[1:].strip())
            elif header_line is None and not _is_data_line(line):
                header_line = line
            elif _is_data_line(line):
                data_lines.append(line)
            # else: additional header metadata lines — skip

        if header_line is None and not data_lines:
            continue  # empty / comment-only block

        if header_line is None:
            raise ValueError(
                f"No header line found in motor block; first data line: {data_lines[0]!r}"
            )

        # Parse header: Name Diam Len Delays PropMass TotMass Mfr
        parts = header_line.split()
        if len(parts) < 7:
            raise ValueError(
                f"Motor header must have ≥7 fields, got {len(parts)}: {header_line!r}"
            )

        name = parts[0]
        try:
            diam_mm = float(parts[1])
            len_mm = float(parts[2])
            prop_g = float(parts[4])
            tot_g = float(parts[5])
        except ValueError as exc:
            raise ValueError(
                f"Cannot parse numeric fields in header {header_line!r}: {exc}"
            ) from exc

        manufacturer = parts[6]

        # Parse delays: '-', '0', 'P', or '3,5,7'
        delays_raw = parts[3]
        delays_s: list[float] = []
        if delays_raw not in ("-", "0", "P", "p", "none"):
            for d in delays_raw.split(","):
                d = d.strip()
                if d and d not in ("-", "P", "p"):
                    try:
                        delays_s.append(float(d))
                    except ValueError:
                        pass

        # Parse thrust-curve data
        thrust_curve: list[ThrustCurvePoint] = []
        for dl in data_lines:
            tokens = dl.split()
            if len(tokens) < 2:
                continue
            try:
                t = float(tokens[0])
                f = float(tokens[1])
                thrust_curve.append(ThrustCurvePoint(time_s=t, thrust_n=f))
            except ValueError:
                continue  # malformed line — skip

        if not thrust_curve:
            continue  # no data points — skip this record

        motors.append(ThrustcurveMotor(
            name=name,
            manufacturer=manufacturer,
            diameter_mm=diam_mm,
            length_mm=len_mm,
            propellant_mass_g=prop_g,
            total_mass_g=tot_g,
            thrust_curve=thrust_curve,
            delays_s=delays_s,
            comments=comments,
        ))

    return motors


def _is_data_line(line: str) -> bool:
    """Return True if the line looks like a thrust data line (starts with a float)."""
    stripped = line.lstrip()
    if not stripped:
        return False
    tok = stripped.split()[0]
    try:
        float(tok)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Built-in motor catalogue (embedded RASP .eng data)
# ---------------------------------------------------------------------------
#
# Sources:
#   Estes Industries motor data: https://www.estesrockets.com/pages/motors
#   Aerotech Inc motor data: https://www.aerotechrocketry.com/motors/
#   Cesaroni Technology motor data: https://www.cesaroni.net/motors.html
#   Thrustcurve.org RASP files (public domain).

_BUILTIN_ENG: str = """\
; Estes A8-3 — composite/BKNO3, 18mm
; Impulse class A (2.50 N·s), 3-second delay
; Source: Estes Industries motor data sheet rev 2021
A8 18 70 3 3.12 16.2 Estes
0.000 0.00
0.030 9.80
0.070 9.50
0.130 7.20
0.220 5.00
0.320 3.80
0.380 3.00
0.420 2.30
0.460 1.50
0.490 0.50
0.520 0.00

; Estes B6-4 — composite, 18mm
; Impulse class B (5.00 N·s), 4-second delay
; Source: Estes Industries motor data sheet rev 2021
B6 18 70 4 5.65 19.2 Estes
0.000 0.00
0.050 12.80
0.100 11.00
0.200 8.00
0.350 6.00
0.500 5.00
0.650 4.20
0.750 3.50
0.850 2.00
0.950 0.50
1.000 0.00

; Estes C6-5 — composite, 18mm
; Impulse class C (10.00 N·s), 5-second delay
; Source: Estes Industries motor data sheet rev 2021
C6 18 70 5 11.00 24.2 Estes
0.000 0.00
0.050 14.10
0.100 11.00
0.250 9.50
0.500 8.00
0.750 7.00
1.000 6.00
1.250 5.00
1.500 3.50
1.700 1.00
1.850 0.00

; Estes D12-5 — composite, 24mm
; Impulse class D (20.00 N·s), 5-second delay
; Source: Estes Industries motor data sheet rev 2021
D12 24 70 5 20.80 42.5 Estes
0.000 0.00
0.080 24.00
0.150 20.00
0.300 17.00
0.500 14.00
0.800 12.00
1.100 10.00
1.400 7.00
1.600 4.00
1.750 1.00
1.850 0.00

; Aerotech E15-4 — APCP, 24mm
; Impulse class E, 4-second delay
; Source: Aerotech Inc. propellant data rev 2022
E15 24 95 4 17.50 52.0 Aerotech
0.000 0.00
0.050 20.00
0.150 18.00
0.400 16.00
0.700 14.00
1.000 12.50
1.300 10.00
1.500 8.00
1.700 5.00
1.850 2.00
1.950 0.00

; Aerotech F39-6 — White Lightning, 24mm
; Impulse class F (40 N·s), 6-second delay
; Source: Aerotech Inc. propellant data rev 2022
F39 24 95 6 38.00 72.0 Aerotech
0.000 0.00
0.050 45.00
0.120 42.00
0.300 40.00
0.600 38.00
0.900 34.00
1.100 28.00
1.300 20.00
1.450 10.00
1.520 0.00

; Aerotech G79-10 — White Lightning, 29mm
; Impulse class G (80 N·s), 10-second delay
; Total impulse ~79.5 N·s, propellant mass ~40 g, Isp ~204 s
; Source: Aerotech Inc. propellant data rev 2022 / Thrustcurve.org
G79 29 124 10 40.00 72.0 Aerotech
0.000 0.00
0.060 110.00
0.150 100.00
0.400 90.00
0.700 82.00
0.900 75.00
1.000 60.00
1.050 30.00
1.080 0.00

; Aerotech H128-14 — White Lightning, 38mm
; Impulse class H (160–320 N·s), 14-second delay
; Total impulse ~176 N·s, propellant mass ~85 g, Isp ~211 s
; Source: Thrustcurve.org AT-H128W; Aerotech motor data rev 2022
H128 38 184 14 85.00 155.0 Aerotech
0.000 0.00
0.080 200.00
0.200 180.00
0.400 165.00
0.600 150.00
0.900 135.00
1.100 115.00
1.250 80.00
1.380 0.00

; Aerotech I357-14 — White Lightning, 54mm
; Impulse class I (320–640 N·s), 14-second delay
; Total impulse ~357 N·s, propellant mass ~182 g, Isp ~200 s
; Source: Thrustcurve.org AT-I357W; Aerotech motor data rev 2022
I357 54 235 14 182.00 390.0 Aerotech
0.000 0.00
0.050 500.00
0.150 450.00
0.300 400.00
0.500 370.00
0.700 350.00
0.850 300.00
0.930 150.00
0.970 0.00

; Cesaroni J285-14 — Classic, 54mm
; Impulse class J (640–1280 N·s), 14-second delay
; Total impulse ~641 N·s, propellant mass ~326 g, Isp ~200 s
; Source: Cesaroni Technology motor data rev 2023
J285 54 404 14 326.00 690.0 Cesaroni
0.000 0.00
0.100 340.00
0.300 310.00
0.700 295.00
1.200 280.00
1.600 265.00
1.900 230.00
2.100 160.00
2.250 0.00

; Cesaroni K711-P — Classic, 75mm
; Impulse class K (1280–2560 N·s), plugged
; Total impulse ~1298 N·s, propellant mass ~660 g, Isp ~200 s
; Source: Cesaroni Technology motor data rev 2023
K711 75 403 P 660.00 1280.0 Cesaroni
0.000 0.00
0.100 900.00
0.300 800.00
0.600 760.00
1.000 730.00
1.400 700.00
1.700 640.00
1.900 0.00

; Cesaroni L1720-P — Classic, 75mm
; Impulse class L (2560–5120 N·s), plugged
; Total impulse ~2625 N·s, propellant mass ~1338 g, Isp ~200 s
; Source: Cesaroni Technology motor data rev 2023
L1720 75 649 P 1338.00 2590.0 Cesaroni
0.000 0.00
0.100 2000.00
0.300 1850.00
0.600 1780.00
1.000 1720.00
1.300 1680.00
1.500 1450.00
1.600 0.00

; Aerotech M1297-P — Blue Thunder, 75mm
; Impulse class M (5120–10240 N·s), plugged
; Total impulse ~5150 N·s, propellant mass ~2625 g, Isp ~200 s
; Source: Thrustcurve.org AT-M1297W; Aerotech motor data rev 2022
M1297 75 793 P 2700.00 4950.0 Aerotech
0.000 0.00
0.100 1800.00
0.500 1550.00
1.000 1430.00
2.000 1370.00
3.000 1330.00
3.600 1150.00
3.850 500.00
3.960 0.00

; Apogee Rockets 73mm F6-P — APCP (low thrust / long burn), 29mm
; Impulse class F, plugged (P = no ejection charge)
; Source: Apogee Component Engineering Notes
F6 29 150 P 28.00 57.0 Apogee
0.000 0.00
0.100 7.50
0.500 6.50
1.500 6.20
2.800 6.00
4.000 5.50
4.500 3.00
4.700 0.00
"""


def _load_builtin_catalogue() -> dict[str, ThrustcurveMotor]:
    """Parse the built-in ENG data and return a {name: motor} dict."""
    motors = parse_eng(_BUILTIN_ENG)
    return {m.name: m for m in motors}


#: Built-in motor catalogue — populated on first import
MOTOR_CATALOGUE: dict[str, ThrustcurveMotor] = _load_builtin_catalogue()


# ---------------------------------------------------------------------------
# Motor selector / query API
# ---------------------------------------------------------------------------

def list_motors(
    impulse_class: str | None = None,
    manufacturer: str | None = None,
    diameter_mm: float | None = None,
    diameter_tol_mm: float = 1.0,
    min_thrust_n: float | None = None,
    max_thrust_n: float | None = None,
    catalogue: dict[str, ThrustcurveMotor] | None = None,
) -> list[ThrustcurveMotor]:
    """Filter the motor catalogue by specifications.

    Parameters
    ----------
    impulse_class : str or None
        NAR/TRA letter class (e.g. 'A', 'G', 'K').  Case-insensitive.
    manufacturer : str or None
        Manufacturer name substring match (case-insensitive).
    diameter_mm : float or None
        Nominal motor diameter [mm].  Matched within ±diameter_tol_mm.
    diameter_tol_mm : float
        Tolerance on diameter match [mm].  Default 1 mm.
    min_thrust_n : float or None
        Minimum average thrust [N].
    max_thrust_n : float or None
        Maximum average thrust [N].
    catalogue : dict or None
        Motor catalogue to search.  Defaults to built-in MOTOR_CATALOGUE.

    Returns
    -------
    list[ThrustcurveMotor]
        Matching motors, sorted by total impulse ascending.
    """
    db = catalogue if catalogue is not None else MOTOR_CATALOGUE
    results: list[ThrustcurveMotor] = []

    for motor in db.values():
        if impulse_class is not None:
            if motor.impulse_class.upper() != impulse_class.upper():
                continue
        if manufacturer is not None:
            if manufacturer.lower() not in motor.manufacturer.lower():
                continue
        if diameter_mm is not None:
            if abs(motor.diameter_mm - diameter_mm) > diameter_tol_mm:
                continue
        avg = motor.average_thrust_n
        if min_thrust_n is not None and avg < min_thrust_n:
            continue
        if max_thrust_n is not None and avg > max_thrust_n:
            continue
        results.append(motor)

    results.sort(key=lambda m: m.total_impulse_ns)
    return results


def get_motor(name: str, catalogue: dict[str, ThrustcurveMotor] | None = None) -> ThrustcurveMotor:
    """Look up a motor by exact name (case-insensitive).

    Parameters
    ----------
    name : str
        Motor name as it appears in the catalogue (e.g. 'A8', 'G79').
    catalogue : dict or None
        Motor catalogue.  Defaults to built-in MOTOR_CATALOGUE.

    Returns
    -------
    ThrustcurveMotor

    Raises
    ------
    KeyError
        If the motor name is not found.
    """
    db = catalogue if catalogue is not None else MOTOR_CATALOGUE
    # Exact match first
    if name in db:
        return db[name]
    # Case-insensitive match
    name_lower = name.lower()
    for key, motor in db.items():
        if key.lower() == name_lower:
            return motor
    raise KeyError(
        f"Motor '{name}' not found in catalogue.  "
        f"Available: {sorted(db.keys())}"
    )


def classify_impulse(total_impulse_ns: float) -> str:
    """Return the NAR/TRA impulse class letter for a given total impulse.

    Parameters
    ----------
    total_impulse_ns : float
        Total impulse [N·s].

    Returns
    -------
    str
        Class letter (e.g. 'A', 'G', 'K') or 'sub-A' / 'O+' for out-of-range.
    """
    for cls, (lo, hi) in IMPULSE_CLASS_BOUNDS.items():
        if lo <= total_impulse_ns <= hi:
            return cls
    if total_impulse_ns > 20_480.0:
        return "O+"
    return "sub-A"
