"""Horology (watchmaking) parametric generators.

Sub-package of ``kerf_partsgen.generators`` covering the Swiss lever
escapement train, gear-train wheel/pinion, and mainspring barrel.

Each module exposes the standard ``FAMILY``, ``SIZES``, ``build()`` contract
so the generators can be loaded by ``kerf_partsgen.loader`` when gen_dir is
pointed here.

Public geometry helpers (involute profile, tooth-profile validation, gear
geometry) are also importable directly for unit testing and for the
``kerf-horology`` thin wrapper.
"""

from kerf_partsgen.generators.horology.involute import (  # noqa: F401
    involute_profile,
    check_involute_profile,
)

__all__ = [
    "involute_profile",
    "check_involute_profile",
]
