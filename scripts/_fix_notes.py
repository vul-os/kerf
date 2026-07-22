"""Fix flat-denial kerf notes left stale after status flips (status=yes but note
still says 'No <capability>'). Rewrites each to an honest one-line description of
what actually shipped. Matched by (slug, feature-name). Frontmatter-only edit.
"""
import re, glob, os

# (slug, feature-substring) -> honest note
FIX = {
    ("revit", "Dynamo visual programming"): "NodeGraphCanvas visual node editor + kerf-sdk Python scripting",
    ("vectorworks", "Visual scripting (Marionette)"): "NodeGraphCanvas node editor + Marionette engine (marionette.py)",
    ("rhino", "Visual node scripting"): "NodeGraphCanvas visual node environment + kerf-sdk",
    ("matrixgold", "Jewelry — parametric visual scripting"): "NodeGraphCanvas node editor + Marionette + kerf-sdk Python",
    ("civil3d", "Point cloud integration"): "LAS/XYZ/PLY ingest + voxel downsample + PMF ground classification → TIN",
    ("civil3d", "Plan and profile sheet production"): "Automated plan+profile sheet generator (station grid, profile band, match lines)",
    ("artioscad", "Print pre-press / graphics integration"): "ISO 15930-1 PDF/X-1a export + registration marks + bleed/safety check",
    ("cimatron", "Mold base library"): "DME/HASCO/Misumi mold-base catalogue + 7-plate stack",
    ("cimatron", "Electrode design (EDM)"): "EDM electrode extraction + spark-gap offset + burn sequence",
    ("cimatron", "Wire EDM"): "Wire-EDM 4-axis taper toolpath + G41/G42 G-code",
    ("fibersim", "AFP / ATL manufacturing path output"): "AFP/ATL fibre-placement paths + G-code (M200-M204) / APT-CL export",
    ("fibersim", "Laser projection / flat pattern export"): "Laser projection + flat-pattern ply export (laser_projection.py)",
    ("mozaik", "Cabinet / room layout design"): "Cabinet room layout (CabinetPlacement) + cut-list generation",
    ("adams", "Flexible bodies (FEA mode shapes)"): "Craig-Bampton flexible-body MBD (modal reduction, flexible_body.py)",
    ("adams", "Vehicle dynamics (Adams/Car)"): "Pacejka Magic-Formula tire + vehicle dynamics (vehicle_dynamics.py)",
    ("adams", "Gear / belt / chain machinery (Adams/Machinery)"): "Litvin gear/belt machinery dynamics (kerf-mates machinery)",
    ("gmat", "Libration point orbit design"): "CR3BP libration orbits: halo/Lyapunov/Lissajous (Richardson/Howell)",
    ("zemax", "Multiphysics STOP analysis (thermal + structural)"): "STOP multiphysics (Doyle-Genberg 2002) wired",
    ("zemax", "Metalens design"): "Metalens design (Khorasaninejad 2016 hyperbolic phase)",
    ("blender", "Animation / rigging"): "Keyframe FCurves + armature poser + CCD/FABRIK IK",
    ("max3ds", "Thermal / fluid — visual fluid simulation (Phoenix FD)"): "Visual fluid simulation (Phoenix-FD-equivalent) + CFD suite",
    ("max3ds", "Dynamics — skeletal animation and rigging"): "Armature poser + CCD/FABRIK IK + keyframe animation",
    ("zbrush", "Geometry & core CAD — organic mesh sculpting"): "Sculpt brushes (grab/smooth/inflate/crease/pinch) + dynamesh remesh",
    ("zbrush", "Verticals — character / creature / film VFX"): "Sculpt + dynamesh + auto-weight + LBS pose (sculpt_extended_tools)",
    ("zbrush", "Verticals — texture / polypaint / displacement"): "Polypaint stroke/bake + displacement bake",
    ("ies-ve", "Daylighting + solar radiation simulation"): "Daylighting (CIE S 011 sky) + lux/luminance sim (luminance_lux_sim.py)",
}

NAME_RE = re.compile(r'^\s*(?:-\s*)?(?:feature|name)\s*:\s*"?([^"\n]+?)"?\s*$')
fixed = 0
for path in sorted(glob.glob("public/compare/*.md")):
    slug = os.path.basename(path)[:-3]
    lines = open(path, encoding="utf-8").read().split("\n")
    if not lines or lines[0].strip() != "---":
        continue
    fm_end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    cur_feat = None
    side = None
    for i in range(1, fm_end):
        ln = lines[i]
        m = NAME_RE.match(ln)
        s = ln.strip()
        if m and ("feature:" in s or "name:" in s) and not s.startswith(("status", "note", "evidence")):
            cur_feat = m.group(1).strip()
            side = None
            continue
        if re.match(r'^\s{4}kerf:\s*$', ln):
            side = 'kerf'; continue
        if re.match(r'^\s{4}competitor:\s*$', ln):
            side = 'competitor'; continue
        if side == 'kerf' and cur_feat is not None:
            mn = re.match(r'^(\s*)note:\s*', ln)
            if mn:
                for (fslug, ffeat), newnote in FIX.items():
                    if fslug == slug and cur_feat == ffeat:
                        lines[i] = f'{mn.group(1)}note: "{newnote}"'
                        fixed += 1
                        break
    open(path, "w", encoding="utf-8").write("\n".join(lines))
print(f"fixed {fixed} stale-denial notes")
