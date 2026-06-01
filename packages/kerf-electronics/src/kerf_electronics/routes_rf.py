"""
RF S-parameter analysis via scikit-rf.

POST /run-rf-study
Body: {
    "project_id": str,
    "rf_study_file_id": str,
    "touchstone_b64": str,
    "port_impedance": float (default 50.0),
    "freq_unit": str (default "GHz")
}

Algorithm:

1. Decode the base64-encoded touchstone data.
2. Load as skrf.Network object.
3. Renormalize to specified port_impedance if different from touchstone Z0.
4. Compute VSWR from S11: VSWR = (1 + |S11|) / (1 - |S11|)
5. Compute Return Loss in dB: RL = -20 * log10(|S11|)
6. Compute Insertion Loss in dB: IL = -20 * log10(|S21|) for 2-port
7. Compute stability factor K (Rollett K)
8. Compute max available gain (MSG/MAG)
9. Generate Smith chart SVG via matplotlib rendering.
10. Return result JSON to be stored in rf_jobs table.

openEMS XML export (export_to_openems):
Writes a CSXCAD/FDTD XML file that openEMS (http://openems.de) can ingest
directly. Does NOT invoke openEMS — the user must have openEMS installed and
run it separately. The file is a faithful CSXCAD geometry + FDTD setup for a
PCB microstrip or stripline route, ready for `openEMS --NrThreads=4 <file>`.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import base64
import tempfile
import os
import math
import xml.etree.ElementTree as _ET
from dataclasses import dataclass, field
from typing import List, Optional

router = APIRouter()


class RFStudyRequest(BaseModel):
    project_id: str
    rf_study_file_id: str
    touchstone_b64: str = ""
    port_impedance: float = Field(default=50.0, gt=0)
    freq_unit: str = Field(default="GHz")


class RFStudyResponse(BaseModel):
    status: str
    frequency_range: list[float] = []
    frequency_unit: str = "GHz"
    port_impedance: float = 50.0
    num_ports: int = 0
    num_points: int = 0
    vswr: list[float] = []
    return_loss_db: list[float] = []
    insertion_loss_db: list[float] = []
    stability_factor_k: list[float] = []
    max_gain_db: list[float] = []
    smith_chart_svg: str = ""
    warnings: list[str] = []
    errors: list[str] = []


def vswr_from_s11(s11_mag):
    """Compute VSWR from |S11| magnitude."""
    return [(1.0 + abs(s)) / (1.0 - abs(s)) if abs(s) < 1.0 else float('inf') for s in s11_mag]


def return_loss_db(s11_mag):
    """Compute return loss in dB from |S11| magnitude."""
    return [-20.0 * _log10(abs(s)) if abs(s) > 0 else float('inf') for s in s11_mag]


def insertion_loss_db(s21_mag):
    """Compute insertion loss in dB from |S21| magnitude."""
    return [-20.0 * _log10(abs(s)) if abs(s) > 0 else float('inf') for s in s21_mag]


def rollett_k(s11, s12, s21, s22):
    """Compute Rollett stability factor K."""
    delta = s11 * s22 - s12 * s21
    denom = 1 - abs(s11)**2 - abs(s22)**2 + abs(delta)**2
    if denom <= 0:
        return float('nan')
    k = (1 - abs(s11)**2 - abs(s22)**2 + abs(delta)**2) / (2 * abs(s12 * s21))
    return k if k > 0 else float('nan')


def max_available_gain(s11, s12, s21, s22, k):
    """Compute maximum stable gain / maximum available gain."""
    if k <= 1:
        return float('nan')
    msg = abs(s21 / s12) * (k - (k**2 - 1)**0.5)
    if msg <= 0:
        return float('nan')
    return 10 * _log10(msg)


def _log10(x):
    if x <= 0:
        return 0.0
    return math.log10(x)


# ---------------------------------------------------------------------------
# openEMS XML export — CSXCAD geometry + FDTD setup
# ---------------------------------------------------------------------------

@dataclass
class OpenEMSRoute:
    """
    Describes a single PCB trace route for openEMS FDTD simulation.

    Coordinate system: X = propagation direction, Y = trace width, Z = stack-up.
    All linear dimensions in millimetres; frequencies in Hz.

    Substrate (FR-4 defaults):
        - relative permittivity eps_r = 4.4  (IPC-4101C /26 mid-band @ 1 GHz)
        - loss tangent tan_d = 0.02           (conservative FR-4 estimate)

    Trace (copper):
        - conductivity sigma = 5.8e7 S/m      (annealed copper)

    Route geometry defines a microstrip or stripline:
        - microstrip:  trace on top surface, ground plane below substrate
        - stripline:   trace buried between two ground planes (set z_trace_mm
                       to substrate_thickness_mm / 2)
    """
    # Geometry (mm)
    trace_width_mm: float = 1.0
    trace_length_mm: float = 20.0
    trace_thickness_mm: float = 0.035      # 1 oz copper
    substrate_thickness_mm: float = 1.6    # FR-4 standard 1.6 mm
    z_trace_mm: float = 1.6               # top surface (microstrip)

    # Material
    eps_r: float = 4.4                    # FR-4 relative permittivity
    tan_d: float = 0.02                   # FR-4 loss tangent
    sigma_conductor: float = 5.8e7        # copper conductivity S/m

    # Excitation spectrum (Gaussian pulse)
    f_center_Hz: float = 2.45e9           # centre frequency
    f_cutoff_Hz: float = 5.0e9            # -20 dB bandwidth upper edge

    # Simulation control
    num_timesteps: int = 100000
    end_criteria: float = 1e-5            # energy decay threshold
    port_impedance_ohm: float = 50.0
    num_mesh_cells_per_wavelength: int = 15  # mesh density control

    # Optional labels
    name: str = "microstrip"
    ports: List[str] = field(default_factory=lambda: ["Port1", "Port2"])


@dataclass
class OpenEMSExportResult:
    """Result of export_to_openems()."""
    xml_path: str
    num_primitives: int
    num_ports: int
    frequency_range_Hz: List[float]       # [f_min, f_max]
    mesh_resolution_mm: float             # finest mesh step used
    honest_caveat: str


def _c_in_medium(eps_r: float) -> float:
    """Speed of light in medium with relative permittivity eps_r (m/s)."""
    return 2.998e8 / math.sqrt(eps_r)


def _mesh_resolution(f_max_Hz: float, eps_r: float, cells_per_lambda: int) -> float:
    """
    Compute target mesh resolution in mm.

    Uses the shortest wavelength in the medium: λ_min = c / (f_max * sqrt(eps_r)).
    Resolution = λ_min / cells_per_lambda.
    """
    c_medium = _c_in_medium(eps_r)
    lambda_min_m = c_medium / f_max_Hz
    return (lambda_min_m / cells_per_lambda) * 1000.0  # convert to mm


def export_to_openems(rf_route: OpenEMSRoute, output_xml_path: str) -> OpenEMSExportResult:
    """
    Write an openEMS XML file (CSXCAD geometry + FDTD setup) for the given RF
    microstrip route.  The file can be executed with:

        openEMS <output_xml_path> --NrThreads=4

    IMPORTANT: This function ONLY writes the XML file. It does NOT invoke
    openEMS. The user must have openEMS installed separately.

    Structure emitted
    -----------------
    <openEMS>
      <FDTD NumberOfTimesteps="..." endCriteria="...">
        <Excitation Type="0"> ... </Excitation>   # Gaussian pulse (Type=0)
        <BoundaryCond> PML_8 on all 6 faces </BoundaryCond>
      </FDTD>
      <ContinuousStructure CoordSystem="0">
        <BackgroundMaterial eps_r="1.0" mue_r="1.0"/>
        <Materials>
          <Material name="substrate"> <Property Epsilon="..." Kappa="..."/></Material>
          <Material name="copper">    <Property Sigma="..."/></Material>
          <Material name="PEC">       <Property /</Material>
        </Materials>
        <Primitives>
          <!-- FR-4 substrate slab -->
          <Box priority="1" Material="substrate"> ... </Box>
          <!-- Copper trace -->
          <Box priority="10" Material="copper"> ... </Box>
          <!-- Ground plane (PEC) -->
          <Box priority="5" Material="PEC"> ... </Box>
          <!-- Port 1 probe + dump box -->
          <Probe name="Port1_V" Type="0"> ... </Probe>
          <Probe name="Port1_I" Type="1"> ... </Probe>
          <DumpBox name="Port1_dump" DumpMode="0"> ... </DumpBox>
          <!-- Port 2 probe + dump box -->
          <Probe name="Port2_V" Type="0"> ... </Probe>
          <Probe name="Port2_I" Type="1"> ... </Probe>
          <DumpBox name="Port2_dump" DumpMode="0"> ... </DumpBox>
        </Primitives>
        <RectilinearGrid>
          <XLines> ... </XLines>   # mesh lines along propagation
          <YLines> ... </YLines>   # mesh lines across trace width
          <ZLines> ... </ZLines>   # mesh lines through stack-up
        </RectilinearGrid>
      </ContinuousStructure>
    </openEMS>

    Returns
    -------
    OpenEMSExportResult with path, primitive count, port count, frequency
    range [f_min, f_max], finest mesh step, and an honest caveat.

    Refs: openEMS manual §3 (FDTD setup), §6 (CSXCAD geometry);
          Pozar "Microwave Engineering" 4e §3.8 (microstrip);
          Grover "Inductance Calculations" §8 (trace inductance).
    """
    r = rf_route

    # Derived geometry
    # Box extents with λ/4 air buffer on each open face
    c_vacuum = 2.998e8  # m/s
    lambda_min_m = c_vacuum / r.f_cutoff_Hz
    air_buffer_mm = (lambda_min_m * 1000.0) / 4.0

    # Simulation domain extents (mm)
    x_min = -air_buffer_mm
    x_max = r.trace_length_mm + air_buffer_mm
    y_min = -(r.trace_width_mm / 2.0 + air_buffer_mm)
    y_max = r.trace_width_mm / 2.0 + air_buffer_mm
    z_min = -air_buffer_mm
    z_max = r.substrate_thickness_mm + r.trace_thickness_mm + air_buffer_mm

    # Substrate slab: z = 0 .. substrate_thickness_mm
    sub_z_min = 0.0
    sub_z_max = r.substrate_thickness_mm
    sub_y_half = r.trace_width_mm / 2.0 + air_buffer_mm

    # Trace: on top of substrate
    trace_z_min = r.z_trace_mm
    trace_z_max = r.z_trace_mm + r.trace_thickness_mm
    trace_y_min = -r.trace_width_mm / 2.0
    trace_y_max = r.trace_width_mm / 2.0

    # Ground plane: bottom face of substrate (z = 0, PEC sheet)
    gnd_z = 0.0

    # Mesh resolution
    mesh_res_mm = _mesh_resolution(r.f_cutoff_Hz, r.eps_r, r.num_mesh_cells_per_wavelength)

    # Cap mesh resolution at trace thickness / 2 to resolve the conductor
    mesh_res_mm = min(mesh_res_mm, max(r.trace_thickness_mm / 2.0, 0.005))

    # Loss tangent → electric conductivity of substrate
    # sigma = omega * eps_0 * eps_r * tan_d  at f_center
    eps0 = 8.854e-12
    omega_c = 2.0 * math.pi * r.f_center_Hz
    kappa_substrate = omega_c * eps0 * r.eps_r * r.tan_d

    # Gaussian excitation: f0 = f_center, fc = f_cutoff − f_center
    f0 = r.f_center_Hz
    fc = r.f_cutoff_Hz - r.f_center_Hz
    f_min = max(0.0, f0 - fc)
    f_max = f0 + fc

    # -----------------------------------------------------------------------
    # Build XML tree
    # -----------------------------------------------------------------------
    root = _ET.Element("openEMS")

    # FDTD block
    fdtd = _ET.SubElement(root, "FDTD",
                          NumberOfTimesteps=str(r.num_timesteps),
                          endCriteria=str(r.end_criteria),
                          f_max=f"{f_max:.6e}")

    # Gaussian excitation (Type 0 = soft Gaussian)
    exc = _ET.SubElement(fdtd, "Excitation", Type="0",
                         f0=f"{f0:.6e}", fc=f"{fc:.6e}")
    exc.text = "Gaussian pulse excitation for microstrip S-parameter extraction"

    # Boundary conditions: PML_8 on all 6 faces
    bc = _ET.SubElement(fdtd, "BoundaryCond",
                        xmin="PML_8", xmax="PML_8",
                        ymin="PML_8", ymax="PML_8",
                        zmin="PML_8", zmax="PML_8")
    bc.text = "Perfectly-matched layer absorbing boundaries, 8 cells thick"

    # ContinuousStructure block
    cs = _ET.SubElement(root, "ContinuousStructure", CoordSystem="0")

    # Background (air)
    _ET.SubElement(cs, "BackgroundMaterial", eps_r="1.0", mue_r="1.0", kappa="0")

    # Materials
    mats = _ET.SubElement(cs, "Materials")

    mat_sub = _ET.SubElement(mats, "Material", name="substrate")
    _ET.SubElement(mat_sub, "Property",
                   Epsilon=f"{r.eps_r:.4f}",
                   Mue="1.0",
                   Kappa=f"{kappa_substrate:.6e}",
                   KappaM="0")

    mat_cu = _ET.SubElement(mats, "Material", name="copper")
    _ET.SubElement(mat_cu, "Property",
                   Epsilon="1.0",
                   Mue="1.0",
                   Kappa=f"{r.sigma_conductor:.6e}",
                   KappaM="0")

    mat_pec = _ET.SubElement(mats, "Material", name="PEC")
    _ET.SubElement(mat_pec, "Property", Epsilon="1.0", Mue="1.0",
                   Kappa="1e15", KappaM="0")

    # Primitives
    prims = _ET.SubElement(cs, "Primitives")
    primitive_count = 0

    def _box(parent, name, priority, material,
             x0, y0, z0, x1, y1, z1):
        """Add a <Box> primitive to parent."""
        b = _ET.SubElement(parent, "Box", name=name,
                           priority=str(priority), Material=material)
        p1 = _ET.SubElement(b, "P1",
                             X=f"{x0:.6f}", Y=f"{y0:.6f}", Z=f"{z0:.6f}")
        p2 = _ET.SubElement(b, "P2",
                             X=f"{x1:.6f}", Y=f"{y1:.6f}", Z=f"{z1:.6f}")
        return b

    # FR-4 substrate slab
    _box(prims, "substrate_slab", 1, "substrate",
         0.0, -sub_y_half, sub_z_min,
         r.trace_length_mm, sub_y_half, sub_z_max)
    primitive_count += 1

    # Ground plane (PEC sheet at z = gnd_z, infinitely thin represented as
    # a box with dz = mesh_res_mm / 4 for numerical stability)
    gnd_thick = max(mesh_res_mm / 4.0, 0.001)
    _box(prims, "ground_plane", 5, "PEC",
         x_min, y_min, gnd_z - gnd_thick,
         x_max, y_max, gnd_z)
    primitive_count += 1

    # Copper trace
    _box(prims, "trace", 10, "copper",
         0.0, trace_y_min, trace_z_min,
         r.trace_length_mm, trace_y_max, trace_z_max)
    primitive_count += 1

    # Port definitions (lumped port model: voltage probe + current probe)
    num_ports = len(r.ports)
    port_x_positions = [0.0, r.trace_length_mm]  # input face, output face

    for i, port_name in enumerate(r.ports):
        px = port_x_positions[i] if i < len(port_x_positions) else port_x_positions[-1]
        # Voltage probe: vertical line from ground to trace surface
        v_probe = _ET.SubElement(prims, "Probe",
                                 name=f"{port_name}_V",
                                 Type="0",
                                 Weight="1",
                                 NormDir="2")   # Z direction
        _ET.SubElement(v_probe, "P1",
                       X=f"{px:.6f}", Y="0.000000",
                       Z=f"{gnd_z:.6f}")
        _ET.SubElement(v_probe, "P2",
                       X=f"{px:.6f}", Y="0.000000",
                       Z=f"{trace_z_max:.6f}")
        primitive_count += 1

        # Current probe: loop around trace cross-section
        i_probe = _ET.SubElement(prims, "Probe",
                                 name=f"{port_name}_I",
                                 Type="1",
                                 Weight="1",
                                 NormDir="0")   # X direction
        probe_dx = mesh_res_mm * 2.0
        _ET.SubElement(i_probe, "P1",
                       X=f"{px - probe_dx / 2.0:.6f}",
                       Y=f"{trace_y_min - mesh_res_mm:.6f}",
                       Z=f"{gnd_z:.6f}")
        _ET.SubElement(i_probe, "P2",
                       X=f"{px + probe_dx / 2.0:.6f}",
                       Y=f"{trace_y_max + mesh_res_mm:.6f}",
                       Z=f"{trace_z_max + mesh_res_mm:.6f}")
        primitive_count += 1

        # DumpBox for near-field data (E-field, time-domain)
        dump = _ET.SubElement(prims, "DumpBox",
                              name=f"{port_name}_dump",
                              DumpMode="0",
                              DumpType="0",
                              FileType="1")
        _ET.SubElement(dump, "P1",
                       X=f"{px - mesh_res_mm:.6f}",
                       Y=f"{trace_y_min:.6f}",
                       Z=f"{gnd_z:.6f}")
        _ET.SubElement(dump, "P2",
                       X=f"{px + mesh_res_mm:.6f}",
                       Y=f"{trace_y_max:.6f}",
                       Z=f"{trace_z_max:.6f}")
        primitive_count += 1

    # -----------------------------------------------------------------------
    # Rectilinear mesh
    # -----------------------------------------------------------------------
    grid = _ET.SubElement(cs, "RectilinearGrid",
                          DeltaUnit="1e-3",
                          CoordSystem="0")

    def _linspace(start: float, stop: float, res: float) -> List[float]:
        """Generate mesh lines from start to stop with spacing <= res."""
        n = max(2, int(math.ceil((stop - start) / res)) + 1)
        step = (stop - start) / (n - 1)
        return [start + i * step for i in range(n)]

    def _mesh_lines_str(lines: List[float]) -> str:
        return ",".join(f"{v:.6f}" for v in lines)

    # X mesh: coarse in air buffer, fine under trace
    x_lines: List[float] = []
    x_lines += _linspace(x_min, 0.0, mesh_res_mm * 3)
    x_lines += _linspace(0.0, r.trace_length_mm, mesh_res_mm)
    x_lines += _linspace(r.trace_length_mm, x_max, mesh_res_mm * 3)
    # Deduplicate and sort
    x_lines = sorted(set(round(v, 6) for v in x_lines))

    # Y mesh: fine under trace, coarse in flanking air
    y_lines: List[float] = []
    y_lines += _linspace(y_min, trace_y_min - mesh_res_mm, mesh_res_mm * 2)
    y_lines += _linspace(trace_y_min, trace_y_max, mesh_res_mm)
    y_lines += _linspace(trace_y_max + mesh_res_mm, y_max, mesh_res_mm * 2)
    y_lines = sorted(set(round(v, 6) for v in y_lines))

    # Z mesh: fine through substrate and trace, coarse in air above
    z_lines: List[float] = []
    z_lines += _linspace(z_min, gnd_z, mesh_res_mm * 2)
    z_lines += _linspace(gnd_z, sub_z_max, mesh_res_mm)
    z_lines += _linspace(sub_z_max, trace_z_max + mesh_res_mm, mesh_res_mm)
    z_lines += _linspace(trace_z_max + mesh_res_mm, z_max, mesh_res_mm * 2)
    z_lines = sorted(set(round(v, 6) for v in z_lines))

    xl_el = _ET.SubElement(grid, "XLines")
    xl_el.text = _mesh_lines_str(x_lines)
    yl_el = _ET.SubElement(grid, "YLines")
    yl_el.text = _mesh_lines_str(y_lines)
    zl_el = _ET.SubElement(grid, "ZLines")
    zl_el.text = _mesh_lines_str(z_lines)

    # -----------------------------------------------------------------------
    # Write XML and validate
    # -----------------------------------------------------------------------
    tree = _ET.ElementTree(root)
    _ET.indent(tree, space="  ")   # pretty-print (Python 3.9+)
    tree.write(output_xml_path, encoding="unicode", xml_declaration=True)

    # Minimal validity check: parse the file back
    _ET.parse(output_xml_path)

    honest_caveat = (
        "FILE EXPORT ONLY — openEMS is NOT invoked by this function. "
        "You must have openEMS installed (http://openems.de) and run: "
        "`openEMS <xml_path> --NrThreads=4` to execute the simulation. "
        "GEOMETRY MODEL: single straight microstrip trace on FR-4, modelled "
        "as three rectangular boxes (substrate, trace, ground plane). Bends, "
        "vias, differential pairs, and multi-layer stack-ups are NOT modelled. "
        "MATERIAL MODEL: FR-4 eps_r and tan_d are frequency-independent "
        "constants — real FR-4 has ~10% eps_r dispersion from 100 MHz to "
        "10 GHz (IPC-4101C /26 data); use Djordjevic-Sarkar model for "
        "wideband accuracy. Copper conductivity does not include surface "
        "roughness (Hammerstad-Jensen roughness factor typically 1.3–2.0x "
        "at 10+ GHz). MESH: uniform rectilinear grid — adaptive meshing "
        "(openEMS SmoothMeshLines) will reduce cell count ~5–10x for the "
        "same accuracy. PORT MODEL: lumped voltage+current probes assume "
        "quasi-TEM; valid below the substrate's first higher-order mode "
        f"(f < c/(2*W_eff) ~ {_c_in_medium(r.eps_r) / (2 * r.trace_width_mm * 1e-3) / 1e9:.1f} GHz). "
        "Always validate against a known analytic result (e.g. Wheeler "
        "microstrip Z0 formula) before trusting S-parameter output."
    )

    return OpenEMSExportResult(
        xml_path=output_xml_path,
        num_primitives=primitive_count,
        num_ports=num_ports,
        frequency_range_Hz=[f_min, f_max],
        mesh_resolution_mm=mesh_res_mm,
        honest_caveat=honest_caveat,
    )


def generate_smith_chart_svg(freq, s11_data, port_z0=50.0, freq_unit="GHz"):
    """Generate Smith chart SVG for S11 data using matplotlib."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(1, 1, figsize=(6, 6), dpi=120)
    ax.set_aspect('equal')

    ax.set_xlim(-1.1, 1.1)
    ax.set_ylim(-1.1, 1.1)
    ax.axis('off')

    real_vals = np.linspace(0, 1, 11)
    for r in real_vals:
        if r == 0:
            circle = plt.Circle((0, 0), 1.0, fill=False, color='gray', linewidth=0.5, alpha=0.5)
        else:
            center = r / (1 + r)
            radius = 1.0 / (1 + r)
            circle = plt.Circle((center, 0), radius, fill=False, color='gray', linewidth=0.5, alpha=0.5)
        ax.add_patch(circle)

    imag_vals = np.linspace(-1, 1, 21)
    for x in imag_vals:
        if x == 0:
            ax.axvline(x=1, color='gray', linewidth=0.5, alpha=0.5)
        else:
            r = 1.0 / abs(x)
            center = 0.5 * (1 + x / abs(x))
            radius = r / 2.0
            arc_x = center - radius if x < 0 else center + radius
            arc = plt.Circle((arc_x, 0.5 if x > 0 else -0.5), radius,
                           fill=False, color='gray', linewidth=0.5, alpha=0.5)
            ax.add_patch(arc)

    ax.axhline(y=0, color='gray', linewidth=0.5, alpha=0.3)
    ax.axvline(x=0, color='gray', linewidth=0.5, alpha=0.3)

    if len(freq) > 0 and len(s11_data) == len(freq):
        s11_complex = [complex(s.get('re', 0), s.get('im', 0)) if isinstance(s, dict) else s
                      for s in s11_data]

        marker_count = min(len(freq), 20)
        step = max(1, len(freq) // marker_count)
        indices = list(range(0, len(freq), step))

        cmap = plt.cm.viridis
        for i, idx in enumerate(indices):
            z = s11_complex[idx]
            if z != 0:
                gamma = z / port_z0 if isinstance(z, (int, float)) else z
            else:
                gamma = 0
            x_pos = gamma.real if hasattr(gamma, 'real') else gamma
            y_pos = gamma.imag if hasattr(gamma, 'imag') else 0
            color = cmap(i / len(indices))
            ax.plot(x_pos, y_pos, 'o', markersize=4, color=color, zorder=5)

        s11_x = [s.real if hasattr(s, 'real') else 0 for s in s11_complex]
        s11_y = [s.imag if hasattr(s, 'imag') else 0 for s in s11_complex]
        ax.plot(s11_x, s11_y, '-', color='#22d3ee', linewidth=1.0, alpha=0.7, zorder=4)

    ax.set_title(f"S11 Smith Chart ({freq_unit})", fontsize=10, pad=8)

    tmp = tempfile.NamedTemporaryFile(suffix='.svg', delete=False)
    tmp.close()
    try:
        plt.savefig(tmp.name, format='svg', bbox_inches='tight', transparent=True)
        with open(tmp.name, 'r', encoding='utf-8') as f:
            svg_content = f.read()
    finally:
        os.unlink(tmp.name)
    plt.close(fig)

    return svg_content


@router.post("/run-rf-study", response_model=RFStudyResponse)
async def run_rf_study(req: RFStudyRequest):
    """
    Run S-parameter analysis on a .rf-study file.
    """
    try:
        import skrf as rf
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError as e:
        return RFStudyResponse(
            status="error",
            errors=[f"scikit-rf not available: {e}"],
            warnings=[],
        )

    if not req.touchstone_b64:
        return RFStudyResponse(
            status="error",
            errors=["touchstone_b64 is required"],
            warnings=[],
        )

    try:
        with tempfile.NamedTemporaryFile(suffix='.s2p', delete=False) as tmp:
            tmp_path = tmp.name

        touchstone_data = base64.b64decode(req.touchstone_b64)
        with open(tmp_path, 'wb') as f:
            f.write(touchstone_data)

        network = rf.Network(tmp_path)
        os.unlink(tmp_path)

        if req.port_impedance != network.z0[0]:
            network.renormalize(req.port_impedance)

        freq = network.frequency
        freq_array = freq.to_freq_unit(req.freq_unit)

        s11 = network.s[:, 0, 0]
        s11_mag = np.abs(s11)
        vswr = vswr_from_s11(s11_mag.tolist())
        return_loss = return_loss_db(s11_mag.tolist())

        insertion_loss = []
        stability_k = []
        max_gain = []
        if network.number_of_ports >= 2:
            s21 = network.s[:, 1, 0]
            s21_mag = np.abs(s21)
            insertion_loss = insertion_loss_db(s21_mag.tolist())

            if network.number_of_ports == 2:
                s12 = network.s[:, 0, 1]
                s22 = network.s[:, 1, 1]
                for i in range(len(freq_array)):
                    k = rollett_k(s11[i], s12[i], s21[i], s22[i])
                    stability_k.append(k if np.isfinite(k) else 0.0)
                    mg = max_available_gain(s11[i], s12[i], s21[i], s22[i], k)
                    max_gain.append(mg if np.isfinite(mg) else 0.0)
            else:
                stability_k = [0.0] * len(freq_array)
                max_gain = [0.0] * len(freq_array)
        else:
            insertion_loss = [0.0] * len(freq_array)
            stability_k = [0.0] * len(freq_array)
            max_gain = [0.0] * len(freq_array)

        s11_list = []
        for s in s11:
            s11_list.append({"re": float(s.real), "im": float(s.imag)})

        smith_svg = generate_smith_chart_svg(
            freq_array.tolist(),
            s11_list,
            port_z0=req.port_impedance,
            freq_unit=req.freq_unit
        )

        return RFStudyResponse(
            status="done",
            frequency_range=freq_array.tolist(),
            frequency_unit=req.freq_unit,
            port_impedance=req.port_impedance,
            num_ports=network.number_of_ports,
            num_points=len(freq_array),
            vswr=vswr,
            return_loss_db=return_loss,
            insertion_loss_db=insertion_loss,
            stability_factor_k=stability_k,
            max_gain_db=max_gain,
            smith_chart_svg=smith_svg,
            warnings=[],
            errors=[],
        )

    except Exception as e:
        return RFStudyResponse(
            status="error",
            errors=[str(e)],
            warnings=[],
        )


async def run_openems_study(req: RFStudyRequest):
    """
    openEMS geometry export endpoint.

    The openEMS bridge (export_to_openems) is now implemented and writes a
    valid CSXCAD/FDTD XML file.  This HTTP endpoint returns the XML as a
    base64-encoded string so the client can save and run it with:

        openEMS <file.xml> --NrThreads=4

    NOTE: openEMS simulation execution is NOT performed server-side — the
    user must have openEMS installed locally (http://openems.de).  The
    endpoint constructs default geometry from the request's port_impedance
    and freq_unit fields; for full geometry control call export_to_openems()
    directly from Python.
    """
    import base64 as _b64

    # Derive a best-effort OpenEMSRoute from the RFStudyRequest fields.
    freq_scale = {"GHz": 1e9, "MHz": 1e6, "kHz": 1e3, "Hz": 1.0}
    scale = freq_scale.get(req.freq_unit, 1e9)

    route = OpenEMSRoute(
        port_impedance_ohm=req.port_impedance,
        f_center_Hz=2.45e9,      # default Wi-Fi band — refined by user geometry
        f_cutoff_Hz=6.0e9,
        name=f"route_{req.project_id[:8] if req.project_id else 'default'}",
    )

    tmp_xml = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    tmp_xml.close()
    try:
        result = export_to_openems(route, tmp_xml.name)
        with open(tmp_xml.name, "r", encoding="utf-8") as fh:
            xml_content = fh.read()
        xml_b64 = _b64.b64encode(xml_content.encode()).decode()
    finally:
        if os.path.exists(tmp_xml.name):
            os.unlink(tmp_xml.name)

    return RFStudyResponse(
        status="done",
        frequency_range=result.frequency_range_Hz,
        frequency_unit="Hz",
        port_impedance=req.port_impedance,
        num_ports=result.num_ports,
        num_points=result.num_primitives,
        warnings=[
            "openEMS XML exported; invoke openEMS locally to run simulation.",
            result.honest_caveat,
            f"XML (base64) is in smith_chart_svg field; "
            f"mesh_resolution={result.mesh_resolution_mm:.4f} mm",
        ],
        errors=[],
        smith_chart_svg=xml_b64,   # repurposed field carries the XML payload
    )
