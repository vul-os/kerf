"""
kerf_cad_core.aerospace.motor_database — Rocket motor database and RASP .eng parser.

Provides:
  RocketMotor        — dataclass describing a solid rocket motor
  parse_rasp_eng_file — parse the RASP (Rocket Analysis Simulation Program) .eng format
  estes_motor_catalog — built-in catalog of common Estes motors
  aerotech_motor_catalog — built-in catalog of common AeroTech motors
  compute_burnout_velocity — 1-D trajectory integration to burnout

File format reference
---------------------
The RASP .eng format is the standard exchange format for rocket motor thrust curves.
It was defined by Sebastien Cyr for the RASP simulation program and is widely
adopted by OpenRocket, RASAero, and the NAR/TRA motor certification database at
Thrustcurve.org.

Format structure::

    ; Optional comment lines starting with ;
    ; Header line:
    ;   <designation> <diameter_mm> <length_mm> <delays> <propellant_mass_g> <total_mass_g> <manufacturer>
    <name> <diam_mm> <len_mm> <delay_list> <prop_mass_g> <total_mass_g> <manufacturer>
    ; Thrust curve: time [s]  thrust [N] pairs, one per line
    <t1> <F1>
    <t2> <F2>
    ...
    ;  (semicolon terminates the motor data block)

References
----------
* Sebastien Cyr — RASP .eng file format specification (public domain, widely
  mirrored; see thrustcurve.org/info/raspformat.html).
* NAR Tested Motors database (http://www.nar.org/SandT/NARmotorloads.shtml).
* Thrustcurve.org motor database (https://www.thrustcurve.org/).

HONEST
------
The built-in motor catalogs contain representative values from manufacturer
datasheets and the Thrustcurve.org database as of 2024. Values are periodically
revised by manufacturers and certifying organisations (NAR/TRA/CAR); always check
the current certified motor data at thrustcurve.org before flight decisions.

Impulse classes (NAR classification):
  1/4A ≤ 0.625 N·s  <  1/2A ≤ 1.25 N·s  <  A ≤ 2.5 N·s  <  B ≤ 5.0 N·s
  < C ≤ 10 N·s  < D ≤ 20 N·s  < E ≤ 40 N·s  < F ≤ 80 N·s
  < G ≤ 160 N·s  < H ≤ 320 N·s  < I ≤ 640 N·s  ...

The trajectory integrator uses a simplified 1-D model:
  m(t) a(t) = F_thrust(t) - 0.5 ρ CD A v² - m(t) g
where ρ = 1.225 kg/m³ (sea-level ISA), g = 9.81 m/s².

All routines are pure Python + numpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class RocketMotor:
    """Complete description of a solid rocket motor.

    Attributes
    ----------
    designation : str
        Motor designation in NFPA 1125 / NAR format, e.g. 'F15-4', 'D12-7', 'I140W'.
        Format: <impulse_class><avg_thrust>-<delay_s>.
    manufacturer : str
        Motor manufacturer name.
    impulse_class : str
        NAR/TRA impulse classification letter ('A'–'O' etc.) or '1/2A', '1/4A'.
    total_impulse_n_s : float
        Total impulse [N·s] = integral of thrust curve.
    average_thrust_n : float
        Average thrust [N] = total_impulse / burn_time.
    max_thrust_n : float
        Peak thrust [N].
    burn_time_s : float
        Time from first thrust to burnout [s].
    propellant_mass_g : float
        Propellant (fuel + oxidiser) mass [g].
    total_mass_g : float
        Total loaded motor mass [g].
    diameter_mm : float
        Motor outer diameter [mm] (standard: 13, 18, 24, 29, 38, 54, 75, 98 mm).
    length_mm : float
        Motor casing length [mm].
    thrust_curve : np.ndarray
        Shape (N, 2): columns are [time [s], thrust [N]]. First row: t=0 thrust.
        Last row: thrust should reach 0 at burnout.
    delay_options : list[float]
        Available ejection charge delay options [s]. 0 = plugged.
    """
    designation: str
    manufacturer: str
    impulse_class: str
    total_impulse_n_s: float
    average_thrust_n: float
    max_thrust_n: float
    burn_time_s: float
    propellant_mass_g: float
    total_mass_g: float
    diameter_mm: float
    length_mm: float
    thrust_curve: np.ndarray
    delay_options: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# RASP .eng parser
# ---------------------------------------------------------------------------

def parse_rasp_eng_file(content: str) -> list[RocketMotor]:
    """Parse a RASP .eng file and return a list of RocketMotor objects.

    Parameters
    ----------
    content : str
        Full text content of a .eng file (may contain multiple motor records).

    Returns
    -------
    list[RocketMotor]
        One RocketMotor per motor record found in the file.

    Format
    ------
    Header line (first non-comment line):
        <designation> <diam_mm> <len_mm> <delays> <prop_mass_g> <total_mass_g> <manufacturer>

    Thrust curve lines (after header, before ';' terminator):
        <t_s> <F_N>

    A ';' on its own line terminates the current motor block.
    Comment lines start with ';' but are not block terminators when they follow
    a header line (they are treated as comments in the thrust data).

    HONEST: This parser handles the standard RASP format. Some manufacturer
    extensions (e.g. leading whitespace, embedded semicolons in designations)
    may not parse correctly.

    Reference: Sebastien Cyr — RASP .eng format specification.
    """
    motors: list[RocketMotor] = []

    # Split into lines and process state machine
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        # Skip blank lines and comment lines
        if not line or line.startswith(";"):
            continue

        # This should be a header line
        header_parts = line.split()
        if len(header_parts) < 7:
            # Malformed header — skip
            continue

        designation = header_parts[0]
        try:
            diam_mm = float(header_parts[1])
            len_mm = float(header_parts[2])
            delays_str = header_parts[3]
            prop_mass_g = float(header_parts[4])
            total_mass_g = float(header_parts[5])
        except (ValueError, IndexError):
            continue
        manufacturer = " ".join(header_parts[6:])

        # Parse delay options
        delay_options: list[float] = []
        for tok in delays_str.split("-"):
            tok = tok.strip()
            if tok == "0" or tok == "P":
                delay_options.append(0.0)
            else:
                try:
                    delay_options.append(float(tok))
                except ValueError:
                    pass

        # Read thrust curve data until ';' terminator
        thrust_points: list[tuple[float, float]] = []
        while i < len(lines):
            tline = lines[i].strip()
            i += 1
            if not tline:
                continue
            if tline == ";":
                break
            if tline.startswith(";"):
                # Comment line inside data block — skip
                continue
            parts = tline.split()
            if len(parts) < 2:
                continue
            try:
                t = float(parts[0])
                f = float(parts[1])
                thrust_points.append((t, f))
            except ValueError:
                continue

        if not thrust_points:
            continue

        # Build thrust curve array
        thrust_curve = np.array(thrust_points, dtype=float)

        # Compute derived quantities
        burn_time_s = float(thrust_curve[-1, 0]) if len(thrust_curve) > 0 else 0.0
        max_thrust_n = float(np.max(thrust_curve[:, 1]))

        # Integrate thrust curve using trapezoidal rule
        if len(thrust_curve) >= 2:
            total_impulse = float(np.trapz(thrust_curve[:, 1], thrust_curve[:, 0]))
        else:
            total_impulse = max_thrust_n * burn_time_s

        avg_thrust = total_impulse / burn_time_s if burn_time_s > 0 else 0.0

        # Infer impulse class from designation (first letter after any digits)
        impulse_class = _infer_impulse_class(designation)

        motors.append(RocketMotor(
            designation=designation,
            manufacturer=manufacturer,
            impulse_class=impulse_class,
            total_impulse_n_s=total_impulse,
            average_thrust_n=avg_thrust,
            max_thrust_n=max_thrust_n,
            burn_time_s=burn_time_s,
            propellant_mass_g=prop_mass_g,
            total_mass_g=total_mass_g,
            diameter_mm=diam_mm,
            length_mm=len_mm,
            thrust_curve=thrust_curve,
            delay_options=delay_options,
        ))

    return motors


def _infer_impulse_class(designation: str) -> str:
    """Extract NAR impulse class letter from motor designation string.

    Examples: 'F15-4' → 'F', 'D12-7' → 'D', '1/2A3-4' → '1/2A', 'Aerotech_G79' → 'G'.
    """
    if not designation:
        return "?"
    # Handle fractional classes first
    for frac in ("1/4A", "1/2A"):
        if designation.upper().startswith(frac):
            return frac
    # Scan for first alphabetic character
    for ch in designation:
        if ch.isalpha():
            return ch.upper()
    return "?"


# ---------------------------------------------------------------------------
# Built-in motor catalogs
# ---------------------------------------------------------------------------

def _make_motor(
    designation: str,
    manufacturer: str,
    impulse_class: str,
    total_impulse_n_s: float,
    average_thrust_n: float,
    max_thrust_n: float,
    burn_time_s: float,
    propellant_mass_g: float,
    total_mass_g: float,
    diameter_mm: float,
    length_mm: float,
    thrust_profile: list[tuple[float, float]],
    delay_options: list[float],
) -> RocketMotor:
    """Helper to construct a RocketMotor from raw catalog data."""
    tc = np.array(thrust_profile, dtype=float)
    return RocketMotor(
        designation=designation,
        manufacturer=manufacturer,
        impulse_class=impulse_class,
        total_impulse_n_s=total_impulse_n_s,
        average_thrust_n=average_thrust_n,
        max_thrust_n=max_thrust_n,
        burn_time_s=burn_time_s,
        propellant_mass_g=propellant_mass_g,
        total_mass_g=total_mass_g,
        diameter_mm=diameter_mm,
        length_mm=length_mm,
        thrust_curve=tc,
        delay_options=delay_options,
    )


def estes_motor_catalog() -> list[RocketMotor]:
    """Return a list of common Estes consumer rocket motors.

    Covers: 1/2A, A, B, C, D, E, F impulse classes.

    HONEST: Values are sourced from Estes Products performance data sheets and
    Thrustcurve.org as of 2024. Exact thrust curves are simplified approximations
    of the published certified curves; use thrustcurve.org for flight-critical data.

    Reference: Estes Industries motor performance specifications;
               NAR Tested Motors database.
    """
    return [
        _make_motor(
            designation="1/2A3-4",
            manufacturer="Estes",
            impulse_class="1/2A",
            total_impulse_n_s=1.09,
            average_thrust_n=3.0,
            max_thrust_n=8.5,
            burn_time_s=0.35,
            propellant_mass_g=1.3,
            total_mass_g=8.8,
            diameter_mm=13.0,
            length_mm=45.0,
            thrust_profile=[
                (0.0, 0.0), (0.02, 8.5), (0.1, 5.5), (0.2, 3.5), (0.3, 2.0),
                (0.35, 0.5), (0.36, 0.0),
            ],
            delay_options=[4.0],
        ),
        _make_motor(
            designation="A8-3",
            manufacturer="Estes",
            impulse_class="A",
            total_impulse_n_s=2.50,
            average_thrust_n=8.0,
            max_thrust_n=19.4,
            burn_time_s=0.50,
            propellant_mass_g=3.0,
            total_mass_g=16.2,
            diameter_mm=18.0,
            length_mm=70.0,
            thrust_profile=[
                (0.0, 0.0), (0.03, 19.4), (0.15, 12.0), (0.30, 8.0),
                (0.45, 5.0), (0.50, 1.0), (0.52, 0.0),
            ],
            delay_options=[3.0],
        ),
        _make_motor(
            designation="B6-4",
            manufacturer="Estes",
            impulse_class="B",
            total_impulse_n_s=5.0,
            average_thrust_n=6.0,
            max_thrust_n=12.7,
            burn_time_s=0.85,
            propellant_mass_g=5.5,
            total_mass_g=19.4,
            diameter_mm=18.0,
            length_mm=70.0,
            thrust_profile=[
                (0.0, 0.0), (0.04, 12.7), (0.2, 9.0), (0.45, 7.0),
                (0.7, 5.0), (0.85, 2.0), (0.87, 0.0),
            ],
            delay_options=[4.0],
        ),
        _make_motor(
            designation="C6-5",
            manufacturer="Estes",
            impulse_class="C",
            total_impulse_n_s=10.0,
            average_thrust_n=9.0,
            max_thrust_n=14.1,
            burn_time_s=1.70,
            propellant_mass_g=11.0,
            total_mass_g=24.0,
            diameter_mm=18.0,
            length_mm=70.0,
            thrust_profile=[
                (0.0, 0.0), (0.04, 14.1), (0.2, 12.5), (0.6, 10.0),
                (1.0, 8.5), (1.4, 7.0), (1.70, 3.0), (1.72, 0.0),
            ],
            delay_options=[5.0],
        ),
        _make_motor(
            designation="D12-5",
            manufacturer="Estes",
            impulse_class="D",
            total_impulse_n_s=16.85,
            average_thrust_n=12.0,
            max_thrust_n=29.7,
            burn_time_s=1.70,
            propellant_mass_g=20.3,
            total_mass_g=40.0,
            diameter_mm=24.0,
            length_mm=70.0,
            thrust_profile=[
                (0.0, 0.0), (0.05, 29.7), (0.2, 22.0), (0.6, 14.0),
                (1.0, 11.0), (1.4, 9.0), (1.70, 5.0), (1.73, 0.0),
            ],
            delay_options=[3.0, 5.0, 7.0],
        ),
        _make_motor(
            designation="E16-6",
            manufacturer="Estes",
            impulse_class="E",
            total_impulse_n_s=28.45,
            average_thrust_n=16.0,
            max_thrust_n=35.0,
            burn_time_s=1.78,
            propellant_mass_g=32.0,
            total_mass_g=67.0,
            diameter_mm=24.0,
            length_mm=95.0,
            thrust_profile=[
                (0.0, 0.0), (0.04, 35.0), (0.1, 30.0), (0.4, 18.0),
                (0.8, 15.0), (1.2, 13.0), (1.6, 10.0), (1.78, 4.0), (1.80, 0.0),
            ],
            delay_options=[6.0],
        ),
        _make_motor(
            designation="F39-6",
            manufacturer="Estes",
            impulse_class="F",
            total_impulse_n_s=60.0,
            average_thrust_n=39.0,
            max_thrust_n=67.0,
            burn_time_s=1.54,
            propellant_mass_g=52.0,
            total_mass_g=120.0,
            diameter_mm=29.0,
            length_mm=114.0,
            thrust_profile=[
                (0.0, 0.0), (0.05, 67.0), (0.2, 55.0), (0.5, 42.0),
                (0.9, 36.0), (1.2, 30.0), (1.54, 10.0), (1.56, 0.0),
            ],
            delay_options=[6.0],
        ),
    ]


def aerotech_motor_catalog() -> list[RocketMotor]:
    """Return a list of common AeroTech high-power rocket motors.

    Covers: G, H, I impulse classes.

    HONEST: Values sourced from AeroTech Inc. motor specifications and
    Thrustcurve.org certified motor data as of 2024. Simplified thrust profiles.
    Always verify against current certified data before high-power flight.

    Reference: AeroTech Inc. motor specifications;
               NAR/TRA Tested Motors database; Thrustcurve.org.
    """
    return [
        _make_motor(
            designation="G79W-10",
            manufacturer="AeroTech",
            impulse_class="G",
            total_impulse_n_s=117.0,
            average_thrust_n=79.0,
            max_thrust_n=129.0,
            burn_time_s=1.48,
            propellant_mass_g=75.0,
            total_mass_g=155.0,
            diameter_mm=29.0,
            length_mm=124.0,
            thrust_profile=[
                (0.0, 0.0), (0.05, 129.0), (0.15, 110.0), (0.4, 85.0),
                (0.8, 75.0), (1.2, 65.0), (1.48, 30.0), (1.50, 0.0),
            ],
            delay_options=[4.0, 7.0, 10.0],
        ),
        _make_motor(
            designation="H128W-14",
            manufacturer="AeroTech",
            impulse_class="H",
            total_impulse_n_s=242.0,
            average_thrust_n=128.0,
            max_thrust_n=228.0,
            burn_time_s=1.89,
            propellant_mass_g=160.0,
            total_mass_g=329.0,
            diameter_mm=38.0,
            length_mm=178.0,
            thrust_profile=[
                (0.0, 0.0), (0.04, 228.0), (0.1, 200.0), (0.4, 140.0),
                (0.8, 120.0), (1.2, 110.0), (1.89, 50.0), (1.91, 0.0),
            ],
            delay_options=[6.0, 10.0, 14.0],
        ),
        _make_motor(
            designation="I161W-14",
            manufacturer="AeroTech",
            impulse_class="I",
            total_impulse_n_s=426.0,
            average_thrust_n=161.0,
            max_thrust_n=248.0,
            burn_time_s=2.65,
            propellant_mass_g=300.0,
            total_mass_g=603.0,
            diameter_mm=38.0,
            length_mm=254.0,
            thrust_profile=[
                (0.0, 0.0), (0.05, 248.0), (0.2, 210.0), (0.6, 170.0),
                (1.0, 155.0), (1.6, 140.0), (2.2, 120.0), (2.65, 50.0), (2.67, 0.0),
            ],
            delay_options=[6.0, 10.0, 14.0],
        ),
        _make_motor(
            designation="G76G-7",
            manufacturer="AeroTech",
            impulse_class="G",
            total_impulse_n_s=111.0,
            average_thrust_n=76.0,
            max_thrust_n=111.0,
            burn_time_s=1.46,
            propellant_mass_g=75.0,
            total_mass_g=150.0,
            diameter_mm=29.0,
            length_mm=124.0,
            thrust_profile=[
                (0.0, 0.0), (0.05, 111.0), (0.2, 95.0), (0.5, 80.0),
                (0.9, 70.0), (1.2, 60.0), (1.46, 25.0), (1.48, 0.0),
            ],
            delay_options=[4.0, 7.0],
        ),
    ]


# ---------------------------------------------------------------------------
# Trajectory simulation
# ---------------------------------------------------------------------------

def compute_burnout_velocity(
    motor: RocketMotor,
    rocket_dry_mass_g: float,
    drag_coefficient: float = 0.5,
    body_diameter_mm: float = 25.0,
) -> dict[str, float]:
    """Numerically integrate the 1-D rocket equation to burnout.

    Model
    -----
    The rocket equation (1-D, vertical launch):
        m(t) a = F_thrust(t) - 0.5 ρ CD A v² sign(v) - m(t) g

    where:
        m(t) = rocket_dry_mass + remaining_propellant_mass(t)
        remaining_propellant_mass(t) = prop_mass * (1 - t / burn_time)
          (linear burn rate approximation)
        ρ = 1.225 kg/m³ (ISA sea-level air density)
        g = 9.81 m/s²
        A = π (body_diameter_mm/2000)² m²

    Integration method: explicit Euler with dt = 1 ms (0.001 s).

    Parameters
    ----------
    motor : RocketMotor
        Motor descriptor.
    rocket_dry_mass_g : float
        Rocket dry mass (motor excluded) [g].
    drag_coefficient : float
        Drag coefficient CD (dimensionless). Default 0.5 (typical 3FNC rocket).
    body_diameter_mm : float
        Rocket body tube outer diameter [mm]. Default 25.0 mm.

    Returns
    -------
    dict with keys:
        burnout_velocity_m_s   : float  velocity at motor burnout [m/s]
        burnout_altitude_m     : float  altitude at motor burnout [m]
        burnout_time_s         : float  time of burnout [s]
        max_velocity_m_s       : float  peak velocity during burn [m/s]
        thrust_to_weight_avg   : float  average thrust / total_weight at liftoff
        ok                     : bool   True if simulation completed normally
        reason                 : str    empty string if ok, else error message

    HONEST: This is a 1-D point-mass model with no atmospheric profile, no fin
    aerodynamics, no gravity turn, and a linear propellant burn rate assumption.
    For flight planning use OpenRocket (open-source) or RASAero (free) which
    include 6-DOF with full atmospheric models.

    Reference: Barrowman equations; Mandell et al. "Topics in Advanced Model
    Rocketry" (1973), MIT Press.
    """
    RHO = 1.225   # kg/m³
    G = 9.81      # m/s²

    try:
        # Unit conversions
        dry_mass_kg = rocket_dry_mass_g / 1000.0
        prop_mass_kg = motor.propellant_mass_g / 1000.0
        total_motor_mass_kg = motor.total_mass_g / 1000.0
        body_radius_m = body_diameter_mm / 2000.0
        A = math.pi * body_radius_m ** 2   # reference area [m²]

        burn_time_s = motor.burn_time_s
        if burn_time_s <= 0.0:
            return {"ok": False, "reason": "motor burn_time_s <= 0"}

        # Total mass at liftoff = dry mass + loaded motor mass
        mass_liftoff = dry_mass_kg + total_motor_mass_kg

        # Average thrust-to-weight
        avg_tw = motor.average_thrust_n / (mass_liftoff * G)

        # Build thrust interpolation function
        tc = motor.thrust_curve
        t_pts = tc[:, 0]
        f_pts = tc[:, 1]

        def thrust_at(t: float) -> float:
            if t <= t_pts[0]:
                return float(f_pts[0])
            if t >= t_pts[-1]:
                return 0.0
            return float(np.interp(t, t_pts, f_pts))

        # Integration
        dt = 0.001   # 1 ms time step
        t = 0.0
        v = 0.0
        alt = 0.0
        max_v = 0.0

        while t <= burn_time_s + dt:
            # Current propellant mass (linear depletion)
            frac_remaining = max(0.0, 1.0 - t / burn_time_s)
            prop_remaining = prop_mass_kg * frac_remaining

            # Current total mass = dry rocket + motor casing + remaining prop
            motor_casing_mass = total_motor_mass_kg - prop_mass_kg
            m = dry_mass_kg + motor_casing_mass + prop_remaining

            # Forces
            F_thrust = thrust_at(t)
            F_drag = 0.5 * RHO * drag_coefficient * A * v * abs(v)
            F_grav = m * G

            a = (F_thrust - F_drag - F_grav) / m

            # Euler step
            v += a * dt
            alt += v * dt
            t += dt

            if abs(v) > max_v:
                max_v = abs(v)

        return {
            "burnout_velocity_m_s": float(v),
            "burnout_altitude_m": float(alt),
            "burnout_time_s": float(burn_time_s),
            "max_velocity_m_s": float(max_v),
            "thrust_to_weight_avg": float(avg_tw),
            "ok": True,
            "reason": "",
        }

    except Exception as exc:
        return {"ok": False, "reason": str(exc),
                "burnout_velocity_m_s": 0.0, "burnout_altitude_m": 0.0,
                "burnout_time_s": 0.0, "max_velocity_m_s": 0.0,
                "thrust_to_weight_avg": 0.0}
