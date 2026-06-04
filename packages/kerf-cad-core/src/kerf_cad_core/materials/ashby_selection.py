"""
kerf_cad_core.materials.ashby_selection — Ashby material selection indices,
multi-objective scoring, and Pareto-front analysis.

Implements Cambridge Engineering Selector-equivalent selection methodology
(CES EduPack / Granta MI parity) using publicly documented Ashby indices.

The three stages of Ashby selection (Ashby 2017 Ch. 5):
  1. Screen by constraints (filter_materials / SelectionConstraint)
  2. Rank by objective via performance index (select_materials / SelectionObjective)
  3. Support info for documentation (SelectionResult metadata)

Ashby charts
------------
build_ashby_chart returns data ready for log-log bubble plotting,
directly analogous to CES EduPack Chart tool outputs.

Pareto front
------------
pareto_front returns non-dominated materials for two properties,
equivalent to "Pareto line" display in Granta MI.

References
----------
* Ashby, M.F. (2017). "Materials Selection in Mechanical Design." 5th ed.,
  Butterworth-Heinemann. §5 (Performance indices), §9 (Multiple objectives),
  Table 5.1 (Index compilation).
* Ashby, M.F. (2018). "Materials: Engineering, Science, Processing, Design."
  4th ed., Butterworth-Heinemann. §4 (Attribute charts).
* CES EduPack User Manual (Granta Material Intelligence; public references).
* Dym, C.L. & Shames, I.H. (2013). "Solid Mechanics." Springer. §2 (elastic
  relations for beam/plate performance indices).

HONEST FLAG: This module implements the analytical Ashby framework with a
representative subset of materials. Production material selection should be
cross-checked against Granta MI, vendor data sheets, and safety factors.

Author: imranparuk
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kerf_cad_core.materials.material_db import Material, MaterialDatabase


# ---------------------------------------------------------------------------
# Ashby material performance index helpers
# (Table 5.1, Ashby 2017 "Materials Selection in Mechanical Design" 5e)
# ---------------------------------------------------------------------------

def material_index_minimum_mass_stiff_beam_bending() -> str:
    """Ashby index for lightest stiff beam in bending (stiffness-limited).

    Minimise mass → maximise E^(1/2) / ρ

    Derivation: Beam bending stiffness S = C₁ EI / L³; cross-section free to
    scale. Mass m = ρ A L. Combining: m ∝ (ρ / E^½). Maximise inverse.

    Ashby (2017) §5.4, Table 5.1 — "Stiff beam, minimum mass".
    Formula string uses Material field names (youngs_modulus_gpa, density_kg_m3).
    """
    return "youngs_modulus_gpa**0.5/density_kg_m3"


def material_index_minimum_mass_strong_tie() -> str:
    """Ashby index for lightest strong tie (yield-strength-limited).

    Minimise mass → maximise σ_y / ρ

    Derivation: Tie must carry load F. σ = F/A; m = ρ A L. At yield: A = F/σ_y.
    So m = ρ F L / σ_y. Maximise σ_y / ρ to minimise mass.

    Ashby (2017) §5.3, Table 5.1 — "Strong tie, minimum mass".
    Formula string uses Material field names.
    """
    return "yield_strength_mpa/density_kg_m3"


def material_index_minimum_mass_strong_beam_bending() -> str:
    """Ashby index for lightest strong beam in bending (yield-limited).

    Minimise mass → maximise σ_y^(2/3) / ρ

    Derivation: Beam bending stress σ = M c / I; rectangular section free to
    scale. Mass m ∝ ρ / σ_y^(2/3). Maximise inverse.

    Ashby (2017) §5.4, Table 5.1 — "Strong beam, minimum mass".
    Formula string uses Material field names.
    """
    return "yield_strength_mpa**0.667/density_kg_m3"


def material_index_minimum_cost_stiff_beam() -> str:
    """Ashby index for cheapest stiff beam in bending.

    Minimise cost → maximise E^(1/2) / (ρ · cost_per_kg_usd)

    Derivation: Same geometry as stiffness-limited beam; multiply mass by cost/kg.
    Cost C ∝ ρ · cost_per_kg / E^½. Maximise inverse.

    Ashby (2017) §5.7 — "Minimum cost" modification of stiff beam index.
    Formula string uses Material field names.
    """
    return "youngs_modulus_gpa**0.5/(density_kg_m3*cost_per_kg_usd)"


def material_index_minimum_mass_stiff_plate_bending() -> str:
    """Ashby index for lightest stiff plate in bending (stiffness-limited).

    Minimise mass → maximise E^(1/3) / ρ

    Derivation: Plate bending; both dimensions free to scale. Stiffness
    S ∝ E t³ / a²; mass m = ρ t a². Combining: m ∝ ρ / E^(1/3).

    Ashby (2017) §5.4, Table 5.1 — "Stiff plate, minimum mass".
    """
    return "youngs_modulus_gpa**0.333/density_kg_m3"


def material_index_minimum_mass_strong_plate_bending() -> str:
    """Ashby index for lightest strong plate in bending (yield-limited).

    Minimise mass → maximise σ_y^(1/2) / ρ

    Derivation: Plate bending; yield surface limited. m ∝ ρ / σ_y^(1/2).

    Ashby (2017) §5.4, Table 5.1 — "Strong plate, minimum mass".
    """
    return "yield_strength_mpa**0.5/density_kg_m3"


def material_index_thermal_insulation_panel() -> str:
    """Ashby index for thermal insulation panel (minimum thickness for given insulation).

    Minimise thickness → minimise λ / E^(1/3)  (structural + insulation)
    Or simply minimise thermal conductivity for pure insulation.

    Ashby (2018) §4 — thermal/structural panel.
    """
    return "thermal_conductivity_w_m_k"  # minimise (structural ties handled separately)


# ---------------------------------------------------------------------------
# Selection constraint and objective dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SelectionConstraint:
    """A hard constraint that a material must satisfy.

    Parameters
    ----------
    property : str
        Name of a Material attribute (e.g. 'yield_strength_mpa', 'density_kg_m3').
    operator : str
        Comparison operator: '>=' | '<=' | '>' | '<' | '=='
    value : float
        Threshold value in the property's natural units.
    """
    property: str
    operator: str  # '>=' | '<=' | '>' | '<' | '=='
    value: float

    def satisfied_by(self, material: Material) -> bool:
        """Return True iff the material satisfies this constraint.

        A None property value always returns False (conservative).
        """
        mat_val = getattr(material, self.property, None)
        if mat_val is None:
            return False
        try:
            mat_val = float(mat_val)
        except (TypeError, ValueError):
            return False

        op = self.operator
        v = self.value
        if op == ">=":
            return mat_val >= v
        if op == "<=":
            return mat_val <= v
        if op == ">":
            return mat_val > v
        if op == "<":
            return mat_val < v
        if op == "==":
            return math.isclose(mat_val, v, rel_tol=1e-6)
        raise ValueError(f"Unknown operator {op!r}; use >=, <=, >, <, ==")


@dataclass
class SelectionObjective:
    """A ranked objective for multi-criteria material scoring.

    Parameters
    ----------
    formula : str
        A Python expression using Material attribute names as variables, e.g.::

            'youngs_modulus_gpa**0.5/density_kg_m3'
            'yield_strength_mpa**0.667/density_kg_m3'

        Evaluated via _eval_formula().
    direction : str
        'maximize' or 'minimize'.
    weight : float
        Relative importance weight for multi-objective weighted sum (default 1.0).
    """
    formula: str
    direction: str  # 'maximize' | 'minimize'
    weight: float = 1.0


@dataclass
class SelectionResult:
    """One material's result from a select_materials query.

    Parameters
    ----------
    material : Material
        The candidate material.
    score : float
        Weighted-sum multi-objective score (higher = better after normalisation).
    rank : int
        1-based rank among all candidates (1 = best).
    constraints_satisfied : bool
        True if all constraints passed.
    failed_constraints : list[str]
        List of constraint descriptions that failed (empty if all passed).
    """
    material: Material
    score: float
    rank: int
    constraints_satisfied: bool
    failed_constraints: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Formula evaluator
# ---------------------------------------------------------------------------

def _eval_formula(formula: str, material: Material) -> float:
    """Evaluate an Ashby index formula string against a Material.

    The formula is evaluated in a restricted namespace containing only
    the material's numeric attributes. Returns float('nan') on error
    (e.g. None property, division by zero).

    Examples
    --------
    >>> _eval_formula('youngs_modulus_gpa**0.5/density_kg_m3', mat)
    >>> _eval_formula('yield_strength_mpa/density_kg_m3', mat)
    """
    import dataclasses

    # Build namespace from material fields
    ns: dict[str, float] = {}
    for f in dataclasses.fields(material):
        val = getattr(material, f.name, None)
        if val is not None:
            try:
                ns[f.name] = float(val)
            except (TypeError, ValueError):
                ns[f.name] = float("nan")
        else:
            ns[f.name] = float("nan")

    # Add math helpers available in formulas
    ns["sqrt"] = math.sqrt
    ns["log"] = math.log
    ns["exp"] = math.exp

    try:
        result = eval(formula, {"__builtins__": {}}, ns)  # noqa: S307
        return float(result)
    except Exception:
        return float("nan")


# ---------------------------------------------------------------------------
# Core selection engine
# ---------------------------------------------------------------------------

def select_materials(
    db: MaterialDatabase,
    constraints: list[SelectionConstraint],
    objectives: list[SelectionObjective],
    top_k: int = 10,
) -> list[SelectionResult]:
    """Filter by constraints, score by weighted objectives, rank.

    Algorithm
    ---------
    1. Evaluate all constraints; record failed constraints per material.
    2. Compute raw score for each objective formula.
    3. Normalise each objective's scores to [0, 1] using min-max scaling
       across all non-NaN candidates (not just those passing constraints).
    4. For 'minimize' objectives, invert the normalised score (1 - x).
    5. Compute weighted sum.
    6. Sort by score descending; assign ranks.
    7. Return top_k results (constrained-passing materials first).

    Multi-objective via weighted-sum scalarization following Ashby (2017) §9.3.

    Parameters
    ----------
    db : MaterialDatabase
    constraints : list[SelectionConstraint]
    objectives : list[SelectionObjective]
    top_k : int
        Maximum number of results to return.

    Returns
    -------
    list[SelectionResult]
        Sorted by score (best first). Constraint-failing materials included
        with constraints_satisfied=False so callers can see near-misses.
    """
    if not objectives:
        raise ValueError("At least one SelectionObjective is required.")

    # Step 1: Compute raw objective values for all materials
    all_mats = list(db.materials)
    raw: list[list[float]] = []  # raw[mat_idx][obj_idx]
    for mat in all_mats:
        row = [_eval_formula(obj.formula, mat) for obj in objectives]
        raw.append(row)

    raw_arr = np.array(raw, dtype=float)  # shape (n_mats, n_obj)

    # Step 2: Normalise each objective column to [0, 1]
    norm_arr = np.empty_like(raw_arr)
    for j in range(len(objectives)):
        col = raw_arr[:, j]
        finite = col[np.isfinite(col)]
        if len(finite) == 0:
            norm_arr[:, j] = 0.0
            continue
        lo, hi = float(finite.min()), float(finite.max())
        rng = hi - lo
        if rng == 0:
            norm_arr[:, j] = 0.5
        else:
            norm_arr[:, j] = (col - lo) / rng

    # Step 3: Invert minimise objectives; apply weights
    weights = np.array([obj.weight for obj in objectives], dtype=float)
    for j, obj in enumerate(objectives):
        if obj.direction == "minimize":
            norm_arr[:, j] = 1.0 - norm_arr[:, j]
        elif obj.direction != "maximize":
            raise ValueError(
                f"Objective direction {obj.direction!r} must be 'maximize' or 'minimize'"
            )

    weighted = norm_arr * weights[np.newaxis, :]
    scores = weighted.sum(axis=1) / weights.sum()

    # Step 4: Evaluate constraints
    results: list[SelectionResult] = []
    for i, mat in enumerate(all_mats):
        failed: list[str] = []
        for c in constraints:
            if not c.satisfied_by(mat):
                failed.append(
                    f"{c.property} {c.operator} {c.value}"
                )
        results.append(SelectionResult(
            material=mat,
            score=float(scores[i]),
            rank=0,
            constraints_satisfied=(len(failed) == 0),
            failed_constraints=failed,
        ))

    # Step 5: Sort — constraint-passing materials first, then by score desc
    results.sort(
        key=lambda r: (0 if r.constraints_satisfied else 1, -r.score)
    )

    # Step 6: Assign ranks
    for rank_idx, r in enumerate(results, start=1):
        r.rank = rank_idx

    return results[:top_k]


# ---------------------------------------------------------------------------
# Ashby chart data
# ---------------------------------------------------------------------------

@dataclass
class AshbyChart:
    """Data for an Ashby material-property bubble chart.

    Each material is a point at (x_values[i], y_values[i]) on a (typically
    log-log) property chart. This is the canonical Ashby/CES chart format.

    Attributes
    ----------
    x_property : str
        Name of the Material attribute on the x-axis.
    y_property : str
        Name of the Material attribute on the y-axis.
    x_values : list[float]
        Property values for the x-axis (parallel to materials list).
    y_values : list[float]
        Property values for the y-axis (parallel to materials list).
    materials : list[Material]
        The materials represented (same order as x_values, y_values).
    log_x : bool
        True if the x-axis should be log-scale (default True).
    log_y : bool
        True if the y-axis should be log-scale (default True).
    """
    x_property: str
    y_property: str
    x_values: list[float]
    y_values: list[float]
    materials: list[Material]
    log_x: bool = True
    log_y: bool = True


def build_ashby_chart(
    db: MaterialDatabase,
    x_property: str,
    y_property: str,
    exclude_none: bool = True,
) -> AshbyChart:
    """Build Ashby chart data for any two Material properties.

    Returns a data structure ready for plotting on a log-log bubble chart.
    Materials missing either property (None value) are excluded by default.

    Common charts (Ashby 2017 §4):
      * Strength vs Density  : 'yield_strength_mpa', 'density_kg_m3'
      * Stiffness vs Density : 'youngs_modulus_gpa', 'density_kg_m3'
      * Strength vs Modulus  : 'yield_strength_mpa', 'youngs_modulus_gpa'
      * Fracture toughness vs strength (requires KIc — not in base DB)

    Parameters
    ----------
    db : MaterialDatabase
    x_property : str
        Material attribute name for the x-axis.
    y_property : str
        Material attribute name for the y-axis.
    exclude_none : bool
        Exclude materials where either property is None (default True).

    Returns
    -------
    AshbyChart
        len(x_values) == len(y_values) == len(materials).
    """
    mats_out: list[Material] = []
    x_vals: list[float] = []
    y_vals: list[float] = []

    for mat in db.materials:
        xv = getattr(mat, x_property, None)
        yv = getattr(mat, y_property, None)
        if exclude_none and (xv is None or yv is None):
            continue
        try:
            xf = float(xv)
            yf = float(yv)
        except (TypeError, ValueError):
            if exclude_none:
                continue
            xf = float("nan")
            yf = float("nan")
        mats_out.append(mat)
        x_vals.append(xf)
        y_vals.append(yf)

    return AshbyChart(
        x_property=x_property,
        y_property=y_property,
        x_values=x_vals,
        y_values=y_vals,
        materials=mats_out,
        log_x=True,
        log_y=True,
    )


# ---------------------------------------------------------------------------
# Pareto front
# ---------------------------------------------------------------------------

def pareto_front(
    db: MaterialDatabase,
    x_property: str,
    y_property: str,
    direction_x: str = "maximize",
    direction_y: str = "maximize",
) -> list[Material]:
    """Return the non-dominated (Pareto-optimal) materials on a 2D front.

    A material is non-dominated if no other material is simultaneously at
    least as good on both objectives and strictly better on at least one.

    This is equivalent to the "Pareto line" in Granta MI /
    CES EduPack chart view. Used to identify optimal trade-offs between
    two conflicting properties (e.g. stiffness vs density).

    Algorithm: O(n²) dominance check — suitable for catalog sizes ≤ 1000.

    Parameters
    ----------
    db : MaterialDatabase
    x_property : str
        Name of a Material attribute for the first axis.
    y_property : str
        Name of a Material attribute for the second axis.
    direction_x : str
        'maximize' or 'minimize' for x-axis objective.
    direction_y : str
        'maximize' or 'minimize' for y-axis objective.

    Returns
    -------
    list[Material]
        Non-dominated materials, sorted by x-axis value ascending.

    References
    ----------
    Ashby (2017) §9.3 "Pareto frontier"; Deb (2001) "Multi-objective
    optimization using evolutionary algorithms" §2.
    """
    if direction_x not in ("maximize", "minimize"):
        raise ValueError(f"direction_x must be 'maximize' or 'minimize', got {direction_x!r}")
    if direction_y not in ("maximize", "minimize"):
        raise ValueError(f"direction_y must be 'maximize' or 'minimize', got {direction_y!r}")

    # Collect materials with finite values for both properties
    candidates: list[tuple[float, float, Material]] = []
    for mat in db.materials:
        xv = getattr(mat, x_property, None)
        yv = getattr(mat, y_property, None)
        if xv is None or yv is None:
            continue
        try:
            xf, yf = float(xv), float(yv)
        except (TypeError, ValueError):
            continue
        if math.isfinite(xf) and math.isfinite(yf):
            # Flip sign for minimise objectives so we always maximise
            sx = xf if direction_x == "maximize" else -xf
            sy = yf if direction_y == "maximize" else -yf
            candidates.append((sx, sy, mat))

    if not candidates:
        return []

    # Non-dominated sort (two objective Pareto front)
    non_dominated: list[tuple[float, float, Material]] = []
    for i, (xi, yi, mi) in enumerate(candidates):
        dominated = False
        for j, (xj, yj, _mj) in enumerate(candidates):
            if i == j:
                continue
            # j dominates i if xj >= xi AND yj >= yi AND (xj > xi OR yj > yi)
            if xj >= xi and yj >= yi and (xj > xi or yj > yi):
                dominated = True
                break
        if not dominated:
            non_dominated.append((xi, yi, mi))

    # Sort by original x-property value ascending
    sign_x = 1.0 if direction_x == "maximize" else -1.0
    non_dominated.sort(key=lambda t: sign_x * t[0])

    return [m for _, _, m in non_dominated]
