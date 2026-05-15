# Author: imranparuk
"""Flex and rigid-flex stackup models for kerf-electronics."""

from .stackup import (
    BendRegion,
    FlexType,
    Layer,
    LayerType,
    Stackup,
    ZoneType,
)

__all__ = [
    "Layer",
    "LayerType",
    "ZoneType",
    "FlexType",
    "Stackup",
    "BendRegion",
]
