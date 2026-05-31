"""
kerf_cad_core.gdt.dimension_chain — ASME Y14.5-2018 §5.3 tolerance stack-up.

Computes worst-case (WC) and statistical (RSS) tolerance stack-up for a linear
chain of nominal dimensions.  The result reports the nominal gap, worst-case
assembly gap range, and the RSS gap range, together with the dominant (largest
contributor) link and an honest caveat on assumptions.

References
----------
ASME Y14.5-2018 §5.3 — "Tolerance Accumulation" / "Tolerance Stackup".
Bralla, J. G. (ed.), *Design for Manufacturability Handbook*, 2nd ed. (McGraw-Hill
1999), §1.1 — worst-case and RSS (Statistical) tolerance stack-up methods.

Physics summary
---------------
Given N dimension links, each with nominal length d_i and bilateral tolerance
(+t⁺_i, −t⁻_i) and a sign s_i ∈ {+1, −1} (direction relative to the chain):

Nominal gap:
    G_nom = Σ s_i · d_i

Worst-case:
    The gap is minimised when all positive-direction links are at their LMC
    (smallest) and all negative-direction links are at their MMC (largest).
    WC tolerance accumulation = Σ |t_max_i|  where t_max_i = max(t⁺_i, t⁻_i).
    G_wc_min = G_nom − Σ t_max_i
    G_wc_max = G_nom + Σ t_max_i

    Per ASME Y14.5-2018 §5.3: every contributing link goes simultaneously to its
    extreme limit — physically pessimistic but guarantees 100% assemblability.

RSS (Root Sum Squares / Statistical):
    When link dimensions are independent and normally distributed, the combined
    variance equals the sum of component variances.  For a bilateral tolerance t_i
    at 3σ (99.73% of the process output):
        σ_i = t_i / 3
        σ_combined = sqrt(Σ σ_i²)
        T_RSS = 3 · σ_combined = sqrt(Σ t_i²)    ← "6σ ratio"
    G_rss_min = G_nom − T_RSS
    G_rss_max = G_nom + T_RSS

    Here t_i = max(t⁺_i, t⁻_i) (half-range of the bilateral tolerance band).

Honest caveat
-------------
RSS assumes independent, normally distributed component dimensions each centred
on nominal — a 3σ bilateral half-band.  Real manufacturing processes may be
skewed, correlated, or multimodal; process capability (Cpk < 1) shrinks the
effective tolerance.  RSS is unconservative in such cases.  For high-confidence
predictions use Monte Carlo simulation with measured process distributions.
Worst-case is always 100% conservative.

Dominant link is defined as the link with the largest half-tolerance max(t⁺, t⁻).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

_CODE_SECTION = "ASME Y14.5-2018 §5.3 + Bralla 'Design for Manufacturability Handbook' §1"

_HONEST_CAVEAT = (
    "RSS method assumes independent, normally distributed component dimensions "
    "centred on nominal at 3σ bilateral half-bands; process Cpk=1.0 assumed for "
    "all links.  Correlation between links (e.g. same fixture datum) and "
    "non-normal distributions are not modelled — RSS is unconservative in those "
    "cases.  Worst-case (WC) is always 100% conservative and guarantees "
    "assemblability regardless of distribution.  For higher fidelity use "
    "Monte Carlo simulation with measured process distributions per "
    "Bralla §1 and ASME Y14.5-2018 §5.3 commentary."
)

_VALID_DIRECTIONS = frozenset({"positive", "negative"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DimensionLink:
    """
    One link in a linear dimension chain.

    Attributes
    ----------
    link_id:
        Unique identifier for the link (e.g. "shaft_length", "housing_bore").
    nominal_mm:
        Nominal dimension in mm (> 0).
    tol_plus_mm:
        Upper bilateral tolerance half-band (mm, ≥ 0).  The link's actual size
        is in the range [nominal − tol_minus_mm, nominal + tol_plus_mm].
    tol_minus_mm:
        Lower bilateral tolerance half-band (mm, ≥ 0).  Use positive value;
        the sign is implied by the "minus" name.
    direction:
        "positive" — this link increases the gap (adds to the gap accumulation).
        "negative" — this link closes the gap (subtracts from the gap accumulation).
    """
    link_id: str
    nominal_mm: float
    tol_plus_mm: float
    tol_minus_mm: float
    direction: str

    def __post_init__(self) -> None:
        lid = str(self.link_id).strip()
        if not lid:
            raise ValueError("DimensionLink: link_id must not be empty")
        self.link_id = lid

        try:
            nom = float(self.nominal_mm)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"DimensionLink '{self.link_id}': nominal_mm must be numeric, "
                f"got '{self.nominal_mm}'"
            ) from exc
        if nom < 0:
            raise ValueError(
                f"DimensionLink '{self.link_id}': nominal_mm must be >= 0, got {nom}"
            )
        self.nominal_mm = nom

        for attr_name in ("tol_plus_mm", "tol_minus_mm"):
            raw = getattr(self, attr_name)
            try:
                val = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"DimensionLink '{self.link_id}': {attr_name} must be numeric, "
                    f"got '{raw}'"
                ) from exc
            if val < 0:
                raise ValueError(
                    f"DimensionLink '{self.link_id}': {attr_name} must be >= 0 "
                    f"(sign is implied by name), got {val}"
                )
            setattr(self, attr_name, val)

        dir_str = str(self.direction).strip().lower()
        if dir_str not in _VALID_DIRECTIONS:
            raise ValueError(
                f"DimensionLink '{self.link_id}': direction must be one of "
                f"{sorted(_VALID_DIRECTIONS)}, got '{self.direction}'"
            )
        self.direction = dir_str

    @property
    def sign(self) -> float:
        """+1 for 'positive', −1 for 'negative'."""
        return 1.0 if self.direction == "positive" else -1.0

    @property
    def tol_max_mm(self) -> float:
        """Half-tolerance for worst-case / RSS: max(t⁺, t⁻)."""
        return max(self.tol_plus_mm, self.tol_minus_mm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "nominal_mm": self.nominal_mm,
            "tol_plus_mm": self.tol_plus_mm,
            "tol_minus_mm": self.tol_minus_mm,
            "direction": self.direction,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DimensionLink":
        return cls(
            link_id=d["link_id"],
            nominal_mm=d["nominal_mm"],
            tol_plus_mm=d["tol_plus_mm"],
            tol_minus_mm=d["tol_minus_mm"],
            direction=d["direction"],
        )


@dataclass
class DimensionChainReport:
    """
    Result of a linear dimension chain tolerance stack-up analysis.

    Attributes
    ----------
    nominal_gap_mm:
        Nominal (design) gap = Σ s_i · d_i.
    worst_case_min_mm:
        Minimum possible gap under worst-case (100% conservative) analysis.
    worst_case_max_mm:
        Maximum possible gap under worst-case analysis.
    rss_min_mm:
        Minimum gap under RSS (statistical, ±3σ, 99.73%) analysis.
    rss_max_mm:
        Maximum gap under RSS analysis.
    links_count:
        Number of links in the chain.
    dominant_link:
        link_id of the link with the largest half-tolerance max(t⁺, t⁻).
        Tightening this link has the greatest effect on reducing stack-up.
    honest_caveat:
        Scope limitation notice per ASME Y14.5-2018 §5.3 + Bralla §1.
    """
    nominal_gap_mm: float
    worst_case_min_mm: float
    worst_case_max_mm: float
    rss_min_mm: float
    rss_max_mm: float
    links_count: int
    dominant_link: str
    honest_caveat: str = _HONEST_CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "nominal_gap_mm": self.nominal_gap_mm,
            "worst_case_min_mm": self.worst_case_min_mm,
            "worst_case_max_mm": self.worst_case_max_mm,
            "rss_min_mm": self.rss_min_mm,
            "rss_max_mm": self.rss_max_mm,
            "links_count": self.links_count,
            "dominant_link": self.dominant_link,
            "honest_caveat": self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_dimension_chain(
    chain: list[DimensionLink],
    target_gap_min_mm: float,
    target_gap_max_mm: float,
) -> DimensionChainReport:
    """
    Compute worst-case and RSS (statistical) tolerance stack-up for a dimension chain.

    Parameters
    ----------
    chain:
        Ordered list of DimensionLink objects forming the closed loop.  Must have
        at least one link.
    target_gap_min_mm:
        Required minimum assembly gap (mm).  Used only for validation; not stored
        in the report (call site can compare report values against target).
    target_gap_max_mm:
        Required maximum assembly gap (mm).  Must be >= target_gap_min_mm.

    Returns
    -------
    DimensionChainReport
        Contains nominal_gap_mm, worst_case_{min,max}_mm, rss_{min,max}_mm,
        links_count, dominant_link, honest_caveat.

    Raises
    ------
    ValueError
        If chain is empty, or target_gap_min_mm > target_gap_max_mm.

    Algorithm
    ---------
    1. Nominal gap  G_nom = Σ s_i · d_i
       (s_i = +1 for "positive", −1 for "negative")

    2. Worst-case accumulation (ASME §5.3):
         T_WC = Σ max(t⁺_i, t⁻_i)
         G_wc_min = G_nom − T_WC
         G_wc_max = G_nom + T_WC

    3. RSS accumulation (Bralla §1, 3σ bilateral):
         T_RSS = sqrt(Σ max(t⁺_i, t⁻_i)²)
         G_rss_min = G_nom − T_RSS
         G_rss_max = G_nom + T_RSS

    4. Dominant link = link with largest max(t⁺, t⁻).
    """
    if not chain:
        raise ValueError("compute_dimension_chain: chain must not be empty")

    try:
        t_min = float(target_gap_min_mm)
        t_max = float(target_gap_max_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"compute_dimension_chain: target_gap values must be numeric: {exc}"
        ) from exc

    if t_min > t_max:
        raise ValueError(
            f"compute_dimension_chain: target_gap_min_mm ({t_min}) must be "
            f"<= target_gap_max_mm ({t_max})"
        )

    # 1. Nominal gap
    nominal_gap = sum(link.sign * link.nominal_mm for link in chain)

    # 2. Worst-case
    t_wc = sum(link.tol_max_mm for link in chain)
    wc_min = nominal_gap - t_wc
    wc_max = nominal_gap + t_wc

    # 3. RSS
    t_rss = math.sqrt(sum(link.tol_max_mm ** 2 for link in chain))
    rss_min = nominal_gap - t_rss
    rss_max = nominal_gap + t_rss

    # 4. Dominant link (largest half-tolerance)
    dominant = max(chain, key=lambda lnk: lnk.tol_max_mm)

    # Round to 10 decimal places (avoid float-rep noise in report)
    return DimensionChainReport(
        nominal_gap_mm=round(nominal_gap, 10),
        worst_case_min_mm=round(wc_min, 10),
        worst_case_max_mm=round(wc_max, 10),
        rss_min_mm=round(rss_min, 10),
        rss_max_mm=round(rss_max, 10),
        links_count=len(chain),
        dominant_link=dominant.link_id,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper (gated import — registry not available in unit-test context)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]  # noqa: F401

    _gdt_compute_dimension_chain_spec = ToolSpec(
        name="gdt_compute_dimension_chain",
        description=(
            "Compute worst-case (WC) and statistical RSS tolerance stack-up for a "
            "linear dimension chain per ASME Y14.5-2018 §5.3.\n"
            "\n"
            "A dimension chain is a closed loop of nominal dimensions whose sum "
            "determines the assembly gap (clearance or interference).  Each link "
            "has a bilateral tolerance (+t_plus / −t_minus) and a direction "
            "('positive' adds to the gap, 'negative' subtracts).\n"
            "\n"
            "Methods:\n"
            "  Worst-case (WC): T_WC = Σ max(t⁺, t⁻); 100% assemblability, "
            "pessimistic.\n"
            "  RSS (Statistical): T_RSS = √(Σ max(t⁺, t⁻)²); assumes independent, "
            "normally distributed links at 3σ — ~99.73% assemblability.\n"
            "\n"
            "Returns:\n"
            "  nominal_gap_mm        — Σ s_i · d_i\n"
            "  worst_case_min/max_mm — [nominal − T_WC, nominal + T_WC]\n"
            "  rss_min/max_mm        — [nominal − T_RSS, nominal + T_RSS]\n"
            "  dominant_link         — link_id with largest half-tolerance\n"
            "  honest_caveat         — RSS assumption flags\n"
            "\n"
            "HONEST FLAG: RSS assumes independent normal distributions centred on "
            "nominal (Cpk=1.0); correlated or non-normal processes may be "
            "unconservative. Use WC for 100% guarantee; Monte Carlo for "
            "high-accuracy statistical results."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "chain": {
                    "type": "array",
                    "description": "Ordered list of dimension links forming the chain.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "link_id": {
                                "type": "string",
                                "description": "Unique identifier for this link.",
                            },
                            "nominal_mm": {
                                "type": "number",
                                "description": "Nominal dimension in mm (>= 0).",
                            },
                            "tol_plus_mm": {
                                "type": "number",
                                "description": "Upper tolerance half-band in mm (>= 0).",
                            },
                            "tol_minus_mm": {
                                "type": "number",
                                "description": (
                                    "Lower tolerance half-band in mm (>= 0; "
                                    "sign is implied by name)."
                                ),
                            },
                            "direction": {
                                "type": "string",
                                "enum": ["positive", "negative"],
                                "description": (
                                    "'positive' — this link increases the gap; "
                                    "'negative' — this link closes the gap."
                                ),
                            },
                        },
                        "required": [
                            "link_id",
                            "nominal_mm",
                            "tol_plus_mm",
                            "tol_minus_mm",
                            "direction",
                        ],
                    },
                    "minItems": 1,
                },
                "target_gap_min_mm": {
                    "type": "number",
                    "description": "Required minimum assembly gap (mm).",
                },
                "target_gap_max_mm": {
                    "type": "number",
                    "description": "Required maximum assembly gap (mm, >= target_gap_min_mm).",
                },
            },
            "required": ["chain", "target_gap_min_mm", "target_gap_max_mm"],
        },
    )

    @register(_gdt_compute_dimension_chain_spec, write=False)
    async def run_gdt_compute_dimension_chain(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        for field_name in ("chain", "target_gap_min_mm", "target_gap_max_mm"):
            if field_name not in a:
                return err_payload(f"'{field_name}' is required", "BAD_ARGS")

        raw_chain = a.get("chain")
        if not isinstance(raw_chain, list):
            return err_payload("chain must be an array", "BAD_ARGS")
        if not raw_chain:
            return err_payload("chain must have at least one link", "BAD_ARGS")

        try:
            links = [DimensionLink.from_dict(item) for item in raw_chain]
        except (ValueError, KeyError, TypeError) as exc:
            return err_payload(f"chain parse error: {exc}", "BAD_ARGS")

        try:
            target_min = float(a["target_gap_min_mm"])
            target_max = float(a["target_gap_max_mm"])
        except (TypeError, ValueError) as exc:
            return err_payload(f"target_gap values must be numeric: {exc}", "BAD_ARGS")

        try:
            report = compute_dimension_chain(links, target_min, target_max)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload(report.to_dict())

    _TOOL_REGISTERED = True

except ImportError:
    # Registry not available (pure unit-test context or kerf_chat not installed).
    # DimensionLink, DimensionChainReport, and compute_dimension_chain()
    # remain fully usable.
    _TOOL_REGISTERED = False
