"""
kerf-entertainment — theatrical / entertainment design domain.

Provides:
  • Lighting plot + DMX patch (fixture instances, conflict detection,
    circuit schedule, patch sheet, magic-sheet data)
  • Rigging load analysis (truss reactions at hoists/bridles,
    overload detection, bridle leg tension geometry)

LLM tools:
  lighting_plot_patch   — full patch sheet + load summary
  lighting_dmx_check    — DMX address conflict check only
  rigging_load_analysis — hoist reactions + bridle tensions
"""
