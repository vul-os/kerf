// src/lib/panels/mfg.js — panel registry fragment for CAM, mold, packaging,
// PLM, BIM quantity, geometry import, drawings, and GD&T panels.
//
// Each entry maps a file `kind` and/or filename extension(s) to a lazily-
// loaded React panel. The `content` prop (string) is parsed with JSON.parse
// try/catch and merged over each panel's defaults where applicable.
//
// Rules:
//   kinds  — lower-cased file.kind values set by the backend
//   exts   — lower-cased filename extensions (including the leading dot)

export default [
  // ── CAM / machining ──────────────────────────────────────────────────────

  {
    id: 'cam_verify',
    kinds: ['cam_verify', 'cam_material_removal'],
    exts: ['.cam_verify'],
    label: 'Material Removal Verify',
    load: () => import('../../components/CAMVerifyPanel.jsx').then(m => ({
      default: withContent(m.default, camVerifyMapper),
    })),
  },

  {
    id: 'cam_machine_sim',
    kinds: ['cam_machine_sim', 'cam_collision'],
    exts: ['.cam_sim'],
    label: 'Machine Collision Check',
    load: () => import('../../components/CAMMachineSimPanel.jsx').then(m => ({
      default: withContent(m.default, camMachineMapper),
    })),
  },

  {
    id: 'cam_probing',
    kinds: ['cam_probing', 'cam_onmachine_probe'],
    exts: ['.probe_plan'],
    label: 'On-Machine Probing',
    load: () => import('../../components/CAMProbingPanel.jsx').then(m => ({
      default: withContentPassthrough(m.default),
    })),
  },

  // ── Mold / injection ─────────────────────────────────────────────────────

  {
    id: 'injection_fill',
    kinds: ['injection_fill', 'mold_fill'],
    exts: ['.fill_result'],
    label: 'Injection Fill',
    load: () => import('../../components/InjectionFillPanel.jsx').then(m => ({
      default: contentToField(m.default, 'parsedContent'),
    })),
  },

  {
    id: 'parting_cavity',
    kinds: ['parting_cavity', 'mold_parting'],
    exts: ['.parting_result'],
    label: 'Parting Line / Cavity Split',
    load: () => import('../../components/PartingCavityPanel.jsx').then(m => ({
      default: contentToField(m.default, 'parsedContent'),
    })),
  },

  {
    id: 'mold_cooling_warpage',
    kinds: ['mold_cooling', 'mold_warpage', 'runner_balance'],
    exts: ['.mold_result'],
    label: 'Mold Cooling / Warpage',
    load: () => import('../../components/MoldCoolingWarpagePanel.jsx').then(m => ({
      default: contentToField(m.default, 'parsedContent'),
    })),
  },

  // ── Additive manufacturing process simulation ────────────────────────────

  {
    id: 'am_process_sim',
    kinds: ['am_process_sim', 'am_distortion', 'am_residual_stress'],
    exts: ['.am_result'],
    label: 'AM Process Simulation',
    load: () => import('../../components/AMProcessSimPanel.jsx').then(m => ({
      default: contentToField(m.default, 'parsedContent'),
    })),
  },

  {
    id: 'am_thermomechanical',
    kinds: ['am_thermomechanical', 'am_thermo_mech', 'am_melt_pool'],
    exts: ['.am_tm_result'],
    label: 'AM Thermo-Mechanical Simulation',
    load: () => import('../../components/AMProcessSimPanel.jsx').then(m => ({
      // Re-uses AMProcessSimPanel — auto-detects thermo-mechanical data
      // from the presence of layer_peak_temp_k field.
      default: contentToField(m.default, 'parsedContent'),
    })),
  },

  // ── Packaging ────────────────────────────────────────────────────────────

  {
    id: 'packaging_prepress',
    kinds: ['packaging_prepress', 'prepress'],
    exts: ['.prepress'],
    label: 'Packaging Pre-Press',
    load: () => import('../../components/packaging/PackagingPrePressPanel.jsx').then(m => ({
      default: withContentPassthrough(m.default),
    })),
  },

  {
    id: 'packaging_material_yield',
    kinds: ['packaging_yield', 'packaging_material'],
    exts: ['.pkg_yield'],
    label: 'Material Yield',
    load: () => import('../../components/packaging/PackagingMaterialYieldPanel.jsx').then(m => ({
      default: withContentPassthrough(m.default),
    })),
  },

  // ── PLM ──────────────────────────────────────────────────────────────────

  {
    id: 'quote_to_delivery',
    kinds: ['quote_to_delivery', 'plm_job'],
    exts: ['.plm_job'],
    label: 'Quote to Delivery',
    load: () => import('../../components/plm/QuoteToDeliveryPanel.jsx').then(m => ({
      default: withContentPassthrough(m.default),
    })),
  },

  // ── BIM quantity ─────────────────────────────────────────────────────────

  {
    id: 'quantity_schedule',
    kinds: ['quantity_schedule', 'bim_qty'],
    exts: ['.qty_schedule'],
    label: 'Quantity Schedule',
    load: () => import('../../components/QuantitySchedulePanel.jsx').then(m => ({
      // QuantitySchedulePanel already accepts `content` natively; pass-through.
      default: m.default,
    })),
  },

  // ── Geometry import ──────────────────────────────────────────────────────

  {
    id: 'geometry_import',
    kinds: ['geometry_import'],
    exts: ['.step', '.stp', '.iges', '.igs', '.3dm', '.dxf', '.fcstd'],
    label: 'Geometry Import',
    load: () => import('../../components/GeometryImportPanel.jsx').then(m => ({
      default: withGeomImport(m.default),
    })),
  },

  // ── Drawings ─────────────────────────────────────────────────────────────

  {
    id: 'drawing_sheet',
    kinds: ['drawing_sheet', 'drawing'],
    exts: ['.drawing'],
    label: 'Drawing Sheet',
    load: () => import('../../components/drawings/DrawingSheetPanel.jsx').then(m => ({
      // DrawingSheetPanel takes no data props — render as-is.
      default: m.default,
    })),
  },

  // ── GD&T / PMI ───────────────────────────────────────────────────────────

  {
    id: 'gdnt_pmi',
    kinds: ['gdnt_pmi', 'gdt'],
    exts: ['.gdnt'],
    label: 'GD&T / PMI',
    load: () => import('../../components/GdntPmiPanel.jsx').then(m => ({
      default: withGdnt(m.default),
    })),
  },
]

// ---------------------------------------------------------------------------
// Wrapper helpers
// ---------------------------------------------------------------------------

/**
 * withContent — wraps a component so that when a `content` string prop is
 * passed the content is JSON.parse'd (try/catch) and the result is spread
 * over the props supplied by the caller (extra props win over parsed content).
 *
 * @param {React.ComponentType} Panel
 * @param {(parsed:object, raw:string) => object} mapper
 *   Maps the parsed JSON object to the props the wrapped Panel expects.
 *   Receives (parsedObject, rawString); rawString passed when JSON.parse fails.
 * @returns {React.ComponentType}
 */
function withContent(Panel, mapper) {
  function ContentWrapper({ content, ...rest }) {
    let extra = {}
    if (content && typeof content === 'string') {
      try {
        const parsed = JSON.parse(content)
        extra = mapper(parsed, content)
      } catch {
        // Non-JSON content — pass raw string through mapper fallback
        extra = mapper(null, content)
      }
    }
    // Explicit props win over content-derived props
    return Panel({ ...extra, ...rest })
  }
  ContentWrapper.displayName = `WithContent(${Panel.displayName || Panel.name || 'Panel'})`
  return ContentWrapper
}

/**
 * contentToField — simple case: map `content` → `{fieldName: content}`.
 * The wrapped panel receives the raw string in the named field.
 */
function contentToField(Panel, fieldName) {
  function FieldWrapper({ content, ...rest }) {
    const fieldProps = content !== undefined ? { [fieldName]: content } : {}
    return Panel({ ...fieldProps, ...rest })
  }
  FieldWrapper.displayName = `ContentToField(${fieldName})`
  return FieldWrapper
}

/**
 * withContentPassthrough — for panels that manage their own internal state
 * (PackagingPrePressPanel, PackagingMaterialYieldPanel, QuoteToDeliveryPanel).
 * The `content` prop is accepted and silently ignored so the registry contract
 * is satisfied without breaking the panel's self-contained behaviour.
 */
function withContentPassthrough(Panel) {
  // eslint-disable-next-line no-unused-vars
  function PassthroughWrapper({ content, file, fileId, projectId, ...rest }) {
    return Panel(rest)
  }
  PassthroughWrapper.displayName = `ContentPassthrough(${Panel.displayName || Panel.name || 'Panel'})`
  return PassthroughWrapper
}

/**
 * withGeomImport — GeometryImportPanel needs `projectId` from the file context.
 * Maps { file, content, projectId, fileId } → { projectId }.
 */
function withGeomImport(Panel) {
  function GeomWrapper({ content, file, projectId, fileId, ...rest }) { // eslint-disable-line no-unused-vars
    return Panel({ projectId, ...rest })
  }
  GeomWrapper.displayName = 'WithGeomImport(GeometryImportPanel)'
  return GeomWrapper
}

/**
 * withGdnt — GdntPmiPanel accepts `drawing` (parsed JSON) via `content`.
 */
function withGdnt(Panel) {
  function GdntWrapper({ content, file, projectId, fileId, ...rest }) { // eslint-disable-line no-unused-vars
    let drawing = null
    if (content && typeof content === 'string') {
      try { drawing = JSON.parse(content) } catch { /* non-JSON */ }
    }
    return Panel({ drawing, ...rest })
  }
  GdntWrapper.displayName = 'WithGdnt(GdntPmiPanel)'
  return GdntWrapper
}

// ---------------------------------------------------------------------------
// Mapper functions for panels with structured data props
// ---------------------------------------------------------------------------

/**
 * Map parsed JSON → CAMVerifyPanel props.
 * Content format: { cl_points?, gcode?, stock_bounds, tool_diameter_mm?,
 *   tool_kind?, part_surface_z?, resolution_mm? }
 */
function camVerifyMapper(parsed) {
  if (!parsed) return {}
  return {
    clPoints:      parsed.cl_points,
    gcode:         parsed.gcode,
    stockBounds:   parsed.stock_bounds,
    toolDiameter:  parsed.tool_diameter_mm ?? 6,
    toolKind:      parsed.tool_kind ?? 'flat',
    partSurfaceZ:  parsed.part_surface_z,
    resolutionMm:  parsed.resolution_mm ?? 0.5,
  }
}

/**
 * Map parsed JSON → CAMMachineSimPanel props.
 * Content format: { toolpath_points?, tool_diameter_mm?, tool_length_mm?,
 *   holder_diameter_mm?, holder_length_mm?, stock_bounds?, table_pivot_z? }
 */
function camMachineMapper(parsed) {
  if (!parsed) return {}
  return {
    toolpathPoints:  parsed.toolpath_points,
    toolDiameter:    parsed.tool_diameter_mm ?? 12,
    toolLength:      parsed.tool_length_mm ?? 80,
    holderDiameter:  parsed.holder_diameter_mm ?? 32,
    holderLength:    parsed.holder_length_mm ?? 50,
    stockBounds:     parsed.stock_bounds,
    tablePivotZ:     parsed.table_pivot_z ?? 0,
  }
}
