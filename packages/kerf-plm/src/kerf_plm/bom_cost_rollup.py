"""
kerf_plm.bom_cost_rollup
========================

Multi-level BOM cost roll-up per ISO 10303-44 (STEP AP44 product structure)
and APICS dictionary "rolled-up cost" definition.

The rolled-up cost at any assembly node is:

    rolled_cost(node) = node.internal_cost
                      + sum(qty_i * rolled_cost(child_i)
                            for child_i, qty_i in node.children)

All costs are converted to the target currency via fx_rates before summing.

Honest caveats
--------------
- Static unit costs only: no scrap allowance, no overhead absorption,
  no yield-based costing, no learning-curve amortisation.
- FX rates are caller-supplied constants; no live market feed.
- Quantity must be a positive real number (e.g. continuous materials).
- No activity-based or machine-rate overhead; direct material cost only.
- Shared sub-assemblies (diamonds in the BOM DAG) are costed once per
  occurrence path, not deduplicated.

References
----------
- ISO 10303-44:2021 (STEP Application Protocol 44 — product structure)
- APICS Dictionary, 16th ed.: "rolled-up cost"
- Horngren, C.T. et al. *Cost Accounting: A Managerial Emphasis*, 16th ed.
  §7 for multi-level BOM costing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

HONEST_CAVEAT = (
    "Static unit-cost rollup only. "
    "No scrap allowance, overhead absorption, yield-based costing, "
    "learning-curve amortisation, or activity-based costing. "
    "FX rates are caller-supplied constants. "
    "ISO 10303-44 product structure; APICS rolled-up cost definition."
)


@dataclass
class BomNode:
    """A node in the multi-level Bill of Materials tree.

    Parameters
    ----------
    part_number:   Unique part identifier (e.g. 'PN-001').
    name:          Human-readable part name.
    unit_cost:     Cost of this node's own labour/process contribution
                   (excluding children).  Same as ``internal_cost`` when
                   the node is a purchased leaf part.
    currency:      ISO 4217 currency code for unit_cost and internal_cost.
    children:      Ordered list of (child_node, quantity) pairs.
    internal_cost: Cost intrinsic to this assembly node beyond its children
                   (e.g. assembly labour, fixture cost).  Defaults to
                   ``unit_cost`` when node is a leaf (children=[]).
    """

    part_number: str
    name: str
    unit_cost: float
    currency: str
    children: list[tuple["BomNode", float]] = field(default_factory=list)
    internal_cost: float = 0.0

    def __post_init__(self) -> None:
        if self.unit_cost < 0:
            raise ValueError(
                f"unit_cost must be >= 0 for part '{self.part_number}', "
                f"got {self.unit_cost}"
            )
        if self.internal_cost < 0:
            raise ValueError(
                f"internal_cost must be >= 0 for part '{self.part_number}', "
                f"got {self.internal_cost}"
            )


@dataclass
class RollupReport:
    """Result of a BOM cost roll-up computation.

    Attributes
    ----------
    part_number:           Root part number.
    total_cost:            Rolled-up total cost in the target currency.
    currency:              Target currency code.
    num_unique_parts:      Number of distinct part_number values in the tree.
    depth:                 Maximum depth of the BOM tree (root = 0).
    cost_breakdown_by_node: Mapping of part_number → rolled-up cost in the
                            target currency for every node visited.
    honest_caveat:         Plain-English scope limitation statement.
    """

    part_number: str
    total_cost: float
    currency: str
    num_unique_parts: int
    depth: int
    cost_breakdown_by_node: dict[str, float]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Default FX rates (informational baseline — caller should supply live rates)
# ---------------------------------------------------------------------------

_DEFAULT_FX_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.10,
    "GBP": 1.27,
    "ZAR": 0.054,
    "JPY": 0.0067,
    "CAD": 0.74,
    "AUD": 0.65,
    "CHF": 1.12,
    "CNY": 0.138,
    "INR": 0.012,
}


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def rollup_bom_cost(
    root: "BomNode",
    currency: str = "USD",
    fx_rates: Optional[dict[str, float]] = None,
) -> RollupReport:
    """Compute the rolled-up cost at every assembly node in the BOM tree.

    The algorithm performs a depth-first post-order traversal: children are
    costed before their parents, then the parent's cost is the sum of
    (child_rolled_cost × qty) plus the node's own internal_cost, all
    expressed in the target *currency*.

    Parameters
    ----------
    root:      Root BomNode of the BOM tree.
    currency:  ISO 4217 target currency.  All costs are converted to this
               currency before summation.
    fx_rates:  Dict mapping ISO 4217 code → rate-to-USD (e.g. EUR→1.10 means
               1 EUR = 1.10 USD).  If omitted, a built-in baseline table is
               used.  Supply your own for accurate conversion.

    Returns
    -------
    RollupReport with total_cost, per-node breakdown, depth, unique-part count,
    and an honest caveat string.

    Raises
    ------
    ValueError
        If a cycle is detected in the BOM tree (part_number A → … → A).
    ValueError
        If a required currency is missing from fx_rates.
    ValueError
        If qty for any child is not a positive number.
    """
    if fx_rates is None:
        fx_rates = dict(_DEFAULT_FX_RATES)

    # Validate target currency
    if currency not in fx_rates:
        raise ValueError(
            f"Target currency '{currency}' not found in fx_rates. "
            f"Available: {sorted(fx_rates)}"
        )

    cost_breakdown: dict[str, float] = {}
    unique_parts: set[str] = set()
    max_depth: list[int] = [0]

    # ancestor_stack tracks the path from root to current node for cycle detection
    ancestor_stack: list[str] = []

    def _convert(amount: float, from_currency: str) -> float:
        """Convert *amount* from *from_currency* to target *currency*."""
        if from_currency == currency:
            return amount
        if from_currency not in fx_rates:
            raise ValueError(
                f"Currency '{from_currency}' not found in fx_rates. "
                f"Available: {sorted(fx_rates)}"
            )
        # Convert: amount in from_currency → USD → target currency
        amount_usd = amount * fx_rates[from_currency]
        amount_target = amount_usd / fx_rates[currency]
        return amount_target

    def _recurse(node: "BomNode", depth: int) -> float:
        """Return rolled-up cost of *node* in target currency."""
        if node.part_number in ancestor_stack:
            cycle_path = ancestor_stack + [node.part_number]
            raise ValueError(
                f"Cycle detected in BOM tree: "
                + " -> ".join(cycle_path)
            )

        unique_parts.add(node.part_number)
        if depth > max_depth[0]:
            max_depth[0] = depth

        ancestor_stack.append(node.part_number)

        # Own internal cost (includes unit_cost for purchased leaf parts
        # when internal_cost was not explicitly set — but dataclass default
        # is 0.0; leaf callers should set internal_cost=unit_cost explicitly,
        # or rely on unit_cost being the leaf's own cost via the helper).
        own_cost = _convert(node.internal_cost, node.currency)

        # If no children and internal_cost == 0.0 (default), treat unit_cost
        # as the leaf cost.  This matches APICS "rolled-up cost" for purchased
        # parts where unit_cost is the purchase price.
        if not node.children and node.internal_cost == 0.0:
            own_cost = _convert(node.unit_cost, node.currency)

        children_cost = 0.0
        for child, qty in node.children:
            if qty <= 0:
                raise ValueError(
                    f"Quantity for child '{child.part_number}' under "
                    f"'{node.part_number}' must be > 0, got {qty}"
                )
            child_rolled = _recurse(child, depth + 1)
            children_cost += qty * child_rolled

        rolled = own_cost + children_cost
        cost_breakdown[node.part_number] = rolled

        ancestor_stack.pop()
        return rolled

    total = _recurse(root, 0)

    return RollupReport(
        part_number=root.part_number,
        total_cost=round(total, 6),
        currency=currency,
        num_unique_parts=len(unique_parts),
        depth=max_depth[0],
        cost_breakdown_by_node={k: round(v, 6) for k, v in cost_breakdown.items()},
        honest_caveat=HONEST_CAVEAT,
    )
