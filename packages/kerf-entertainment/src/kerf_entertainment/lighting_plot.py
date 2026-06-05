"""
Theatrical lighting plot + DMX patch engine.

Implements:
  • Fixture instances (type, position, focus, channel, dimmer, color/gel, accessories)
  • DMX universe/address patching with conflict detection (overlapping footprints)
  • Channel/circuit schedule — which dimmer feeds which fixture(s)
  • Instrument count + electrical load (per-fixture wattage → total per circuit)
  • Patch sheet export (sorted by dimmer / channel / universe)
  • Magic-sheet data (layout grid of fixtures keyed by channel)

DMX addressing
--------------
Each fixture occupies a consecutive block of DMX addresses starting at
`dmx_address` within `dmx_universe`.  For single-parameter (intensity-only)
dimmers the footprint is 1.  Moving lights and multi-cell fixtures use wider
footprints.  Addresses are 1–512 per universe (per DMX512 standard).

References
----------
USITT DMX512-A (ANSI E1.11-2008)
PLASA E1.20 RDM (Remote Device Management)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FixtureType:
    """
    A fixture type (instrument) from the user's library.

    Parameters
    ----------
    type_name : str
        Human-readable name, e.g. 'ETC Source Four 36°'.
    wattage : float
        Power consumption (W).  Use 0 for LED fixtures with unknown draw.
    dmx_footprint : int
        Number of consecutive DMX addresses consumed (default 1 = single-channel
        dimmer, higher for moving lights / LED pars).
    amperage : float
        Rated current at 120 V (A).  If 0, computed from wattage / 120.
    weight_kg : float
        Fixture weight in kg (used for rigging load calcs).
    accessory_slots : int
        Number of accessory slots (gobo, color, iris, etc.).
    """
    type_name: str = ""
    wattage: float = 575.0
    dmx_footprint: int = 1
    amperage: float = 0.0
    weight_kg: float = 4.5
    accessory_slots: int = 2

    def __post_init__(self):
        if self.amperage == 0.0 and self.wattage > 0:
            self.amperage = self.wattage / 120.0


@dataclass
class FixtureInstance:
    """
    A single instrument placed in the lighting plot.

    Parameters
    ----------
    fixture_id : str
        Unique identifier for this instance (e.g. '101', 'L-A-3').
    fixture_type : FixtureType
        Reference to the instrument type.
    position : str
        Hanging position label (e.g. 'FOH Boom A', 'Pipe 1').
    unit_number : int
        Unit number on the position (1-based).
    x_ft, y_ft, z_ft : float
        Spatial coordinates in feet (stage coordinate system: X = SL→SR,
        Y = downstage→upstage, Z = height above stage deck).
    channel : int
        Control channel (1-based, within the patch/console universe).
    dimmer : int
        Physical dimmer/circuit number (1-based).
    dmx_universe : int
        DMX universe (0-based; universe 1 = index 0).
    dmx_address : int
        Starting DMX address within the universe (1–512).
    color : str
        Gel or dichroic filter (e.g. 'R02', 'L201', 'no color').
    focus_note : str
        Focus target description (e.g. 'CS pool', 'DSL special').
    accessories : list[str]
        Installed accessories (gobo, iris, top hat, barn doors, etc.).
    note : str
        Free-form note for patch sheet.
    """
    fixture_id: str = ""
    fixture_type: FixtureType = field(default_factory=FixtureType)
    position: str = ""
    unit_number: int = 1
    x_ft: float = 0.0
    y_ft: float = 0.0
    z_ft: float = 0.0
    channel: int = 0
    dimmer: int = 0
    dmx_universe: int = 0
    dmx_address: int = 1
    color: str = "no color"
    focus_note: str = ""
    accessories: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def wattage(self) -> float:
        return self.fixture_type.wattage

    @property
    def weight_kg(self) -> float:
        return self.fixture_type.weight_kg

    @property
    def dmx_footprint(self) -> int:
        return self.fixture_type.dmx_footprint

    @property
    def dmx_end_address(self) -> int:
        """Last DMX address consumed by this fixture (inclusive)."""
        return self.dmx_address + self.dmx_footprint - 1


# ---------------------------------------------------------------------------
# DMX patch + conflict detection
# ---------------------------------------------------------------------------

@dataclass
class DmxConflict:
    """A DMX address-range overlap between two fixtures."""
    universe: int
    address_range: tuple[int, int]   # (start, end) inclusive — overlapping region
    fixture_a: str
    fixture_b: str
    message: str


def check_dmx_conflicts(fixtures: list[FixtureInstance]) -> list[DmxConflict]:
    """
    Detect DMX address conflicts (overlapping footprints within the same universe).

    Two fixtures conflict if their address ranges overlap in the same universe:
        [addr_a, addr_a + footprint_a - 1] ∩ [addr_b, addr_b + footprint_b - 1] ≠ ∅

    Parameters
    ----------
    fixtures : list[FixtureInstance]

    Returns
    -------
    list[DmxConflict]
        One entry per conflicting pair.  Empty list means no conflicts.
    """
    conflicts: list[DmxConflict] = []

    # Group by universe
    by_universe: dict[int, list[FixtureInstance]] = {}
    for f in fixtures:
        by_universe.setdefault(f.dmx_universe, []).append(f)

    for universe, group in by_universe.items():
        # Sort by start address for O(n log n) sweep
        sorted_group = sorted(group, key=lambda x: x.dmx_address)
        for i in range(len(sorted_group)):
            a = sorted_group[i]
            for j in range(i + 1, len(sorted_group)):
                b = sorted_group[j]
                # If b starts after a ends, no more overlaps possible
                if b.dmx_address > a.dmx_end_address:
                    break
                # Overlap exists
                overlap_start = max(a.dmx_address, b.dmx_address)
                overlap_end = min(a.dmx_end_address, b.dmx_end_address)
                conflicts.append(DmxConflict(
                    universe=universe,
                    address_range=(overlap_start, overlap_end),
                    fixture_a=a.fixture_id,
                    fixture_b=b.fixture_id,
                    message=(
                        f"Universe {universe}: fixture '{a.fixture_id}' "
                        f"(addr {a.dmx_address}–{a.dmx_end_address}) overlaps "
                        f"'{b.fixture_id}' (addr {b.dmx_address}–{b.dmx_end_address}) "
                        f"at addresses {overlap_start}–{overlap_end}"
                    ),
                ))

    return conflicts


# ---------------------------------------------------------------------------
# Circuit / dimmer schedule
# ---------------------------------------------------------------------------

@dataclass
class CircuitRow:
    """One row in the circuit/dimmer schedule."""
    dimmer: int
    circuit: int                # same as dimmer in simple rigs; separate in patchable systems
    fixtures: list[str]         # fixture_ids on this circuit
    total_wattage: float        # sum of fixture wattages
    total_amperage: float       # total_wattage / 120 (North-America) or / 230 (EU)
    channels: list[int]         # control channels on this dimmer
    overloaded: bool            # True if total_wattage > dimmer_capacity_W
    overload_margin_W: float    # positive = headroom, negative = overload


def circuit_schedule(
    fixtures: list[FixtureInstance],
    dimmer_capacity_W: float = 2400.0,
    supply_voltage: float = 120.0,
) -> list[CircuitRow]:
    """
    Build the circuit/dimmer schedule: group fixtures by dimmer, sum wattage,
    and flag overloads.

    Parameters
    ----------
    fixtures : list[FixtureInstance]
    dimmer_capacity_W : float
        Rated capacity of each dimmer (W).  Default 2400 W (20 A × 120 V).
    supply_voltage : float
        Mains voltage for amperage calculation.  Default 120 V.

    Returns
    -------
    list[CircuitRow]  sorted by dimmer number.
    """
    grouped: dict[int, list[FixtureInstance]] = {}
    for f in fixtures:
        grouped.setdefault(f.dimmer, []).append(f)

    rows: list[CircuitRow] = []
    for dimmer, group in sorted(grouped.items()):
        total_W = sum(f.wattage for f in group)
        total_A = total_W / supply_voltage if supply_voltage > 0 else 0.0
        channels = sorted({f.channel for f in group if f.channel > 0})
        overload_margin = dimmer_capacity_W - total_W
        rows.append(CircuitRow(
            dimmer=dimmer,
            circuit=dimmer,
            fixtures=[f.fixture_id for f in group],
            total_wattage=total_W,
            total_amperage=total_A,
            channels=channels,
            overloaded=(overload_margin < 0),
            overload_margin_W=overload_margin,
        ))

    return rows


# ---------------------------------------------------------------------------
# Patch sheet export
# ---------------------------------------------------------------------------

@dataclass
class PatchRow:
    """One row in the formatted patch sheet."""
    channel: int
    dimmer: int
    fixture_ids: list[str]
    position: str
    unit_number: int
    dmx_universe: int
    dmx_address: int
    dmx_end_address: int
    fixture_type: str
    wattage: float
    color: str
    focus_note: str
    accessories: list[str]
    note: str


def patch_sheet(
    fixtures: list[FixtureInstance],
    sort_by: str = "channel",
) -> list[PatchRow]:
    """
    Generate a patch sheet — one row per fixture instance, sortable by
    channel, dimmer, or universe/address.

    Parameters
    ----------
    fixtures : list[FixtureInstance]
    sort_by : str
        One of 'channel', 'dimmer', 'universe', 'position'.

    Returns
    -------
    list[PatchRow]  sorted appropriately.
    """
    def _key(f: FixtureInstance):
        if sort_by == "channel":
            return (f.channel, f.dimmer, f.fixture_id)
        if sort_by == "dimmer":
            return (f.dimmer, f.channel, f.fixture_id)
        if sort_by == "universe":
            return (f.dmx_universe, f.dmx_address, f.fixture_id)
        # position
        return (f.position, f.unit_number)

    rows = []
    for f in sorted(fixtures, key=_key):
        rows.append(PatchRow(
            channel=f.channel,
            dimmer=f.dimmer,
            fixture_ids=[f.fixture_id],
            position=f.position,
            unit_number=f.unit_number,
            dmx_universe=f.dmx_universe,
            dmx_address=f.dmx_address,
            dmx_end_address=f.dmx_end_address,
            fixture_type=f.fixture_type.type_name,
            wattage=f.wattage,
            color=f.color,
            focus_note=f.focus_note,
            accessories=f.accessories,
            note=f.note,
        ))
    return rows


# ---------------------------------------------------------------------------
# Magic-sheet data
# ---------------------------------------------------------------------------

@dataclass
class MagicSheetEntry:
    """One cell in the magic-sheet grid."""
    channel: int
    fixture_type: str
    color: str
    position: str
    focus_note: str
    x_ft: float
    y_ft: float


def magic_sheet(fixtures: list[FixtureInstance]) -> list[MagicSheetEntry]:
    """
    Return magic-sheet data: one entry per unique channel (or per fixture if
    multiple fixtures share a channel), sorted by channel.

    A magic sheet is a simplified, channel-centric layout used by operators
    during focus and cue programming.
    """
    entries: list[MagicSheetEntry] = []
    for f in sorted(fixtures, key=lambda x: (x.channel, x.fixture_id)):
        entries.append(MagicSheetEntry(
            channel=f.channel,
            fixture_type=f.fixture_type.type_name,
            color=f.color,
            position=f.position,
            focus_note=f.focus_note,
            x_ft=f.x_ft,
            y_ft=f.y_ft,
        ))
    return entries


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

@dataclass
class LightingPlotSummary:
    """High-level summary of the lighting plot."""
    total_fixtures: int
    fixture_counts_by_type: dict[str, int]
    total_wattage: float
    total_amperage: float           # at supply_voltage
    universes_used: list[int]
    dmx_conflicts: list[DmxConflict]
    circuit_rows: list[CircuitRow]
    overloaded_circuits: list[int]  # dimmer numbers
    supply_voltage: float


def lighting_plot_summary(
    fixtures: list[FixtureInstance],
    dimmer_capacity_W: float = 2400.0,
    supply_voltage: float = 120.0,
) -> LightingPlotSummary:
    """
    Compute the full summary of a lighting plot.

    Parameters
    ----------
    fixtures : list[FixtureInstance]
    dimmer_capacity_W : float
    supply_voltage : float

    Returns
    -------
    LightingPlotSummary
    """
    type_counts: dict[str, int] = {}
    for f in fixtures:
        name = f.fixture_type.type_name
        type_counts[name] = type_counts.get(name, 0) + 1

    total_W = sum(f.wattage for f in fixtures)
    total_A = total_W / supply_voltage if supply_voltage > 0 else 0.0
    universes = sorted({f.dmx_universe for f in fixtures})
    conflicts = check_dmx_conflicts(fixtures)
    circuits = circuit_schedule(fixtures, dimmer_capacity_W, supply_voltage)
    overloaded = [c.dimmer for c in circuits if c.overloaded]

    return LightingPlotSummary(
        total_fixtures=len(fixtures),
        fixture_counts_by_type=type_counts,
        total_wattage=total_W,
        total_amperage=total_A,
        universes_used=universes,
        dmx_conflicts=conflicts,
        circuit_rows=circuits,
        overloaded_circuits=overloaded,
        supply_voltage=supply_voltage,
    )
