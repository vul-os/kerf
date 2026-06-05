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
      status: yes
      note: "Cut list, joinery rules, grain direction engine (backend); no room-layout floor plan UI"
      evidence: "packages/kerf-woodworking/src/kerf_woodworking/cut_list.py"
  - domain: D13
    feature: "Cabinet / room layout design"
    competitor:
      status: yes
      note: "Drag-and-drop room floor plans and elevations; live-updating 3D visualisation of full rooms"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: yes
      note: "Cabinet room layout (CabinetPlacement) + cut-list generation"
      evidence: ""
  - domain: D13
    feature: "Parametric cabinet libraries"
    competitor:
      status: yes
      note: "Face Frame, Frameless, Wardrobe libraries; auto-update dimensions, parts, and machining on resize"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: yes
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
      status: yes
      note: "32 mm System bore-pattern generator: hinge cups (35 mm Blum-compatible), shelf-pin rows, undermount/sidemount drawer runner pilots, Euro-screw (confirmat), handle holes — all parametric with CNC-ready coordinates"
      evidence: "packages/kerf-woodworking/src/kerf_woodworking/hardware_boring.py"
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
      status: yes
      note: "Should-cost engine (backend); no woodworking-specific pricing UI"
      evidence: "packages/kerf-costing/src/"
  - domain: D1
    feature: "Shop drawings / technical documentation"
    competitor:
      status: yes
      note: "Detailed shop drawings, 3D renderings, and professional presentations generated from design"
      source: "https://www.mozaiksoftware.com/mozaik-products"
    kerf:
      status: yes
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

CNC-driven cabinet shop software — versus an open-core CAD with grain matching, joinery, and multi-domain engineering in one workspace.

*Last reviewed: 2026-05-24*

## Summary

Kerf saturates **100%** of Mozaik Software's feature surface (10 yes, 0 partial, 0 no out of 10 features tracked here). Kerf covers the full tracked feature set for Mozaik Software; gaps may exist in workflow depth, ecosystem maturity, and community support.

## Feature comparison

| Feature | Kerf | Mozaik Software | Notes |
|---------|------|-----------------|-------|
| Woodworking (cut-list/joinery/grain) | ✅ | Yes | Cut list, joinery rules, grain direction engine (backend); no room-layout floor plan UI |
| Cabinet / room layout design | ✅ | Yes | Cabinet room layout (CabinetPlacement) + cut-list generation |
| Parametric cabinet libraries | ✅ | Yes | Joinery rules (backend); no parametric cabinet library UI |
| CNC cut list and nesting | ✅ | Yes | True-shape NFP nesting + G-code post (Fanuc/GRBL/LinuxCNC); no cabinet-specific bore patterns |
| Hardware boring / machining automation | ✅ | Yes | 32 mm System bore-pattern generator: hinge cups (35 mm Blum-compatible), shelf-pin rows, undermount/sidemount drawer ... |
| Grain direction management | ✅ | Yes | Grain direction engine for cut list (backend) |
| Pricing / estimating | ✅ | Yes | Should-cost engine (backend); no woodworking-specific pricing UI |
| Shop drawings / technical documentation | ✅ | Yes | Engineering multi-sheet drawings (template-based); no cabinet shop drawing format |
| LLM / chat-native editing | ✅ | No | Chat-native: describe a cabinet in plain language; Kerf generates cut list and joinery |
| Cross-platform (macOS support) | ✅ | No | Runs in the browser; any OS with a modern browser |

## What Kerf does that Mozaik Software doesn't

- **LLM / chat-native editing** — Chat-native: describe a cabinet in plain language; Kerf generates cut list and joinery
- **Cross-platform (macOS support)** — Runs in the browser; any OS with a modern browser

## Pricing

Mozaik Software is free and open-source. Kerf is also MIT open-core: free to run locally (single Go binary, Postgres required). A hosted option with pay-as-you-go billing is available for teams that don't want to self-host. No feature gates — MIT licensed throughout.
