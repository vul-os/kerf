"""ISO 4762 — hexagon socket head cap screw (Allen / socket-head bolt).

Authored generator (human-written, MIT).  SIZES freezes the standard's
tabulated dimensions for M3..M24: cylindrical head diameter ``dk``, head
height ``k``, hexagonal socket size ``s`` (across-flats), and socket depth
``t``, plus a representative shank length ``l`` per size.  These are
uncopyrightable dimensional facts, transcribed once and frozen here so
``enumerate`` never needs the LLM again.

Geometry (composed purely from the Kerf OCCT kernel facade):
  head   = cylinder (dk diameter, k height) centred at z in [-k, 0]
  socket = hex prism (s across-flats, t deep) cut from the top of the head
  shank  = plain cylinder at nominal major diameter, running +Z from z=0

Thread is modelled as a smooth cylindrical envelope — the same convention
used by every parts-library generator in this package.  Real helical threads
are omitted deliberately (they cost huge B-rep complexity and are never
needed for interference/clearance design use).

Dimension source: ISO 4762:2004 (previously DIN 912), Table 1.
All dimension values are standard tabulated facts; the code is original.
"""

from __future__ import annotations

import math

from kerf_partsgen import kernel

FAMILY = {
    "family_id": "iso_4762_socket_head_cap_screw",
    "name": "ISO 4762 socket-head cap screw",
    "standard": "ISO 4762",
    "domain": "mechanical",
    "category": "mechanical/fastener",
    "units": "mm",
}


def _row(size, nominal_d, head_dk, head_k, socket_s, socket_t, length):
    """Build one SIZES row + precompute expected bbox and nominal volume.

    bbox: the XY footprint is the head diameter dk (head is always wider than
    the shank); Z is head height k + shank length l.
    volume: head cylinder + shank cylinder - socket hex prism (nominal).
    """
    circum_r_sock = (socket_s / 2.0) / math.cos(math.pi / 6.0)
    hex_area = (3.0 * math.sqrt(3.0) / 2.0) * circum_r_sock ** 2
    vol = (
        math.pi * (head_dk / 2.0) ** 2 * head_k   # head
        + math.pi * (nominal_d / 2.0) ** 2 * length  # shank
        - hex_area * socket_t                          # minus socket
    )
    return {
        "size": size,
        "params": {
            "nominal_d": nominal_d,
            "head_dk": head_dk,
            "head_k": head_k,
            "socket_s": socket_s,
            "socket_t": socket_t,
            "length": length,
        },
        "expect": {
            "bbox_mm": [
                round(head_dk, 3),
                round(head_dk, 3),
                round(head_k + length, 3),
            ],
            "volume_mm3": round(vol, 2),
        },
    }


# ISO 4762:2004 Table 1 — (size, d nominal, dk head Ø, k head h,
#                           s socket AF, t socket depth, l representative
#                           length).  Lengths chosen as mid-range per size.
SIZES = [
    _row("M3",  3,  5.5, 3.0, 2.5, 1.3,  16),
    _row("M4",  4,  7.0, 4.0, 3.0, 2.0,  20),
    _row("M5",  5,  8.5, 5.0, 4.0, 2.5,  25),
    _row("M6",  6, 10.0, 6.0, 5.0, 3.0,  30),
    _row("M8",  8, 13.0, 8.0, 6.0, 4.0,  40),
    _row("M10", 10, 16.0, 10.0, 8.0, 5.0, 50),
    _row("M12", 12, 18.0, 12.0, 10.0, 6.0, 60),
    _row("M16", 16, 24.0, 16.0, 14.0, 8.0, 80),
    _row("M20", 20, 30.0, 20.0, 17.0, 10.0, 100),
    _row("M24", 24, 36.0, 24.0, 19.0, 12.0, 120),
]


def build(row: dict):
    p = row["params"]
    head_k = p["head_k"]
    length = p["length"]
    socket_t = p["socket_t"]

    # Head: cylinder, placed at z in [-head_k, 0] (flat face on XY plane)
    head = kernel.cylinder(radius=p["head_dk"] / 2.0, height=head_k)
    head = kernel.translate(head, 0.0, 0.0, -head_k / 2.0)

    # Hex socket recess: hex prism cut into the top face of the head.
    # The socket sits at the top of the head (z in [-socket_t, 0]) and we cut
    # it from the head solid.
    socket = kernel.hex_prism(across_flats=p["socket_s"], height=socket_t)
    # hex_prism is centred: move it so its top face is at z=0 (head top).
    socket = kernel.translate(socket, 0.0, 0.0, -socket_t / 2.0)
    head = kernel.cut(head, socket)

    # Shank: cylinder running from z=0 to z=+length
    shank = kernel.cylinder(radius=p["nominal_d"] / 2.0, height=length)
    shank = kernel.translate(shank, 0.0, 0.0, length / 2.0)

    return kernel.union(head, shank)
