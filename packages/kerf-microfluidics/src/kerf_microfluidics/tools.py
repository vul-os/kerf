"""
LLM-callable tools for the kerf-microfluidics plugin.

Tools exposed
-------------
``microfluidics_channel``
    Compute hydraulic resistance and pressure drop for a rectangular or
    circular microchannel.

``microfluidics_network``
    Solve a microfluidic resistor network for nodal pressures and flow rates.

``microfluidics_mems``
    Compute stiffness and resonance frequency of a MEMS cantilever beam.

``microfluidics_mixer``
    Generate serpentine or herringbone mixer geometry.
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_microfluidics._compat import (  # type: ignore[assignment]
        ToolSpec,
        err_payload,
        ok_payload,
        ProjectCtx,
    )

from kerf_microfluidics.channels import (
    circ_channel_resistance,
    flow_rate,
    pressure_drop,
    rect_channel_resistance,
)
from kerf_microfluidics.mems_cantilever import (
    cantilever_resonance,
    cantilever_stiffness,
)
from kerf_microfluidics.mixers import herringbone_geometry, serpentine_geometry
from kerf_microfluidics.networks import MicrofluidicNetwork


# ---------------------------------------------------------------------------
# microfluidics_channel
# ---------------------------------------------------------------------------

microfluidics_channel_spec = ToolSpec(
    name="microfluidics_channel",
    description=(
        "Compute the hydraulic resistance and pressure drop for a single "
        "rectangular or circular microchannel.  Returns resistance [Pa·s/m³] "
        "and, if a flow rate or pressure drop is supplied, the complementary value."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "shape": {
                "type": "string",
                "enum": ["rectangular", "circular"],
                "description": "Cross-section shape of the channel.",
            },
            "mu": {
                "type": "number",
                "description": "Dynamic viscosity [Pa·s]. Default: 1e-3 (water at 20°C).",
            },
            "length": {"type": "number", "description": "Channel length [m]."},
            "width": {
                "type": "number",
                "description": "Channel width (rectangular only, larger dimension) [m].",
            },
            "height": {
                "type": "number",
                "description": "Channel height (rectangular only, smaller dimension) [m].",
            },
            "radius": {"type": "number", "description": "Channel radius (circular only) [m]."},
            "flow_rate_m3s": {
                "type": "number",
                "description": "Volumetric flow rate [m³/s]. If provided, returns ΔP.",
            },
            "delta_p_pa": {
                "type": "number",
                "description": "Pressure drop [Pa]. If provided, returns Q.",
            },
        },
        "required": ["shape", "length"],
    },
)


async def run_microfluidics_channel(args: dict, ctx: ProjectCtx) -> str:
    try:
        shape = args["shape"]
        mu = float(args.get("mu", 1e-3))
        L = float(args["length"])

        if shape == "rectangular":
            w = float(args["width"])
            h = float(args["height"])
            R = rect_channel_resistance(mu, L, w, h)
        elif shape == "circular":
            r = float(args["radius"])
            R = circ_channel_resistance(mu, L, r)
        else:
            return err_payload(f"Unknown shape: {shape}", "BAD_ARGS")

        result: dict = {"resistance_Pa_s_per_m3": R}

        if "flow_rate_m3s" in args:
            Q = float(args["flow_rate_m3s"])
            result["delta_p_Pa"] = pressure_drop(Q, R)

        if "delta_p_pa" in args:
            dP = float(args["delta_p_pa"])
            result["flow_rate_m3s"] = flow_rate(dP, R)

        return ok_payload(result)

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")


# ---------------------------------------------------------------------------
# microfluidics_network
# ---------------------------------------------------------------------------

microfluidics_network_spec = ToolSpec(
    name="microfluidics_network",
    description=(
        "Solve a microfluidic resistor network.  Provide a list of channel "
        "segments (node_a, node_b, resistance) and pressure boundary conditions "
        "(node, pressure).  Returns nodal pressures and flow rates."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "channels": {
                "type": "array",
                "description": "List of channel segments.",
                "items": {
                    "type": "object",
                    "properties": {
                        "node_a": {"type": "string"},
                        "node_b": {"type": "string"},
                        "resistance": {"type": "number", "description": "[Pa·s/m³]"},
                        "label": {"type": "string"},
                    },
                    "required": ["node_a", "node_b", "resistance"],
                },
            },
            "pressure_bcs": {
                "type": "array",
                "description": "Pressure boundary conditions.",
                "items": {
                    "type": "object",
                    "properties": {
                        "node": {"type": "string"},
                        "pressure": {"type": "number", "description": "[Pa]"},
                    },
                    "required": ["node", "pressure"],
                },
            },
        },
        "required": ["channels", "pressure_bcs"],
    },
)


async def run_microfluidics_network(args: dict, ctx: ProjectCtx) -> str:
    try:
        net = MicrofluidicNetwork()
        all_nodes: set[str] = set()
        for ch in args["channels"]:
            all_nodes.add(ch["node_a"])
            all_nodes.add(ch["node_b"])
        for node in sorted(all_nodes):
            net.add_node(node)
        for ch in args["channels"]:
            kw: dict = {"resistance": float(ch["resistance"])}
            if "label" in ch:
                kw["label"] = ch["label"]
            net.add_channel(ch["node_a"], ch["node_b"], **kw)
        for bc in args["pressure_bcs"]:
            net.set_pressure(bc["node"], float(bc["pressure"]))

        result = net.solve()
        # Serialise tuple keys in flows dict
        flows_serial = {
            f"{a}→{b} ({lbl})": Q
            for (a, b, lbl), Q in result["flows"].items()
        }
        return ok_payload({"pressures": result["pressures"], "flows": flows_serial})

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")


# ---------------------------------------------------------------------------
# microfluidics_mems
# ---------------------------------------------------------------------------

microfluidics_mems_spec = ToolSpec(
    name="microfluidics_mems",
    description=(
        "Compute the stiffness k and fundamental resonance frequency f₁ of a "
        "MEMS cantilever beam using Euler-Bernoulli theory."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "E": {"type": "number", "description": "Young's modulus [Pa]."},
            "rho": {"type": "number", "description": "Density [kg/m³]."},
            "thickness": {
                "type": "number",
                "description": "Beam thickness (bending direction) t [m].",
            },
            "width": {"type": "number", "description": "Beam width w [m]."},
            "length": {"type": "number", "description": "Beam length L [m]."},
        },
        "required": ["E", "rho", "thickness", "width", "length"],
    },
)


async def run_microfluidics_mems(args: dict, ctx: ProjectCtx) -> str:
    try:
        E = float(args["E"])
        rho = float(args["rho"])
        t = float(args["thickness"])
        w = float(args["width"])
        L = float(args["length"])

        k = cantilever_stiffness(E, t, w, L)
        f1 = cantilever_resonance(E, rho, t, w, L)

        return ok_payload(
            {
                "stiffness_N_per_m": k,
                "resonance_freq_Hz": f1,
            }
        )

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")


# ---------------------------------------------------------------------------
# microfluidics_mixer
# ---------------------------------------------------------------------------

microfluidics_mixer_spec = ToolSpec(
    name="microfluidics_mixer",
    description=(
        "Generate the geometry of a passive microfluidic mixer.  "
        "Supports 'serpentine' and 'herringbone' types.  "
        "Returns waypoints / groove positions in metres."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mixer_type": {
                "type": "string",
                "enum": ["serpentine", "herringbone"],
            },
            "channel_width": {"type": "number", "description": "[m]"},
            # serpentine
            "n_turns": {"type": "integer", "description": "Serpentine: number of U-turns."},
            "straight_length": {"type": "number", "description": "Serpentine: length of each straight [m]."},
            "turn_radius": {"type": "number", "description": "Serpentine: U-turn radius [m] (optional)."},
            # herringbone
            "channel_length": {"type": "number", "description": "Herringbone: total channel length [m]."},
            "groove_depth": {"type": "number", "description": "Herringbone: groove depth [m]."},
            "groove_width": {"type": "number", "description": "Herringbone: groove ridge width [m]."},
            "groove_pitch": {"type": "number", "description": "Herringbone: groove centre-to-centre spacing [m]."},
            "groove_angle": {"type": "number", "description": "Herringbone: half-angle of V [degrees]. Default 45."},
        },
        "required": ["mixer_type", "channel_width"],
    },
)


async def run_microfluidics_mixer(args: dict, ctx: ProjectCtx) -> str:
    try:
        mixer_type = args["mixer_type"]

        if mixer_type == "serpentine":
            geom = serpentine_geometry(
                n_turns=int(args["n_turns"]),
                channel_width=float(args["channel_width"]),
                straight_length=float(args["straight_length"]),
                turn_radius=float(args["turn_radius"]) if "turn_radius" in args else None,
            )
        elif mixer_type == "herringbone":
            geom = herringbone_geometry(
                channel_length=float(args["channel_length"]),
                channel_width=float(args["channel_width"]),
                groove_depth=float(args["groove_depth"]),
                groove_width=float(args["groove_width"]),
                groove_pitch=float(args["groove_pitch"]),
                groove_angle=float(args.get("groove_angle", 45.0)),
            )
        else:
            return err_payload(f"Unknown mixer_type: {mixer_type}", "BAD_ARGS")

        return ok_payload(geom)

    except (KeyError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")
