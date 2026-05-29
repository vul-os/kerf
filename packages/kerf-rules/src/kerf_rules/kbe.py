"""
kerf_rules.kbe — General Knowledge-Based Engineering (KBE) rule engine.

KBE rules drive PARAMETRIC DESIGN — they don't just validate; they SELECT
and DERIVE values from engineering standards.  A KBE rule encodes domain
knowledge like "given span + load, pick the lightest AISC W-shape that
satisfies LRFD demand/capacity".

Architecture
------------
KBERule
    Richer than the compliance engine's Rule:
    • precondition  — callable(State) → bool  (when to fire)
    • derivation    — callable(State) → dict  (what to compute/select)
    • confidence    — 0..1 weighting for conflict resolution
    • provenance    — cites the standard/handbook this rule encodes

KBEEngine
    Forward-chaining inference loop.  On each cycle every applicable rule
    fires and deposits its derived values into the State.  Conflict
    resolution: higher-confidence rule wins; tiebreak = rule declaration
    order (earlier wins).

KBELibrary
    Persistent rule store keyed by domain ("structural", "mechanical",
    "electrical", "plumbing").  Loads from a built-in Python dict; can be
    extended from JSON/YAML files.

Standard-library starter pack (10 rules, 4 domains)
-----------------------------------------------------
Structural:
  KBE-S-01  AISC W-shape selection (span + udl → lightest adequate section)
  KBE-S-02  ACI 318 flexural rebar selection (Mu → min As)
  KBE-S-03  ASCE 7 wind load case selection (exposure + velocity → governing LC)

Mechanical:
  KBE-M-01  Bearing dynamic load rating from L10 life target (ISO 281)
  KBE-M-02  Shaft diameter via DE-Goodman fatigue criterion (ASME B106)

Electrical:
  KBE-E-01  Wire gauge from NEC ampacity (NEC 310.16)
  KBE-E-02  Breaker rating from connected load (NEC 240.4, 210.20)
  KBE-E-03  Transformer kVA selection (NEC 450 / IEEE C57.12)

Plumbing:
  KBE-P-01  Pipe size from drainage fixture units — IPC Table 710.1(1)
  KBE-P-02  Pump head from system curve (Darcy-Weisbach + fittings)

Integration with kerf_rules compliance engine
----------------------------------------------
KBEEngine.run(state) returns an InferenceResult whose .derived dict can be
fed directly into a compliance rule pack:

    from kerf_rules.kbe import KBEEngine, KBELibrary, KBEState
    from kerf_rules.engine import evaluate

    library = KBELibrary.default()
    engine  = KBEEngine(library.all_rules())
    state   = KBEState(params={"span_m": 10, "udl_kN_m2": 8, "trib_m": 1.0})
    result  = engine.run(state)
    # result.derived["section"] == "W21X68" (or heavier)
    # Feed into Configurator / BOM / compliance checks downstream.

References
----------
AISC Steel Construction Manual 16th ed. (ANSI/AISC 360-22)
ACI 318-19 §9 (Flexure)
ASCE 7-22 §26–27 (Wind loads)
ISO 281:2007 (Rolling bearing life)
ASME B106.1M-1985 (Transmission Shafting)
NEC 2023 Article 310, 240, 210, 450
IPC 2021 Table 710.1(1) (Drainage fixture units)
Darcy-Weisbach + Colebrook-White (pipe flow)

Author: imranparuk
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State — the shared working memory the engine reads/writes
# ---------------------------------------------------------------------------

@dataclass
class KBEState:
    """
    Shared inference state.

    params  — input parameters provided by the user/configurator.
    derived — values set by KBE rules (accumulates during inference).
    trace   — which rules fired (in order), for audit.
    """
    params:  dict[str, Any] = field(default_factory=dict)
    derived: dict[str, Any] = field(default_factory=dict)
    trace:   list[str]      = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Unified lookup: derived first, then params."""
        if key in self.derived:
            return self.derived[key]
        return self.params.get(key, default)

    def set(self, updates: dict[str, Any], rule_id: str) -> None:
        """Merge rule-derived values; record in trace."""
        self.derived.update(updates)
        self.trace.append(rule_id)


# ---------------------------------------------------------------------------
# KBERule
# ---------------------------------------------------------------------------

@dataclass
class KBERule:
    """
    A single KBE rule that DRIVES parametric design.

    Parameters
    ----------
    id : str
        Unique rule identifier, e.g. "KBE-S-01".
    domain : str
        Domain bucket: "structural", "mechanical", "electrical", "plumbing".
    description : str
        Human-readable summary of what the rule computes.
    provenance : str
        Full citation — standard name, edition, section.
    confidence : float
        0.0 .. 1.0.  Higher confidence wins conflicts.  Rules from primary
        standards should use 0.9+; handbook approximations 0.7–0.89;
        heuristics < 0.7.
    precondition : Callable[[KBEState], bool]
        Returns True when the rule should fire given the current state.
    derivation : Callable[[KBEState], dict[str, Any]]
        Computes and returns a dict of derived values.  Receives the
        full state so it can read already-derived fields.
    """
    id:           str
    domain:       str
    description:  str
    provenance:   str
    confidence:   float
    precondition: Callable[[KBEState], bool]
    derivation:   Callable[[KBEState], dict[str, Any]]

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"KBERule {self.id}: confidence must be 0..1, got {self.confidence}")
        if not self.provenance.strip():
            raise ValueError(f"KBERule {self.id}: provenance must be non-empty")

    def fires(self, state: KBEState) -> bool:
        """Return True if the precondition is satisfied."""
        try:
            return bool(self.precondition(state))
        except Exception as exc:
            logger.debug("KBERule %s precondition error: %s", self.id, exc)
            return False

    def apply(self, state: KBEState) -> dict[str, Any]:
        """Execute derivation and return the new key/value pairs."""
        return self.derivation(state)


# ---------------------------------------------------------------------------
# Conflict resolution
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    rule: KBERule
    updates: dict[str, Any]


def _resolve_conflicts(candidates: list[_Candidate]) -> list[_Candidate]:
    """
    For each derived key, keep only the update from the highest-confidence
    rule.  Tiebreak: first-declared rule (lowest index in candidates list).

    Returns the winning candidates (may be fewer than input if some rules
    contributed no keys after resolution).
    """
    # Map: key → winning candidate
    winner: dict[str, _Candidate] = {}
    for cand in candidates:
        for key in cand.updates:
            if key not in winner:
                winner[key] = cand
            else:
                if cand.rule.confidence > winner[key].rule.confidence:
                    winner[key] = cand
    # Rebuild: keep candidates that won at least one key
    winning_set = set(id(c) for c in winner.values())
    # Preserve order
    seen = set()
    result = []
    for cand in candidates:
        if id(cand) in winning_set and id(cand) not in seen:
            seen.add(id(cand))
            # Trim updates to only keys this candidate won
            trimmed = {k: v for k, v in cand.updates.items() if winner.get(k) is cand}
            result.append(_Candidate(rule=cand.rule, updates=trimmed))
    return result


# ---------------------------------------------------------------------------
# Inference result
# ---------------------------------------------------------------------------

@dataclass
class InferenceResult:
    """
    Outcome of one KBEEngine.run() call.

    Attributes
    ----------
    derived : dict
        All values derived by the rules that fired.
    fired : list[str]
        Rule IDs that fired (in order).
    conflicts_resolved : int
        Number of key conflicts that were resolved.
    state : KBEState
        The final state (params + derived).
    """
    derived:            dict[str, Any]
    fired:              list[str]
    conflicts_resolved: int
    state:              KBEState


# ---------------------------------------------------------------------------
# KBEEngine
# ---------------------------------------------------------------------------

class KBEEngine:
    """
    Forward-chaining KBE inference engine.

    Iterates rules until no new rules fire (fixed point) or the iteration
    limit is reached (default 20 cycles — prevents infinite loops in badly
    specified rule sets).
    """

    def __init__(
        self,
        rules: list[KBERule],
        *,
        max_cycles: int = 20,
    ) -> None:
        self.rules = list(rules)
        self.max_cycles = max_cycles

    def run(self, state: KBEState) -> InferenceResult:
        """
        Execute forward-chaining inference.

        Each cycle:
        1. Collect all rules whose precondition holds on the current state.
        2. Execute their derivations.
        3. Resolve conflicts (per-key, highest confidence wins).
        4. Merge winning updates into the state.
        5. Repeat until stable (no new keys) or max_cycles exhausted.

        Returns InferenceResult with the final derived values.
        """
        fired: list[str] = []
        conflicts_total = 0

        for _cycle in range(self.max_cycles):
            candidates: list[_Candidate] = []
            for rule in self.rules:
                if rule.fires(state):
                    try:
                        updates = rule.apply(state)
                    except Exception as exc:
                        logger.warning("KBERule %s derivation error: %s", rule.id, exc)
                        continue
                    if updates:
                        candidates.append(_Candidate(rule=rule, updates=updates))

            if not candidates:
                break  # fixed point reached

            # Conflict resolution
            resolved = _resolve_conflicts(candidates)
            conflicts_total += len(candidates) - len(resolved)

            new_updates: dict[str, Any] = {}
            new_fired: list[str] = []
            for cand in resolved:
                new_updates.update(cand.updates)
                new_fired.append(cand.rule.id)

            # Only continue if we actually derived new/changed keys
            changed = {k: v for k, v in new_updates.items() if state.derived.get(k) != v}
            if not changed:
                break

            for cand in resolved:
                filtered = {k: v for k, v in cand.updates.items() if k in changed}
                if filtered:
                    state.set(filtered, cand.rule.id)
                    if cand.rule.id not in fired:
                        fired.append(cand.rule.id)

        return InferenceResult(
            derived=dict(state.derived),
            fired=fired,
            conflicts_resolved=conflicts_total,
            state=state,
        )


# ---------------------------------------------------------------------------
# KBELibrary
# ---------------------------------------------------------------------------

class KBELibrary:
    """
    Persistent rule store, keyed by domain.

    Usage::

        library = KBELibrary.default()           # built-in starter pack
        struct  = library.rules_for("structural") # domain subset
        engine  = KBEEngine(library.all_rules())
    """

    def __init__(self, rules: list[KBERule] | None = None) -> None:
        self._rules: list[KBERule] = list(rules or [])

    def register(self, rule: KBERule) -> None:
        """Add a rule to the library."""
        self._rules.append(rule)

    def all_rules(self) -> list[KBERule]:
        return list(self._rules)

    def rules_for(self, domain: str) -> list[KBERule]:
        return [r for r in self._rules if r.domain == domain]

    def get(self, rule_id: str) -> KBERule | None:
        for r in self._rules:
            if r.id == rule_id:
                return r
        return None

    @classmethod
    def default(cls) -> "KBELibrary":
        """Return a KBELibrary populated with the built-in 10-rule starter pack."""
        return cls(rules=_BUILTIN_RULES)

    @classmethod
    def from_json(cls, path: str | Path) -> "KBELibrary":
        """
        Load a library from a JSON file.

        The JSON must be a list of objects with keys:
          id, domain, description, provenance, confidence,
          precondition_expr (Python bool expression, state accessible as 's'),
          derivation_expr   (Python dict expression, state accessible as 's').

        This is intentionally limited — complex rules should be registered
        programmatically via register().
        """
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        rules: list[KBERule] = []
        for item in raw:
            pre_expr = item["precondition_expr"]
            der_expr = item["derivation_expr"]

            def _make_pre(expr: str) -> Callable[[KBEState], bool]:
                def _pre(s: KBEState) -> bool:  # noqa: ANN001
                    return bool(eval(expr, {"s": s, "__builtins__": {}, "math": math}))  # noqa: S307
                return _pre

            def _make_der(expr: str) -> Callable[[KBEState], dict]:
                def _der(s: KBEState) -> dict:  # noqa: ANN001
                    return eval(expr, {"s": s, "__builtins__": {}, "math": math})  # noqa: S307
                return _der

            rules.append(KBERule(
                id=item["id"],
                domain=item["domain"],
                description=item["description"],
                provenance=item["provenance"],
                confidence=float(item["confidence"]),
                precondition=_make_pre(pre_expr),
                derivation=_make_der(der_expr),
            ))
        return cls(rules=rules)


# ===========================================================================
# Built-in starter-pack rules (10 rules, 4 domains)
# ===========================================================================
#
# Design notes:
# • Rules import from kerf_structural / kerf_cad_core only when they fire
#   (lazy import inside derivation) so the library loads even if those
#   packages are absent.
# • All preconditions are kept simple and composable.
# • Confidence levels:
#   0.95 — primary AISC/ACI/NEC tables (exact lookup)
#   0.90 — ISO/ASME computed formula
#   0.85 — handbook approximation / simplifying assumption
# ===========================================================================


# ---------------------------------------------------------------------------
# STRUCTURAL — KBE-S-01: AISC W-shape selection
# ---------------------------------------------------------------------------
# Given span (m) + uniformly distributed load (kN/m²) + tributary width (m),
# compute the required moment and select the lightest AISC W-shape whose
# φMn ≥ Mu.  The minimum required depth ≥ span/16 is checked (AISC SCM
# Table 9-1 serviceability guideline).

def _s01_pre(s: KBEState) -> bool:
    return (
        s.get("span_m") is not None
        and s.get("udl_kN_m2") is not None
        and "section" not in s.derived
    )


def _s01_der(s: KBEState) -> dict[str, Any]:
    """Select lightest adequate AISC W-shape for span + UDL."""
    from kerf_structural.steel_beam import _W_TABLE, design_steel_beam, w_section

    span_m   = float(s.get("span_m"))
    udl_kNm2 = float(s.get("udl_kN_m2"))
    trib_m   = float(s.get("trib_m", 1.0))

    # Total line load w = udl × tributary width  [kN/m]
    w_kNm  = udl_kNm2 * trib_m
    w_klf  = w_kNm * 0.06852  # kN/m → kip/ft  (1 kN = 0.22481 kip, 1 m = 3.2808 ft)

    span_ft = span_m * 3.28084
    # Simple-span LRFD:  Mu = (1.2D + 1.6L) w L² / 8
    # Approximate: use full factored load w_u ≈ 1.4 × service  (conservative)
    w_u_klf = 1.4 * w_klf
    Mu_kip_ft = w_u_klf * span_ft ** 2 / 8.0

    # Minimum depth for serviceability: depth ≥ span/16
    span_in  = span_m * 39.3701
    min_depth_in = span_in / 16.0

    # Unbraced length = span (conservative — assume no intermediate bracing)
    Lb_ft = span_ft

    # Iterate over W-sections in ascending weight order; pick lightest that works
    _WEIGHT_RE = __import__("re").compile(r"W\d+X(\d+)")
    def _weight(desig: str) -> float:
        m = _WEIGHT_RE.search(desig)
        return float(m.group(1)) if m else 999.0

    sections_sorted = sorted(_W_TABLE.keys(), key=_weight)
    selected = None
    selected_result = None
    for desig in sections_sorted:
        sec = w_section(desig)
        if sec.d < min_depth_in:
            continue
        res = design_steel_beam(desig, Lb_ft)
        if res.ok and res.phi_Mn_kip_ft >= Mu_kip_ft:
            selected = desig
            selected_result = res
            break

    if selected is None:
        return {
            "section": None,
            "section_error": f"No W-shape in built-in table satisfies Mu={Mu_kip_ft:.1f} kip-ft",
        }

    return {
        "section":        selected,
        "Mu_kip_ft":      round(Mu_kip_ft, 2),
        "phi_Mn_kip_ft":  round(selected_result.phi_Mn_kip_ft, 2),
        "ltb_zone":       selected_result.ltb_zone,
        "span_ft":        round(span_ft, 2),
        "udl_kN_m2":      udl_kNm2,
        "rule_source":    "KBE-S-01",
    }


_RULE_S01 = KBERule(
    id="KBE-S-01",
    domain="structural",
    description=(
        "AISC W-shape selection: given simple-span + UDL, compute LRFD demand "
        "and select the lightest W-section with φMn ≥ Mu and depth ≥ span/16."
    ),
    provenance=(
        "ANSI/AISC 360-22 Chapter F (F2 LTB); "
        "AISC Steel Construction Manual 16th ed., Tables 3-2 and 9-1; "
        "ASCE 7-22 §2.3 (LRFD load factors)."
    ),
    confidence=0.95,
    precondition=_s01_pre,
    derivation=_s01_der,
)


# ---------------------------------------------------------------------------
# STRUCTURAL — KBE-S-02: ACI 318 flexural rebar selection
# ---------------------------------------------------------------------------

def _s02_pre(s: KBEState) -> bool:
    return (
        s.get("Mu_kip_ft") is not None
        and s.get("beam_b_in") is not None
        and s.get("beam_h_in") is not None
        and "As_required_in2" not in s.derived
    )


def _s02_der(s: KBEState) -> dict[str, Any]:
    from kerf_structural.rc_beam import design_rc_beam

    res = design_rc_beam(
        b=float(s.get("beam_b_in")),
        h=float(s.get("beam_h_in")),
        Mu_kip_ft=float(s.get("Mu_kip_ft")),
        fc=float(s.get("fc_psi", 4_000.0)),
        fy=float(s.get("fy_psi", 60_000.0)),
    )
    if not res.ok:
        return {"As_error": res.reason}

    return {
        "As_required_in2": round(res.As_required, 3),
        "rho_design":      round(res.rho, 6),
        "rho_min":         round(res.rho_min, 6),
        "rho_max":         round(res.rho_max, 6),
        "rc_Rn_psi":       round(res.Rn, 2),
        "rule_source":     "KBE-S-02",
    }


_RULE_S02 = KBERule(
    id="KBE-S-02",
    domain="structural",
    description=(
        "ACI 318 flexural rebar: given Mu + beam dimensions, compute minimum "
        "tension steel area As using the R_n strength-design method."
    ),
    provenance=(
        "ACI 318-19 §9.3 (Flexural strength), §9.6 (Min/max reinforcement), "
        "§22.2 (Equivalent stress-block assumptions); "
        "Wight, 'Reinforced Concrete: Mechanics and Design', 8th ed."
    ),
    confidence=0.95,
    precondition=_s02_pre,
    derivation=_s02_der,
)


# ---------------------------------------------------------------------------
# STRUCTURAL — KBE-S-03: ASCE 7 wind load case selection
# ---------------------------------------------------------------------------

def _s03_pre(s: KBEState) -> bool:
    return (
        s.get("wind_speed_mph") is not None
        and s.get("exposure_category") is not None
        and "wind_pressure_psf" not in s.derived
    )


def _s03_der(s: KBEState) -> dict[str, Any]:
    """
    ASCE 7-22 §27.3 simplified envelope wind pressure on MWFRS.

    p = qz × G × Cp   (qz = 0.00256 × Kz × Kzt × Kd × V²)

    Uses simplified roof-height Kz for exposure B/C/D; Kzt=1 (flat terrain);
    Kd=0.85 (building); Cp=0.8 windward + (-0.5) leeward = governing 1.3.
    """
    V   = float(s.get("wind_speed_mph"))
    exp = str(s.get("exposure_category", "B")).upper().strip()
    z   = float(s.get("mean_roof_height_ft", 30.0))

    # ASCE 7-22 Table 26.10-1 Kz for given exposure at height z
    # Simplified formula: Kz = 2.01 × (z/zg)^(2/alpha)
    _EXP = {
        "B": {"alpha": 7.0,  "zg": 1200.0},
        "C": {"alpha": 9.5,  "zg": 900.0},
        "D": {"alpha": 11.5, "zg": 700.0},
    }
    params = _EXP.get(exp, _EXP["B"])
    alpha, zg = params["alpha"], params["zg"]
    z_eff = max(z, 15.0)  # ASCE 7 §26.10.1 minimum height
    Kz = 2.01 * (z_eff / zg) ** (2.0 / alpha)

    Kzt = 1.0   # flat terrain
    Kd  = 0.85  # directional factor for buildings
    G   = 0.85  # gust factor (rigid building, §26.11)
    qz  = 0.00256 * Kz * Kzt * Kd * V ** 2   # psf

    # Governing net pressure (windward + leeward per §27.3)
    Cp_net = 1.3   # 0.8 + 0.5
    p_net  = qz * G * Cp_net

    # Select governing ASCE 7 §2.3.1 wind load combination
    # LC6: 0.9D + 1.0W (uplift-governing for lightweight roofs)
    # LC4: 1.2D + 1.0W + 0.5L (typical strength combination)
    wind_lc = "LC4: 1.2D + 1.0W + 0.5L"
    if s.get("D_kip_ft") and s.get("W_kip_ft"):
        D = float(s.get("D_kip_ft"))
        W = float(s.get("W_kip_ft"))
        lc4 = 1.2 * D + 1.0 * W
        lc6 = 0.9 * D + 1.0 * W
        if lc6 < 0 or (abs(lc6) > abs(lc4)):
            wind_lc = "LC6: 0.9D + 1.0W"

    return {
        "wind_pressure_psf":    round(p_net, 2),
        "qz_psf":               round(qz, 3),
        "Kz":                   round(Kz, 3),
        "governing_wind_lc":    wind_lc,
        "wind_exposure":        exp,
        "rule_source":          "KBE-S-03",
    }


_RULE_S03 = KBERule(
    id="KBE-S-03",
    domain="structural",
    description=(
        "ASCE 7 wind load case selection: given design wind speed + exposure "
        "category + mean roof height, compute velocity pressure qz and select "
        "governing MWFRS load combination."
    ),
    provenance=(
        "ASCE 7-22 §26.10 (Velocity pressure), §26.11 (Gust factor), "
        "§27.3 (MWFRS — Directional Procedure), §2.3.1 (Strength load combos)."
    ),
    confidence=0.90,
    precondition=_s03_pre,
    derivation=_s03_der,
)


# ---------------------------------------------------------------------------
# MECHANICAL — KBE-M-01: Bearing selection from ISO 281 L10 life target
# ---------------------------------------------------------------------------

def _m01_pre(s: KBEState) -> bool:
    return (
        s.get("bearing_load_N") is not None
        and s.get("bearing_speed_rpm") is not None
        and s.get("bearing_L10h_target") is not None
        and "bearing_C_required_N" not in s.derived
    )


def _m01_der(s: KBEState) -> dict[str, Any]:
    """
    Invert ISO 281 L10 formula to find required dynamic load rating C.

    L10 = (C/P)^p  →  C = P × L10^(1/p)
    where L10 is in 10^6 revolutions.
    """
    from kerf_cad_core.shaft.calc import bearing_l10  # noqa: F401 (verify import available)

    P_N   = float(s.get("bearing_load_N"))
    n_rpm = float(s.get("bearing_speed_rpm"))
    L10h  = float(s.get("bearing_L10h_target"))
    btype = str(s.get("bearing_type", "ball")).lower()

    p = 3.0 if btype == "ball" else 10.0 / 3.0

    # Convert target L10 hours → 10^6 revolutions
    L10_rev = L10h * 60.0 * n_rpm / 1e6

    # Required C
    C_required_N = P_N * (L10_rev ** (1.0 / p))

    # Verify the oracle: bearing_l10(C_required, P, n) should ≥ L10h
    from kerf_cad_core.shaft.calc import bearing_l10 as _bl10
    verify = _bl10(C_required_N, P_N, n_rpm, btype)
    actual_L10h = verify.get("L10_hours", 0.0) if verify.get("ok") else 0.0

    return {
        "bearing_C_required_N":  round(C_required_N, 1),
        "bearing_L10_rev":       round(L10_rev, 4),
        "bearing_L10h_achieved": round(actual_L10h, 1),
        "bearing_p_exponent":    p,
        "bearing_type":          btype,
        "rule_source":           "KBE-M-01",
    }


_RULE_M01 = KBERule(
    id="KBE-M-01",
    domain="mechanical",
    description=(
        "ISO 281 bearing selection: given equivalent radial load P, shaft speed, "
        "and target L10 life (hours), compute the required basic dynamic load "
        "rating C to satisfy the life criterion."
    ),
    provenance=(
        "ISO 281:2007 §5.1 — Basic dynamic load ratings and rating life; "
        "SKF Bearing Catalogue §4 (design selection procedure); "
        "Shigley's Mechanical Engineering Design, 10th ed., §11-9."
    ),
    confidence=0.95,
    precondition=_m01_pre,
    derivation=_m01_der,
)


# ---------------------------------------------------------------------------
# MECHANICAL — KBE-M-02: Shaft diameter via DE-Goodman (ASME B106)
# ---------------------------------------------------------------------------

def _m02_pre(s: KBEState) -> bool:
    return (
        s.get("shaft_M_Nm") is not None
        and s.get("shaft_T_Nm") is not None
        and s.get("shaft_Se_Pa") is not None
        and "shaft_diameter_m" not in s.derived
    )


def _m02_der(s: KBEState) -> dict[str, Any]:
    from kerf_cad_core.shaft.calc import shaft_diameter

    result = shaft_diameter(
        M=float(s.get("shaft_M_Nm")),
        T=float(s.get("shaft_T_Nm")),
        sigma_allow=float(s.get("shaft_Se_Pa")),
        method="DE-Goodman",
        Kf=float(s.get("shaft_Kf", 1.0)),
        Kfs=float(s.get("shaft_Kfs", 1.0)),
        safety_factor=float(s.get("shaft_safety_factor", 1.5)),
    )
    if not result.get("ok"):
        return {"shaft_error": result.get("reason", "unknown")}

    d_m = result["diameter_m"]
    return {
        "shaft_diameter_m":  round(d_m, 5),
        "shaft_diameter_mm": round(d_m * 1_000.0, 2),
        "shaft_method":      "DE-Goodman",
        "rule_source":       "KBE-M-02",
    }


_RULE_M02 = KBERule(
    id="KBE-M-02",
    domain="mechanical",
    description=(
        "Shaft diameter via DE-Goodman fatigue criterion: given bending moment "
        "M, torque T, and endurance limit Se, compute required solid shaft "
        "diameter for infinite life."
    ),
    provenance=(
        "ASME B106.1M-1985 — Design of Transmission Shafting; "
        "Shigley's Mechanical Engineering Design, 10th ed., §6-14 "
        "(Distortion-Energy / Goodman combined criterion)."
    ),
    confidence=0.90,
    precondition=_m02_pre,
    derivation=_m02_der,
)


# ---------------------------------------------------------------------------
# ELECTRICAL — KBE-E-01: Wire gauge from NEC ampacity
# ---------------------------------------------------------------------------
# NEC 2023 Table 310.16 (Cu, 75°C column, 3+ conductors in conduit)
# Common values:
#   14 AWG → 15 A    12 AWG → 20 A    10 AWG → 30 A
#    8 AWG → 50 A     6 AWG → 65 A     4 AWG → 85 A
#    3 AWG → 100 A    2 AWG → 115 A    1 AWG → 130 A
#   1/0   → 150 A   2/0   → 175 A   3/0   → 200 A   4/0   → 230 A
# ---------------------------------------------------------------------------

# (AWG_code, ampacity_A): NEC 310.16, 75°C Cu, 3 conductors
_NEC_AMPACITY: list[tuple[str, int]] = [
    ("14",  15),
    ("12",  20),
    ("10",  30),
    ("8",   50),
    ("6",   65),
    ("4",   85),
    ("3",  100),
    ("2",  115),
    ("1",  130),
    ("1/0", 150),
    ("2/0", 175),
    ("3/0", 200),
    ("4/0", 230),
    ("250kcmil", 255),
    ("300kcmil", 285),
    ("350kcmil", 310),
    ("400kcmil", 335),
    ("500kcmil", 380),
]


def _e01_pre(s: KBEState) -> bool:
    return (
        s.get("load_current_A") is not None
        and "wire_gauge_awg" not in s.derived
    )


def _e01_der(s: KBEState) -> dict[str, Any]:
    I_A      = float(s.get("load_current_A"))
    # NEC 210.20: branch circuit must be rated ≥ 125% of continuous load
    continuous = bool(s.get("continuous_load", True))
    I_design   = I_A * 1.25 if continuous else I_A

    for gauge, amp in _NEC_AMPACITY:
        if amp >= I_design:
            return {
                "wire_gauge_awg":       gauge,
                "wire_ampacity_A":      amp,
                "design_current_A":     round(I_design, 2),
                "continuous_load":      continuous,
                "rule_source":          "KBE-E-01",
            }
    return {"wire_error": f"Current {I_design:.1f} A exceeds 500 kcmil ampacity table"}


_RULE_E01 = KBERule(
    id="KBE-E-01",
    domain="electrical",
    description=(
        "NEC wire gauge selection: given load current, select the smallest "
        "copper conductor whose 75°C ampacity meets the design current "
        "(125% of continuous load per NEC 210.20)."
    ),
    provenance=(
        "NEC 2023 Table 310.16 — Allowable Ampacities of Insulated Conductors "
        "(Cu, 75°C column, 3 or fewer current-carrying conductors in raceway); "
        "NEC 2023 §210.20(A) — Continuous loads."
    ),
    confidence=0.95,
    precondition=_e01_pre,
    derivation=_e01_der,
)


# ---------------------------------------------------------------------------
# ELECTRICAL — KBE-E-02: Breaker rating from connected load
# ---------------------------------------------------------------------------

def _e02_pre(s: KBEState) -> bool:
    return (
        s.get("load_current_A") is not None
        and "breaker_rating_A" not in s.derived
    )


def _e02_der(s: KBEState) -> dict[str, Any]:
    I_A      = float(s.get("load_current_A"))
    continuous = bool(s.get("continuous_load", True))

    # NEC 240.4(B): breaker must not exceed ampacity of conductor
    # NEC 210.20: continuous load → breaker ≥ 125% of load
    I_breaker = I_A * 1.25 if continuous else I_A

    # Standard breaker ratings (NEC 240.6)
    _STANDARD_RATINGS = [
        15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100,
        110, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500,
        600, 700, 800, 1000, 1200,
    ]
    rating = next((r for r in _STANDARD_RATINGS if r >= I_breaker), None)
    if rating is None:
        return {"breaker_error": f"Load {I_breaker:.1f} A exceeds 1200 A breaker table"}

    return {
        "breaker_rating_A":  rating,
        "design_current_A":  round(I_breaker, 2),
        "continuous_load":   continuous,
        "rule_source":       "KBE-E-02",
    }


_RULE_E02 = KBERule(
    id="KBE-E-02",
    domain="electrical",
    description=(
        "NEC breaker rating: select the next standard overcurrent device size "
        "≥ design current (125% of continuous load) per NEC 210.20 and 240.4."
    ),
    provenance=(
        "NEC 2023 §210.20(A) — Continuous loads on branch circuits; "
        "NEC 2023 §240.4(B) — Overcurrent device exceeding conductor ampacity; "
        "NEC 2023 §240.6(A) — Standard ampere ratings."
    ),
    confidence=0.90,
    precondition=_e02_pre,
    derivation=_e02_der,
)


# ---------------------------------------------------------------------------
# ELECTRICAL — KBE-E-03: Transformer kVA selection
# ---------------------------------------------------------------------------

def _e03_pre(s: KBEState) -> bool:
    return (
        s.get("load_kW") is not None
        and "transformer_kVA" not in s.derived
    )


def _e03_der(s: KBEState) -> dict[str, Any]:
    kW  = float(s.get("load_kW"))
    pf  = float(s.get("power_factor", 0.85))
    # Add 25% NEC safety margin for continuous loads
    margin = float(s.get("transformer_margin", 1.25))

    kVA_required = (kW / pf) * margin

    # Standard dry-type transformer ratings (kVA) — IEEE C57.12.01 / NEC 450
    _KVA_RATINGS = [
        1, 1.5, 2, 3, 5, 7.5, 10, 15, 25, 37.5, 50, 75, 100, 112.5,
        150, 167, 200, 225, 250, 333, 400, 500, 600, 667, 750,
        1000, 1500, 2000, 2500, 3000, 3750, 5000,
    ]
    selected_kVA = next((k for k in _KVA_RATINGS if k >= kVA_required), None)
    if selected_kVA is None:
        return {"transformer_error": f"Required {kVA_required:.1f} kVA exceeds standard table"}

    return {
        "transformer_kVA":      selected_kVA,
        "kVA_required":         round(kVA_required, 2),
        "load_pf":              pf,
        "rule_source":          "KBE-E-03",
    }


_RULE_E03 = KBERule(
    id="KBE-E-03",
    domain="electrical",
    description=(
        "Transformer kVA selection: given load kW + power factor, compute "
        "apparent power with NEC 125% safety margin and select next standard "
        "dry-type kVA rating."
    ),
    provenance=(
        "NEC 2023 §450.3 — Overcurrent protection for transformers; "
        "IEEE C57.12.01-2015 — Standard for dry-type distribution transformers "
        "(standard kVA ratings table); "
        "NEC 2023 §210.20(A) — 125% continuous load margin."
    ),
    confidence=0.90,
    precondition=_e03_pre,
    derivation=_e03_der,
)


# ---------------------------------------------------------------------------
# PLUMBING — KBE-P-01: Pipe size from drainage fixture units (IPC)
# ---------------------------------------------------------------------------
# IPC 2021 Table 710.1(1): horizontal branches and stacks
# DFU limits per nominal pipe size (in inches)
# ---------------------------------------------------------------------------

_IPC_PIPE_SIZES: list[tuple[float, int]] = [
    # (nominal_diameter_in, max_DFU_horizontal_branch)
    (1.25,   1),
    (1.5,    3),
    (2.0,    6),
    (2.5,   12),
    (3.0,   20),
    (4.0,  160),
    (5.0,  360),
    (6.0,  620),
    (8.0, 1400),
]


def _p01_pre(s: KBEState) -> bool:
    return (
        s.get("drainage_fixture_units") is not None
        and "drain_pipe_diameter_in" not in s.derived
    )


def _p01_der(s: KBEState) -> dict[str, Any]:
    dfu = float(s.get("drainage_fixture_units"))

    for dia_in, max_dfu in _IPC_PIPE_SIZES:
        if max_dfu >= dfu:
            return {
                "drain_pipe_diameter_in": dia_in,
                "drain_pipe_max_dfu":     max_dfu,
                "design_dfu":             dfu,
                "rule_source":            "KBE-P-01",
            }
    return {"drain_error": f"DFU={dfu} exceeds IPC table (max 1400 for 8-in pipe)"}


_RULE_P01 = KBERule(
    id="KBE-P-01",
    domain="plumbing",
    description=(
        "IPC pipe sizing from drainage fixture units: select minimum pipe "
        "diameter for a horizontal branch per IPC Table 710.1(1)."
    ),
    provenance=(
        "IPC 2021 Table 710.1(1) — Drainage Fixture Units for Fixtures and Groups "
        "(horizontal branch and stack sizing); "
        "ASPE Data Book Vol. 1 §4 — Drain, Waste, and Vent Systems."
    ),
    confidence=0.95,
    precondition=_p01_pre,
    derivation=_p01_der,
)


# ---------------------------------------------------------------------------
# PLUMBING — KBE-P-02: Pump head from system curve (Darcy-Weisbach)
# ---------------------------------------------------------------------------

def _p02_pre(s: KBEState) -> bool:
    return (
        s.get("flow_rate_m3s") is not None
        and s.get("pipe_length_m") is not None
        and s.get("pipe_diameter_m") is not None
        and "pump_head_m" not in s.derived
    )


def _p02_der(s: KBEState) -> dict[str, Any]:
    """
    Darcy-Weisbach + Moody friction factor (Colebrook-White approximation).

    h_f = f × (L/D) × V²/(2g)
    Total head = static_head + h_f + minor_losses(K × V²/2g)
    """
    Q      = float(s.get("flow_rate_m3s"))       # m³/s
    L      = float(s.get("pipe_length_m"))        # m
    D      = float(s.get("pipe_diameter_m"))      # m
    eps    = float(s.get("pipe_roughness_m", 4.6e-5))  # m  (steel)
    nu     = float(s.get("kinematic_viscosity_m2s", 1e-6))  # m²/s (water 20°C)
    H_s    = float(s.get("static_head_m", 0.0))  # m
    K_fit  = float(s.get("fitting_K_sum", 5.0))  # sum of minor loss coefficients
    g      = 9.81  # m/s²

    A = math.pi / 4.0 * D ** 2
    V = Q / A  # m/s

    Re = V * D / nu if nu > 0 else 1e6

    # Colebrook-White (Swamee-Jain explicit approximation)
    if Re < 2300:
        f = 64.0 / Re  # laminar
    else:
        # Swamee-Jain: f = 0.25 / [log(eps/(3.7D) + 5.74/Re^0.9)]²
        f = 0.25 / (math.log10(eps / (3.7 * D) + 5.74 / Re ** 0.9)) ** 2

    h_friction = f * (L / D) * V ** 2 / (2.0 * g)
    h_minor    = K_fit * V ** 2 / (2.0 * g)
    h_total    = H_s + h_friction + h_minor

    return {
        "pump_head_m":        round(h_total, 3),
        "friction_head_m":    round(h_friction, 3),
        "minor_head_m":       round(h_minor, 3),
        "static_head_m":      H_s,
        "pipe_velocity_ms":   round(V, 3),
        "Re":                 round(Re, 0),
        "darcy_f":            round(f, 5),
        "rule_source":        "KBE-P-02",
    }


_RULE_P02 = KBERule(
    id="KBE-P-02",
    domain="plumbing",
    description=(
        "Pump head via Darcy-Weisbach system curve: given flow rate, pipe "
        "geometry, and static head, compute total head loss (friction + minor "
        "losses) to size the pump."
    ),
    provenance=(
        "Darcy-Weisbach equation (ISO 4006); "
        "Swamee-Jain explicit friction factor approximation "
        "(Swamee & Jain, J. Hydraulics Div., 1976); "
        "Colebrook-White equation (Colebrook, 1939); "
        "ASPE Data Book Vol. 2 §2 — Pump selection and system curves."
    ),
    confidence=0.90,
    precondition=_p02_pre,
    derivation=_p02_der,
)


# ---------------------------------------------------------------------------
# Assemble the built-in rule list (declaration order is tiebreak priority)
# ---------------------------------------------------------------------------

_BUILTIN_RULES: list[KBERule] = [
    _RULE_S01,
    _RULE_S02,
    _RULE_S03,
    _RULE_M01,
    _RULE_M02,
    _RULE_E01,
    _RULE_E02,
    _RULE_E03,
    _RULE_P01,
    _RULE_P02,
]


# ---------------------------------------------------------------------------
# Convenience function: apply rules to a flat params dict
# ---------------------------------------------------------------------------

def apply_rules(
    params: dict[str, Any],
    *,
    domains: list[str] | None = None,
    library: KBELibrary | None = None,
) -> InferenceResult:
    """
    High-level entry point — run the KBE engine on a params dict.

    Parameters
    ----------
    params  : input parameters (span, loads, etc.)
    domains : if provided, restrict to rules in these domains.
    library : custom KBELibrary; defaults to KBELibrary.default().

    Returns
    -------
    InferenceResult
    """
    lib   = library or KBELibrary.default()
    rules = lib.all_rules()
    if domains:
        rules = [r for r in rules if r.domain in domains]
    engine = KBEEngine(rules)
    state  = KBEState(params=dict(params))
    return engine.run(state)
