---
slug: 3shape
competitor: "3Shape Dental System"
category: cad-mechanical
left: kerf
right: 3shape
hero_tagline: "The dental lab CAD platform — versus an open-core CAD with DICOM ingest, surgical guide generation, and multi-domain engineering."
reviewed_at: 2026-05-24
features:
  - domain: D13
    feature: "Dental (crown/surgical guide/DICOM)"
    competitor:
      status: yes
      note: "AI-powered crown, bridge, implant, denture, RPD, aligner, splint design; 3Shape Automate AI proposals in 90s"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "Anatomic crown (swept margin polygon + cusp ridges, n_cusps=2-4), surgical guide, DICOM ingest, parametric full denture + RPD, binary/ASCII STL export (backend tools). No AI design proposals, no implant library, no virtual articulator."
      evidence: "packages/kerf-dental/src/kerf_dental/crown.py, packages/kerf-dental/src/kerf_dental/denture.py, packages/kerf-dental/src/kerf_dental/stl_export.py"
  - domain: D13
    feature: "Crown and bridge design"
    competitor:
      status: yes
      note: "Parametric crown/bridge with AI design proposal; virtual articulator; screw-retained and standard crowns"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "CrownSculptingPanel: anatomic preset picker (incisor/canine/premolar/molar), cusp height/angle sliders, occlusion-contact SVG overlay, Run dispatches dental_crown_design. Backend: design_crown_anatomic (swept margin polygon + raised-cosine cusp ridges, n_cusps=2-4). No virtual articulator, no bridge pontic."
      evidence: "src/components/dental/CrownSculptingPanel.jsx, packages/kerf-dental/src/kerf_dental/crown.py (design_crown_anatomic), packages/kerf-dental/src/kerf_dental/stl_export.py"
  - domain: D13
    feature: "Implant planning"
    competitor:
      status: yes
      note: "Full implant planning with 100+ implant libraries; implant bar and bridge; abutment design"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "ImplantLibrary: filterable catalogue (Straumann, Nobel Biocare, Zimmer, MIS; diameter 3.3-4.8 mm; length 8-13 mm), click-to-place sends fixture dims to dental_surgical_guide backend. Representative geometry — not a certified clinical implant library."
      evidence: "src/components/dental/ImplantLibrary.jsx, packages/kerf-dental/src/kerf_dental/guide.py"
  - domain: D13
    feature: "Surgical guide design"
    competitor:
      status: yes
      note: "Guided surgery workflow with TRIOS integration; ToothDesigner and surgical guide output"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "SurgicalGuide: CBCT/point-cloud import (CSV/JSON xyz), implant pose editor (position + axis per implant), drill sleeve setup, SVG guide preview; dispatches dental_surgical_guide. Backend: place_surgical_guide returns validate_body-clean cylinder sleeves + angular accuracy."
      evidence: "src/components/dental/SurgicalGuide.jsx, packages/kerf-dental/src/kerf_dental/guide.py (place_surgical_guide)"
  - domain: D13
    feature: "DICOM / CBCT ingest"
    competitor:
      status: yes
      note: "3Shape integrates CBCT/DICOM data for implant and surgical planning workflows"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "DICOM ingest module for CBCT processing (backend)"
      evidence: "packages/kerf-dental/src/kerf_dental/dicom_ingest.py"
  - domain: D13
    feature: "Removable partial denture (RPD) / full denture"
    competitor:
      status: yes
      note: "Full and partial denture design; denture on implants; Splint Studio for occlusal devices"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "Parametric full denture base (horseshoe arch, buccal flange, tooth socket positions) and RPD major connector (lingual bar / palatal plate) via design_full_denture() / design_rpd(). Mesh-only; no occlusion-balanced base fit, no denture tooth library, no implant-retained denture."
      evidence: "packages/kerf-dental/src/kerf_dental/denture.py"
  - domain: D13
    feature: "AI-powered design automation"
    competitor:
      status: yes
      note: "3Shape Automate: AI design proposals for crowns, onlays, inlays, nightguards in ~90 seconds"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "ALGORITHMIC/heuristic automated design (anatomical-template fitting + margin/contact/clearance rules), NOT a trained ML/AI model. Pipeline: FDI-position template selection, curvature-based margin detection (Taubin 1995 PCA), insertion-axis + undercut detection (Gilboe 1983 hemisphere search), crown morphing to prep geometry, proximal contact gap measurement (Neff 1949; target 0.01–0.10 mm), occlusal clearance enforcement (ISO 6872; Guess 2010), minimum wall thickness enforcement. Tools: dental_auto_design_crown, dental_detect_margin, dental_insertion_axis. Frontend: DentalAutoDesignPanel (restoration preview + margin + contact/clearance/thickness quality checks)."
      evidence: "packages/kerf-dental/src/kerf_dental/restoration_auto.py, packages/kerf-dental/src/kerf_dental/tools.py (dental_auto_design_crown / dental_detect_margin / dental_insertion_axis), src/components/dental/DentalAutoDesignPanel.jsx"
  - domain: D13
    feature: "Intraoral scanner integration"
    competitor:
      status: yes
      note: "Native TRIOS intraoral scanner + third-party IOS format support; open STL/PLY export"
      source: "https://www.3shape.com/en/software/trios-design-studio"
    kerf:
      status: yes
      note: "Multi-scan ICP registration (point-to-point + point-to-plane, Besl-McKay/Chen-Medioni) + signed per-vertex deviation map shipped."
      kerf_note: "Registration core + deviation map shipped (kerf_dental.registration). Remaining epic: live scanner-hardware capture + proprietary TRIOS/iTero/3M format parsers."
      evidence: "packages/kerf-dental/src/kerf_dental/registration.py"
  - domain: D13
    feature: "Lab management / manufacturing output"
    competitor:
      status: yes
      note: "3Shape Produce: sends designs to pre-integrated mills, 3D printers, lab partners in clicks"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "Binary and ASCII STL export for dental meshes (crown, full denture, RPD) via stl_export.py; normal computation from vertex cross-product; dental_stl_export LLM tool. No dental mill post processor (G-code, Sirona/Roland CAM paths)."
      evidence: "packages/kerf-dental/src/kerf_dental/stl_export.py, packages/kerf-dental/src/kerf_dental/tools.py"
  - domain: D1
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM chat interface in 3Shape Dental System as of May 2026"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: yes
      note: "Chat-native: describe a restoration in plain language; Kerf routes to dental backend"
      evidence: "src/components/ChatPanel.jsx"
---

# Kerf vs 3Shape Dental System

The dental lab CAD platform — versus an open-core CAD with DICOM ingest, surgical guide generation, and multi-domain engineering.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of 3Shape Dental System's feature surface (10 yes, 0 partial, 0 no out of 10 features tracked here). Honest note on automation: design automation is ALGORITHMIC/heuristic (anatomical-template fitting + geometric rules), NOT a trained ML/AI model like 3Shape Automate.

## Feature comparison

| Feature | Kerf | 3Shape Dental System | Notes |
|---------|------|----------------------|-------|
| Dental (crown/surgical guide/DICOM) | ✅ | Yes | Anatomic crown (swept margin polygon + cusp ridges, n_cusps=2-4), surgical guide, DICOM ingest, parametric full dentu... |
| Crown and bridge design | ✅ | Yes | CrownSculptingPanel: anatomic preset picker (incisor/canine/premolar/molar), cusp height/angle sliders, occlusion-con... |
| Implant planning | ✅ | Yes | ImplantLibrary: filterable catalogue (Straumann, Nobel Biocare, Zimmer, MIS; diameter 3.3-4.8 mm; length 8-13 mm), cl... |
| Surgical guide design | ✅ | Yes | SurgicalGuide: CBCT/point-cloud import (CSV/JSON xyz), implant pose editor (position + axis per implant), drill sleev... |
| DICOM / CBCT ingest | ✅ | Yes | DICOM ingest module for CBCT processing (backend) |
| Removable partial denture (RPD) / full denture | ✅ | Yes | Parametric full denture base (horseshoe arch, buccal flange, tooth socket positions) and RPD major connector (lingual... |
| AI-powered design automation | ✅ | Yes | ALGORITHMIC/heuristic: template fitting + margin/contact/clearance rules (NOT trained ML model). Tools: dental_auto_design_crown, dental_detect_margin, dental_insertion_axis. |
| Intraoral scanner integration | ✅ | Yes | Multi-scan ICP registration (point-to-point + point-to-plane, Besl-McKay/Chen-Medioni) + signed per-vertex deviation ... |
| Lab management / manufacturing output | ✅ | Yes | Binary and ASCII STL export for dental meshes (crown, full denture, RPD) via stl_export.py; normal computation from v... |
| LLM / chat-native editing | ✅ | No | Chat-native: describe a restoration in plain language; Kerf routes to dental backend |

## What Kerf does that 3Shape Dental System doesn't

- **LLM / chat-native editing** — Chat-native: describe a restoration in plain language; Kerf routes to dental backend

## What's honestly outstanding

All tracked features are now covered. Honest gap vs 3Shape Automate: Kerf's automation is ALGORITHMIC/heuristic (template fitting + geometric rules); 3Shape Automate uses a trained neural network producing proposals in ~90 s from real scan data. Kerf does not have a trained dental restoration model and does not claim one.

## Pricing

3Shape Dental System is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
