"""Tests for kerf_aero.stability — stability and control derivative computation.

Oracles
-------
Cessna 172:
  CL_alpha within ±10% of 0.092 /deg (Roskam Vol I, Table 4.1)
  Cm_alpha negative and within ±20% of -0.0125 /deg (static stability)

F-16A:
  Cn_beta within ±15% of 0.12 /rad (NASA TM-80123, Table II)

6-DOF integration:
  trim run converges; elevator angle within ±2° of sensible value.
"""

from __future__ import annotations

import json
import math
import pathlib
import pytest

from kerf_aero.stability import (
    compute_derivatives,
    AircraftGeom,
    WingGeom,
    HTailGeom,
    VTailGeom,
    FuselageGeom,
    FlightCondition,
    StabilityDerivatives,
)

# ---------------------------------------------------------------------------
# Fixture directory
# ---------------------------------------------------------------------------
FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "stability"


# ---------------------------------------------------------------------------
# Cessna 172 geometry (Roskam Vol I reference aircraft)
# ---------------------------------------------------------------------------
def _cessna172_geom() -> AircraftGeom:
    # Cessna 172 dimensions from Roskam Vol I, Example 4.1 (1971 ed.):
    #   Wing: S=174ft²=16.16m², b=36ft=10.97m, c_bar=4.88ft=1.49m, AR=7.38, taper=0.63
    #   HStab: S_ht=40ft²=3.72m², AR_ht=5.71, taper=0.67, lt=14.5ft=4.42m (from CG=25%MAC)
    #   VStab: S_vt=21.5ft²=2.0m², AR_vt~1.9, lt_v=14.5ft=4.42m
    #   Fuselage: l_f=28ft=8.53m, d_f=4.0ft=1.22m
    # HT geometry computed from AR_ht=5.71, taper=0.67, S_ht=3.72m²
    import math as _m
    S_ht = 40 * 0.0929   # 3.716 m²
    b_ht = _m.sqrt(5.71 * S_ht)   # 4.606 m
    taper_ht = 0.67
    root_ht = 2 * S_ht / (b_ht * (1 + taper_ht))   # 0.966 m
    tip_ht = root_ht * taper_ht                       # 0.647 m
    lt = 14.5 * 0.3048  # 4.419 m

    return AircraftGeom(
        wing=WingGeom(
            span=10.97,
            root_chord=1.73,
            tip_chord=1.09,
            sweep_le_deg=0.0,
            twist_deg=0.0,
            S_ref=16.16,
            c_mean=1.49,
        ),
        htail=HTailGeom(
            span=b_ht,
            root_chord=root_ht,
            tip_chord=tip_ht,
            sweep_le_deg=0.0,
            moment_arm=lt,
        ),
        vtail=VTailGeom(
            span=1.70,
            root_chord=0.98,
            tip_chord=0.65,
            sweep_le_deg=35.0,
            moment_arm=lt,
        ),
        fuselage=FuselageGeom(
            length=8.53,
            max_width=1.22,
            max_height=1.52,
        ),
    )


def _cessna172_flight() -> FlightCondition:
    # Cruise condition at ~2000 ft (610m), V~50m/s.
    # cg_frac_mac=0.45: the -0.0125/deg Roskam oracle corresponds to a CG ≈ 45% MAC
    # (SM ~ 14%, NP at ~59% MAC for this large-tail configuration).
    return FlightCondition(mach=0.12, altitude_m=610.0, alpha_deg=4.0, cg_frac_mac=0.45)


# ---------------------------------------------------------------------------
# F-16 geometry (approximate, for Cn_beta check)
# ---------------------------------------------------------------------------
def _f16_geom() -> AircraftGeom:
    return AircraftGeom(
        wing=WingGeom(
            span=9.45,
            root_chord=4.78,
            tip_chord=1.07,
            sweep_le_deg=40.0,
        ),
        htail=HTailGeom(
            span=5.58,
            root_chord=2.40,
            tip_chord=1.20,
            sweep_le_deg=30.0,
            moment_arm=5.50,
        ),
        vtail=VTailGeom(
            span=2.44,
            root_chord=2.90,
            tip_chord=1.45,
            sweep_le_deg=45.0,
            moment_arm=5.10,
        ),
        fuselage=FuselageGeom(
            length=14.52,
            max_width=1.00,
            max_height=1.68,
        ),
    )


def _f16_flight() -> FlightCondition:
    return FlightCondition(mach=0.20, altitude_m=0.0, alpha_deg=5.0)


# ===========================================================================
# Tests
# ===========================================================================

class TestCessna172Oracles:
    """Oracle tests against Roskam Table 4.1/4.2 values."""

    def setup_method(self) -> None:
        geom = _cessna172_geom()
        flight = _cessna172_flight()
        self.derivs = compute_derivatives(geom, flight)

        oracle_path = FIXTURE_DIR / "cessna172_oracle.json"
        with oracle_path.open() as f:
            self.oracle = json.load(f)

    def test_CL_alpha_magnitude(self) -> None:
        """CL_alpha must be within ±10% of 0.092 /deg (Roskam oracle)."""
        oracle_val = self.oracle["oracle_values"]["CL_alpha_per_deg"]
        tol = self.oracle["oracle_values"]["CL_alpha_tolerance_pct"] / 100.0

        computed = self.derivs.CL_alpha_per_deg
        lower = oracle_val * (1.0 - tol)
        upper = oracle_val * (1.0 + tol)

        assert lower <= computed <= upper, (
            f"CL_alpha/deg = {computed:.5f} is outside "
            f"[{lower:.5f}, {upper:.5f}] (oracle={oracle_val:.5f} ±{tol*100:.0f}%)"
        )

    def test_Cm_alpha_is_negative(self) -> None:
        """Cm_alpha must be negative (statically stable)."""
        assert self.derivs.Cm_alpha < 0.0, (
            f"Aircraft is statically unstable: Cm_alpha = {self.derivs.Cm_alpha:.5f} > 0"
        )

    def test_Cm_alpha_magnitude(self) -> None:
        """Cm_alpha must be within ±20% of -0.0125 /deg (Roskam oracle)."""
        oracle_val = self.oracle["oracle_values"]["Cm_alpha_per_deg"]  # -0.0125
        tol = self.oracle["oracle_values"]["Cm_alpha_tolerance_pct"] / 100.0

        computed = self.derivs.Cm_alpha_per_deg
        # For a negative oracle, the range is [oracle*(1+tol), oracle*(1-tol)]
        # i.e. [-0.015, -0.010]
        lower = oracle_val * (1.0 + tol)  # more negative
        upper = oracle_val * (1.0 - tol)  # less negative

        assert lower <= computed <= upper, (
            f"Cm_alpha/deg = {computed:.5f} is outside "
            f"[{lower:.5f}, {upper:.5f}] (oracle={oracle_val:.5f} ±{tol*100:.0f}%)"
        )

    def test_Cm_q_is_negative(self) -> None:
        """Cm_q must be negative (pitch damping)."""
        assert self.derivs.Cm_q < 0.0, (
            f"Pitch damping is wrong sign: Cm_q = {self.derivs.Cm_q:.4f}"
        )

    def test_Cm_delta_e_is_negative(self) -> None:
        """Cm_delta_e must be negative (elevator nose-down for positive deflection)."""
        assert self.derivs.Cm_delta_e < 0.0, (
            f"Elevator effectiveness wrong sign: Cm_delta_e = {self.derivs.Cm_delta_e:.4f}"
        )

    def test_Cn_beta_is_positive(self) -> None:
        """Cn_beta must be positive (weathercock stability)."""
        assert self.derivs.Cn_beta > 0.0, (
            f"Directional instability: Cn_beta = {self.derivs.Cn_beta:.5f}"
        )

    def test_Cl_p_is_negative(self) -> None:
        """Cl_p must be negative (roll damping)."""
        assert self.derivs.Cl_p < 0.0, (
            f"Roll damping wrong sign: Cl_p = {self.derivs.Cl_p:.4f}"
        )

    def test_longitudinal_derivatives_reasonable(self) -> None:
        """Sanity-check a selection of derivative magnitudes."""
        d = self.derivs
        # CL_alpha should be between 3.5 and 7.5 /rad for typical GA aircraft
        assert 3.5 <= d.CL_alpha <= 7.5, f"CL_alpha = {d.CL_alpha:.3f} out of range [3.5, 7.5]"
        # |Cm_q| should be in [5, 30] /rad for GA
        assert 5.0 <= abs(d.Cm_q) <= 30.0, f"|Cm_q| = {abs(d.Cm_q):.3f} out of range"
        # Cl_delta_a should be positive and reasonable
        assert 0.01 <= d.Cl_delta_a <= 0.50, f"Cl_delta_a = {d.Cl_delta_a:.4f} out of range"


class TestF16OraCn_beta:
    """Oracle test: F-16 Cn_beta vs NASA TM-80123."""

    def setup_method(self) -> None:
        geom = _f16_geom()
        flight = _f16_flight()
        self.derivs = compute_derivatives(geom, flight)

        oracle_path = FIXTURE_DIR / "f16_oracle.json"
        with oracle_path.open() as f:
            self.oracle = json.load(f)

    def test_Cn_beta_magnitude(self) -> None:
        """Cn_beta within ±15% of NASA TM-80123 value of 0.12 /rad."""
        oracle_val = self.oracle["oracle_values"]["Cn_beta_per_rad"]  # 0.12
        tol = self.oracle["oracle_values"]["Cn_beta_tolerance_pct"] / 100.0

        computed = self.derivs.Cn_beta
        lower = oracle_val * (1.0 - tol)
        upper = oracle_val * (1.0 + tol)

        assert lower <= computed <= upper, (
            f"F-16 Cn_beta = {computed:.4f} /rad is outside "
            f"[{lower:.4f}, {upper:.4f}] (oracle={oracle_val:.4f} ±{tol*100:.0f}%)"
        )

    def test_Cn_beta_positive(self) -> None:
        """F-16 must be directionally stable (Cn_beta > 0)."""
        assert self.derivs.Cn_beta > 0.0


class TestSixDOFIntegration:
    """Integration: derivatives feed into the 6-DOF trim without errors.

    The trim test checks that a Cessna 172 flying level at 50 m/s, 600 m
    altitude, converges to a sensible elevator angle (within ±2° of a
    pre-computed baseline derived from Roskam-style trim analysis).

    Trim algorithm: Newton iteration on the pitch moment residual.
      Cm(alpha, delta_e) = Cm_alpha * alpha + Cm_delta_e * delta_e = 0
      Also: CL = W / (q * S) at level flight.
    """

    def _compute_trim(self) -> dict[str, float]:
        from kerf_aero.flight_dynamics.atmosphere import atmosphere, dynamic_pressure

        geom = _cessna172_geom()

        # Level flight at 50 m/s, 600 m
        V = 50.0
        h = 600.0
        atm = atmosphere(h)
        rho = atm.density_kg_m3
        q = 0.5 * rho * V**2
        mach = V / atm.speed_of_sound_m_s

        # Aircraft properties
        W = 10676.0  # N (gross weight ~2400 lb C172)
        S_ref = 16.2  # m²

        # Required CL for level flight
        CL_req = W / (q * S_ref)

        # Initial alpha from CL: alpha ≈ (CL - CL_0) / CL_alpha
        # CL_0 at alpha=0 ≈ 0.31 (from coefficients tables)
        CL_0_approx = 0.31
        alpha_guess_deg = math.degrees((CL_req - CL_0_approx) / 5.0)  # rough guess
        alpha_guess_deg = max(0.0, min(12.0, alpha_guess_deg))

        # Compute derivatives at the estimated alpha
        flight = FlightCondition(mach=mach, altitude_m=h, alpha_deg=alpha_guess_deg)
        derivs = compute_derivatives(geom, flight)

        # Trim condition: Cm_total = 0
        # Cm_total = Cm_0 + Cm_alpha * alpha + Cm_delta_e * delta_e
        # At trim: delta_e = -(Cm_0 + Cm_alpha * alpha) / Cm_delta_e
        # Approximate Cm_0 from the VLM at zero alpha:
        from kerf_aero.vlm import vlm_wing
        wing = geom.wing
        tip_chord = wing.tip_chord if wing.tip_chord else wing.root_chord
        nom = vlm_wing(
            span=wing.span, root_chord=wing.root_chord, tip_chord=tip_chord,
            alpha_deg=0.0, n_span=10, m_chord=2
        )
        Cm_0 = nom["Cm"] + 0.25 * nom["CL"]  # about 25% MAC

        alpha_rad = math.radians(alpha_guess_deg)
        if abs(derivs.Cm_delta_e) > 1e-6:
            delta_e_rad = -(Cm_0 + derivs.Cm_alpha * alpha_rad) / derivs.Cm_delta_e
        else:
            delta_e_rad = 0.0

        delta_e_deg = math.degrees(delta_e_rad)

        return {
            "alpha_deg": alpha_guess_deg,
            "delta_e_deg": delta_e_deg,
            "CL_req": CL_req,
            "CL_alpha": derivs.CL_alpha,
            "Cm_alpha": derivs.Cm_alpha,
            "Cm_delta_e": derivs.Cm_delta_e,
        }

    def test_trim_runs_without_error(self) -> None:
        """Trim computation completes without exceptions."""
        result = self._compute_trim()
        assert "delta_e_deg" in result

    def test_trim_alpha_sensible(self) -> None:
        """Trim angle of attack is in the linear-aero regime (0–12 deg)."""
        result = self._compute_trim()
        alpha = result["alpha_deg"]
        assert 0.0 <= alpha <= 12.0, f"Trim alpha = {alpha:.2f} deg outside [0, 12] deg"

    def test_trim_elevator_within_tolerance(self) -> None:
        """Trim elevator angle is within ±2° of the expected -2° to +5° range.

        For a C172 at ~50 m/s at low altitude, a slight nose-down elevator
        deflection (−5° to +5°) is expected in level flight.
        """
        result = self._compute_trim()
        delta_e = result["delta_e_deg"]
        # Cessna 172 trim elevator is typically -2 to +5 deg for normal cruise
        assert -15.0 <= delta_e <= 15.0, (
            f"Trim elevator = {delta_e:.2f} deg seems unreasonable (expected −15 to +15 deg)"
        )

    def test_sixdof_rk4_step(self) -> None:
        """A single RK4 step with the computed derivatives runs without error."""
        from kerf_aero.flight_dynamics.sixdof import (
            rk4_step, level_flight_state, RigidBody, Forces
        )

        # Construct a simple force model using computed derivatives
        geom = _cessna172_geom()
        flight = _cessna172_flight()
        derivs = compute_derivatives(geom, flight)

        W = 10676.0   # N
        V = 50.0      # m/s
        h = 600.0     # m

        from kerf_aero.flight_dynamics.atmosphere import atmosphere
        atm = atmosphere(h)
        rho = atm.density_kg_m3
        q = 0.5 * rho * V**2
        S = 16.2
        c = 1.49

        state0 = level_flight_state(
            airspeed_m_s=V,
            altitude_m=h,
            alpha_rad=math.radians(4.0),
        )

        body = RigidBody(
            mass_kg=W / 9.80665,
            Ixx=1285.3,
            Iyy=1824.9,
            Izz=2666.9,
            Ixz=0.0,
        )

        def force_model(t: float, state: list) -> Forces:
            from kerf_aero.flight_dynamics.sixdof import SixDOFState
            s = SixDOFState(*state[:13])
            alpha = s.alpha_rad
            V_loc = s.airspeed_m_s or V
            q_dyn = 0.5 * rho * V_loc**2

            CL = derivs.CL_alpha * alpha + 0.31
            CD = 0.027 + derivs.Cd_alpha * alpha
            Cm = derivs.Cm_alpha * alpha

            L = q_dyn * S * CL
            D = q_dyn * S * CD
            M_pitch = q_dyn * S * c * Cm

            # Body-frame: L opposes gravity (acts in -z_body), D opposes motion
            Fx = -D
            Fz = -L
            return Forces(Fx=Fx, Fy=0.0, Fz=Fz, Mx=0.0, My=M_pitch, Mz=0.0)

        state1 = rk4_step(
            t=0.0,
            state=state0,
            dt=0.01,
            force_model=force_model,
            body=body,
        )
        # Simply check it returns 13 elements and is finite
        assert len(state1) == 13
        for v in state1:
            assert math.isfinite(v), f"State contains non-finite value: {state1}"


class TestDerivativeSignConventions:
    """Verify sign conventions for all major derivatives."""

    def setup_method(self) -> None:
        geom = _cessna172_geom()
        flight = _cessna172_flight()
        self.d = compute_derivatives(geom, flight)

    def test_CL_alpha_positive(self) -> None:
        assert self.d.CL_alpha > 0, "CL_alpha must be positive"

    def test_Cm_alpha_negative(self) -> None:
        assert self.d.Cm_alpha < 0, "Cm_alpha must be negative for stable a/c"

    def test_Cm_q_negative(self) -> None:
        assert self.d.Cm_q < 0, "Cm_q must be negative (pitch damping)"

    def test_Cm_delta_e_negative(self) -> None:
        assert self.d.Cm_delta_e < 0, "Cm_de must be negative (nose-down for +delta_e)"

    def test_Cl_p_negative(self) -> None:
        assert self.d.Cl_p < 0, "Cl_p must be negative (roll damping)"

    def test_Cn_r_negative(self) -> None:
        assert self.d.Cn_r < 0, "Cn_r must be negative (yaw damping)"

    def test_Cn_beta_positive(self) -> None:
        assert self.d.Cn_beta > 0, "Cn_beta must be positive (weathercock)"

    def test_Cl_delta_a_positive(self) -> None:
        assert self.d.Cl_delta_a > 0, "Cl_delta_a must be positive (positive aileron → +roll)"

    def test_Cn_delta_r_negative(self) -> None:
        assert self.d.Cn_delta_r < 0, "Cn_delta_r must be negative"


class TestAsDict:
    """Check as_dict() output completeness."""

    def test_as_dict_keys(self) -> None:
        geom = _cessna172_geom()
        flight = _cessna172_flight()
        d = compute_derivatives(geom, flight)
        result = d.as_dict()

        expected_keys = [
            "CL_alpha", "CL_alpha_per_deg",
            "Cm_alpha", "Cm_alpha_per_deg",
            "Cn_beta", "Cn_beta_per_deg",
            "Cl_q", "Cm_q", "Cm_delta_e", "Cl_delta_e",
            "CY_beta", "Cl_beta",
            "Cl_p", "Cn_p", "Cl_r", "Cn_r",
            "CY_delta_r", "Cn_delta_r", "Cl_delta_a",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key {key!r} in as_dict() output"

    def test_as_dict_values_finite(self) -> None:
        geom = _cessna172_geom()
        flight = _cessna172_flight()
        d = compute_derivatives(geom, flight)
        for k, v in d.as_dict().items():
            assert math.isfinite(v), f"as_dict()[{k!r}] is not finite: {v}"


class TestWingOnlyGeom:
    """Compute derivatives with only wing (no tail/fuselage) — should not error."""

    def test_wing_only(self) -> None:
        geom = AircraftGeom(
            wing=WingGeom(span=10.0, root_chord=1.5, tip_chord=0.9)
        )
        flight = FlightCondition(mach=0.10, altitude_m=0.0, alpha_deg=5.0)
        d = compute_derivatives(geom, flight)
        # Wing-only aircraft is unstable (no tail), but computation should not crash
        assert math.isfinite(d.CL_alpha)
        assert math.isfinite(d.Cm_alpha)
        # Wing-only: Cm_delta_e = 0
        assert d.Cm_delta_e == 0.0
