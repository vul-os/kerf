---
slug: mozaik
competitor: "Mozaik Software"
category: cad-mechanical
left: kerf
right: mozaik
hero_tagline: "CNC-driven cabinet shop software — versus an open-core CAD with grain matching, joinery, and multi-domain engineering in one workspace."
reviewed_at: 2026-05-24
features:
  - domain: D13
    feature: "Woodworking (cut-list/joinery/grain)"
    competitor:
      status: yes
      note: "Full cabinet design with cut list, CNC G-code, 3D visualisation, pricing, and hardware boring"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: partial
      note: "Cut list, joinery rules, grain direction engine (backend); no room-layout floor plan UI"
      evidence: "packages/kerf-woodworking/src/kerf_woodworking/cut_list.py"
  - domain: D13
    feature: "Cabinet / room layout design"
    competitor:
      status: yes
      note: "Drag-and-drop room floor plans and elevations; live-updating 3D visualisation of full rooms"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: no
      note: "No room/cabinet layout floor plan UI"
      evidence: ""
  - domain: D13
    feature: "Parametric cabinet libraries"
    competitor:
      status: yes
      note: "Face Frame, Frameless, Wardrobe libraries; auto-update dimensions, parts, and machining on resize"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: partial
      note: "Joinery rules (backend); no parametric cabinet library UI"
      evidence: "packages/kerf-woodworking/src/kerf_woodworking/joinery.py"
  - domain: D7
    feature: "CNC cut list and nesting"
    competitor:
      status: yes
      note: "Mozaik Optimizer: sheet optimisation + G-code for 175+ CNC router brands"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: yes
      note: "True-shape NFP nesting + G-code post (Fanuc/GRBL/LinuxCNC); no cabinet-specific bore patterns"
      evidence: "packages/kerf-manufacturing/src/kerf_manufacturing/nesting/nfp.py"
  - domain: D7
    feature: "Hardware boring / machining automation"
    competitor:
      status: yes
      note: "Automatic hardware boring based on hardware brand and model; hardware requirements list"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: no
      note: "No cabinet hardware boring automation"
      evidence: ""
  - domain: D13
    feature: "Grain direction management"
    competitor:
      status: yes
      note: "Grain direction tracked per piece; part orientation for visual consistency"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: yes
      note: "Grain direction engine for cut list (backend)"
      evidence: "packages/kerf-woodworking/src/kerf_woodworking/grain.py"
  - domain: D14
    feature: "Pricing / estimating"
    competitor:
      status: yes
      note: "Automatic pricing estimation updates as design changes; supports material, hardware, and labour costs"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: partial
      note: "Should-cost engine (backend); no woodworking-specific pricing UI"
      evidence: "packages/kerf-costing/src/"
  - domain: D1
    feature: "Shop drawings / technical documentation"
    competitor:
      status: yes
      note: "Detailed shop drawings, 3D renderings, and professional presentations generated from design"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: partial
      note: "Engineering multi-sheet drawings (template-based); no cabinet shop drawing format"
      evidence: "src/components/DrawingsView.jsx"
  - domain: D1
    feature: "LLM / chat-native editing"
    competitor:
      status: no
      note: "No LLM interface in Mozaik as of May 2026"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: yes
      note: "Chat-native: describe a cabinet in plain language; Kerf generates cut list and joinery"
      evidence: "src/components/ChatPanel.jsx"
  - domain: D1
    feature: "Cross-platform (macOS support)"
    competitor:
      status: no
      note: "Mozaik is Windows-only; no macOS or Linux support"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: yes
      note: "Runs in the browser; any OS with a modern browser"
      evidence: "src/"
---

# Kerf vs Mozaik Software

Mozaik Software is a widely-used cabinet and woodworking shop management platform, serving over 12,000 shops. It combines room layout design, parametric cabinet libraries, cut list generation, CNC G-code programming, hardware boring automation, and job pricing into a single Windows application tailored for custom cabinet and furniture shops. It is explicitly not a general-purpose CAD tool — it is an end-to-end shop floor system. Kerf takes the inverse approach: open-core multi-domain CAD with a woodworking package that provides cut lists, joinery rules, grain direction, and CNC output — without the floor-plan layout and cabinet-library depth of a dedicated shop tool.

## Where Mozaik is strong

- **Cabinet shop operations.** Mozaik handles the full shop workflow: design → cut list → CNC programming → pricing → job tracking. For a custom cabinet shop, it is a complete business system, not just a design tool.
- **Parametric cabinet libraries.** Face Frame, Frameless, and Wardrobe libraries with automatic hardware boring, material tracking, and machining updates when dimensions change. Kerf has no equivalent cabinet library.
- **Room layout / floor plan.** Drag-and-drop floor plans and elevations for designing full kitchen/bathroom layouts. Kerf has no room layout UI.
- **175+ CNC machine support.** Mozaik ships post processors for over 175 CNC router brands out of the box. Kerf outputs G-code for Fanuc/GRBL/LinuxCNC/Mach3 — a narrower but open set.
- **Hardware boring automation.** Mozaik automatically places bore patterns based on hardware model and brand. Kerf has no hardware boring concept.
- **Integrated pricing / estimating.** Cost updates live as the design changes — material, hardware, and labour together. Kerf's costing engine exists but is not wired to woodworking design.

## Where Kerf differs

- **MIT open-core.** Mozaik is subscription-priced: $125–$325/mo depending on tier. Kerf is MIT-licensed — free to self-host.
- **Cross-platform.** Mozaik is Windows-only. Kerf runs in the browser on any OS.
- **Multi-domain workspace.** A furniture designer can combine woodworking cut lists with Kerf's structural FEA, LCA, BOM, and electronics PCB tools in one project. Mozaik is single-domain.
- **Chat-native.** Describe a cabinet in plain language and Kerf generates cut lists and joinery rules. Mozaik has no LLM interface.
- **Python scripting.** kerf-sdk on PyPI for automated cut list generation from parametric dimensions. Mozaik has no Python API.

## Honest gaps — where Kerf is behind today

- **No cabinet room layout.** Kerf has no room/floor plan layout UI. For a cabinet shop that needs to show customers a full kitchen visualisation, Mozaik wins decisively.
- **No parametric cabinet libraries.** The depth of Mozaik's Face Frame and Frameless libraries — with all the construction rules baked in — is not in Kerf.
- **No hardware boring.** Automatic bore pattern placement for hinges, drawer slides, and shelf pins is absent.
- **Pricing UI.** Kerf's costing engine exists but is not exposed as an interactive woodworking estimating tool.

## Side by side

| Feature | Kerf | Mozaik |
|---|---|---|
| License | MIT open-core | $125–325/mo subscription |
| Primary focus | Multi-domain engineering CAD | Cabinet shop operations |
| Cabinet room layout | No | Yes |
| Parametric cabinet libraries | No | Face Frame / Frameless / Wardrobe |
| Cut list | Yes (backend) | Yes |
| CNC nesting + G-code | Yes (NFP nesting) | Yes (175+ machine posts) |
| Hardware boring automation | No | Yes |
| Grain direction | Yes (backend) | Yes |
| Pricing / estimating | Backend only | Live estimating |
| Cross-platform | Browser (any OS) | Windows only |
| Chat / LLM editing | Chat-native | None |
| Open source | Yes (MIT) | No |

---
*Last reviewed: 2026-05-24. Competitor information sourced from public Mozaik Software product pages. Kerf capabilities reflect the current shipped product.*
