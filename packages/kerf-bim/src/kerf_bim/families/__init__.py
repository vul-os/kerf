"""
kerf_bim.families
=================

Built-in starter family library for the GDL-replacement Family Editor.

Each module in this package exports a ``family_def: FamilyDef`` at module
level.  The 10 bundled starters are:

Doors
~~~~~
- ``door_single_swing``   — single-leaf hinged door
- ``door_double_swing``   — pair of doors with gap

Windows
~~~~~~~
- ``window_casement``     — side-hinged casement, variable pane count
- ``window_sliding``      — horizontal sliding sashes

Furniture
~~~~~~~~~
- ``cabinet_base``        — base cabinet with drawers + shelves
- ``chair_dining``        — dining / side chair
- ``desk_office``         — office desk with optional pedestal drawer

Lighting Fixtures
~~~~~~~~~~~~~~~~~
- ``light_pendant``       — suspended pendant luminaire

Plumbing Fixtures
~~~~~~~~~~~~~~~~~
- ``toilet_standard``     — close-coupled toilet (standard + ADA variant)
- ``kitchen_sink_single`` — single-bowl kitchen sink

Usage::

    from kerf_bim.families.door_single_swing import family_def
    from kerf_bim.family_editor import instantiate_family

    result = instantiate_family(family_def, {"width": 800, "height": 2100})
"""
from __future__ import annotations

from kerf_bim.families.cabinet_base import family_def as cabinet_base
from kerf_bim.families.chair_dining import family_def as chair_dining
from kerf_bim.families.desk_office import family_def as desk_office
from kerf_bim.families.door_double_swing import family_def as door_double_swing
from kerf_bim.families.door_single_swing import family_def as door_single_swing
from kerf_bim.families.kitchen_sink_single import family_def as kitchen_sink_single
from kerf_bim.families.light_pendant import family_def as light_pendant
from kerf_bim.families.toilet_standard import family_def as toilet_standard
from kerf_bim.families.window_casement import family_def as window_casement
from kerf_bim.families.window_sliding import family_def as window_sliding

__all__ = [
    "door_single_swing",
    "door_double_swing",
    "window_casement",
    "window_sliding",
    "cabinet_base",
    "chair_dining",
    "desk_office",
    "light_pendant",
    "toilet_standard",
    "kitchen_sink_single",
    "ALL_STARTER_FAMILIES",
]

ALL_STARTER_FAMILIES = [
    door_single_swing,
    door_double_swing,
    window_casement,
    window_sliding,
    cabinet_base,
    chair_dining,
    desk_office,
    light_pendant,
    toilet_standard,
    kitchen_sink_single,
]
