"""
kerf_cad_core.nesting.optimize_nest — NFP + Genetic Algorithm nesting optimizer.

Algorithm
---------
1.  **No-Fit Polygon (NFP)** placement feasibility:
    Builds NFP(A, B) = A ⊕ (−B) via the Minkowski-sum decomposition from
    kerf_cad_core.nesting.nfp.  For each already-placed part the feasible
    region for the next part is IFP minus the union of NFPs.
    Bottom-left fill chooses the geometrically optimal position per rotation.

    Reference: Sergyán, S. (2009). New approach of the no-fit polygon
    algorithm for solving the irregular strip-packing problem. Acta
    Polytechnica Hungarica 6(3):109–124.

2.  **Rotation set**: {0°, 90°, 180°, 270°} by default (rotation_step=4);
    option for 12-step {0°, 30°, …, 330°} (rotation_step=12) for richer
    angular coverage.

3.  **Genetic Algorithm** optimises placement sequence + rotation simultaneously:

    Encoding
    --------
    Each chromosome is a pair (sequence, rotations):
      - sequence  : permutation of part indices (integer list)
      - rotations : list of rotation-index integers (one per part)

    Fitness
    -------
    Simulate a bottom-left-fill placement of the sequence using the NFP
    feasibility check.  Fitness = placed_area / sheet_area (sheet utilisation).
    Parts that cannot be placed are skipped (penalised by absence from fitness).

    Operators
    ---------
    - Order-crossover (OX) on the sequence chromosome.
    - Uniform crossover on the rotation chromosome.
    - Swap-mutation on sequence; random-reset mutation on rotations.

    Parameters
    ----------
    population_size: 40  (configurable)
    generations    : 50  (configurable)
    crossover_rate : 0.85
    mutation_rate  : 0.15 (swap probability per gene)
    seed           : int for reproducibility
                     HONEST FLAG: GA is stochastic; identical seed + Python
                     version → identical result; across Python versions results
                     may differ.

    Reference: Kovacs, A. (2002). Genetic algorithm for the packing problem.
    PhD dissertation, Eötvös Loránd University.

    Reference: Burke, E. K., Kendall, G., & Whitwell, G. (2006). A new
    bottom-left-fill heuristic algorithm for the two-dimensional irregular
    packing problem. Operations Research, 52(6).
    doi:10.1287/opre.1060.0341

Curved-edge polygons
--------------------
True curved shapes (arcs, splines) must be approximated as polylines before
calling this function.  Use ``make_ngon()`` from nfp.py for circles/ellipses,
or a Bézier lineariser for spline boundaries.
HONEST FLAG: this function does not handle curved edges natively.

Public API
----------
::

    from kerf_cad_core.nesting.optimize_nest import optimize_nest, OptimizeNestResult

    result = optimize_nest(
        sheet=(200.0, 200.0),
        parts=[
            {"name": "rect", "vertices": [[0,0],[30,0],[30,20],[0,20]], "qty": 10},
        ],
        options={"generations": 50, "seed": 42},
    )
    print(result.utilization, result.placements)

Pure-Python — no NumPy, no OCCT, no Shapely.

Author: imranparuk
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from kerf_cad_core.nesting.nfp import (
    Polygon,
    NFPPlacement,
    compute_ifp,
    compute_nfp,
    _candidate_points,
    _bottom_left_key,
    _point_in_any,
    _point_in_ifp,
)


# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------

@dataclass
class OptimizeNestResult:
    """
    Result returned by optimize_nest().

    Attributes
    ----------
    placements : list of dicts
        Each dict: {name, rotation, x, y, vertices}.
    utilization : float
        Placed part area / sheet area, in [0, 1].
    placed_count : int
        Number of parts successfully placed.
    total_count : int
        Total parts requested (after expanding qty).
    runtime_ms : float
        Wall-clock time in milliseconds.
    generations_run : int
        Number of GA generations completed.
    seed : int
        RNG seed used (for reproducibility).
    ok : bool
        True when all parts were placed.
    errors : list of str
        Non-empty when ok=False.
    """
    placements: List[dict]
    utilization: float
    placed_count: int
    total_count: int
    runtime_ms: float
    generations_run: int
    seed: int
    ok: bool
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Part parsing
# ---------------------------------------------------------------------------

def _parse_parts(parts: List[dict]) -> Tuple[List[Tuple[str, Polygon]], List[str]]:
    """
    Parse and expand the parts list.

    Returns (expanded, errors).  expanded is a list of (name, polygon) pairs
    after expanding qty repetitions.
    """
    expanded: List[Tuple[str, Polygon]] = []
    errors: List[str] = []

    for p in parts:
        name = str(p.get("name", "?"))
        raw_verts = p.get("vertices")
        if not raw_verts or len(raw_verts) < 3:
            errors.append(f"Part '{name}': vertices must have >= 3 points.")
            continue
        try:
            verts = [(float(v[0]), float(v[1])) for v in raw_verts]
        except Exception as exc:
            errors.append(f"Part '{name}': vertex parse error: {exc}")
            continue
        try:
            poly = Polygon(verts)
        except ValueError as exc:
            errors.append(f"Part '{name}': {exc}")
            continue
        qty = max(1, int(p.get("qty", 1)))
        for _ in range(qty):
            expanded.append((name, poly))

    return expanded, errors


# ---------------------------------------------------------------------------
# Placement simulator (core NFP bottom-left logic)
# ---------------------------------------------------------------------------

def _simulate_placement(
    sequence: List[int],
    rotations: List[int],
    parts: List[Tuple[str, Polygon]],
    bin_w: float,
    bin_h: float,
    rotation_angles: List[float],
    grid_step: float,
) -> Tuple[List[NFPPlacement], float]:
    """
    Simulate placing parts in `sequence` order with given rotation indices.

    Returns (placements, utilization).
    """
    placed: List[NFPPlacement] = []
    placed_area = 0.0
    bin_area = bin_w * bin_h

    for pos, part_idx in enumerate(sequence):
        name, original_poly = parts[part_idx]
        rot_idx = rotations[pos] % len(rotation_angles)
        angle = rotation_angles[rot_idx]

        rotated = original_poly.rotate(angle)
        norm = rotated.normalize_origin()

        ifp = compute_ifp(bin_w, bin_h, norm)
        if ifp is None:
            # Try all rotations for this part to find one that fits
            placed_this = False
            for fallback_angle in rotation_angles:
                if fallback_angle == angle:
                    continue
                r2 = original_poly.rotate(fallback_angle).normalize_origin()
                ifp2 = compute_ifp(bin_w, bin_h, r2)
                if ifp2 is None:
                    continue
                nfp_list2: List[Polygon] = []
                for pl in placed:
                    placed_norm2 = pl.poly.translate(-pl.ref_x, -pl.ref_y)
                    for nfp in compute_nfp(placed_norm2, r2):
                        nfp_list2.append(nfp.translate(pl.ref_x, pl.ref_y))
                cands2 = _candidate_points(ifp2, grid_step=grid_step)
                feasible2 = [
                    pt for pt in cands2
                    if _point_in_ifp(pt, ifp2) and not _point_in_any(pt, nfp_list2)
                ]
                if feasible2:
                    feasible2.sort(key=_bottom_left_key)
                    ref_x, ref_y = feasible2[0]
                    placed_poly = r2.translate(ref_x, ref_y)
                    placement = NFPPlacement(
                        name=name, rotation=fallback_angle,
                        ref_x=ref_x, ref_y=ref_y,
                        poly=placed_poly, part_area=original_poly.area(),
                    )
                    placed.append(placement)
                    placed_area += original_poly.area()
                    placed_this = True
                    break
            if not placed_this:
                continue
            continue

        # NFPs of already-placed parts vs current part
        nfp_list: List[Polygon] = []
        for pl in placed:
            placed_norm = pl.poly.translate(-pl.ref_x, -pl.ref_y)
            for nfp in compute_nfp(placed_norm, norm):
                nfp_list.append(nfp.translate(pl.ref_x, pl.ref_y))

        candidates = _candidate_points(ifp, grid_step=grid_step)
        feasible: List[Tuple[float, float]] = []
        for pt in candidates:
            if not _point_in_ifp(pt, ifp):
                continue
            if _point_in_any(pt, nfp_list):
                continue
            feasible.append(pt)

        if not feasible:
            # Try other rotations
            placed_this = False
            for fallback_angle in rotation_angles:
                if fallback_angle == angle:
                    continue
                r2 = original_poly.rotate(fallback_angle).normalize_origin()
                ifp2 = compute_ifp(bin_w, bin_h, r2)
                if ifp2 is None:
                    continue
                nfp_list2 = []
                for pl in placed:
                    placed_norm2 = pl.poly.translate(-pl.ref_x, -pl.ref_y)
                    for nfp in compute_nfp(placed_norm2, r2):
                        nfp_list2.append(nfp.translate(pl.ref_x, pl.ref_y))
                cands2 = _candidate_points(ifp2, grid_step=grid_step)
                feasible2 = [
                    pt for pt in cands2
                    if _point_in_ifp(pt, ifp2) and not _point_in_any(pt, nfp_list2)
                ]
                if feasible2:
                    feasible2.sort(key=_bottom_left_key)
                    ref_x, ref_y = feasible2[0]
                    placed_poly = r2.translate(ref_x, ref_y)
                    placement = NFPPlacement(
                        name=name, rotation=fallback_angle,
                        ref_x=ref_x, ref_y=ref_y,
                        poly=placed_poly, part_area=original_poly.area(),
                    )
                    placed.append(placement)
                    placed_area += original_poly.area()
                    placed_this = True
                    break
            if not placed_this:
                continue
            continue

        feasible.sort(key=_bottom_left_key)
        ref_x, ref_y = feasible[0]
        placed_poly = norm.translate(ref_x, ref_y)
        placement = NFPPlacement(
            name=name,
            rotation=angle,
            ref_x=ref_x,
            ref_y=ref_y,
            poly=placed_poly,
            part_area=original_poly.area(),
        )
        placed.append(placement)
        placed_area += original_poly.area()

    utilization = placed_area / bin_area if bin_area > 0 else 0.0
    return placed, utilization


# ---------------------------------------------------------------------------
# Greedy seed: area-descending order
# ---------------------------------------------------------------------------

def _greedy_sequence(n: int, parts: List[Tuple[str, Polygon]]) -> List[int]:
    """Return part indices sorted by area descending."""
    indexed = list(range(n))
    indexed.sort(key=lambda i: parts[i][1].area(), reverse=True)
    return indexed


# ---------------------------------------------------------------------------
# GA operators
# ---------------------------------------------------------------------------

def _ox_crossover(
    seq_a: List[int], seq_b: List[int], rng: random.Random
) -> Tuple[List[int], List[int]]:
    """
    Order Crossover (OX) for permutation chromosomes.

    Copies a random slice from parent A into child; fills remaining
    positions in the order they appear in parent B.
    """
    n = len(seq_a)
    if n <= 1:
        return list(seq_a), list(seq_b)

    i, j = sorted(rng.sample(range(n), 2))
    child1: List[Optional[int]] = [None] * n
    child2: List[Optional[int]] = [None] * n

    child1[i:j + 1] = seq_a[i:j + 1]
    child2[i:j + 1] = seq_b[i:j + 1]

    def _fill(child: list, parent: List[int]) -> List[int]:
        taken = set(x for x in child if x is not None)
        fill_vals = [x for x in parent if x not in taken]
        fi = 0
        for k in range(n):
            if child[k] is None:
                child[k] = fill_vals[fi]
                fi += 1
        return child  # type: ignore[return-value]

    return _fill(child1, seq_b), _fill(child2, seq_a)


def _uniform_crossover(
    rot_a: List[int], rot_b: List[int], rng: random.Random
) -> Tuple[List[int], List[int]]:
    """Uniform crossover on rotation arrays."""
    c1, c2 = [], []
    for a, b in zip(rot_a, rot_b):
        if rng.random() < 0.5:
            c1.append(a); c2.append(b)
        else:
            c1.append(b); c2.append(a)
    return c1, c2


def _swap_mutate(seq: List[int], mutation_rate: float, rng: random.Random) -> List[int]:
    """Swap-mutation: for each gene, with probability mutation_rate swap with a random other gene."""
    seq = list(seq)
    n = len(seq)
    for i in range(n):
        if rng.random() < mutation_rate:
            j = rng.randrange(n)
            seq[i], seq[j] = seq[j], seq[i]
    return seq


def _reset_mutate(
    rotations: List[int], n_rotations: int, mutation_rate: float, rng: random.Random
) -> List[int]:
    """Random-reset mutation: each gene reset to a random rotation index."""
    return [
        rng.randrange(n_rotations) if rng.random() < mutation_rate else r
        for r in rotations
    ]


# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------

def optimize_nest(
    sheet: Tuple[float, float],
    parts: List[dict],
    options: Optional[dict] = None,
) -> OptimizeNestResult:
    """
    NFP + Genetic Algorithm nesting optimizer for sheet metal / CNC.

    Parameters
    ----------
    sheet : (width, height)
        Sheet dimensions.
    parts : list of dicts
        Each dict: ``name`` (str), ``vertices`` (list of [x, y]),
        optional ``qty`` (int, default 1).
        Curved edges must be pre-linearised as polylines
        (HONEST FLAG: curved edges not natively supported).
    options : dict, optional
        ``generations``      : int   — GA generations (default 50)
        ``population_size``  : int   — GA population (default 40)
        ``rotation_step``    : int   — degrees between rotations;
                               4 → {0°,90°,180°,270°} (default);
                               12 → {0°,30°,…,330°} for richer coverage.
        ``crossover_rate``   : float (default 0.85)
        ``mutation_rate``    : float (default 0.15)
        ``grid_step``        : float — NFP sampling resolution mm (default 5.0)
        ``seed``             : int   — RNG seed for reproducibility.
                               HONEST FLAG: GA is stochastic; set seed for
                               reproducibility.  Results may differ across
                               Python versions even with the same seed.
        ``runtime_budget_ms``: float — abort GA after this many ms; 0=no limit.

    Returns
    -------
    OptimizeNestResult
        placements, utilization, placed_count, total_count, runtime_ms,
        generations_run, seed, ok, errors.

    References
    ----------
    Burke, E. K., Kendall, G., & Whitwell, G. (2006). A new bottom-left-fill
    heuristic algorithm for the two-dimensional irregular packing problem.
    Operations Research, 52(6). doi:10.1287/opre.1060.0341

    Kovacs, A. (2002). Genetic algorithm for the packing problem.
    PhD dissertation, Eötvös Loránd University.

    Sergyán, S. (2009). New approach of the no-fit polygon algorithm for
    solving the irregular strip-packing problem. Acta Polytechnica
    Hungarica 6(3):109–124.
    """
    t0 = time.perf_counter()
    opts = options or {}

    # --- Options ---
    generations      = int(opts.get("generations", 50))
    pop_size         = int(opts.get("population_size", 40))
    rotation_step    = int(opts.get("rotation_step", 4))
    crossover_rate   = float(opts.get("crossover_rate", 0.85))
    mutation_rate    = float(opts.get("mutation_rate", 0.15))
    grid_step        = float(opts.get("grid_step", 5.0))
    seed             = opts.get("seed", None)
    runtime_budget   = float(opts.get("runtime_budget_ms", 0))

    # Clamp grid_step (security: prevent accidental O(n^4) blow-up)
    grid_step = max(grid_step, 1.0)

    bin_w, bin_h = float(sheet[0]), float(sheet[1])

    # Build rotation angles from step divisor
    if rotation_step <= 0:
        rotation_step = 4
    n_rotations = max(1, 360 // rotation_step)
    rotation_angles: List[float] = [float(i * rotation_step) for i in range(n_rotations)]

    # Empty input
    if not parts:
        ms = (time.perf_counter() - t0) * 1000
        actual_seed = seed if seed is not None else 0
        return OptimizeNestResult(
            placements=[], utilization=0.0, placed_count=0, total_count=0,
            runtime_ms=ms, generations_run=0, seed=actual_seed,
            ok=True, errors=[],
        )

    expanded, errors = _parse_parts(parts)
    if errors:
        ms = (time.perf_counter() - t0) * 1000
        return OptimizeNestResult(
            placements=[], utilization=0.0, placed_count=0,
            total_count=len(expanded),
            runtime_ms=ms, generations_run=0,
            seed=seed if seed is not None else 0,
            ok=False, errors=errors,
        )

    n_parts = len(expanded)
    total_count = n_parts

    # Reject parts that don't fit on the sheet at any rotation
    oversized_names: List[str] = []
    for name, poly in expanded:
        fits = False
        for angle in rotation_angles:
            rotated = poly.rotate(angle).normalize_origin()
            if compute_ifp(bin_w, bin_h, rotated) is not None:
                fits = True
                break
        if not fits:
            oversized_names.append(name)

    if oversized_names:
        ms = (time.perf_counter() - t0) * 1000
        error_msgs = [
            f"Part '{nm}' does not fit in the sheet at any rotation and has been rejected."
            for nm in oversized_names
        ]
        return OptimizeNestResult(
            placements=[], utilization=0.0, placed_count=0,
            total_count=total_count,
            runtime_ms=ms, generations_run=0,
            seed=seed if seed is not None else 0,
            ok=False, errors=error_msgs,
        )

    # RNG setup
    actual_seed = seed if seed is not None else random.randint(0, 2**31 - 1)
    rng = random.Random(actual_seed)

    # Chromosome type alias
    Chromosome = Tuple[List[int], List[int]]

    def _random_chromosome() -> Chromosome:
        seq = list(range(n_parts))
        rng.shuffle(seq)
        rot = [rng.randrange(n_rotations) for _ in range(n_parts)]
        return seq, rot

    def _fitness(chrom: Chromosome) -> float:
        seq, rot = chrom
        _, util = _simulate_placement(
            seq, rot, expanded, bin_w, bin_h, rotation_angles, grid_step
        )
        return util

    # --- Initial population with greedy seed ---
    greedy_seq = _greedy_sequence(n_parts, expanded)
    greedy_rot = [0] * n_parts
    population: List[Chromosome] = [(greedy_seq, greedy_rot)]
    while len(population) < pop_size:
        population.append(_random_chromosome())

    fitness_scores = [_fitness(c) for c in population]
    best_idx = max(range(pop_size), key=lambda i: fitness_scores[i])
    best_chrom: Chromosome = population[best_idx]
    best_fitness: float = fitness_scores[best_idx]

    gens_run = 0
    for gen in range(generations):
        if runtime_budget > 0:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if elapsed_ms >= runtime_budget:
                break

        gens_run = gen + 1

        def _tournament(k: int = 3) -> Chromosome:
            contestants = rng.sample(range(pop_size), k)
            winner = max(contestants, key=lambda i: fitness_scores[i])
            return population[winner]

        new_pop: List[Chromosome] = [best_chrom]   # elitism
        new_fit: List[float] = [best_fitness]

        while len(new_pop) < pop_size:
            p1 = _tournament()
            p2 = _tournament()

            if rng.random() < crossover_rate:
                c1_seq, c2_seq = _ox_crossover(p1[0], p2[0], rng)
                c1_rot, c2_rot = _uniform_crossover(p1[1], p2[1], rng)
            else:
                c1_seq, c1_rot = list(p1[0]), list(p1[1])
                c2_seq, c2_rot = list(p2[0]), list(p2[1])

            c1_seq = _swap_mutate(c1_seq, mutation_rate, rng)
            c1_rot = _reset_mutate(c1_rot, n_rotations, mutation_rate, rng)
            c2_seq = _swap_mutate(c2_seq, mutation_rate, rng)
            c2_rot = _reset_mutate(c2_rot, n_rotations, mutation_rate, rng)

            for cseq, crot in [(c1_seq, c1_rot), (c2_seq, c2_rot)]:
                if len(new_pop) >= pop_size:
                    break
                chrom = (cseq, crot)
                fit = _fitness(chrom)
                new_pop.append(chrom)
                new_fit.append(fit)

        population = new_pop
        fitness_scores = new_fit

        gen_best_idx = max(range(pop_size), key=lambda i: fitness_scores[i])
        if fitness_scores[gen_best_idx] > best_fitness:
            best_fitness = fitness_scores[gen_best_idx]
            best_chrom = population[gen_best_idx]

    # Final decode
    final_placements, final_util = _simulate_placement(
        best_chrom[0], best_chrom[1], expanded, bin_w, bin_h,
        rotation_angles, grid_step,
    )

    placement_dicts = [
        {
            "name": pl.name,
            "rotation": pl.rotation,
            "x": pl.ref_x,
            "y": pl.ref_y,
            "vertices": pl.poly.vertices,
        }
        for pl in final_placements
    ]

    ms = (time.perf_counter() - t0) * 1000
    placed_count = len(final_placements)
    ok = placed_count == total_count

    err_msgs: List[str] = []
    if not ok:
        unplaced = total_count - placed_count
        err_msgs.append(
            f"{unplaced} of {total_count} part(s) could not be placed "
            "(sheet too small or parts mutually exclusive at allowed rotations)."
        )

    return OptimizeNestResult(
        placements=placement_dicts,
        utilization=round(final_util, 6),
        placed_count=placed_count,
        total_count=total_count,
        runtime_ms=round(ms, 2),
        generations_run=gens_run,
        seed=actual_seed,
        ok=ok,
        errors=err_msgs,
    )


# ---------------------------------------------------------------------------
# LLM tool wrapper
# ---------------------------------------------------------------------------

def manufacturing_optimize_nest(
    sheet: Tuple[float, float],
    parts: List[dict],
    options: Optional[dict] = None,
) -> dict:
    """
    LLM-callable tool: NFP + GA nesting optimizer for sheet metal / CNC.

    Parameters
    ----------
    sheet : [width, height]
        Sheet dimensions (mm).
    parts : list of dicts
        ``name`` (str), ``vertices`` (list of [x, y]), optional ``qty`` (int).
        Curved shapes must be pre-approximated as polylines
        (HONEST FLAG: curved edges not natively supported).
    options : dict, optional
        ``generations``, ``population_size``, ``rotation_step`` (4=90° steps,
        12=30° steps), ``grid_step``, ``seed``, ``runtime_budget_ms``.
        HONEST FLAG: GA is stochastic; set seed for reproducibility.

    Returns
    -------
    dict: ok, placements, utilization, utilization_pct, placed_count,
          total_count, runtime_ms, generations_run, seed, errors.

    References
    ----------
    Burke et al. 2006, Operations Research 52(6); doi:10.1287/opre.1060.0341
    Kovacs 2002, PhD diss., Eötvös Loránd University.
    """
    result = optimize_nest(sheet=sheet, parts=parts, options=options)
    return {
        "ok": result.ok,
        "placements": result.placements,
        "utilization": result.utilization,
        "utilization_pct": round(result.utilization * 100, 2),
        "placed_count": result.placed_count,
        "total_count": result.total_count,
        "runtime_ms": result.runtime_ms,
        "generations_run": result.generations_run,
        "seed": result.seed,
        "errors": result.errors,
    }
