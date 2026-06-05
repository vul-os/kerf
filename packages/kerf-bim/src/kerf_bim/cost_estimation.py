"""
kerf_bim.cost_estimation
=========================

5D Cost Estimation engine.

Performs quantity takeoff (area / volume / count) from BIM elements and
multiplies against a unit-cost database to produce a cost rollup by
phase / trade / element category.

Method references:
  RICS NRM 1:2012 — RICS New Rules of Measurement Order of Cost Estimating
  ISO 12006-2:2015 — Organisation of information about construction works
  IFC4 ADD2 TC1   — IfcQuantityArea, IfcQuantityVolume, IfcQuantityCount

Public API
----------
  UnitCostEntry(category, trade, phase, unit, unit_cost, currency)
      A unit-cost rate for a given element category + trade + phase.

  UnitCostDB(entries)
      Lookup database for unit costs.

  QuantityRecord(element_id, category, trade, phase, quantity, unit)
      A measured quantity from a BIM element (IFC QuantitySet equivalent).

  take_off(elements) -> list[QuantityRecord]
      Extract quantities from element dicts (area/volume/count).

  cost_rollup(quantities, db) -> CostRollup
      Multiply quantities by unit costs; group by phase/trade.

  CostRollup
      Holds line items and summary by phase, trade, and category.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Unit-cost database
# ---------------------------------------------------------------------------

@dataclass
class UnitCostEntry:
    """A unit-cost rate for a category + optional trade/phase filter.

    Parameters
    ----------
    category : str
        BIM element category (e.g. 'Wall', 'Slab', 'Column', 'Door').
    trade : str
        Trade/discipline (e.g. 'structural', 'architectural', 'mep').
        Empty string = wildcard (matches any trade).
    phase : str
        Construction phase label (e.g. 'shell', 'fit-out', 'finishes').
        Empty string = wildcard.
    unit : str
        Measurement unit: 'm2' | 'm3' | 'each' | 'lm' (linear metre).
    unit_cost : float
        Cost per unit in the specified currency.
    currency : str
        ISO 4217 currency code (e.g. 'USD', 'ZAR').
    description : str
        Human-readable description of the rate.
    """

    category: str
    unit: str
    unit_cost: float
    trade: str = ""
    phase: str = ""
    currency: str = "USD"
    description: str = ""

    def __post_init__(self):
        valid_units = {"m2", "m3", "each", "lm", "kg", "m"}
        if self.unit not in valid_units:
            raise ValueError(
                f"UnitCostEntry.unit must be one of {sorted(valid_units)}, got '{self.unit}'"
            )
        if self.unit_cost < 0:
            raise ValueError("UnitCostEntry.unit_cost must be >= 0")


@dataclass
class UnitCostDB:
    """Lookup database for unit costs.

    Lookup priority: exact (category + trade + phase) > partial match > wildcard.
    The first matching entry is used.
    """

    entries: List[UnitCostEntry] = field(default_factory=list)

    def lookup(
        self,
        category: str,
        trade: str = "",
        phase: str = "",
    ) -> Optional[UnitCostEntry]:
        """Return the best-matching entry, or None."""
        # Priority: exact match > category+trade > category+phase > category only
        candidates = [e for e in self.entries if e.category == category]
        if not candidates:
            return None

        # Exact
        for e in candidates:
            if (e.trade == trade or e.trade == "") and (e.phase == phase or e.phase == ""):
                if (e.trade == trade) and (e.phase == phase):
                    return e

        # Trade matches
        for e in candidates:
            if e.trade == trade and (e.phase == "" or e.phase == phase):
                return e

        # Phase matches
        for e in candidates:
            if e.phase == phase and (e.trade == "" or e.trade == trade):
                return e

        # Wildcard (any with empty trade+phase)
        for e in candidates:
            if e.trade == "" and e.phase == "":
                return e

        return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Quantity records
# ---------------------------------------------------------------------------

@dataclass
class QuantityRecord:
    """A single measured quantity from a BIM element.

    Maps to IFC4 IfcPhysicalQuantity (IfcQuantityArea / IfcQuantityVolume /
    IfcQuantityCount).
    """

    element_id: str
    category: str
    quantity: float
    unit: str          # 'm2' | 'm3' | 'each' | 'lm'
    trade: str = ""
    phase: str = ""
    description: str = ""


# ---------------------------------------------------------------------------
# Quantity take-off
# ---------------------------------------------------------------------------

_AREA_KEYS = ("gross_floor_area", "net_floor_area", "surface_area", "area",
              "face_area", "wall_area")
_VOLUME_KEYS = ("volume", "gross_volume", "net_volume")
_LENGTH_KEYS = ("length",)

# Category → preferred unit mapping
_CAT_UNIT: Dict[str, str] = {
    "Wall":         "m2",
    "Slab":         "m2",
    "Floor":        "m2",
    "Roof":         "m2",
    "Ceiling":      "m2",
    "Column":       "m3",
    "Beam":         "m3",
    "Foundation":   "m3",
    "Pile":         "m3",
    "Door":         "each",
    "Window":       "each",
    "Stair":        "each",
    "Railing":      "lm",
    "MEP":          "each",
    "Furniture":    "each",
    "Generic":      "each",
}


def _extract_quantity(element: dict) -> tuple[float, str]:
    """Extract the primary quantity and unit from an element dict.

    Returns (quantity, unit). Falls back to 1.0 / 'each' if nothing found.
    """
    category = element.get("category", "Generic")
    preferred_unit = _CAT_UNIT.get(category, "each")

    if preferred_unit == "m2":
        for key in _AREA_KEYS:
            v = element.get(key) or element.get("properties", {}).get(key)
            if isinstance(v, (int, float)) and v > 0:
                return float(v), "m2"
        # Try deriving area from dimensions
        w = element.get("width") or element.get("properties", {}).get("width", 0)
        h = element.get("height") or element.get("properties", {}).get("height", 0)
        l = element.get("length") or element.get("properties", {}).get("length", 0)
        if w and h:
            return float(w) * float(h), "m2"
        if l and h:
            return float(l) * float(h), "m2"

    if preferred_unit == "m3":
        for key in _VOLUME_KEYS:
            v = element.get(key) or element.get("properties", {}).get(key)
            if isinstance(v, (int, float)) and v > 0:
                return float(v), "m3"

    if preferred_unit == "lm":
        for key in _LENGTH_KEYS:
            v = element.get(key) or element.get("properties", {}).get(key)
            if isinstance(v, (int, float)) and v > 0:
                return float(v), "lm"

    return 1.0, "each"


def take_off(elements: List[dict]) -> List[QuantityRecord]:
    """Extract quantity records from a list of BIM element dicts.

    Each element dict should have at minimum:
      - 'id': element identifier
      - 'category': BIM category string
    Optional dimension fields are used for area/volume computation.

    Parameters
    ----------
    elements : list[dict]

    Returns
    -------
    List of :class:`QuantityRecord`.
    """
    records: List[QuantityRecord] = []
    for el in elements:
        eid = str(el.get("id", el.get("element_id", "")))
        if not eid:
            continue
        category = str(el.get("category", "Generic"))
        trade = str(el.get("trade", el.get("discipline", "")))
        phase = str(el.get("phase", el.get("construction_phase", "")))

        qty, unit = _extract_quantity(el)
        records.append(QuantityRecord(
            element_id=eid,
            category=category,
            quantity=qty,
            unit=unit,
            trade=trade,
            phase=phase,
            description=str(el.get("name", el.get("type", ""))),
        ))

    return records


# ---------------------------------------------------------------------------
# Cost line item and rollup
# ---------------------------------------------------------------------------

@dataclass
class CostLineItem:
    """A single priced line in the cost estimate."""

    element_id: str
    category: str
    trade: str
    phase: str
    description: str
    quantity: float
    unit: str
    unit_cost: float
    total_cost: float
    currency: str


@dataclass
class CostRollup:
    """Aggregated cost estimate.

    Attributes
    ----------
    line_items : list[CostLineItem]
        One item per quantity record that matched a unit cost.
    unpriced : list[QuantityRecord]
        Records with no matching unit-cost entry.
    total_cost : float
        Sum of all line item costs.
    by_phase : dict[str, float]
        Cost grouped by phase label.
    by_trade : dict[str, float]
        Cost grouped by trade label.
    by_category : dict[str, float]
        Cost grouped by element category.
    currency : str
        Currency of all costs (from unit-cost DB entries).
    """

    line_items: List[CostLineItem] = field(default_factory=list)
    unpriced: List[QuantityRecord] = field(default_factory=list)
    total_cost: float = 0.0
    by_phase: Dict[str, float] = field(default_factory=dict)
    by_trade: Dict[str, float] = field(default_factory=dict)
    by_category: Dict[str, float] = field(default_factory=dict)
    currency: str = "USD"


def cost_rollup(
    quantities: List[QuantityRecord],
    db: UnitCostDB,
) -> CostRollup:
    """Multiply quantities by unit costs and aggregate.

    RICS NRM 1:2012 method: each quantity record is priced individually;
    unpriced records are listed separately; totals are grouped by phase,
    trade, and category.

    Parameters
    ----------
    quantities : list[QuantityRecord]
    db : UnitCostDB

    Returns
    -------
    :class:`CostRollup`
    """
    rollup = CostRollup()
    currencies_seen: set = set()

    for qr in quantities:
        entry = db.lookup(qr.category, qr.trade, qr.phase)
        if entry is None:
            rollup.unpriced.append(qr)
            continue

        total = qr.quantity * entry.unit_cost
        currencies_seen.add(entry.currency)

        item = CostLineItem(
            element_id=qr.element_id,
            category=qr.category,
            trade=qr.trade,
            phase=qr.phase,
            description=qr.description,
            quantity=qr.quantity,
            unit=qr.unit,
            unit_cost=entry.unit_cost,
            total_cost=total,
            currency=entry.currency,
        )
        rollup.line_items.append(item)
        rollup.total_cost += total

        phase_key = qr.phase or "(unphased)"
        trade_key = qr.trade or "(unassigned)"
        rollup.by_phase[phase_key] = rollup.by_phase.get(phase_key, 0.0) + total
        rollup.by_trade[trade_key] = rollup.by_trade.get(trade_key, 0.0) + total
        rollup.by_category[qr.category] = rollup.by_category.get(qr.category, 0.0) + total

    if currencies_seen:
        rollup.currency = next(iter(currencies_seen))

    # Round totals
    rollup.total_cost = round(rollup.total_cost, 2)
    rollup.by_phase = {k: round(v, 2) for k, v in rollup.by_phase.items()}
    rollup.by_trade = {k: round(v, 2) for k, v in rollup.by_trade.items()}
    rollup.by_category = {k: round(v, 2) for k, v in rollup.by_category.items()}

    return rollup


# ---------------------------------------------------------------------------
# Default unit-cost database (indicative USD rates, RICS NRM 1 basis)
# ---------------------------------------------------------------------------

def default_unit_cost_db(currency: str = "USD") -> UnitCostDB:
    """Return a built-in indicative unit-cost database.

    Rates are order-of-magnitude for feasibility studies per RICS NRM 1:2012.
    Users should replace with project-specific rates for detailed estimates.
    """
    entries = [
        UnitCostEntry("Wall",       "m2",   250.0,  trade="architectural", currency=currency, description="External/party wall — blockwork + plaster"),
        UnitCostEntry("Wall",       "m2",   180.0,  trade="",              currency=currency, description="Internal wall — stud/plasterboard"),
        UnitCostEntry("Slab",       "m2",   320.0,  trade="structural",    currency=currency, description="Reinforced concrete slab"),
        UnitCostEntry("Floor",      "m2",   280.0,  trade="structural",    currency=currency, description="Ground-bearing slab"),
        UnitCostEntry("Roof",       "m2",   420.0,  trade="architectural", currency=currency, description="Flat roof incl. waterproofing"),
        UnitCostEntry("Column",     "m3",  1800.0,  trade="structural",    currency=currency, description="RC column"),
        UnitCostEntry("Beam",       "m3",  1600.0,  trade="structural",    currency=currency, description="RC beam"),
        UnitCostEntry("Foundation", "m3",   900.0,  trade="structural",    currency=currency, description="Strip/pad foundation"),
        UnitCostEntry("Door",       "each", 1200.0, trade="architectural", currency=currency, description="Timber door + frame"),
        UnitCostEntry("Window",     "each", 1800.0, trade="architectural", currency=currency, description="Double-glazed aluminium window"),
        UnitCostEntry("Stair",      "each", 8500.0, trade="structural",    currency=currency, description="Precast concrete stair flight"),
        UnitCostEntry("Railing",    "lm",    650.0, trade="architectural", currency=currency, description="Stainless steel railing"),
        UnitCostEntry("Ceiling",    "m2",    120.0, trade="architectural", currency=currency, description="Suspended ceiling tile system"),
        UnitCostEntry("MEP",        "each",  500.0, trade="mep",           currency=currency, description="MEP component allowance"),
        UnitCostEntry("Generic",    "each",  200.0, trade="",              currency=currency, description="Generic element allowance"),
    ]
    return UnitCostDB(entries=entries)


__all__ = [
    "UnitCostEntry",
    "UnitCostDB",
    "QuantityRecord",
    "CostLineItem",
    "CostRollup",
    "take_off",
    "cost_rollup",
    "default_unit_cost_db",
]
