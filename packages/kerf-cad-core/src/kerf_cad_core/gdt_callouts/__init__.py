"""
kerf_cad_core.gdt_callouts — Auto-proposal of GD&T callouts from model features.

Given a list of classified features (holes, slots, planar faces, cylindrical
surfaces, patterns) and a set of reference datums plus an IT tolerance grade,
this submodule auto-proposes feature control frames following ASME Y14.5 /
ISO 1101 best-practice rules:

  - Holes / patterns of holes  → POSITION (⊕), cylindrical zone, primary datum
  - Planar faces vs datum plane → PERPENDICULARITY (⊥) or PARALLELISM (∥)
  - Cylindrical surfaces        → RUNOUT (↗) about an AXIS datum
  - Free-form surfaces          → PROFILE_SURFACE (⌓) to a datum

Tolerance band magnitudes are derived from ISO 286-1 IT (International
Tolerance) grades.  The default grade is IT7.

Submodules:
  propose  — core IT-grade maths and per-feature-type callout rules
  tools    — LLM tool wrappers: gdt_auto_callouts, gdt_callout_balloon_table
"""
from __future__ import annotations

from kerf_cad_core.gdt_callouts.propose import (
    propose_callouts,
    it_grade_tolerance,
    IT_GRADES,
    VALID_GRADES,
)

__all__ = [
    "propose_callouts",
    "it_grade_tolerance",
    "IT_GRADES",
    "VALID_GRADES",
]
