"""
SPEF (Standard Parasitic Exchange Format) writer.

Emits a simplified IEEE 1481-1999-style SPEF file from a ParasiticReport.

Only the essential sections required for downstream STA/SPICE tools are
generated:

  *SPEF header
  *NAME_MAP        — (empty for unnamed instances; present for completeness)
  *PORTS           — (stub; full-chip flow would list I/O ports here)
  *D_NET sections  — one per net with *C and *R values

Units
-----
Resistance : Ω
Capacitance: F  (SPEF typically uses pF; we emit in F and set *UNITS accordingly)

Reference
---------
IEEE Std 1481-1999, "Standard for Integrated Circuit (IC) Open Library
Architecture (OLA)"
"""
from __future__ import annotations

import datetime
import os
from typing import IO

from .rc_extract import ParasiticReport


# ---------------------------------------------------------------------------
# SPEF emitter
# ---------------------------------------------------------------------------

def to_spef(
    report: ParasiticReport,
    output_path: str | os.PathLike,
) -> None:
    """
    Write *report* to *output_path* in IEEE 1481-style SPEF format.

    Parameters
    ----------
    report      : ParasiticReport from extract_rc().
    output_path : Destination file path (created/overwritten).
    """
    with open(output_path, "w", encoding="utf-8") as fh:
        _write_header(fh)
        _write_name_map(fh, report)
        _write_ports(fh)
        _write_nets(fh, report)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_header(fh: IO[str]) -> None:
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fh.write('*SPEF "IEEE 1481-1999"\n')
    fh.write('*DESIGN "kerf_extracted"\n')
    fh.write(f'*DATE "{now}"\n')
    fh.write('*VENDOR "kerf-silicon"\n')
    fh.write('*PROGRAM "kerf_silicon.parasitics"\n')
    fh.write('*VERSION "1.0"\n')
    fh.write('*DESIGN_FLOW "EXTRACTED"\n')
    fh.write('*DIVIDER /\n')
    fh.write('*DELIMITER :\n')
    fh.write('*BUS_DELIMITER [ ]\n')
    # Resistance in Ω, capacitance in F (scale factor 1)
    fh.write('*T_UNIT 1 NS\n')
    fh.write('*C_UNIT 1 FF\n')   # femtofarads
    fh.write('*R_UNIT 1 OHM\n')
    fh.write('*L_UNIT 1 HENRY\n')
    fh.write('\n')


def _write_name_map(fh: IO[str], report: ParasiticReport) -> None:
    """Emit *NAME_MAP section mapping integer indices to net names."""
    fh.write('*NAME_MAP\n')
    for idx, net_name in enumerate(sorted(report.nets.keys()), start=1):
        fh.write(f'*{idx} {net_name}\n')
    fh.write('\n')


def _write_ports(fh: IO[str]) -> None:
    """Emit an empty *PORTS section (stub for full-chip flows)."""
    fh.write('*PORTS\n')
    fh.write('\n')


def _write_nets(fh: IO[str], report: ParasiticReport) -> None:
    """Emit one *D_NET block per net."""
    # Build name→index map for cross-references
    name_to_idx = {
        name: idx
        for idx, name in enumerate(sorted(report.nets.keys()), start=1)
    }

    for net_name in sorted(report.nets.keys()):
        net = report.nets[net_name]
        idx = name_to_idx[net_name]

        # Total capacitance in femtofarads (FF as declared in *C_UNIT)
        c_ff = net.C_total_F * 1e15

        fh.write(f'*D_NET *{idx} {c_ff:.6g}\n')

        # *CONN section (driver/load pins — stub)
        fh.write('*CONN\n')

        # *CAP section — one entry per capacitance segment
        fh.write('*CAP\n')
        for seg_idx, c_seg in enumerate(net.C_segments, start=1):
            c_seg_ff = c_seg.C_total_F * 1e15
            fh.write(f'{seg_idx} *{idx}:1 {c_seg_ff:.6g}\n')

        # *RES section — one entry per resistance segment
        fh.write('*RES\n')
        for seg_idx, r_seg in enumerate(net.R_segments, start=1):
            fh.write(
                f'{seg_idx} *{idx}:1 *{idx}:{seg_idx + 1} {r_seg.R_ohm:.6g}\n'
            )

        fh.write('*END\n')
        fh.write('\n')
