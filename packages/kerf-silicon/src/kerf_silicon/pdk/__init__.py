"""kerf_silicon.pdk — Process Design Kit (PDK) registry.

Each sub-package exposes a PDK's layer table, standard-cell library,
design-rule set, and installer helper.
"""

from kerf_silicon.pdk.sky130 import SKY130_PDK  # noqa: F401

__all__ = ["SKY130_PDK"]
