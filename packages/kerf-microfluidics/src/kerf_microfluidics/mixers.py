"""
Passive mixer geometry generators.

Produces lists of 2-D waypoints (x, y) and ridge/groove metadata that can
be exported to a CAD kernel or visualised directly.  All dimensions are in
metres.

Mixer types
-----------
``serpentine``
    Classic S-shaped channel with rectangular turns.  Mixing relies on
    diffusion across the elongated path length and Dean vortices at bends.

``herringbone``
    Staggered herringbone groove (SHG) mixer (Stroock et al., *Science* 2002).
    Returns the centerline of the main channel plus the groove geometry.

References
----------
Stroock, A. D. et al. (2002). Chaotic Mixer for Microchannels. *Science*,
    295(5555), 647–651. https://doi.org/10.1126/science.1066238

Nguyen, N.-T. & Wu, Z. (2005). Micromixers — a review. *Journal of
    Micromechanics and Microengineering*, 15(2), R1–R16.
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Serpentine mixer
# ---------------------------------------------------------------------------

def serpentine_geometry(
    n_turns: int,
    channel_width: float,
    straight_length: float,
    turn_radius: float | None = None,
    *,
    start_x: float = 0.0,
    start_y: float = 0.0,
) -> dict[str, Any]:
    """
    Generate the centreline waypoints of a serpentine (S-channel) mixer.

    The channel alternates between straight segments running in the +x
    direction and 180-degree U-turns.  Each turn is approximated as a
    semicircle of radius ``turn_radius`` (default: ``channel_width / 2``).

    Parameters
    ----------
    n_turns : int
        Number of 180° U-turns (each turn adds one additional straight leg).
    channel_width : float
        Width of the channel [m].
    straight_length : float
        Length of each straight segment between turns [m].
    turn_radius : float, optional
        Radius of the U-turn centreline [m].
        Defaults to ``channel_width / 2``.
    start_x, start_y : float
        Starting coordinates of the centreline [m].

    Returns
    -------
    dict with keys:
      ``waypoints`` : list of (x, y) tuples — centreline path
      ``channel_width`` : float
      ``total_length`` : float — approximate centreline length [m]
      ``n_turns`` : int
    """
    if n_turns < 1:
        raise ValueError("n_turns must be >= 1")
    if channel_width <= 0 or straight_length <= 0:
        raise ValueError("channel_width and straight_length must be positive")
    if turn_radius is None:
        turn_radius = channel_width / 2.0
    if turn_radius <= 0:
        raise ValueError("turn_radius must be positive")

    waypoints: list[tuple[float, float]] = []
    x, y = start_x, start_y
    # Approximate U-turn arc by a series of points (16 segments per semicircle)
    arc_segments = 16

    # direction: +1 → moving right along x, -1 → moving left
    direction = 1
    waypoints.append((x, y))

    for turn_idx in range(n_turns + 1):
        # Straight segment
        x_end = x + direction * straight_length
        waypoints.append((x_end, y))
        x = x_end

        if turn_idx < n_turns:
            # U-turn: centre is at (x, y ± turn_radius)
            sign = 1 if direction == 1 else -1
            cx = x
            cy = y + sign * turn_radius
            # Arc from bottom of circle back up the other side
            start_angle = -sign * math.pi / 2.0  # pointing away from centre
            for k in range(1, arc_segments + 1):
                theta = start_angle + sign * math.pi * k / arc_segments
                arc_x = cx + turn_radius * math.cos(theta)
                arc_y = cy + turn_radius * math.sin(theta)
                waypoints.append((arc_x, arc_y))

            # After the arc y has moved by 2*turn_radius
            y += sign * 2.0 * turn_radius
            direction *= -1  # flip

    # Total centreline length (approximate)
    total_length = 0.0
    for i in range(1, len(waypoints)):
        dx = waypoints[i][0] - waypoints[i - 1][0]
        dy = waypoints[i][1] - waypoints[i - 1][1]
        total_length += math.hypot(dx, dy)

    return {
        "waypoints": waypoints,
        "channel_width": channel_width,
        "total_length": total_length,
        "n_turns": n_turns,
    }


# ---------------------------------------------------------------------------
# Herringbone groove mixer
# ---------------------------------------------------------------------------

def herringbone_geometry(
    channel_length: float,
    channel_width: float,
    groove_depth: float,
    groove_width: float,
    groove_pitch: float,
    groove_angle: float = 45.0,
    n_asymmetric_cycles: int = 1,
    *,
    start_x: float = 0.0,
    start_y: float = 0.0,
) -> dict[str, Any]:
    """
    Generate the staggered herringbone groove (SHG) mixer geometry.

    Returns the main-channel centreline and the position/orientation of each
    groove pair (a V-shaped ridge on the channel floor/ceiling).

    The SHG mixer uses asymmetric herringbone ridges that alternate their
    centre-offset between groups, creating a chaotic folding flow.

    Parameters
    ----------
    channel_length : float
        Total length of the main channel [m].
    channel_width : float
        Width of the main channel [m].
    groove_depth : float
        Depth of the grooves (below the channel floor) [m].
    groove_width : float
        Width (thickness) of each groove ridge [m].
    groove_pitch : float
        Centre-to-centre spacing between adjacent groove pairs [m].
    groove_angle : float
        Half-angle of the V-groove arms from the channel axis [degrees].
        Stroock et al. use 45°.
    n_asymmetric_cycles : int
        Number of asymmetric cycles (each cycle = 2 half-cycles with offset
        shifted from w/4 to 3w/4 and back).
    start_x, start_y : float
        Origin of the channel centreline [m].

    Returns
    -------
    dict with keys:
      ``centreline`` : list of (x, y) — two-point channel centreline
      ``grooves``    : list of groove dicts, each with keys:
          ``x``         : axial position of groove apex [m]
          ``angle_deg`` : signed angle of right arm from +y axis [degrees]
          ``offset_y``  : lateral offset of V-apex from centreline [m]
          ``depth``     : groove depth [m]
          ``width``     : groove ridge width [m]
      ``channel_width`` : float
      ``channel_length`` : float
    """
    if channel_length <= 0 or channel_width <= 0:
        raise ValueError("channel_length and channel_width must be positive")
    if groove_depth <= 0 or groove_width <= 0 or groove_pitch <= 0:
        raise ValueError("groove_depth, groove_width, groove_pitch must be positive")
    if not (0.0 < groove_angle < 90.0):
        raise ValueError("groove_angle must be in (0, 90) degrees")

    centreline = [
        (start_x, start_y),
        (start_x + channel_length, start_y),
    ]

    grooves: list[dict[str, Any]] = []
    angle_rad = math.radians(groove_angle)

    # SHG pattern: half-cycle A uses offset +w/4, half-cycle B uses offset -w/4
    # A half-cycle occupies groove_pitch * n_grooves_per_half_cycle space
    # We tile them along the channel.
    offsets_cycle = [channel_width / 4.0, -channel_width / 4.0]

    x_pos = start_x + groove_pitch / 2.0
    cycle_idx = 0

    while x_pos <= start_x + channel_length - groove_pitch / 2.0:
        offset = offsets_cycle[cycle_idx % 2]
        grooves.append(
            {
                "x": x_pos,
                "angle_deg": groove_angle,
                "offset_y": offset,
                "depth": groove_depth,
                "width": groove_width,
            }
        )
        x_pos += groove_pitch
        # Alternate half-cycle every n_asymmetric_cycles grooves
        if len(grooves) % n_asymmetric_cycles == 0:
            cycle_idx += 1

    return {
        "centreline": centreline,
        "grooves": grooves,
        "channel_width": channel_width,
        "channel_length": channel_length,
    }
