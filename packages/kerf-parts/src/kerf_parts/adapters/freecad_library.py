"""FreeCAD-library adapter — SCAFFOLD (fetch wired, conversion deferred).

FreeCAD-library (https://github.com/FreeCAD/FreeCAD-library) is a flat tree
of ready-made parts as ``.FCStd`` (FreeCAD native) plus exported ``.step`` /
``.stp`` / ``.brep`` files, organized by category folders.

Kerf ALREADY has a full FreeCAD importer — ``kerf_imports.freecad`` (see
``kerf_imports/tools/import_freecad.py``) — and a STEP import path. The
correct, low-duplication way to ingest this source is therefore to *reuse*
that importer per file rather than write a second parser here. Wiring that
per-file import + Parts Library write is non-trivial (it needs the OCCT
worker for geometry), so it is deferred; this adapter implements the
registry interface and enumerates the candidate files so the seam is ready.

WHAT IS REAL:  manifest entry + fetch into .parts-cache/freecad-library/;
               candidate-file discovery (discover_part_files).
WHAT IS TODO:  for each .FCStd -> kerf_imports.freecad import; for each
               .step -> kerf_imports STEP import; write each as a
               kind='part' (or 'step') file with provenance metadata.
"""
from __future__ import annotations

from pathlib import Path

from ..manifest import Source
from ..model import KerfPart

_PART_SUFFIXES = (".fcstd", ".step", ".stp", ".brep")


def discover_part_files(src_dir) -> list[Path]:
    """Enumerate importable part files (used by tests + future impl)."""
    src = Path(src_dir)
    out: list[Path] = []
    for p in sorted(src.rglob("*")):
        if p.is_file() and p.suffix.lower() in _PART_SUFFIXES:
            out.append(p)
    return out


def adapt(source: Source, src_dir) -> list[KerfPart]:
    """SCAFFOLD: returns []. Reuse path = kerf_imports.freecad / STEP import.

    See module docstring. Deliberately a no-op so the heavy OCCT geometry
    path is not pulled into seed-time; the fetch + discovery are real.
    """
    return []
