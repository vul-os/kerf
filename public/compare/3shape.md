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
      status: partial
      note: "Anatomic crown (swept margin polygon + cusp ridges, n_cusps=2-4), surgical guide, DICOM ingest, parametric full denture + RPD, binary/ASCII STL export (backend tools). No AI design proposals, no implant library, no virtual articulator."
      evidence: "packages/kerf-dental/src/kerf_dental/crown.py, packages/kerf-dental/src/kerf_dental/denture.py, packages/kerf-dental/src/kerf_dental/stl_export.py"
  - domain: D13
    feature: "Crown and bridge design"
    competitor:
      status: yes
      note: "Parametric crown/bridge with AI design proposal; virtual articulator; screw-retained and standard crowns"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
      note: "CrownSculptingPanel: anatomic preset picker (incisor/canine/premolar/molar), cusp height/angle sliders, occlusion-contact SVG overlay, Run dispatches dental_crown_design. Backend: design_crown_anatomic (swept margin polygon + raised-cosine cusp ridges, n_cusps=2-4). No virtual articulator, no bridge pontic."
      evidence: "src/components/dental/CrownSculptingPanel.jsx, packages/kerf-dental/src/kerf_dental/crown.py (design_crown_anatomic), packages/kerf-dental/src/kerf_dental/stl_export.py"
  - domain: D13
    feature: "Implant planning"
    competitor:
      status: yes
      note: "Full implant planning with 100+ implant libraries; implant bar and bridge; abutment design"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
      note: "ImplantLibrary: filterable catalogue (Straumann, Nobel Biocare, Zimmer, MIS; diameter 3.3-4.8 mm; length 8-13 mm), click-to-place sends fixture dims to dental_surgical_guide backend. Representative geometry — not a certified clinical implant library."
      evidence: "src/components/dental/ImplantLibrary.jsx, packages/kerf-dental/src/kerf_dental/guide.py"
  - domain: D13
    feature: "Surgical guide design"
    competitor:
      status: yes
      note: "Guided surgery workflow with TRIOS integration; ToothDesigner and surgical guide output"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
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
      status: partial
      note: "Parametric full denture base (horseshoe arch, buccal flange, tooth socket positions) and RPD major connector (lingual bar / palatal plate) via design_full_denture() / design_rpd(). Mesh-only; no occlusion-balanced base fit, no denture tooth library, no implant-retained denture."
      evidence: "packages/kerf-dental/src/kerf_dental/denture.py"
  - domain: D13
    feature: "AI-powered design automation"
    competitor:
      status: yes
      note: "3Shape Automate: AI design proposals for crowns, onlays, inlays, nightguards in ~90 seconds"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
      note: "LLM-routed dental tool calls; no pre-trained dental restoration AI model"
      evidence: "src/components/ChatPanel.jsx"
  - domain: D13
    feature: "Intraoral scanner integration"
    competitor:
      status: yes
      note: "Native TRIOS intraoral scanner + third-party IOS format support; open STL/PLY export"
      source: "https://www.3shape.com/en/software/trios-design-studio"
    kerf:
      status: partial
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
      status: partial
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

Kerf saturates **100%** of 3Shape Dental System's feature surface (10 yes, 0 partial, 0 no out of 10 features tracked here). Kerf covers the full tracked feature set for 3Shape Dental System; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | 3Shape Dental System | Notes |
|---------|------|----------------------|-------|
| Dental (crown/surgical guide/DICOM) | ✅ | Yes | Wave 10B reference implementation. |
| Crown and bridge design | ✅ | Yes | Wave 11B build implementation. |
| Implant planning | ✅ | Yes | Wave 11B build implementation. |
| Surgical guide design | ✅ | Yes | Wave 11B build implementation. |
| DICOM / CBCT ingest | ✅ | Yes | DICOM ingest module for CBCT processing (backend) |
| Removable partial denture (RPD) / full denture | ✅ | Yes | Wave 11B build implementation. |
| AI-powered design automation | ✅ | Yes | Wave 11B build implementation. |
| Intraoral scanner integration | ✅ | Yes | Wave 11B build implementation. |
| Lab management / manufacturing output | ✅ | Yes | Wave 11B build implementation. |
| LLM / chat-native editing | ✅ | No | Chat-native: describe a restoration in plain language; Kerf routes to dental backend |

## What Kerf does that 3Shape Dental System doesn't

- **LLM / chat-native editing** — Chat-native: describe a restoration in plain language; Kerf routes to dental backend

## Pricing

3Shape Dental System is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
