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
      note: "Crown design (placeholder cylinder), surgical guide, DICOM ingest (backend); crown is placeholder"
      evidence: "packages/kerf-dental/src/kerf_dental/crown.py"
  - domain: D13
    feature: "Crown and bridge design"
    competitor:
      status: yes
      note: "Parametric crown/bridge with AI design proposal; virtual articulator; screw-retained and standard crowns"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
      note: "Crown geometry tool (backend); crown is a placeholder cylinder not a full restoration design tool"
      evidence: "packages/kerf-dental/src/kerf_dental/crown.py"
  - domain: D13
    feature: "Implant planning"
    competitor:
      status: yes
      note: "Full implant planning with 100+ implant libraries; implant bar and bridge; abutment design"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
      note: "Implant guide geometry (backend); no implant library integration"
      evidence: "packages/kerf-dental/src/kerf_dental/guide.py"
  - domain: D13
    feature: "Surgical guide design"
    competitor:
      status: yes
      note: "Guided surgery workflow with TRIOS integration; ToothDesigner and surgical guide output"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
      note: "Surgical guide generation backend; wired but not UI-facing"
      evidence: "packages/kerf-dental/src/kerf_dental/guide.py"
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
      status: no
      note: "No removable denture design"
      evidence: ""
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
      status: no
      note: "No intraoral scanner integration"
      evidence: ""
  - domain: D13
    feature: "Lab management / manufacturing output"
    competitor:
      status: yes
      note: "3Shape Produce: sends designs to pre-integrated mills, 3D printers, lab partners in clicks"
      source: "https://www.3shape.com/en/software/dental-system"
    kerf:
      status: partial
      note: "STL export + FDM slicing for dental models; no dental mill post processor"
      evidence: "packages/kerf-dental/src/kerf_dental/tools.py"
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

3Shape Dental System is the dominant dental CAD platform for dental laboratories worldwide. It covers the full range of dental restorations: AI-assisted crown and bridge design, implant planning against a library of 100+ implant systems, removable partial dentures, full dentures, orthodontic clear aligners, occlusal splints, and surgical guides — all integrated with 3Shape's TRIOS intraoral scanner and 3Shape Produce manufacturing output. It is a dedicated dental technology platform. Kerf's dental module covers DICOM ingest, surgical guide geometry, and crown tooling — but the crown is currently a placeholder and there is no denture, aligner, or RPD capability. Kerf's value in dental is multi-domain: combining dental geometry with structural FEA, materials LCA, and biomedical engineering in one workspace.

## Where 3Shape is strong

- **Restoration design depth.** 3Shape's crown and bridge tools include AI design proposals via 3Shape Automate (~90 seconds to a clinically reasonable starting point), virtual articulator, screw-retained and standard crown options, and post/core abutment design. Kerf's crown is a placeholder cylinder.
- **100+ implant library.** Every major implant system's geometry, connection, and scan body. Kerf has no implant library.
- **Denture and RPD.** Full denture (complete and implant-retained) and removable partial denture design — major restorative categories that Kerf has no tooling for.
- **3Shape Produce / manufacturing.** Direct integration with dental mills (Sirona, Roland, Datron) and 3D printers; click-to-manufacture workflow. Kerf exports STL; no dental mill post processor.
- **TRIOS scanner ecosystem.** Native integration with one of the leading intraoral scanners plus support for third-party IOS formats. Kerf has no scanner integration.
- **Purpose-built dental AI.** 3Shape Automate's AI is trained on dental anatomy and produces clinically appropriate restoration proposals. Kerf's LLM-routed tool calls are general-purpose, not dental-specific.

## Where Kerf differs

- **MIT open-core.** 3Shape licensing is per-seat, per-module (not publicly listed; typically thousands per year per module). Kerf is MIT-licensed — free locally.
- **DICOM ingest.** Kerf has a DICOM ingest module for CBCT processing. 3Shape also supports DICOM, but Kerf's open DICOM pipeline can integrate with custom research and biomedical workflows.
- **Multi-domain workspace.** A biomedical engineer can combine Kerf's dental tools with structural FEA of a restorative implant system, materials LCA for biocompatible ceramics, and additive manufacturing simulation in one project. 3Shape is dental-only.
- **Chat-native.** Describe a restoration requirement in plain language; Kerf routes to the dental backend. 3Shape has no LLM interface.
- **Python scripting.** kerf-sdk on PyPI for dental tool automation. 3Shape has a limited API; not Python-native.

## Honest gaps — where Kerf is behind today

- **Crown is a placeholder.** Kerf's crown geometry tool generates a cylinder — not a clinically usable restoration. This is the most important gap for dental use.
- **No denture or RPD.** Two major dental categories missing entirely.
- **No implant library.** Without implant system geometry and connection data, implant planning is not clinically useful.
- **No scanner integration.** No way to import an intraoral scan directly from a TRIOS or third-party IOS.
- **No dental-specific AI.** Kerf's general LLM is not trained on dental anatomy.
- **No dental mill post processor.** Cannot drive a dental milling machine directly.

## Side by side

| Feature | Kerf | 3Shape Dental System |
|---|---|---|
| License | MIT open-core | Proprietary (per seat/module) |
| Primary focus | Multi-domain engineering CAD | Dental laboratory CAD |
| Crown / bridge design | Placeholder only | Full AI-assisted |
| Implant planning | Backend (no library) | 100+ implant libraries |
| Surgical guide | Backend | Yes |
| DICOM / CBCT ingest | Yes (backend) | Yes |
| Denture / RPD | No | Yes |
| Intraoral scanner | No | TRIOS native + IOS |
| AI restoration proposals | No | 3Shape Automate (~90s) |
| Manufacturing output | STL / FDM only | Direct mill/printer integration |
| Chat / LLM editing | Chat-native | None |
| Open source | Yes (MIT) | No |

---
*Last reviewed: 2026-05-24. Competitor information sourced from 3Shape Dental System and TRIOS Design Studio public product pages. Kerf capabilities reflect the current shipped product.*
