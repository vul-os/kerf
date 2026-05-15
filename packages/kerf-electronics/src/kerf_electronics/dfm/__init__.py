"""
kerf_electronics.dfm — Design-for-Manufacture rule engine.

Exports the public surface consumed by bom_cost.py and tests:

    run_dfm_checks(circuit_json, board_class=2)
        → list[DFMFinding]

    score_dfm(findings)
        → int  (0–100; 100 = no issues)

IPC references:
    IPC-2221B  Generic Standard on Printed Board Design
    IPC-A-600K Acceptability of Printed Boards
    IPC-7711/7721 Rework, Modification and Repair of Electronics Assemblies
"""

from kerf_electronics.dfm.rules import run_dfm_checks, score_dfm, DFMFinding

__all__ = ["run_dfm_checks", "score_dfm", "DFMFinding"]
