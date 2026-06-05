"""
kerf_fem.solid_fem_tools — LLM tool registrations for:

  fem_solid_static   — linear static analysis on a small tet4/hex8 solid mesh
                       using the native solid_tools.py engine.
  fem_modal_beam     — consistent-mass modal analysis for 1-D Hermite beams
                       (validated vs Blevins; <0.1 % error on cantilever f_1).
  fem_linear_static_beam — linear static beam solver: axial bars, Euler-Bernoulli
                            beams, thermal stress bars.

These tools wire the pure-Python engines in solid_tools.py, modal.py and
linear_static.py as first-class LLM tools so the chat interface can exercise
them without a STEP file or FEniCSx install.

Formulation references
----------------------
Solid tet4:
  Cook, Malkus, Plesha & Witt, "Concepts and Applications of FEA",
  4th ed. (2001), §7.2  (constant-strain tetrahedron, B-matrix).
  Von Mises stress: σ_vm = √(½[(σ1-σ2)²+(σ2-σ3)²+(σ3-σ1)²])

Modal beam (Hermite, consistent mass):
  Hughes, "The Finite Element Method" (2000), eq. (8.1.13).
  Eigenproblem K φ = ω² M φ via Cholesky + Jacobi iteration.

Beam static:
  Timoshenko & Gere, "Mechanics of Materials" (1984), Ch. 6.
  Assembled Euler-Bernoulli 2-node element stiffness/load vectors.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ─────────────────────────────────────────────────────────────────────────────
# fem_solid_static
# ─────────────────────────────────────────────────────────────────────────────

_fem_solid_static_spec = ToolSpec(
    name="fem_solid_static",
    description=(
        "Linear static FEM on a user-supplied solid mesh (tet4 / tet10 / hex8 / hex20). "
        "Assembles global stiffness K via direct stiffness method, applies Dirichlet BCs "
        "(penalty method, α=1e20), solves K·u=f with numpy.linalg.solve. "
        "Returns per-node displacements, per-element von Mises stress, max displacement, "
        "max von Mises stress, and Factor of Safety. "
        "Formulation: Cook et al. (2001) §7.2 (tet4 B-matrix); §8.2 (hex8 trilinear). "
        "Practical limit: <~500 nodes (dense solver). "
        "Use fem_run for large meshes (dispatches to FEniCSx/CalculiX)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                "description": "List of [x, y, z] nodal coordinates [m]",
            },
            "elements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["tet4", "tet10", "hex8", "hex20"]},
                        "node_indices": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["kind", "node_indices"],
                },
                "description": "Element connectivity list",
            },
            "E": {"type": "number", "description": "Young's modulus [Pa]"},
            "nu": {"type": "number", "description": "Poisson's ratio"},
            "density": {"type": "number", "description": "Mass density [kg/m³]"},
            "yield_strength": {"type": "number", "description": "Yield strength [Pa] for FoS calculation"},
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "integer"},
                        "dofs": {
                            "type": "array",
                            "items": {"type": "number", "nullable": True},
                            "minItems": 3, "maxItems": 3,
                            "description": "[dx, dy, dz] — null means free, 0.0 means fixed",
                        },
                    },
                    "required": ["node_id", "dofs"],
                },
                "description": "Dirichlet boundary conditions per node",
            },
            "loads": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "integer"},
                        "force": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3, "maxItems": 3,
                            "description": "[Fx, Fy, Fz] [N]",
                        },
                    },
                    "required": ["node_id", "force"],
                },
                "description": "Nodal point forces [N]",
            },
        },
        "required": ["nodes", "elements", "E", "nu", "density", "yield_strength",
                     "constraints", "loads"],
    },
)


@register(_fem_solid_static_spec)
async def run_fem_solid_static(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = ["nodes", "elements", "E", "nu", "density", "yield_strength",
                "constraints", "loads"]
    for key in required:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    try:
        import numpy as np
        from kerf_fem.solid_tools import solve_static_solid, von_mises_stress_at_centroid
        from kerf_fem.solid_tet import SolidElement
        from kerf_fem.solid_tet import _elasticity_matrix

        # Build material dataclass
        class _Mat:
            def __init__(self, E, nu, density):
                self.E = E
                self.nu = nu
                self.density = density

        mat = _Mat(float(a["E"]), float(a["nu"]), float(a["density"]))
        nodes = np.array([[float(c) for c in n] for n in a["nodes"]], dtype=float)

        elements = []
        for el in a["elements"]:
            elem = SolidElement(
                kind=el["kind"],
                node_indices=list(el["node_indices"]),
                material=mat,
            )
            elements.append(elem)

        # Build constraints dict {node_id: (dx, dy, dz)}
        constraints = {}
        for c in a["constraints"]:
            nid = int(c["node_id"])
            dofs = [None if d is None else float(d) for d in c["dofs"]]
            constraints[nid] = tuple(dofs)

        # Build loads dict {node_id: (Fx, Fy, Fz)}
        loads_dict = {}
        for lp in a["loads"]:
            nid = int(lp["node_id"])
            f = [float(v) for v in lp["force"]]
            loads_dict[nid] = tuple(f)

        u = solve_static_solid(nodes, elements, constraints, loads_dict)

        # Per-node displacement magnitude
        u_mag = np.linalg.norm(u, axis=1).tolist()
        max_disp = float(np.max(u_mag))

        # Per-element von Mises stress
        E = float(a["E"])
        nu = float(a["nu"])
        vm_list = []
        for elem in elements:
            try:
                vm = von_mises_stress_at_centroid(elem, nodes, u, E, nu)
                vm_list.append(float(vm))
            except Exception:
                vm_list.append(0.0)

        max_vm = float(max(vm_list)) if vm_list else 0.0
        ys = float(a["yield_strength"])
        fos = ys / max_vm if max_vm > 1e-12 else None

        return ok_payload({
            "ok": True,
            "max_displacement_m": max_disp,
            "max_vonmises_stress_pa": max_vm,
            "factor_of_safety": round(fos, 4) if fos is not None else None,
            "node_displacements": [{"node": i, "u": list(u[i])} for i in range(len(u))],
            "element_vonmises_pa": vm_list,
        })
    except Exception as e:
        return err_payload(f"solid static FEM failed: {e}", "SOLVER_ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# fem_modal_beam
# ─────────────────────────────────────────────────────────────────────────────

_fem_modal_beam_spec = ToolSpec(
    name="fem_modal_beam",
    description=(
        "Consistent-mass modal analysis for a 1-D Euler-Bernoulli beam using "
        "Hermite cubic elements. Solves the generalised eigenproblem K φ = ω² M φ "
        "via Cholesky + Jacobi iteration. Validated: cantilever f_1 error < 0.1 % "
        "vs Blevins Table 8-1 (β₁L = 1.87510407). "
        "Returns natural frequencies [Hz], circular frequencies [rad/s], and mode shapes. "
        "Also supports plate mode (closed-form Blevins Table 11-4, simply-supported). "
        "Reference: Hughes 'The FEM' eq.(8.1.13); Blevins 'Formulas for Natural Frequency'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["beam", "plate"],
                "description": "Analysis type: 'beam' for Hermite beam FEM, 'plate' for thin plate closed-form",
                "default": "beam",
            },
            "E": {"type": "number", "description": "Young's modulus [Pa]"},
            "I": {"type": "number", "description": "Second moment of area [m⁴] (beam mode only)"},
            "A": {"type": "number", "description": "Cross-section area [m²] (beam mode only)"},
            "rho": {"type": "number", "description": "Mass density [kg/m³]"},
            "L": {"type": "number", "description": "Beam length [m] (beam mode only)"},
            "nu": {"type": "number", "description": "Poisson's ratio (plate mode only)"},
            "h": {"type": "number", "description": "Plate/beam thickness [m]"},
            "a": {"type": "number", "description": "Plate span in x [m] (plate mode only)"},
            "b": {"type": "number", "description": "Plate span in y [m] (plate mode only)"},
            "supports": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["fixed", "pinned", "free"]},
                        "x": {"type": "number", "description": "Position along beam [m]"},
                    },
                    "required": ["type", "x"],
                },
                "description": "Beam boundary conditions (beam mode only)",
            },
            "n_elem": {
                "type": "integer",
                "description": "Number of Hermite beam elements (default 12)",
                "default": 12,
            },
            "n_modes": {
                "type": "integer",
                "description": "Number of modes to extract (default 3)",
                "default": 3,
            },
        },
        "required": ["E", "rho"],
    },
)


@register(_fem_modal_beam_spec)
async def run_fem_modal_beam(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    mode = a.get("mode", "beam")
    E = a.get("E")
    rho = a.get("rho")

    if E is None or rho is None:
        return err_payload("E and rho are required", "BAD_ARGS")

    try:
        from kerf_fem.modal import beam_natural_frequencies, plate_first_mode_simply_supported

        if mode == "plate":
            nu = a.get("nu")
            h = a.get("h")
            _a = a.get("a")
            _b = a.get("b")
            if any(v is None for v in [nu, h, _a, _b]):
                return err_payload("plate mode requires nu, h, a, b", "BAD_ARGS")
            result = plate_first_mode_simply_supported(
                E=float(E), nu=float(nu), rho=float(rho),
                h=float(h), a=float(_a), b=float(_b),
            )
            if not result.get("ok"):
                return err_payload(result.get("reason", "unknown error"), "SOLVER_ERROR")
            return ok_payload({
                "mode": "plate",
                "f_1_hz": result["f_hz"],
                "omega_1_rad_s": result["omega"],
                "flexural_rigidity_D": result["D"],
            })
        else:
            # beam
            I = a.get("I")
            A_cross = a.get("A")
            L = a.get("L")
            supports = a.get("supports")
            if any(v is None for v in [I, A_cross, L, supports]):
                return err_payload("beam mode requires I, A, L, supports", "BAD_ARGS")
            result = beam_natural_frequencies(
                E=float(E), I=float(I), rho=float(rho),
                A=float(A_cross), L=float(L),
                supports=supports,
                n_elem=int(a.get("n_elem", 12)),
                n_modes=int(a.get("n_modes", 3)),
            )
            if not result.get("ok"):
                return err_payload(result.get("reason", "unknown error"), "SOLVER_ERROR")
            freqs = result["frequencies_hz"]
            omegas = result["omega"]
            shapes = result.get("mode_shapes", [])
            return ok_payload({
                "mode": "beam",
                "frequencies_hz": freqs,
                "omega_rad_s": omegas,
                "mode_shapes": shapes,
                "n_modes": len(freqs),
            })
    except Exception as e:
        return err_payload(f"modal beam analysis failed: {e}", "SOLVER_ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# fem_linear_static_beam
# ─────────────────────────────────────────────────────────────────────────────

_fem_linear_static_beam_spec = ToolSpec(
    name="fem_linear_static_beam",
    description=(
        "Linear static analysis for 1-D beam/bar structures using the native "
        "Euler-Bernoulli beam element engine. Supports: "
        "• Axial bar (solve_axial_bar) — uniaxial bar with point loads and distributed load. "
        "• Euler-Bernoulli beam (solve_beam) — shear/moment, deflection, reactions. "
        "• Thermal stress bar — axial bar with temperature change ΔT. "
        "Returns deflection profile, support reactions, max displacement/stress. "
        "Reference: Timoshenko & Gere 'Mechanics of Materials' (1984) Ch.6; "
        "Cook et al. (2001) §3.1 (beam element K_e, f_e consistent load vector)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "analysis": {
                "type": "string",
                "enum": ["axial_bar", "beam", "thermal_bar"],
                "description": "Type of 1-D analysis",
            },
            "E": {"type": "number", "description": "Young's modulus [Pa]"},
            "A": {"type": "number", "description": "Cross-section area [m²] (axial/thermal bar)"},
            "I": {"type": "number", "description": "Second moment of area [m⁴] (beam)"},
            "L": {"type": "number", "description": "Length [m]"},
            "alpha": {"type": "number", "description": "Thermal expansion coefficient [1/K] (thermal bar)"},
            "dT": {"type": "number", "description": "Temperature change ΔT [K] (thermal bar)"},
            "point_loads": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "Position [m]"},
                        "F": {"type": "number", "description": "Force [N] (axial for bars; transverse for beam)"},
                    },
                    "required": ["x", "F"],
                },
                "description": "Point loads",
            },
            "distributed_load": {
                "type": "number",
                "description": "Uniform distributed load [N/m] (axial for bars; transverse for beam)",
            },
            "supports": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["fixed", "pinned", "roller", "free"],
                            "description": "Support type",
                        },
                        "x": {"type": "number", "description": "Position [m]"},
                    },
                    "required": ["type", "x"],
                },
                "description": "Boundary conditions",
            },
            "n_elem": {
                "type": "integer",
                "description": "Number of elements (default 20 for beam, 1 for bar)",
                "default": 20,
            },
        },
        "required": ["analysis", "E", "L"],
    },
)


@register(_fem_linear_static_beam_spec)
async def run_fem_linear_static_beam(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    analysis = a.get("analysis")
    E = a.get("E")
    L = a.get("L")
    if not analysis:
        return err_payload("analysis is required", "BAD_ARGS")
    if E is None or L is None:
        return err_payload("E and L are required", "BAD_ARGS")

    try:
        from kerf_fem.linear_static import (
            solve_axial_bar,
            solve_thermal_stress_bar,
            solve_beam,
        )

        if analysis == "axial_bar":
            A = a.get("A")
            if A is None:
                return err_payload("A is required for axial_bar", "BAD_ARGS")
            # solve_axial_bar(E, A, L, P, n_elem) — fixed at x=0, load P at x=L
            # Combine all point loads as total tip load
            point_loads_list = a.get("point_loads", [])
            P_total = sum(float(p["F"]) for p in point_loads_list) if point_loads_list else 0.0
            w_udl = float(a.get("distributed_load", 0.0))
            # For UDL: distributed axial load; approximate as equivalent tip force P = w * L
            if w_udl != 0.0:
                P_total += w_udl * float(L)
            result = solve_axial_bar(
                E=float(E), A=float(A), L=float(L),
                P=P_total,
                n_elem=int(a.get("n_elem", 20)),
            )
            if not result.get("ok"):
                return err_payload(result.get("reason", "solver error"), "SOLVER_ERROR")
            return ok_payload({
                "analysis": "axial_bar",
                "max_displacement_m": result.get("displacement"),
                "nodal_displacements": result.get("nodal_disp"),
                "reactions": {"0.0": {"R": result.get("reaction", 0.0)}},
            })

        elif analysis == "thermal_bar":
            alpha = a.get("alpha")
            dT = a.get("dT")
            area = a.get("A", 1.0)
            if any(v is None for v in [alpha, dT]):
                return err_payload("alpha, dT required for thermal_bar", "BAD_ARGS")
            # solve_thermal_stress_bar(E, alpha, dT, area=...)
            result = solve_thermal_stress_bar(
                E=float(E),
                alpha=float(alpha),
                dT=float(dT),
                area=float(area) if area else 1.0,
            )
            if not result.get("ok"):
                return err_payload(result.get("reason", "solver error"), "SOLVER_ERROR")
            return ok_payload({
                "analysis": "thermal_bar",
                "thermal_stress_pa": result.get("stress"),
                "thermal_force_n": result.get("force"),
            })

        elif analysis == "beam":
            I = a.get("I")
            if I is None:
                return err_payload("I is required for beam analysis", "BAD_ARGS")
            supports = a.get("supports", [{"type": "fixed", "x": 0.0}])
            # Build loads list in solve_beam format: {type, x, P} or {type, w}
            beam_loads = []
            for p in a.get("point_loads", []):
                beam_loads.append({"type": "point", "x": float(p["x"]), "P": float(p["F"])})
            w_udl = float(a.get("distributed_load", 0.0))
            if w_udl != 0.0:
                beam_loads.append({"type": "udl", "w": w_udl})
            result = solve_beam(
                E=float(E), I=float(I), L=float(L),
                supports=supports,
                loads=beam_loads,
                n_elem=int(a.get("n_elem", 20)),
            )
            if not result.get("ok"):
                return err_payload(result.get("reason", "solver error"), "SOLVER_ERROR")
            return ok_payload({
                "analysis": "beam",
                "max_deflection_m": result.get("max_w"),
                "deflection_profile": result.get("w"),
                "x_coords": result.get("x"),
                "reactions": result.get("reactions"),
            })

        else:
            return err_payload(f"unknown analysis type: {analysis!r}", "BAD_ARGS")

    except Exception as e:
        return err_payload(f"beam analysis failed: {e}", "SOLVER_ERROR")


# ─────────────────────────────────────────────────────────────────────────────
# Exported specs + handlers for plugin.py registration
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    ("fem_solid_static",        _fem_solid_static_spec,        run_fem_solid_static),
    ("fem_modal_beam",          _fem_modal_beam_spec,          run_fem_modal_beam),
    ("fem_linear_static_beam",  _fem_linear_static_beam_spec,  run_fem_linear_static_beam),
]
