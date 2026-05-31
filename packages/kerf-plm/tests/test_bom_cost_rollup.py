"""
tests/test_bom_cost_rollup.py
==============================

Validation tests for kerf_plm.bom_cost_rollup.

Per ISO 10303-44:2021 (STEP AP44 product structure) and the APICS dictionary
"rolled-up cost" definition.

Test matrix
-----------
BC-01  Leaf-only node: total_cost == unit_cost (own cost, no children).
BC-02  Two-level BOM: root + 3 children, qty=2 each.
       total = root_internal + 2*c1 + 2*c2 + 2*c3.
BC-03  Three-level BOM: root → sub-assembly → leaf parts.
BC-04  Currency mix: child in EUR, root in USD — FX conversion applied.
BC-05  Cycle detection A→B→A raises ValueError.
BC-06  Empty children (leaf): rolls up internal_cost only.
BC-07  Quantity fractional: 2.5 units of a child.
BC-08  Internal_cost used for assembly node (not unit_cost when children present).
BC-09  Multi-currency tree: some nodes EUR, some ZAR, root USD.
BC-10  Missing target currency in fx_rates → ValueError.
BC-11  Missing source currency in fx_rates → ValueError.
BC-12  Deeper cycle: A→B→C→A raises ValueError with full path.
BC-13  Negative unit_cost raises ValueError at construction.
BC-14  num_unique_parts count is correct for a tree with shared part numbers
       on different branches (counted once per distinct part_number).
BC-15  depth field reflects max depth (root = 0, first level = 1, etc.).
BC-16  cost_breakdown_by_node contains every visited node's rolled-up cost.
BC-17  qty=0 raises ValueError.
BC-18  Re-export: BomNode, RollupReport, rollup_bom_cost importable from kerf_plm.
"""

from __future__ import annotations

import pytest

from kerf_plm.bom_cost_rollup import BomNode, RollupReport, rollup_bom_cost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def leaf(part_number: str, name: str, unit_cost: float, currency: str = "USD") -> BomNode:
    """Convenience: purchased leaf part (no children, unit_cost = cost)."""
    return BomNode(
        part_number=part_number,
        name=name,
        unit_cost=unit_cost,
        currency=currency,
        children=[],
        internal_cost=0.0,  # triggers leaf fallback in rollup
    )


def assembly(
    part_number: str,
    name: str,
    internal_cost: float,
    currency: str,
    children: list[tuple[BomNode, float]],
) -> BomNode:
    """Convenience: assembly node with explicit internal_cost and children."""
    return BomNode(
        part_number=part_number,
        name=name,
        unit_cost=0.0,
        currency=currency,
        children=children,
        internal_cost=internal_cost,
    )


DEFAULT_FX = {"USD": 1.0, "EUR": 1.10, "ZAR": 0.054}


# ---------------------------------------------------------------------------
# BC-01  Leaf-only node
# ---------------------------------------------------------------------------

def test_leaf_only_cost_equals_unit_cost():
    """BC-01: A single leaf's rolled-up cost == unit_cost."""
    node = leaf("PN-001", "Bearing", 12.50)
    report = rollup_bom_cost(node, currency="USD")
    assert report.part_number == "PN-001"
    assert report.total_cost == pytest.approx(12.50, rel=1e-6)
    assert report.currency == "USD"
    assert report.num_unique_parts == 1
    assert report.depth == 0


# ---------------------------------------------------------------------------
# BC-02  Two-level BOM: root + 3 children, qty=2 each
# ---------------------------------------------------------------------------

def test_two_level_bom_three_children():
    """BC-02: root_internal + 2*child1 + 2*child2 + 2*child3."""
    c1 = leaf("PN-C1", "Bolt M6", 0.50)
    c2 = leaf("PN-C2", "Nut M6", 0.20)
    c3 = leaf("PN-C3", "Washer", 0.05)
    root = assembly(
        "PN-ROOT", "Bracket Assembly", 5.00, "USD",
        [(c1, 2.0), (c2, 2.0), (c3, 2.0)],
    )
    report = rollup_bom_cost(root, currency="USD")
    expected = 5.00 + 2 * 0.50 + 2 * 0.20 + 2 * 0.05
    assert report.total_cost == pytest.approx(expected, rel=1e-6)
    assert report.depth == 1
    assert report.num_unique_parts == 4  # root + 3 children


# ---------------------------------------------------------------------------
# BC-03  Three-level BOM
# ---------------------------------------------------------------------------

def test_three_level_bom():
    """BC-03: root → sub → leaf: total = root_ic + qty_sub*(sub_ic + qty_leaf*leaf_uc)."""
    leaf_node = leaf("PN-L1", "Pin", 1.00)
    sub = assembly("PN-SUB", "Pin Housing", 3.00, "USD", [(leaf_node, 4.0)])
    root = assembly("PN-TOP", "Module", 10.00, "USD", [(sub, 2.0)])
    # sub_cost = 3.00 + 4*1.00 = 7.00
    # root_cost = 10.00 + 2*7.00 = 24.00
    report = rollup_bom_cost(root)
    assert report.total_cost == pytest.approx(24.00, rel=1e-6)
    assert report.depth == 2
    assert report.num_unique_parts == 3
    assert report.cost_breakdown_by_node["PN-SUB"] == pytest.approx(7.00, rel=1e-6)
    assert report.cost_breakdown_by_node["PN-TOP"] == pytest.approx(24.00, rel=1e-6)


# ---------------------------------------------------------------------------
# BC-04  Currency mix: child in EUR, root in USD
# ---------------------------------------------------------------------------

def test_currency_mix_eur_to_usd():
    """BC-04: EUR child cost converted to USD at fx 1 EUR = 1.10 USD."""
    fx = {"USD": 1.0, "EUR": 1.10}
    eur_child = leaf("PN-EU1", "German Bearing", 10.00, currency="EUR")
    root = assembly("PN-USA1", "Assembly USD", 5.00, "USD", [(eur_child, 3.0)])
    # child_in_usd = 10.00 * 1.10 / 1.0 = 11.00
    # total = 5.00 + 3 * 11.00 = 38.00
    report = rollup_bom_cost(root, currency="USD", fx_rates=fx)
    assert report.total_cost == pytest.approx(38.00, rel=1e-6)
    assert report.currency == "USD"


# ---------------------------------------------------------------------------
# BC-05  Cycle detection A→B→A
# ---------------------------------------------------------------------------

def test_cycle_detection_simple():
    """BC-05: A→B→A must raise ValueError naming both nodes."""
    # Build manually to create a cycle (bypass __post_init__ on children)
    node_a = BomNode(part_number="PN-A", name="A", unit_cost=1.0, currency="USD", children=[])
    node_b = BomNode(part_number="PN-B", name="B", unit_cost=1.0, currency="USD", children=[])
    # Create cycle: A's children = [(B, 1)], B's children = [(A, 1)]
    object.__setattr__(node_a, "children", [(node_b, 1.0)])
    object.__setattr__(node_b, "children", [(node_a, 1.0)])
    with pytest.raises(ValueError, match="Cycle detected"):
        rollup_bom_cost(node_a)


# ---------------------------------------------------------------------------
# BC-06  Empty children leaf uses internal_cost only
# ---------------------------------------------------------------------------

def test_empty_children_uses_internal_cost():
    """BC-06: Node with children=[] and explicit internal_cost uses that cost."""
    node = BomNode(
        part_number="PN-IC1",
        name="Process Cost Part",
        unit_cost=0.0,
        currency="USD",
        children=[],
        internal_cost=7.77,
    )
    report = rollup_bom_cost(node)
    assert report.total_cost == pytest.approx(7.77, rel=1e-6)


# ---------------------------------------------------------------------------
# BC-07  Fractional quantity
# ---------------------------------------------------------------------------

def test_fractional_quantity():
    """BC-07: qty=2.5 applies correctly to child cost."""
    child = leaf("PN-F1", "Solder Paste", 4.00)
    root = assembly("PN-F-ROOT", "PCB Assembly", 0.0, "USD", [(child, 2.5)])
    # total = 0 + 2.5 * 4.00 = 10.00
    report = rollup_bom_cost(root)
    assert report.total_cost == pytest.approx(10.00, rel=1e-6)


# ---------------------------------------------------------------------------
# BC-08  Assembly node uses internal_cost, not unit_cost
# ---------------------------------------------------------------------------

def test_assembly_uses_internal_cost_not_unit_cost():
    """BC-08: For an assembly with children, internal_cost is used (not unit_cost)."""
    child = leaf("PN-CH1", "Component", 1.00)
    # unit_cost=99.0 should be ignored when internal_cost and children are set
    asm = BomNode(
        part_number="PN-ASM1",
        name="Sub-assembly",
        unit_cost=99.0,
        currency="USD",
        children=[(child, 2.0)],
        internal_cost=5.00,
    )
    report = rollup_bom_cost(asm)
    # expected: 5.00 + 2*1.00 = 7.00, NOT 99.0 + ...
    assert report.total_cost == pytest.approx(7.00, rel=1e-6)


# ---------------------------------------------------------------------------
# BC-09  Multi-currency tree (EUR + ZAR + USD)
# ---------------------------------------------------------------------------

def test_multi_currency_tree():
    """BC-09: Three-currency tree all rolled to USD correctly."""
    fx = {"USD": 1.0, "EUR": 1.10, "ZAR": 0.054}
    eur_leaf = leaf("PN-M1", "EU Widget", 10.0, currency="EUR")   # → 11.0 USD
    zar_leaf = leaf("PN-M2", "SA Widget", 100.0, currency="ZAR")  # → 5.40 USD
    root = assembly("PN-M-ROOT", "Global Asm", 2.0, "USD", [
        (eur_leaf, 1.0),
        (zar_leaf, 2.0),
    ])
    # total = 2.0 + 1*11.0 + 2*5.40 = 2.0 + 11.0 + 10.80 = 23.80
    report = rollup_bom_cost(root, currency="USD", fx_rates=fx)
    assert report.total_cost == pytest.approx(23.80, rel=1e-5)


# ---------------------------------------------------------------------------
# BC-10  Missing target currency → ValueError
# ---------------------------------------------------------------------------

def test_missing_target_currency_raises():
    """BC-10: Target currency not in fx_rates raises ValueError."""
    node = leaf("PN-ERR1", "Part", 10.0, currency="USD")
    with pytest.raises(ValueError, match="'GBP' not found in fx_rates"):
        rollup_bom_cost(node, currency="GBP", fx_rates={"USD": 1.0})


# ---------------------------------------------------------------------------
# BC-11  Missing source currency → ValueError
# ---------------------------------------------------------------------------

def test_missing_source_currency_raises():
    """BC-11: Node currency not in fx_rates raises ValueError during recursion."""
    gbp_child = leaf("PN-GBP1", "UK Part", 5.0, currency="GBP")
    root = assembly("PN-RR", "Root", 0.0, "USD", [(gbp_child, 1.0)])
    with pytest.raises(ValueError, match="'GBP' not found in fx_rates"):
        rollup_bom_cost(root, currency="USD", fx_rates={"USD": 1.0})


# ---------------------------------------------------------------------------
# BC-12  Deeper cycle A→B→C→A
# ---------------------------------------------------------------------------

def test_cycle_detection_three_node():
    """BC-12: Three-node cycle A→B→C→A raises ValueError."""
    node_a = BomNode(part_number="CY-A", name="A", unit_cost=1.0, currency="USD", children=[])
    node_b = BomNode(part_number="CY-B", name="B", unit_cost=1.0, currency="USD", children=[])
    node_c = BomNode(part_number="CY-C", name="C", unit_cost=1.0, currency="USD", children=[])
    object.__setattr__(node_a, "children", [(node_b, 1.0)])
    object.__setattr__(node_b, "children", [(node_c, 1.0)])
    object.__setattr__(node_c, "children", [(node_a, 1.0)])
    with pytest.raises(ValueError, match="Cycle detected"):
        rollup_bom_cost(node_a)


# ---------------------------------------------------------------------------
# BC-13  Negative unit_cost raises ValueError at construction
# ---------------------------------------------------------------------------

def test_negative_unit_cost_raises():
    """BC-13: Negative unit_cost is rejected at dataclass construction."""
    with pytest.raises(ValueError, match="unit_cost must be >= 0"):
        BomNode(part_number="PN-NEG", name="Bad Part", unit_cost=-1.0, currency="USD")


# ---------------------------------------------------------------------------
# BC-14  num_unique_parts counts distinct part_numbers
# ---------------------------------------------------------------------------

def test_num_unique_parts():
    """BC-14: Same part_number on two branches is counted once."""
    shared = leaf("PN-SHARED", "Common Fastener", 0.10)
    branch_a = assembly("PN-BA", "Branch A", 1.0, "USD", [(shared, 3.0)])
    branch_b = assembly("PN-BB", "Branch B", 2.0, "USD", [(shared, 5.0)])
    root = assembly("PN-R", "Root", 0.0, "USD", [(branch_a, 1.0), (branch_b, 1.0)])
    report = rollup_bom_cost(root)
    # Unique part_numbers: PN-R, PN-BA, PN-BB, PN-SHARED (4)
    assert report.num_unique_parts == 4


# ---------------------------------------------------------------------------
# BC-15  depth field
# ---------------------------------------------------------------------------

def test_depth_field():
    """BC-15: depth == max BOM depth below root (root=0)."""
    d2 = leaf("PN-D2", "Depth 2", 1.0)
    d1 = assembly("PN-D1", "Depth 1", 0.0, "USD", [(d2, 1.0)])
    root = assembly("PN-D0", "Root", 0.0, "USD", [(d1, 1.0)])
    report = rollup_bom_cost(root)
    assert report.depth == 2


# ---------------------------------------------------------------------------
# BC-16  cost_breakdown_by_node completeness
# ---------------------------------------------------------------------------

def test_cost_breakdown_contains_all_nodes():
    """BC-16: cost_breakdown_by_node contains every part_number in the tree."""
    c1 = leaf("PN-BB1", "Bolt", 0.30)
    c2 = leaf("PN-BB2", "Nut", 0.10)
    asm = assembly("PN-BBA", "Fastener Kit", 1.0, "USD", [(c1, 4.0), (c2, 4.0)])
    report = rollup_bom_cost(asm)
    assert "PN-BB1" in report.cost_breakdown_by_node
    assert "PN-BB2" in report.cost_breakdown_by_node
    assert "PN-BBA" in report.cost_breakdown_by_node
    # Verify asm breakdown == total
    assert report.cost_breakdown_by_node["PN-BBA"] == pytest.approx(report.total_cost)


# ---------------------------------------------------------------------------
# BC-17  qty=0 raises ValueError
# ---------------------------------------------------------------------------

def test_zero_qty_raises():
    """BC-17: qty=0 is invalid and must raise ValueError."""
    child = leaf("PN-Z1", "Zero Qty Part", 5.0)
    root = assembly("PN-Z-ROOT", "Root", 0.0, "USD", [(child, 0.0)])
    with pytest.raises(ValueError, match="must be > 0"):
        rollup_bom_cost(root)


# ---------------------------------------------------------------------------
# BC-18  Re-export from kerf_plm top-level
# ---------------------------------------------------------------------------

def test_reexport_from_kerf_plm():
    """BC-18: BomNode, RollupReport, rollup_bom_cost importable from kerf_plm."""
    from kerf_plm import BomNode as _BN, RollupReport as _RR, rollup_bom_cost as _rbc
    assert _BN is BomNode
    assert _RR is RollupReport
    assert _rbc is rollup_bom_cost


# ---------------------------------------------------------------------------
# BC-19  Honest caveat is non-empty string in report
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    """BC-19: RollupReport includes a non-empty honest_caveat string."""
    node = leaf("PN-HC1", "Part", 1.0)
    report = rollup_bom_cost(node)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 20  # substantive, not a placeholder


# ---------------------------------------------------------------------------
# BC-20  Default fx_rates used when not supplied
# ---------------------------------------------------------------------------

def test_default_fx_rates_applied():
    """BC-20: When fx_rates is None, the built-in table allows EUR→USD conversion."""
    eur_leaf = leaf("PN-DEF1", "EU Part", 10.0, currency="EUR")
    root = assembly("PN-DEF-ROOT", "Assembly", 0.0, "USD", [(eur_leaf, 1.0)])
    # Built-in EUR rate is 1.10; so 10 EUR = 11.00 USD
    report = rollup_bom_cost(root, currency="USD", fx_rates=None)
    assert report.total_cost == pytest.approx(11.00, rel=1e-5)
