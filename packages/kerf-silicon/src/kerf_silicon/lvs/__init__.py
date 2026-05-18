"""kerf_silicon.lvs — Layout vs Schematic (LVS) engine.

Sub-modules
-----------
extractor   Layout → netlist extraction (union-find connectivity).
compare     Netlist diff / LVS match report.

Quick usage
-----------
    from kerf_silicon.lvs.extractor import extract
    from kerf_silicon.lvs.compare import lvs_match

    netlist = extract(layout, tech)
    report  = lvs_match(netlist, reference_netlist)
    print(report.summary)
"""
from kerf_silicon.lvs.extractor import extract, Netlist, CellInstance, Net
from kerf_silicon.lvs.compare import lvs_match, LvsReport, CellDiff, NetDiff

__all__ = [
    "extract",
    "Netlist",
    "CellInstance",
    "Net",
    "lvs_match",
    "LvsReport",
    "CellDiff",
    "NetDiff",
]
