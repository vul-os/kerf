"""Adapter registry.

The manifest's ``adapter`` field is a string key; it maps here to a callable
with the signature::

    adapt(source: Source, src_dir: Path) -> list[KerfPart]

where ``src_dir`` is the cloned cache directory for that source and the
return value is a list of normalized Kerf-native part records (see
:mod:`kerf_parts.model`).
"""
from __future__ import annotations

from typing import Callable

from ..manifest import Source
from ..model import KerfPart
from . import bolts as _bolts
from . import freecad_library as _freecad
from . import kicad as _kicad

Adapter = Callable[[Source, "object"], list[KerfPart]]

_REGISTRY: dict[str, Adapter] = {
    "kicad": _kicad.adapt,
    # 3D packages reuse the same KiCad adapter path; it records model refs
    # only (heavy STEP/WRL bodies are not converted in-tree).
    "kicad3d": _kicad.adapt_packages3d,
    "bolts": _bolts.adapt,
    "freecad_library": _freecad.adapt,
}


def get_adapter(key: str) -> Adapter:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"unknown adapter {key!r}; known: {', '.join(sorted(_REGISTRY))}"
        ) from None


def adapter_keys() -> list[str]:
    return sorted(_REGISTRY)
