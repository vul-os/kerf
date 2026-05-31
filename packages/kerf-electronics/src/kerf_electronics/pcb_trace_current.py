"""
PCB trace maximum current via IPC-2221 simplified formula.

This module computes the maximum allowable current through a PCB copper trace
given the trace geometry and allowed temperature rise, using the IPC-2221B
empirical power-law (sometimes referred to as the "IPC-2221 simplified
formula" and reproduced in IPC-2152 Annex).

Formula
-------
  I [A] = k · ΔT^0.44 · A^0.725

where:
  A         = cross-sectional area of the trace [mil²]
              = trace_width_mils × copper_thickness_mils
  ΔT        = allowed temperature rise above ambient [°C]
  k         = empirical constant:
                external (outer-layer) copper: k = 0.048
                internal (inner-layer) copper: k = 0.024
              Internal is exactly half of external capacity; this matches the
              IPC-2221B derating factor for buried traces.

Copper thickness mapping (oz/ft² → mils):
  0.5 oz ≈  0.685 mils  (0.5 × 1.37)
  1.0 oz ≈  1.370 mils
  2.0 oz ≈  2.740 mils
  3.0 oz ≈  4.110 mils
  (1 oz/ft² = 34.8 µm = 1.37 mils nominal; see IPC-4562 Table 4-1.)

References
----------
IPC-2221B (2012) "Generic Standard on Printed Board Design", Section 6.2,
Equation 6-4: empirical chart equations for external and internal conductors.

IPC-2152 (2009) "Standard for Determining Current Carrying Capacity in Printed
Board Design": supersedes IPC-2221 charts with a more rigorous test dataset.
The correction factors from IPC-2152 §6.2 (copper-weight correction, board-
thickness/thermal-conductivity correction, plane-proximity correction) are
described in comments but are NOT applied here — this module implements the
IPC-2221B simplified formula only.  See
kerf_electronics.tracecurrent.ampacity.ipc2152_trace_current for the full
IPC-2152 corrected model.

HONEST CAVEATS (always reported)
---------------------------------
1. IPC-2221 simplified formula only.  IPC-2152 (2009) provides more detailed
   thermal curves based on a larger test dataset; it includes copper-weight
   correction factors (cf_cw), board thermal-conductivity correction (cf_th),
   and copper-plane proximity correction (cf_pl) that are NOT modelled here.
   Use tracecurrent.ipc2152_trace_current for the full IPC-2152 model.
2. Temperature coefficient: the IPC-2221 formula uses a fixed ΔT over
   ambient; it does not account for the fact that copper resistivity increases
   with temperature (α_Cu ≈ 3.93e-3 /°C), which would reduce capacity at
   high temperatures.
3. Ambient temperature: the formula result depends only on ΔT (rise above
   ambient), not on the absolute ambient.  At high ambient (e.g. 70 °C) a
   10 °C rise lands at 80 °C trace temperature; the formula does not flag
   this as a concern.  Apply engineering judgment.
4. Trace length / heat spreading: the formula assumes worst-case steady-state
   (no heat spreading to adjacent copper, no vias or pads acting as heat
   sinks).  Shorter traces or traces near large copper pours may safely carry
   more current.
5. Multi-layer proximity: adjacent copper planes increase heat spreading
   (IPC-2152 cf_pl factor); this is not modelled here, so results are
   conservative when a ground plane is present.
6. Copper weight input: values outside the 0.5–3 oz range are accepted but
   are increasingly speculative (IPC-2152 test data covers 0.5–3 oz).

Author: imranparuk
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Physical constants / conversion factors
# ---------------------------------------------------------------------------

# IPC-2221B Eq. 6-4 empirical coefficients
_K_EXTERNAL: float = 0.048
_K_INTERNAL: float = 0.024
_IPC_B: float = 0.44      # temperature-rise exponent
_IPC_C: float = 0.725     # area exponent

# Copper weight → thickness conversion
# 1 oz/ft² ≈ 34.8 µm (IPC-4562 Table 4-1 nominal)
# 34.8 µm / 25.4 µm/mil = 1.3701 mils/oz
_OZ_TO_MILS: float = 1.37   # mils per oz/ft² (nominal; spec states 1.37)

_VALID_LOCATIONS = frozenset({"external", "internal"})


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PcbTraceSpec:
    """PCB trace geometry and thermal specification.

    Attributes:
        trace_width_mils: Trace width [mils].  1 mil = 0.0254 mm.
            Typical values: 10 mil (signal), 20–50 mil (power), 100+ mil
            (high-current busbar).
        copper_weight_oz: Copper weight [oz/ft²].  Common values: 0.5, 1, 2, 3.
            IPC-4562 standard weights; 1 oz ≈ 34.8 µm ≈ 1.37 mils.
        temp_rise_C: Allowable temperature rise above ambient [°C].
            Default 10 °C (IPC-2221B conservative guideline).
            Typical values: 10 °C (conservative), 20 °C (moderate),
            30 °C (aggressive).
        location: Layer location — 'external' (outer layer) or 'internal'
            (buried / inner layer).  Internal traces have approximately half
            the current capacity of external traces (reduced heat dissipation
            due to surrounding FR-4 dielectric).
    """
    trace_width_mils: float
    copper_weight_oz: float
    temp_rise_C: float = 10.0
    location: str = "external"


@dataclass
class PcbTraceCurrentReport:
    """Result of the IPC-2221 PCB trace maximum current calculation.

    Attributes:
        max_current_A: Maximum allowable DC current [A].
        cross_section_mils2: Trace cross-sectional area [mil²] =
            trace_width_mils × copper_thickness_mils.
        formula_used: Human-readable description of the formula applied.
        derate_factor: Multiplicative factor applied relative to the
            external-copper base.  1.0 for external, 0.5 for internal.
        honest_caveat: Engineering notes and model limitations.
    """
    max_current_A: float
    cross_section_mils2: float
    formula_used: str
    derate_factor: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_pcb_trace_max_current(spec: PcbTraceSpec) -> PcbTraceCurrentReport:
    """Compute maximum allowable DC current through a PCB trace (IPC-2221).

    Applies the IPC-2221B Equation 6-4 empirical formula:
      I [A] = k · ΔT^0.44 · A^0.725

    where A is the copper cross-sectional area in mil², ΔT is the allowed
    temperature rise in °C, and k depends on the layer location.

    Args:
        spec: PcbTraceSpec — trace width, copper weight, temperature rise,
            and layer location.

    Returns:
        PcbTraceCurrentReport with max_current_A, cross_section_mils2,
        formula_used, derate_factor, and honest_caveat.

    Raises:
        ValueError: If any input parameter is invalid.
    """
    # ---- input validation ----
    if spec.trace_width_mils is None:
        raise ValueError("trace_width_mils is required")
    if spec.copper_weight_oz is None:
        raise ValueError("copper_weight_oz is required")

    w = float(spec.trace_width_mils)
    oz = float(spec.copper_weight_oz)
    dt = float(spec.temp_rise_C)
    loc = str(spec.location).lower()

    if w <= 0:
        raise ValueError(f"trace_width_mils must be > 0, got {w}")
    if oz <= 0:
        raise ValueError(f"copper_weight_oz must be > 0, got {oz}")
    if dt <= 0:
        raise ValueError(f"temp_rise_C must be > 0, got {dt}")
    if loc not in _VALID_LOCATIONS:
        raise ValueError(
            f"location must be 'external' or 'internal', got {spec.location!r}"
        )

    # ---- geometry ----
    copper_thickness_mils = oz * _OZ_TO_MILS
    cross_section_mils2 = w * copper_thickness_mils

    # ---- IPC-2221B formula ----
    if loc == "external":
        k = _K_EXTERNAL
        derate = 1.0
    else:  # internal
        k = _K_INTERNAL
        derate = 0.5   # internal = 0.5 × external (IPC-2221B §6.2)

    max_current_A = k * (dt ** _IPC_B) * (cross_section_mils2 ** _IPC_C)

    # ---- formula description ----
    formula_str = (
        f"IPC-2221B Eq. 6-4: I = {k} × {dt:.1f}^{_IPC_B} × {cross_section_mils2:.2f}^{_IPC_C} "
        f"= {max_current_A:.4f} A  "
        f"(k={k}, layer={loc}, A={cross_section_mils2:.2f} mil², "
        f"width={w} mil, t={copper_thickness_mils:.3f} mil [{oz} oz])"
    )

    # ---- honest caveat ----
    caveat = (
        "IPC-2221B simplified formula only (k_ext=0.048, k_int=0.024, "
        "ΔT^0.44 × A^0.725). "
        "IPC-2152 (2009) provides a more rigorous model with copper-weight "
        "correction (cf_cw), board thermal-conductivity correction (cf_th), "
        "and plane-proximity correction (cf_pl) that are NOT modelled here — "
        "use tracecurrent.ipc2152_trace_current for the full IPC-2152 model. "
        "The formula assumes worst-case steady-state with no heat spreading "
        "from adjacent copper, vias, or pads. "
        "Copper resistivity increase with temperature (α_Cu ≈ 0.393%/°C) "
        "is not accounted for; results are optimistic at high temperatures. "
        "IPC-2152 test data covers 0.5–3 oz copper; extrapolation beyond "
        "3 oz is speculative."
    )

    return PcbTraceCurrentReport(
        max_current_A=round(max_current_A, 6),
        cross_section_mils2=round(cross_section_mils2, 4),
        formula_used=formula_str,
        derate_factor=derate,
        honest_caveat=caveat,
    )
