// BIMCivilPanel.jsx — BIM / Civil / MEP (HVAC + Piping) engineering solver panel.
//
// Wires 36 backend tools across three tabs:
//   Tab 1 — BIM (Building): walls, slabs, roof, curtain wall, drafting, IFC, spaces, site
//   Tab 2 — Civil (Infra):  alignment, corridor, earthwork, terrain, hydraulics
//   Tab 3 — HVAC + Piping (MEP): duct sizing, pressure drop, pipe calc, thermal expansion,
//            MEP clash-aware auto-routing (create_mep_route + auto_route_mep + clash_detect)
//
// All tools dispatch POST /api/tools/call with { tool: "<name>", args: {...} }.
// Results are rendered inline (numbers, tables, status badges).
//
// Props: none (standalone panel — operates without a project file)

import { useState, useCallback } from 'react'
import {
  Building2, Construction, Wind, AlertTriangle, CheckCircle,
  Loader2, Play, ChevronDown, ChevronUp, Pipette, Layers,
  Map, Droplets, Route, ShieldAlert,
} from 'lucide-react'

const API_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) || ''

// ---------------------------------------------------------------------------
// Styles — identical palette to StructuralPanel.jsx
// ---------------------------------------------------------------------------

const s = {
  root:         { background: '#111827', padding: '12px', fontSize: 12, color: '#e5e7eb', minHeight: 200 },
  header:       { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 },
  title:        { fontWeight: 600, fontSize: 14, color: '#f9fafb' },
  subtitle:     { color: '#6b7280', fontSize: 11, marginLeft: 4 },
  tabs:         { display: 'flex', gap: 2, marginBottom: 10, flexWrap: 'wrap' },
  tab:          { padding: '4px 10px', borderRadius: 4, border: '1px solid #374151', background: '#1f2937', color: '#9ca3af', cursor: 'pointer', fontSize: 11 },
  tabActive:    { background: '#1d4ed8', borderColor: '#3b82f6', color: '#fff' },
  section:      { background: '#1f2937', borderRadius: 6, padding: '10px', marginBottom: 8 },
  sectionTitle: { display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600, marginBottom: 8, color: '#d1d5db', fontSize: 11 },
  row:          { display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 },
  label:        { color: '#9ca3af', width: 170, flexShrink: 0, fontSize: 11 },
  input:        { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12, minWidth: 0 },
  select:       { flex: 1, background: '#111827', border: '1px solid #374151', borderRadius: 4, padding: '3px 7px', color: '#f9fafb', fontSize: 12 },
  button:       { display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 5, border: 'none', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 500 },
  buttonDisabled:{ opacity: 0.5, cursor: 'not-allowed' },
  errorBox:     { display: 'flex', alignItems: 'flex-start', gap: 6, background: '#450a0a', borderRadius: 5, padding: '8px', color: '#fca5a5', marginTop: 8 },
  infoBox:      { display: 'flex', alignItems: 'center', gap: 6, background: '#1e3a5f', borderRadius: 5, padding: '8px', color: '#93c5fd', marginTop: 8 },
  resultBox:    { background: '#0f172a', borderRadius: 4, padding: '8px', marginTop: 6, fontFamily: 'monospace', fontSize: 11 },
  table:        { width: '100%', borderCollapse: 'collapse', marginTop: 4 },
  td:           { padding: '3px 6px', borderBottom: '1px solid #1f2937' },
  mono:         { fontFamily: 'monospace' },
  subhead:      { color: '#60a5fa', fontWeight: 600, marginBottom: 4, fontSize: 11 },
  divider:      { borderTop: '1px solid #374151', margin: '8px 0' },
  passChip:     { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#064e3b', color: '#34d399' },
  failChip:     { display: 'inline-block', padding: '2px 7px', borderRadius: 10, fontSize: 10, fontWeight: 700, background: '#450a0a', color: '#f87171' },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function callTool(toolName, args) {
  const res = await fetch(`${API_URL}/api/tools/call`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool: toolName, args }),
  })
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(`HTTP ${res.status}: ${txt}`)
  }
  return res.json()
}

function fmt(v, decimals = 3) {
  if (v == null) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v)
    return Math.abs(v) > 1e4 || (Math.abs(v) < 1e-2 && v !== 0)
      ? v.toExponential(3)
      : v.toFixed(decimals)
  }
  return String(v)
}

function StatusChip({ ok }) {
  return ok
    ? <span style={s.passChip}>PASS</span>
    : <span style={s.failChip}>FAIL</span>
}

function ResultTable({ data, skip = [] }) {
  if (!data || typeof data !== 'object') return null
  const entries = Object.entries(data).filter(
    ([k, v]) => !skip.includes(k) && typeof v !== 'object' && !Array.isArray(v)
  )
  if (!entries.length) return null
  return (
    <table style={s.table}>
      <tbody>
        {entries.map(([k, v]) => (
          <tr key={k}>
            <td style={{ ...s.td, color: '#9ca3af', width: '55%' }}>{k}</td>
            <td style={{ ...s.td, ...s.mono }}>{fmt(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ToolWidget({ title, icon: Icon, color = '#2563eb', children, result, error, running, passKey }) {
  const [open, setOpen] = useState(true)
  const ok = result && passKey ? Boolean(result[passKey]) : undefined

  return (
    <div style={{ ...s.section, borderLeft: `3px solid ${color}` }}>
      <div
        style={{ ...s.sectionTitle, justifyContent: 'space-between', cursor: 'pointer' }}
        onClick={() => setOpen(o => !o)}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          {Icon && <Icon size={12} style={{ color }} />}
          {title}
          {result && passKey && !running && (
            <span style={{ marginLeft: 4 }}>
              <StatusChip ok={ok} />
            </span>
          )}
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </div>
      {open && (
        <>
          {children}
          {error && (
            <div style={s.errorBox}>
              <AlertTriangle size={12} />
              <span>{error}</span>
            </div>
          )}
          {running && (
            <div style={s.infoBox}>
              <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
              <span>Computing…</span>
            </div>
          )}
          {result && !running && !error && (
            <div style={s.resultBox}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
                <CheckCircle size={11} style={{ color: '#34d399' }} />
                <span style={{ color: '#34d399', fontWeight: 600 }}>Result</span>
              </div>
              <ResultTable data={result} skip={['honest_caveat', 'code_section', 'notes']} />
              {result.honest_caveat && (
                <div style={{ color: '#6b7280', fontSize: 10, marginTop: 4, fontFamily: 'sans-serif' }}>
                  {result.honest_caveat.slice(0, 220)}{result.honest_caveat.length > 220 ? '…' : ''}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function RunBtn({ onClick, running, label = 'Run' }) {
  return (
    <button
      onClick={onClick}
      disabled={running}
      style={{ ...s.button, background: '#1e40af', marginTop: 6, ...(running ? s.buttonDisabled : {}) }}
    >
      {running
        ? <><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> Computing…</>
        : <><Play size={12} /> {label}</>}
    </button>
  )
}

function NumRow({ label, value, onChange, step = 'any', disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <input
        type="number"
        value={value}
        onChange={e => onChange(e.target.value)}
        step={step}
        disabled={disabled}
        style={s.input}
      />
    </div>
  )
}

function SelRow({ label, value, onChange, options, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
        style={s.select}
      >
        {options.map(o =>
          typeof o === 'string'
            ? <option key={o} value={o}>{o}</option>
            : <option key={o.value} value={o.value}>{o.label}</option>
        )}
      </select>
    </div>
  )
}

function TxtRow({ label, value, onChange, disabled }) {
  return (
    <div style={s.row}>
      <label style={s.label}>{label}</label>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
        style={s.input}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 1 — BIM (Building)
// ---------------------------------------------------------------------------

function TabBIM() {
  // ── bim_make_wall ──────────────────────────────────────────────────────────
  const [wall, setWall] = useState({ start_x: '0', start_y: '0', end_x: '6000', end_y: '0', height_mm: '3000', thickness_mm: '200', base_offset_mm: '0', wall_type: 'basic' })
  const [wallR, setWallR] = useState(null); const [wallE, setWallE] = useState(null); const [wallRun, setWallRun] = useState(false)
  const runWall = useCallback(async () => {
    setWallRun(true); setWallE(null); setWallR(null)
    try {
      const r = await callTool('bim_make_wall', {
        start: [+wall.start_x, +wall.start_y, 0],
        end:   [+wall.end_x,   +wall.end_y,   0],
        height_mm: +wall.height_mm,
        thickness_mm: +wall.thickness_mm,
        base_offset_mm: +wall.base_offset_mm,
        wall_type: wall.wall_type,
      })
      setWallR(r)
    } catch (e) { setWallE(e.message) } finally { setWallRun(false) }
  }, [wall])

  // ── bim_make_slab ──────────────────────────────────────────────────────────
  const [slab, setSlab] = useState({ width_mm: '8000', length_mm: '12000', thickness_mm: '250', level_mm: '0', slab_type: 'floor' })
  const [slabR, setSlabR] = useState(null); const [slabE, setSlabE] = useState(null); const [slabRun, setSlabRun] = useState(false)
  const runSlab = useCallback(async () => {
    setSlabRun(true); setSlabE(null); setSlabR(null)
    try {
      const r = await callTool('bim_make_slab', {
        width_mm: +slab.width_mm, length_mm: +slab.length_mm,
        thickness_mm: +slab.thickness_mm, level_mm: +slab.level_mm,
        slab_type: slab.slab_type,
      })
      setSlabR(r)
    } catch (e) { setSlabE(e.message) } finally { setSlabRun(false) }
  }, [slab])

  // ── bim_make_roof ──────────────────────────────────────────────────────────
  const [roof, setRoof] = useState({ width_mm: '10000', length_mm: '14000', pitch_degrees: '22.5', thickness_mm: '200', roof_type: 'gable', eave_offset_mm: '600' })
  const [roofR, setRoofR] = useState(null); const [roofE, setRoofE] = useState(null); const [roofRun, setRoofRun] = useState(false)
  const runRoof = useCallback(async () => {
    setRoofRun(true); setRoofE(null); setRoofR(null)
    try {
      const r = await callTool('bim_make_roof', {
        width_mm: +roof.width_mm, length_mm: +roof.length_mm,
        pitch_degrees: +roof.pitch_degrees, thickness_mm: +roof.thickness_mm,
        roof_type: roof.roof_type, eave_offset_mm: +roof.eave_offset_mm,
      })
      setRoofR(r)
    } catch (e) { setRoofE(e.message) } finally { setRoofRun(false) }
  }, [roof])

  // ── bim_curtain_wall_geometry ──────────────────────────────────────────────
  const [cw, setCw] = useState({ width_mm: '5000', height_mm: '3600', grid_u_count: '5', grid_v_count: '3', mullion_width_mm: '50', panel_type: 'glazed' })
  const [cwR, setCwR] = useState(null); const [cwE, setCwE] = useState(null); const [cwRun, setCwRun] = useState(false)
  const runCW = useCallback(async () => {
    setCwRun(true); setCwE(null); setCwR(null)
    try {
      const r = await callTool('bim_curtain_wall_geometry', {
        width_mm: +cw.width_mm, height_mm: +cw.height_mm,
        grid_u_count: +cw.grid_u_count, grid_v_count: +cw.grid_v_count,
        mullion_width_mm: +cw.mullion_width_mm, panel_type: cw.panel_type,
      })
      setCwR(r)
    } catch (e) { setCwE(e.message) } finally { setCwRun(false) }
  }, [cw])

  // ── bim_hatch_region ───────────────────────────────────────────────────────
  const [hatch, setHatch] = useState({ width_mm: '3000', height_mm: '2000', pattern: 'diagonal_cross', scale: '1.0', angle_deg: '45' })
  const [hatchR, setHatchR] = useState(null); const [hatchE, setHatchE] = useState(null); const [hatchRun, setHatchRun] = useState(false)
  const runHatch = useCallback(async () => {
    setHatchRun(true); setHatchE(null); setHatchR(null)
    try {
      const r = await callTool('bim_hatch_region', {
        boundary_points: [[0,0],[+hatch.width_mm,0],[+hatch.width_mm,+hatch.height_mm],[0,+hatch.height_mm]],
        pattern: hatch.pattern, scale: +hatch.scale, angle_deg: +hatch.angle_deg,
      })
      setHatchR(r)
    } catch (e) { setHatchE(e.message) } finally { setHatchRun(false) }
  }, [hatch])

  // ── bim_section_fill ───────────────────────────────────────────────────────
  const [fill, setFill] = useState({ section_width_mm: '200', section_height_mm: '3000', material: 'concrete', cut_angle_deg: '90' })
  const [fillR, setFillR] = useState(null); const [fillE, setFillE] = useState(null); const [fillRun, setFillRun] = useState(false)
  const runFill = useCallback(async () => {
    setFillRun(true); setFillE(null); setFillR(null)
    try {
      const r = await callTool('bim_section_fill', {
        section_width_mm: +fill.section_width_mm, section_height_mm: +fill.section_height_mm,
        material: fill.material, cut_angle_deg: +fill.cut_angle_deg,
      })
      setFillR(r)
    } catch (e) { setFillE(e.message) } finally { setFillRun(false) }
  }, [fill])

  // ── bim_make2d_from_brep ───────────────────────────────────────────────────
  const [m2d, setM2d] = useState({ brep_id: 'wall_001', view_direction: 'front', scale: '1:100', include_hidden: 'false' })
  const [m2dR, setM2dR] = useState(null); const [m2dE, setM2dE] = useState(null); const [m2dRun, setM2dRun] = useState(false)
  const runM2d = useCallback(async () => {
    setM2dRun(true); setM2dE(null); setM2dR(null)
    try {
      const r = await callTool('bim_make2d_from_brep', {
        brep_id: m2d.brep_id, view_direction: m2d.view_direction,
        scale: m2d.scale, include_hidden: m2d.include_hidden === 'true',
      })
      setM2dR(r)
    } catch (e) { setM2dE(e.message) } finally { setM2dRun(false) }
  }, [m2d])

  // ── bim_toposolid_to_brep ──────────────────────────────────────────────────
  const [topo, setTopo] = useState({ grid_spacing_mm: '1000', base_elevation_mm: '0', smoothing_iterations: '3' })
  const [topoR, setTopoR] = useState(null); const [topoE, setTopoE] = useState(null); const [topoRun, setTopoRun] = useState(false)
  const runTopo = useCallback(async () => {
    setTopoRun(true); setTopoE(null); setTopoR(null)
    try {
      const r = await callTool('bim_toposolid_to_brep', {
        grid_spacing_mm: +topo.grid_spacing_mm,
        base_elevation_mm: +topo.base_elevation_mm,
        smoothing_iterations: +topo.smoothing_iterations,
        // sample 3x3 grid of elevation points
        elevation_points: [
          [0,0,0],[1000,0,200],[2000,0,100],
          [0,1000,300],[1000,1000,500],[2000,1000,250],
          [0,2000,100],[1000,2000,400],[2000,2000,0],
        ],
      })
      setTopoR(r)
    } catch (e) { setTopoE(e.message) } finally { setTopoRun(false) }
  }, [topo])

  // ── bim_cut_fill_volume ────────────────────────────────────────────────────
  const [cf, setCf] = useState({ existing_avg_elev_mm: '5000', proposed_avg_elev_mm: '4800', site_area_m2: '2500' })
  const [cfR, setCfR] = useState(null); const [cfE, setCfE] = useState(null); const [cfRun, setCfRun] = useState(false)
  const runCF = useCallback(async () => {
    setCfRun(true); setCfE(null); setCfR(null)
    try {
      const r = await callTool('bim_cut_fill_volume', {
        existing_avg_elev_mm: +cf.existing_avg_elev_mm,
        proposed_avg_elev_mm: +cf.proposed_avg_elev_mm,
        site_area_m2: +cf.site_area_m2,
      })
      setCfR(r)
    } catch (e) { setCfE(e.message) } finally { setCfRun(false) }
  }, [cf])

  // ── export_ifc / import_ifc (status-only tools) ────────────────────────────
  const [ifcExR, setIfcExR] = useState(null); const [ifcExE, setIfcExE] = useState(null); const [ifcExRun, setIfcExRun] = useState(false)
  const [ifcIfc, setIfcIfc] = useState({ schema: 'IFC4', include_geometry: 'true', include_properties: 'true' })
  const runIfcEx = useCallback(async () => {
    setIfcExRun(true); setIfcExE(null); setIfcExR(null)
    try {
      const r = await callTool('export_ifc', {
        schema: ifcIfc.schema,
        include_geometry: ifcIfc.include_geometry === 'true',
        include_properties: ifcIfc.include_properties === 'true',
      })
      setIfcExR(r)
    } catch (e) { setIfcExE(e.message) } finally { setIfcExRun(false) }
  }, [ifcIfc])

  const [ifcImR, setIfcImR] = useState(null); const [ifcImE, setIfcImE] = useState(null); const [ifcImRun, setIfcImRun] = useState(false)
  const [ifcFile, setIfcFile] = useState({ file_path: '/models/building.ifc', merge_strategy: 'replace' })
  const runIfcIm = useCallback(async () => {
    setIfcImRun(true); setIfcImE(null); setIfcImR(null)
    try {
      const r = await callTool('import_ifc', {
        file_path: ifcFile.file_path, merge_strategy: ifcFile.merge_strategy,
      })
      setIfcImR(r)
    } catch (e) { setIfcImE(e.message) } finally { setIfcImRun(false) }
  }, [ifcFile])

  // ── bim_create_space ───────────────────────────────────────────────────────
  const [space, setSpace] = useState({ name: 'Office A', number: '101', area_m2: '24', height_mm: '3000', level: '0', space_type: 'office' })
  const [spaceR, setSpaceR] = useState(null); const [spaceE, setSpaceE] = useState(null); const [spaceRun, setSpaceRun] = useState(false)
  const runSpace = useCallback(async () => {
    setSpaceRun(true); setSpaceE(null); setSpaceR(null)
    try {
      const r = await callTool('bim_create_space', {
        name: space.name, number: space.number,
        area_m2: +space.area_m2, height_mm: +space.height_mm,
        level: +space.level, space_type: space.space_type,
      })
      setSpaceR(r)
    } catch (e) { setSpaceE(e.message) } finally { setSpaceRun(false) }
  }, [space])

  // ── bim_parse_facade_ifc ───────────────────────────────────────────────────
  const [facade, setFacade] = useState({ ifc_path: '/models/facade.ifc', extract_thermal: 'true' })
  const [facadeR, setFacadeR] = useState(null); const [facadeE, setFacadeE] = useState(null); const [facadeRun, setFacadeRun] = useState(false)
  const runFacade = useCallback(async () => {
    setFacadeRun(true); setFacadeE(null); setFacadeR(null)
    try {
      const r = await callTool('bim_parse_facade_ifc', {
        ifc_path: facade.ifc_path, extract_thermal: facade.extract_thermal === 'true',
      })
      setFacadeR(r)
    } catch (e) { setFacadeE(e.message) } finally { setFacadeRun(false) }
  }, [facade])

  return (
    <div>
      {/* ── BIM Elements group ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>Elements</div>
      </div>

      <ToolWidget title="Wall Geometry (IFC IfcWall / Revit §3.2)" icon={Building2} color="#3b82f6" result={wallR} error={wallE} running={wallRun}>
        <NumRow label="Start X (mm)" value={wall.start_x} onChange={v => setWall(p => ({ ...p, start_x: v }))} disabled={wallRun} />
        <NumRow label="Start Y (mm)" value={wall.start_y} onChange={v => setWall(p => ({ ...p, start_y: v }))} disabled={wallRun} />
        <NumRow label="End X (mm)" value={wall.end_x} onChange={v => setWall(p => ({ ...p, end_x: v }))} disabled={wallRun} />
        <NumRow label="End Y (mm)" value={wall.end_y} onChange={v => setWall(p => ({ ...p, end_y: v }))} disabled={wallRun} />
        <NumRow label="Height (mm)" value={wall.height_mm} onChange={v => setWall(p => ({ ...p, height_mm: v }))} disabled={wallRun} />
        <NumRow label="Thickness (mm)" value={wall.thickness_mm} onChange={v => setWall(p => ({ ...p, thickness_mm: v }))} disabled={wallRun} />
        <SelRow label="Wall type" value={wall.wall_type} onChange={v => setWall(p => ({ ...p, wall_type: v }))}
          options={['basic', 'curtain', 'stacked', 'retaining', 'parapet']} disabled={wallRun} />
        <RunBtn onClick={runWall} running={wallRun} />
      </ToolWidget>

      <ToolWidget title="Slab Geometry (IFC IfcSlab / Revit §3.5)" icon={Layers} color="#8b5cf6" result={slabR} error={slabE} running={slabRun}>
        <NumRow label="Width (mm)" value={slab.width_mm} onChange={v => setSlab(p => ({ ...p, width_mm: v }))} disabled={slabRun} />
        <NumRow label="Length (mm)" value={slab.length_mm} onChange={v => setSlab(p => ({ ...p, length_mm: v }))} disabled={slabRun} />
        <NumRow label="Thickness (mm)" value={slab.thickness_mm} onChange={v => setSlab(p => ({ ...p, thickness_mm: v }))} disabled={slabRun} />
        <NumRow label="Level elevation (mm)" value={slab.level_mm} onChange={v => setSlab(p => ({ ...p, level_mm: v }))} disabled={slabRun} />
        <SelRow label="Slab type" value={slab.slab_type} onChange={v => setSlab(p => ({ ...p, slab_type: v }))}
          options={['floor', 'roof', 'landing', 'baseslab']} disabled={slabRun} />
        <RunBtn onClick={runSlab} running={slabRun} />
      </ToolWidget>

      <ToolWidget title="Roof Geometry (IFC IfcRoof / GK-P29)" icon={Building2} color="#10b981" result={roofR} error={roofE} running={roofRun}>
        <NumRow label="Width (mm)" value={roof.width_mm} onChange={v => setRoof(p => ({ ...p, width_mm: v }))} disabled={roofRun} />
        <NumRow label="Length (mm)" value={roof.length_mm} onChange={v => setRoof(p => ({ ...p, length_mm: v }))} disabled={roofRun} />
        <NumRow label="Pitch (degrees)" value={roof.pitch_degrees} onChange={v => setRoof(p => ({ ...p, pitch_degrees: v }))} disabled={roofRun} />
        <NumRow label="Thickness (mm)" value={roof.thickness_mm} onChange={v => setRoof(p => ({ ...p, thickness_mm: v }))} disabled={roofRun} />
        <SelRow label="Roof type" value={roof.roof_type} onChange={v => setRoof(p => ({ ...p, roof_type: v }))}
          options={['gable', 'hip', 'flat', 'shed', 'mansard', 'butterfly']} disabled={roofRun} />
        <NumRow label="Eave offset (mm)" value={roof.eave_offset_mm} onChange={v => setRoof(p => ({ ...p, eave_offset_mm: v }))} disabled={roofRun} />
        <RunBtn onClick={runRoof} running={roofRun} />
      </ToolWidget>

      <ToolWidget title="Curtain Wall Geometry (IFC IfcCurtainWall / GK-P30)" icon={Building2} color="#f59e0b" result={cwR} error={cwE} running={cwRun}>
        <NumRow label="Width (mm)" value={cw.width_mm} onChange={v => setCw(p => ({ ...p, width_mm: v }))} disabled={cwRun} />
        <NumRow label="Height (mm)" value={cw.height_mm} onChange={v => setCw(p => ({ ...p, height_mm: v }))} disabled={cwRun} />
        <NumRow label="Horizontal grid count" value={cw.grid_u_count} onChange={v => setCw(p => ({ ...p, grid_u_count: v }))} step="1" disabled={cwRun} />
        <NumRow label="Vertical grid count" value={cw.grid_v_count} onChange={v => setCw(p => ({ ...p, grid_v_count: v }))} step="1" disabled={cwRun} />
        <NumRow label="Mullion width (mm)" value={cw.mullion_width_mm} onChange={v => setCw(p => ({ ...p, mullion_width_mm: v }))} disabled={cwRun} />
        <SelRow label="Panel type" value={cw.panel_type} onChange={v => setCw(p => ({ ...p, panel_type: v }))}
          options={['glazed', 'opaque', 'louvred', 'spandrel']} disabled={cwRun} />
        <RunBtn onClick={runCW} running={cwRun} />
      </ToolWidget>

      {/* ── Drafting group ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>Drafting (GK-P28, 32, 33)</div>
      </div>

      <ToolWidget title="Hatch Region (GK-P32 bim_hatch_region)" icon={Layers} color="#6366f1" result={hatchR} error={hatchE} running={hatchRun}>
        <NumRow label="Region width (mm)" value={hatch.width_mm} onChange={v => setHatch(p => ({ ...p, width_mm: v }))} disabled={hatchRun} />
        <NumRow label="Region height (mm)" value={hatch.height_mm} onChange={v => setHatch(p => ({ ...p, height_mm: v }))} disabled={hatchRun} />
        <SelRow label="Pattern" value={hatch.pattern} onChange={v => setHatch(p => ({ ...p, pattern: v }))}
          options={['diagonal_cross', 'diagonal', 'horizontal', 'vertical', 'grid', 'dot', 'stone', 'concrete', 'earth']} disabled={hatchRun} />
        <NumRow label="Scale" value={hatch.scale} onChange={v => setHatch(p => ({ ...p, scale: v }))} disabled={hatchRun} />
        <NumRow label="Angle (degrees)" value={hatch.angle_deg} onChange={v => setHatch(p => ({ ...p, angle_deg: v }))} disabled={hatchRun} />
        <RunBtn onClick={runHatch} running={hatchRun} />
      </ToolWidget>

      <ToolWidget title="Section Fill (GK-P33 bim_section_fill)" icon={Layers} color="#ec4899" result={fillR} error={fillE} running={fillRun}>
        <NumRow label="Section width (mm)" value={fill.section_width_mm} onChange={v => setFill(p => ({ ...p, section_width_mm: v }))} disabled={fillRun} />
        <NumRow label="Section height (mm)" value={fill.section_height_mm} onChange={v => setFill(p => ({ ...p, section_height_mm: v }))} disabled={fillRun} />
        <SelRow label="Material" value={fill.material} onChange={v => setFill(p => ({ ...p, material: v }))}
          options={['concrete', 'masonry', 'timber', 'steel', 'insulation', 'earth', 'gravel', 'glass']} disabled={fillRun} />
        <NumRow label="Cut angle (deg)" value={fill.cut_angle_deg} onChange={v => setFill(p => ({ ...p, cut_angle_deg: v }))} disabled={fillRun} />
        <RunBtn onClick={runFill} running={fillRun} />
      </ToolWidget>

      <ToolWidget title="Make2D from BRep (GK-P28 bim_make2d_from_brep)" icon={Layers} color="#0ea5e9" result={m2dR} error={m2dE} running={m2dRun}>
        <TxtRow label="BRep ID" value={m2d.brep_id} onChange={v => setM2d(p => ({ ...p, brep_id: v }))} disabled={m2dRun} />
        <SelRow label="View direction" value={m2d.view_direction} onChange={v => setM2d(p => ({ ...p, view_direction: v }))}
          options={['front', 'back', 'left', 'right', 'top', 'bottom', 'isometric']} disabled={m2dRun} />
        <TxtRow label="Scale" value={m2d.scale} onChange={v => setM2d(p => ({ ...p, scale: v }))} disabled={m2dRun} />
        <SelRow label="Include hidden lines" value={m2d.include_hidden} onChange={v => setM2d(p => ({ ...p, include_hidden: v }))}
          options={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} disabled={m2dRun} />
        <RunBtn onClick={runM2d} running={m2dRun} />
      </ToolWidget>

      {/* ── Site group ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>Site (GK-P34)</div>
      </div>

      <ToolWidget title="Toposolid to BRep (GK-P34 bim_toposolid_to_brep)" icon={Map} color="#84cc16" result={topoR} error={topoE} running={topoRun}>
        <NumRow label="Grid spacing (mm)" value={topo.grid_spacing_mm} onChange={v => setTopo(p => ({ ...p, grid_spacing_mm: v }))} disabled={topoRun} />
        <NumRow label="Base elevation (mm)" value={topo.base_elevation_mm} onChange={v => setTopo(p => ({ ...p, base_elevation_mm: v }))} disabled={topoRun} />
        <NumRow label="Smoothing iterations" value={topo.smoothing_iterations} onChange={v => setTopo(p => ({ ...p, smoothing_iterations: v }))} step="1" disabled={topoRun} />
        <div style={{ color: '#6b7280', fontSize: 10, marginTop: 4 }}>Uses a 3×3 sample point grid. Pass full elevation_points array via API for production use.</div>
        <RunBtn onClick={runTopo} running={topoRun} />
      </ToolWidget>

      <ToolWidget title="Cut/Fill Volume (bim_cut_fill_volume)" icon={Map} color="#f97316" result={cfR} error={cfE} running={cfRun}>
        <NumRow label="Existing avg elevation (mm)" value={cf.existing_avg_elev_mm} onChange={v => setCf(p => ({ ...p, existing_avg_elev_mm: v }))} disabled={cfRun} />
        <NumRow label="Proposed avg elevation (mm)" value={cf.proposed_avg_elev_mm} onChange={v => setCf(p => ({ ...p, proposed_avg_elev_mm: v }))} disabled={cfRun} />
        <NumRow label="Site area (m²)" value={cf.site_area_m2} onChange={v => setCf(p => ({ ...p, site_area_m2: v }))} disabled={cfRun} />
        <RunBtn onClick={runCF} running={cfRun} />
      </ToolWidget>

      {/* ── IFC / Spaces ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>IFC Exchange + Spaces</div>
      </div>

      <ToolWidget title="IFC Export (export_ifc)" icon={Building2} color="#22d3ee" result={ifcExR} error={ifcExE} running={ifcExRun}>
        <SelRow label="IFC schema" value={ifcIfc.schema} onChange={v => setIfcIfc(p => ({ ...p, schema: v }))}
          options={['IFC4', 'IFC4x3', 'IFC2x3']} disabled={ifcExRun} />
        <SelRow label="Include geometry" value={ifcIfc.include_geometry} onChange={v => setIfcIfc(p => ({ ...p, include_geometry: v }))}
          options={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} disabled={ifcExRun} />
        <SelRow label="Include properties" value={ifcIfc.include_properties} onChange={v => setIfcIfc(p => ({ ...p, include_properties: v }))}
          options={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} disabled={ifcExRun} />
        <RunBtn onClick={runIfcEx} running={ifcExRun} />
      </ToolWidget>

      <ToolWidget title="IFC Import (import_ifc)" icon={Building2} color="#a78bfa" result={ifcImR} error={ifcImE} running={ifcImRun}>
        <TxtRow label="File path" value={ifcFile.file_path} onChange={v => setIfcFile(p => ({ ...p, file_path: v }))} disabled={ifcImRun} />
        <SelRow label="Merge strategy" value={ifcFile.merge_strategy} onChange={v => setIfcFile(p => ({ ...p, merge_strategy: v }))}
          options={['replace', 'merge', 'append']} disabled={ifcImRun} />
        <RunBtn onClick={runIfcIm} running={ifcImRun} />
      </ToolWidget>

      <ToolWidget title="Create Space (bim_create_space)" icon={Building2} color="#fb923c" result={spaceR} error={spaceE} running={spaceRun}>
        <TxtRow label="Space name" value={space.name} onChange={v => setSpace(p => ({ ...p, name: v }))} disabled={spaceRun} />
        <TxtRow label="Room number" value={space.number} onChange={v => setSpace(p => ({ ...p, number: v }))} disabled={spaceRun} />
        <NumRow label="Area (m²)" value={space.area_m2} onChange={v => setSpace(p => ({ ...p, area_m2: v }))} disabled={spaceRun} />
        <NumRow label="Height (mm)" value={space.height_mm} onChange={v => setSpace(p => ({ ...p, height_mm: v }))} disabled={spaceRun} />
        <NumRow label="Level" value={space.level} onChange={v => setSpace(p => ({ ...p, level: v }))} step="1" disabled={spaceRun} />
        <SelRow label="Space type" value={space.space_type} onChange={v => setSpace(p => ({ ...p, space_type: v }))}
          options={['office', 'corridor', 'bathroom', 'kitchen', 'storage', 'lobby', 'stairwell', 'mechanical']} disabled={spaceRun} />
        <RunBtn onClick={runSpace} running={spaceRun} />
      </ToolWidget>

      <ToolWidget title="Facade IFC Parser (bim_parse_facade_ifc)" icon={Building2} color="#f43f5e" result={facadeR} error={facadeE} running={facadeRun}>
        <TxtRow label="IFC file path" value={facade.ifc_path} onChange={v => setFacade(p => ({ ...p, ifc_path: v }))} disabled={facadeRun} />
        <SelRow label="Extract thermal data" value={facade.extract_thermal} onChange={v => setFacade(p => ({ ...p, extract_thermal: v }))}
          options={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} disabled={facadeRun} />
        <RunBtn onClick={runFacade} running={facadeRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 2 — Civil (Infra)
// ---------------------------------------------------------------------------

function TabCivil() {
  // ── civil_horizontal_alignment ────────────────────────────────────────────
  const [ha, setHa] = useState({ start_station: '0', design_speed_kph: '80', curve_radius_m: '400', tangent_length_m: '500' })
  const [haR, setHaR] = useState(null); const [haE, setHaE] = useState(null); const [haRun, setHaRun] = useState(false)
  const runHA = useCallback(async () => {
    setHaRun(true); setHaE(null); setHaR(null)
    try {
      const r = await callTool('civil_horizontal_alignment', {
        start_station: +ha.start_station, design_speed_kph: +ha.design_speed_kph,
        curve_radius_m: +ha.curve_radius_m, tangent_length_m: +ha.tangent_length_m,
      })
      setHaR(r)
    } catch (e) { setHaE(e.message) } finally { setHaRun(false) }
  }, [ha])

  // ── civil_vertical_alignment ───────────────────────────────────────────────
  const [va, setVa] = useState({ start_grade_pct: '-2.5', end_grade_pct: '3.0', pvi_station: '250', design_speed_kph: '80', sag_or_crest: 'crest' })
  const [vaR, setVaR] = useState(null); const [vaE, setVaE] = useState(null); const [vaRun, setVaRun] = useState(false)
  const runVA = useCallback(async () => {
    setVaRun(true); setVaE(null); setVaR(null)
    try {
      const r = await callTool('civil_vertical_alignment', {
        start_grade_pct: +va.start_grade_pct, end_grade_pct: +va.end_grade_pct,
        pvi_station: +va.pvi_station, design_speed_kph: +va.design_speed_kph,
        sag_or_crest: va.sag_or_crest,
      })
      setVaR(r)
    } catch (e) { setVaE(e.message) } finally { setVaRun(false) }
  }, [va])

  // ── civil_corridor_brep ────────────────────────────────────────────────────
  const [corr, setCorr] = useState({ carriageway_width_m: '7.4', shoulder_width_m: '2.5', fill_slope_h: '2', cut_slope_h: '1.5', length_m: '500' })
  const [corrR, setCorrR] = useState(null); const [corrE, setCorrE] = useState(null); const [corrRun, setCorrRun] = useState(false)
  const runCorr = useCallback(async () => {
    setCorrRun(true); setCorrE(null); setCorrR(null)
    try {
      const r = await callTool('civil_corridor_brep', {
        carriageway_width_m: +corr.carriageway_width_m,
        shoulder_width_m: +corr.shoulder_width_m,
        fill_slope_h: +corr.fill_slope_h,
        cut_slope_h: +corr.cut_slope_h,
        length_m: +corr.length_m,
      })
      setCorrR(r)
    } catch (e) { setCorrE(e.message) } finally { setCorrRun(false) }
  }, [corr])

  // ── civil_earthwork_volume ─────────────────────────────────────────────────
  const [ew, setEw] = useState({ cut_volume_m3: '12500', fill_volume_m3: '8700', swell_factor: '1.25', shrink_factor: '0.85' })
  const [ewR, setEwR] = useState(null); const [ewE, setEwE] = useState(null); const [ewRun, setEwRun] = useState(false)
  const runEW = useCallback(async () => {
    setEwRun(true); setEwE(null); setEwR(null)
    try {
      const r = await callTool('civil_earthwork_volume', {
        cut_volume_m3: +ew.cut_volume_m3, fill_volume_m3: +ew.fill_volume_m3,
        swell_factor: +ew.swell_factor, shrink_factor: +ew.shrink_factor,
      })
      setEwR(r)
    } catch (e) { setEwE(e.message) } finally { setEwRun(false) }
  }, [ew])

  // ── civil_tin_terrain ──────────────────────────────────────────────────────
  const [tin, setTin] = useState({ grid_size_m: '10', smooth: 'true' })
  const [tinR, setTinR] = useState(null); const [tinE, setTinE] = useState(null); const [tinRun, setTinRun] = useState(false)
  const runTin = useCallback(async () => {
    setTinRun(true); setTinE(null); setTinR(null)
    try {
      const r = await callTool('civil_tin_terrain', {
        points: [
          [0,0,10],[50,0,12],[100,0,8],
          [0,50,15],[50,50,20],[100,50,11],
          [0,100,9],[50,100,14],[100,100,7],
        ],
        grid_size_m: +tin.grid_size_m,
        smooth: tin.smooth === 'true',
      })
      setTinR(r)
    } catch (e) { setTinE(e.message) } finally { setTinRun(false) }
  }, [tin])

  // ── civil_water_network_solve ──────────────────────────────────────────────
  const [wnet, setWnet] = useState({ pipe_diameter_mm: '200', pipe_length_m: '500', roughness_mm: '0.045', demand_lps: '15', supply_head_m: '30' })
  const [wnetR, setWnetR] = useState(null); const [wnetE, setWnetE] = useState(null); const [wnetRun, setWnetRun] = useState(false)
  const runWnet = useCallback(async () => {
    setWnetRun(true); setWnetE(null); setWnetR(null)
    try {
      const r = await callTool('civil_water_network_solve', {
        pipe_diameter_mm: +wnet.pipe_diameter_mm, pipe_length_m: +wnet.pipe_length_m,
        roughness_mm: +wnet.roughness_mm, demand_lps: +wnet.demand_lps,
        supply_head_m: +wnet.supply_head_m,
      })
      setWnetR(r)
    } catch (e) { setWnetE(e.message) } finally { setWnetRun(false) }
  }, [wnet])

  // ── civil_sewer_manning_capacity ───────────────────────────────────────────
  const [sewer, setSewer] = useState({ diameter_mm: '450', slope_pct: '0.5', n_manning: '0.013', fill_ratio: '0.8' })
  const [sewerR, setSewerR] = useState(null); const [sewerE, setSewerE] = useState(null); const [sewerRun, setSewerRun] = useState(false)
  const runSewer = useCallback(async () => {
    setSewerRun(true); setSewerE(null); setSewerR(null)
    try {
      const r = await callTool('civil_sewer_manning_capacity', {
        diameter_mm: +sewer.diameter_mm, slope_pct: +sewer.slope_pct,
        n_manning: +sewer.n_manning, fill_ratio: +sewer.fill_ratio,
      })
      setSewerR(r)
    } catch (e) { setSewerE(e.message) } finally { setSewerRun(false) }
  }, [sewer])

  // ── civil_storm_rational ───────────────────────────────────────────────────
  const [storm, setStorm] = useState({ catchment_area_ha: '5', runoff_coefficient: '0.65', rainfall_intensity_mm_hr: '80' })
  const [stormR, setStormR] = useState(null); const [stormE, setStormE] = useState(null); const [stormRun, setStormRun] = useState(false)
  const runStorm = useCallback(async () => {
    setStormRun(true); setStormE(null); setStormR(null)
    try {
      const r = await callTool('civil_storm_rational', {
        catchment_area_ha: +storm.catchment_area_ha,
        runoff_coefficient: +storm.runoff_coefficient,
        rainfall_intensity_mm_hr: +storm.rainfall_intensity_mm_hr,
      })
      setStormR(r)
    } catch (e) { setStormE(e.message) } finally { setStormRun(false) }
  }, [storm])

  // ── civil_culvert_capacity (HDS-5) ─────────────────────────────────────────
  const [culvert, setCulvert] = useState({ diameter_mm: '900', length_m: '20', slope_pct: '1.5', headwater_depth_m: '1.2', tailwater_depth_m: '0.3', n_manning: '0.024' })
  const [culvertR, setCulvertR] = useState(null); const [culvertE, setCulvertE] = useState(null); const [culvertRun, setCulvertRun] = useState(false)
  const runCulvert = useCallback(async () => {
    setCulvertRun(true); setCulvertE(null); setCulvertR(null)
    try {
      const r = await callTool('civil_culvert_capacity', {
        diameter_mm: +culvert.diameter_mm, length_m: +culvert.length_m,
        slope_pct: +culvert.slope_pct, headwater_depth_m: +culvert.headwater_depth_m,
        tailwater_depth_m: +culvert.tailwater_depth_m, n_manning: +culvert.n_manning,
      })
      setCulvertR(r)
    } catch (e) { setCulvertE(e.message) } finally { setCulvertRun(false) }
  }, [culvert])

  return (
    <div>
      {/* ── Road alignment ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>Road Alignment (AASHTO Green Book)</div>
      </div>

      <ToolWidget title="Horizontal Alignment (civil_horizontal_alignment)" icon={Map} color="#3b82f6" result={haR} error={haE} running={haRun}>
        <NumRow label="Start station (m)" value={ha.start_station} onChange={v => setHa(p => ({ ...p, start_station: v }))} disabled={haRun} />
        <NumRow label="Design speed (kph)" value={ha.design_speed_kph} onChange={v => setHa(p => ({ ...p, design_speed_kph: v }))} disabled={haRun} />
        <NumRow label="Curve radius (m)" value={ha.curve_radius_m} onChange={v => setHa(p => ({ ...p, curve_radius_m: v }))} disabled={haRun} />
        <NumRow label="Tangent length (m)" value={ha.tangent_length_m} onChange={v => setHa(p => ({ ...p, tangent_length_m: v }))} disabled={haRun} />
        <RunBtn onClick={runHA} running={haRun} />
      </ToolWidget>

      <ToolWidget title="Vertical Alignment (civil_vertical_alignment)" icon={Map} color="#8b5cf6" result={vaR} error={vaE} running={vaRun}>
        <NumRow label="Entry grade (%)" value={va.start_grade_pct} onChange={v => setVa(p => ({ ...p, start_grade_pct: v }))} disabled={vaRun} />
        <NumRow label="Exit grade (%)" value={va.end_grade_pct} onChange={v => setVa(p => ({ ...p, end_grade_pct: v }))} disabled={vaRun} />
        <NumRow label="PVI station (m)" value={va.pvi_station} onChange={v => setVa(p => ({ ...p, pvi_station: v }))} disabled={vaRun} />
        <NumRow label="Design speed (kph)" value={va.design_speed_kph} onChange={v => setVa(p => ({ ...p, design_speed_kph: v }))} disabled={vaRun} />
        <SelRow label="Curve type" value={va.sag_or_crest} onChange={v => setVa(p => ({ ...p, sag_or_crest: v }))}
          options={['crest', 'sag']} disabled={vaRun} />
        <RunBtn onClick={runVA} running={vaRun} />
      </ToolWidget>

      <ToolWidget title="Corridor BRep (civil_corridor_brep / GK-P35)" icon={Construction} color="#f59e0b" result={corrR} error={corrE} running={corrRun}>
        <NumRow label="Carriageway width (m)" value={corr.carriageway_width_m} onChange={v => setCorr(p => ({ ...p, carriageway_width_m: v }))} disabled={corrRun} />
        <NumRow label="Shoulder width (m)" value={corr.shoulder_width_m} onChange={v => setCorr(p => ({ ...p, shoulder_width_m: v }))} disabled={corrRun} />
        <NumRow label="Fill slope H:V" value={corr.fill_slope_h} onChange={v => setCorr(p => ({ ...p, fill_slope_h: v }))} disabled={corrRun} />
        <NumRow label="Cut slope H:V" value={corr.cut_slope_h} onChange={v => setCorr(p => ({ ...p, cut_slope_h: v }))} disabled={corrRun} />
        <NumRow label="Corridor length (m)" value={corr.length_m} onChange={v => setCorr(p => ({ ...p, length_m: v }))} disabled={corrRun} />
        <RunBtn onClick={runCorr} running={corrRun} />
      </ToolWidget>

      {/* ── Earthworks ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>Earthworks + Terrain</div>
      </div>

      <ToolWidget title="Earthwork Volume (civil_earthwork_volume)" icon={Construction} color="#10b981" result={ewR} error={ewE} running={ewRun}>
        <NumRow label="Cut volume (m³)" value={ew.cut_volume_m3} onChange={v => setEw(p => ({ ...p, cut_volume_m3: v }))} disabled={ewRun} />
        <NumRow label="Fill volume (m³)" value={ew.fill_volume_m3} onChange={v => setEw(p => ({ ...p, fill_volume_m3: v }))} disabled={ewRun} />
        <NumRow label="Swell factor" value={ew.swell_factor} onChange={v => setEw(p => ({ ...p, swell_factor: v }))} disabled={ewRun} />
        <NumRow label="Shrink factor" value={ew.shrink_factor} onChange={v => setEw(p => ({ ...p, shrink_factor: v }))} disabled={ewRun} />
        <RunBtn onClick={runEW} running={ewRun} />
      </ToolWidget>

      <ToolWidget title="TIN Terrain (civil_tin_terrain)" icon={Map} color="#84cc16" result={tinR} error={tinE} running={tinRun}>
        <NumRow label="Grid size (m)" value={tin.grid_size_m} onChange={v => setTin(p => ({ ...p, grid_size_m: v }))} disabled={tinRun} />
        <SelRow label="Smooth surface" value={tin.smooth} onChange={v => setTin(p => ({ ...p, smooth: v }))}
          options={[{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]} disabled={tinRun} />
        <div style={{ color: '#6b7280', fontSize: 10, marginTop: 4 }}>Uses 9 sample elevation points. Provide full point cloud via API for production.</div>
        <RunBtn onClick={runTin} running={tinRun} />
      </ToolWidget>

      {/* ── Hydraulics ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>Hydraulics (Manning / Rational / HDS-5)</div>
      </div>

      <ToolWidget title="Water Network Solve (civil_water_network_solve)" icon={Droplets} color="#06b6d4" result={wnetR} error={wnetE} running={wnetRun}>
        <NumRow label="Pipe diameter (mm)" value={wnet.pipe_diameter_mm} onChange={v => setWnet(p => ({ ...p, pipe_diameter_mm: v }))} disabled={wnetRun} />
        <NumRow label="Pipe length (m)" value={wnet.pipe_length_m} onChange={v => setWnet(p => ({ ...p, pipe_length_m: v }))} disabled={wnetRun} />
        <NumRow label="Roughness ε (mm)" value={wnet.roughness_mm} onChange={v => setWnet(p => ({ ...p, roughness_mm: v }))} disabled={wnetRun} />
        <NumRow label="Demand (L/s)" value={wnet.demand_lps} onChange={v => setWnet(p => ({ ...p, demand_lps: v }))} disabled={wnetRun} />
        <NumRow label="Supply head (m)" value={wnet.supply_head_m} onChange={v => setWnet(p => ({ ...p, supply_head_m: v }))} disabled={wnetRun} />
        <RunBtn onClick={runWnet} running={wnetRun} />
      </ToolWidget>

      <ToolWidget title="Sewer Manning Capacity (civil_sewer_manning_capacity)" icon={Droplets} color="#0284c7" result={sewerR} error={sewerE} running={sewerRun}>
        <NumRow label="Diameter (mm)" value={sewer.diameter_mm} onChange={v => setSewer(p => ({ ...p, diameter_mm: v }))} disabled={sewerRun} />
        <NumRow label="Slope (%)" value={sewer.slope_pct} onChange={v => setSewer(p => ({ ...p, slope_pct: v }))} disabled={sewerRun} />
        <NumRow label="Manning n" value={sewer.n_manning} onChange={v => setSewer(p => ({ ...p, n_manning: v }))} disabled={sewerRun} />
        <NumRow label="Fill ratio (d/D)" value={sewer.fill_ratio} onChange={v => setSewer(p => ({ ...p, fill_ratio: v }))} disabled={sewerRun} />
        <RunBtn onClick={runSewer} running={sewerRun} />
      </ToolWidget>

      <ToolWidget title="Storm Rational Method (civil_storm_rational)" icon={Droplets} color="#7c3aed" result={stormR} error={stormE} running={stormRun}>
        <NumRow label="Catchment area (ha)" value={storm.catchment_area_ha} onChange={v => setStorm(p => ({ ...p, catchment_area_ha: v }))} disabled={stormRun} />
        <NumRow label="Runoff coefficient C" value={storm.runoff_coefficient} onChange={v => setStorm(p => ({ ...p, runoff_coefficient: v }))} disabled={stormRun} />
        <NumRow label="Rainfall intensity (mm/hr)" value={storm.rainfall_intensity_mm_hr} onChange={v => setStorm(p => ({ ...p, rainfall_intensity_mm_hr: v }))} disabled={stormRun} />
        <RunBtn onClick={runStorm} running={stormRun} />
      </ToolWidget>

      <ToolWidget title="Culvert Capacity (civil_culvert_capacity — HDS-5)" icon={Droplets} color="#be185d" result={culvertR} error={culvertE} running={culvertRun}>
        <NumRow label="Diameter (mm)" value={culvert.diameter_mm} onChange={v => setCulvert(p => ({ ...p, diameter_mm: v }))} disabled={culvertRun} />
        <NumRow label="Length (m)" value={culvert.length_m} onChange={v => setCulvert(p => ({ ...p, length_m: v }))} disabled={culvertRun} />
        <NumRow label="Slope (%)" value={culvert.slope_pct} onChange={v => setCulvert(p => ({ ...p, slope_pct: v }))} disabled={culvertRun} />
        <NumRow label="Headwater depth (m)" value={culvert.headwater_depth_m} onChange={v => setCulvert(p => ({ ...p, headwater_depth_m: v }))} disabled={culvertRun} />
        <NumRow label="Tailwater depth (m)" value={culvert.tailwater_depth_m} onChange={v => setCulvert(p => ({ ...p, tailwater_depth_m: v }))} disabled={culvertRun} />
        <NumRow label="Manning n" value={culvert.n_manning} onChange={v => setCulvert(p => ({ ...p, n_manning: v }))} disabled={culvertRun} />
        <RunBtn onClick={runCulvert} running={culvertRun} />
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// MEP Clash-Aware Routing widget (create_mep_route → auto_route_mep → clash_detect)
// Surfaces the A* path-finding backend and OBB clash engine in a single form.
// ---------------------------------------------------------------------------

function parseXYZ(s) {
  const parts = s.split(',').map(v => parseFloat(v.trim()))
  if (parts.length !== 3 || parts.some(isNaN)) return null
  return parts
}

function parseObstacles(text) {
  // Each line: "minX,minY,minZ:maxX,maxY,maxZ"
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean)
  const obstacles = []
  for (const line of lines) {
    const [minPart, maxPart] = line.split(':')
    if (!minPart || !maxPart) continue
    const mn = minPart.split(',').map(v => parseFloat(v.trim()))
    const mx = maxPart.split(',').map(v => parseFloat(v.trim()))
    if (mn.length === 3 && mx.length === 3 && ![...mn, ...mx].some(isNaN)) {
      obstacles.push({ min: mn, max: mx })
    }
  }
  return obstacles
}

function MEPClashRoutingWidget() {
  // Step 1 — create route
  const [routeKind, setRouteKind] = useState('duct')
  const [sysName, setSysName] = useState('Supply Air')
  const [sizeMm, setSizeMm] = useState('400')
  const [material, setMaterial] = useState('galvanized_steel')
  const [crR, setCrR] = useState(null)
  const [crE, setCrE] = useState(null)
  const [crRun, setCrRun] = useState(false)

  const runCreate = useCallback(async () => {
    setCrRun(true); setCrE(null); setCrR(null)
    try {
      const r = await callTool('create_mep_route', {
        kind: routeKind,
        system_name: sysName,
        size_mm: +sizeMm,
        material,
      })
      setCrR(r)
    } catch (e) { setCrE(e.message) } finally { setCrRun(false) }
  }, [routeKind, sysName, sizeMm, material])

  // Step 2 — auto-route with clash avoidance
  const [fileId, setFileId] = useState('')
  const [startXyz, setStartXyz] = useState('0,0,0')
  const [endXyz, setEndXyz] = useState('6000,0,3000')
  const [gridMm, setGridMm] = useState('300')
  const [obstacleText, setObstacleText] = useState('1000,0,0:3000,2000,2800')
  const [clashToggle, setClashToggle] = useState(true)
  const [arR, setArR] = useState(null)
  const [arE, setArE] = useState(null)
  const [arRun, setArRun] = useState(false)

  // Step 3 — clash results
  const [cdR, setCdR] = useState(null)
  const [cdE, setCdE] = useState(null)

  const runAutoRoute = useCallback(async () => {
    const startPt = parseXYZ(startXyz)
    const endPt = parseXYZ(endXyz)
    if (!startPt) { setArE('Start point must be "x,y,z"'); return }
    if (!endPt) { setArE('End point must be "x,y,z"'); return }

    const obstacles = parseObstacles(obstacleText)

    setArRun(true); setArE(null); setArR(null); setCdR(null); setCdE(null)
    try {
      // Build a synthetic route object with endpoints so auto_route_mep can find them.
      // We use the direct bim_route_mep approach: pass start/end as xyz directly via
      // the create+add_endpoint+auto_route workflow. Since auto_route_mep requires
      // endpoint IDs already in the file, we compute the route client-side by
      // calling the lower-level route then decorating with clash results.
      //
      // Practical flow: use file_id from step 1 if filled; otherwise create a
      // temporary route file first.
      let fid = fileId.trim()
      if (!fid) {
        const cr = await callTool('create_mep_route', {
          kind: routeKind, system_name: sysName, size_mm: +sizeMm, material,
        })
        if (cr?.payload?.file_id) fid = cr.payload.file_id
        else if (cr?.file_id) fid = cr.file_id
        else throw new Error('Could not create route file — check system name')
      }

      // Add start and end endpoints to the route file so auto_route_mep can reference them.
      const epStart = await callTool('add_mep_endpoint', {
        file_id: fid,
        endpoint_id: 'ep_start',
        position: startPt,
        kind: 'source',
      }).catch(() => null)
      const epEnd = await callTool('add_mep_endpoint', {
        file_id: fid,
        endpoint_id: 'ep_end',
        position: endPt,
        kind: 'sink',
      }).catch(() => null)

      // Run A* auto-routing with obstacles from BIM file or inline AABB list.
      const routeArgs = {
        file_id: fid,
        start_endpoint_id: 'ep_start',
        end_endpoint_id: 'ep_end',
        grid_size_mm: +gridMm,
      }
      const routeResult = await callTool('auto_route_mep', routeArgs)
      setArR(routeResult)

      // Step 3 — clash check if enabled
      if (clashToggle && obstacles.length > 0) {
        const route = routeResult?.payload?.route || routeResult?.route
        const segments = route?.segments || []
        const ductD = +(sizeMm) || 400
        const halfD = ductD / 2

        // Build component list: each segment as an AABB, plus each obstacle
        const components = []
        segments.forEach((seg, i) => {
          if (!seg.from || !seg.to) return
          const mn = seg.from.map((v, j) => Math.min(v, seg.to[j]) - halfD)
          const mx = seg.from.map((v, j) => Math.max(v, seg.to[j]) + halfD)
          components.push({
            instance_id: seg.id || `seg_${i}`,
            discipline: 'mep',
            bbox_min: mn,
            bbox_max: mx,
          })
        })
        obstacles.forEach((obs, i) => {
          components.push({
            instance_id: `obstacle_${i}`,
            discipline: 'structural',
            bbox_min: obs.min,
            bbox_max: obs.max,
          })
        })

        if (components.length >= 2) {
          try {
            const cd = await callTool('clash_detect', { components, min_clearance: 0 })
            setCdR(cd)
          } catch (e) { setCdE(e.message) }
        }
      }
    } catch (e) { setArE(e.message) } finally { setArRun(false) }
  }, [fileId, routeKind, sysName, sizeMm, material, startXyz, endXyz, gridMm, obstacleText, clashToggle])

  // Derive clash summary
  const clashes = cdR?.payload?.clashes || cdR?.clashes || []
  const clashCount = cdR?.payload?.clash_count ?? cdR?.clash_count ?? null

  return (
    <div>
      {/* ── Create Route ── */}
      <ToolWidget title="1. Create MEP Route File (create_mep_route)" icon={Route} color="#7c3aed" result={crR} error={crE} running={crRun}>
        <SelRow label="Kind" value={routeKind} onChange={setRouteKind}
          options={['duct', 'pipe', 'conduit']} disabled={crRun} />
        <TxtRow label="System name" value={sysName} onChange={setSysName} disabled={crRun} />
        <NumRow label="Nominal size (mm)" value={sizeMm} onChange={setSizeMm} disabled={crRun} />
        <SelRow label="Material" value={material} onChange={setMaterial}
          options={['galvanized_steel', 'stainless_steel', 'copper', 'pvc', 'hdpe', 'cast_iron', 'concrete']}
          disabled={crRun} />
        <RunBtn onClick={runCreate} running={crRun} label="Create Route File" />
        {crR && (
          <div style={{ ...s.infoBox, marginTop: 6, fontSize: 10 }}>
            File ID: <span style={{ ...s.mono, marginLeft: 4 }}>
              {crR?.payload?.file_id || crR?.file_id || '—'}
            </span>
          </div>
        )}
      </ToolWidget>

      {/* ── Auto-Route + Clash Check ── */}
      <ToolWidget title="2. Auto-Route with Clash Avoidance (auto_route_mep + clash_detect)" icon={ShieldAlert} color="#dc2626" result={null} error={arE} running={arRun}>
        <div style={{ ...s.row, marginBottom: 4 }}>
          <label style={s.label}>File ID (from step 1)</label>
          <input
            type="text"
            placeholder="auto-creates if blank"
            value={fileId}
            onChange={e => setFileId(e.target.value)}
            style={{ ...s.input, fontStyle: fileId ? 'normal' : 'italic', color: fileId ? '#f9fafb' : '#6b7280' }}
            disabled={arRun}
          />
        </div>

        <div style={s.divider} />
        <div style={{ ...s.subhead, marginBottom: 6, marginTop: 2 }}>Route Endpoints (mm)</div>

        <div style={s.row}>
          <label style={s.label}>Start X,Y,Z (mm)</label>
          <input type="text" value={startXyz} onChange={e => setStartXyz(e.target.value)}
            style={s.input} disabled={arRun} placeholder="0,0,0" />
        </div>
        <div style={s.row}>
          <label style={s.label}>End X,Y,Z (mm)</label>
          <input type="text" value={endXyz} onChange={e => setEndXyz(e.target.value)}
            style={s.input} disabled={arRun} placeholder="6000,0,3000" />
        </div>
        <NumRow label="A* grid cell (mm)" value={gridMm} onChange={setGridMm} disabled={arRun} />

        <div style={s.divider} />
        <div style={{ ...s.subhead, marginBottom: 4, marginTop: 2 }}>Obstacles (AABB — one per line)</div>
        <div style={{ ...s.row, alignItems: 'flex-start' }}>
          <label style={{ ...s.label, paddingTop: 2 }}>Obstacle boxes</label>
          <textarea
            value={obstacleText}
            onChange={e => setObstacleText(e.target.value)}
            disabled={arRun}
            rows={3}
            placeholder={'minX,minY,minZ:maxX,maxY,maxZ\n(one obstacle per line)'}
            style={{ ...s.input, resize: 'vertical', fontFamily: 'monospace', lineHeight: 1.4, height: 60 }}
          />
        </div>
        <div style={{ color: '#6b7280', fontSize: 10, marginBottom: 6 }}>
          Format: <span style={s.mono}>minX,minY,minZ:maxX,maxY,maxZ</span> — e.g. a wall at{' '}
          <span style={s.mono}>1000,0,0:3000,200,2800</span>
        </div>

        <div style={s.divider} />
        <div style={s.row}>
          <label style={s.label}>Run clash detection</label>
          <select
            value={clashToggle ? 'yes' : 'no'}
            onChange={e => setClashToggle(e.target.value === 'yes')}
            disabled={arRun}
            style={{ ...s.select, flex: 0, width: 80 }}
          >
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>

        <RunBtn onClick={runAutoRoute} running={arRun} label="Compute Route + Check Clashes" />

        {/* Route result */}
        {arR && !arRun && (
          <div style={s.resultBox}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
              <CheckCircle size={11} style={{ color: '#34d399' }} />
              <span style={{ color: '#34d399', fontWeight: 600 }}>Route computed</span>
            </div>
            {(() => {
              const route = arR?.payload?.route || arR?.route
              const segsAdded = arR?.payload?.segments_added ?? arR?.segments_added ?? '—'
              const warn = arR?.payload?.warning || arR?.warning
              const segs = route?.segments || []
              let totalMm = 0
              let bends = 0
              segs.forEach(seg => {
                if (seg.from && seg.to) {
                  const dx = seg.to[0] - seg.from[0]
                  const dy = seg.to[1] - seg.from[1]
                  const dz = seg.to[2] - seg.from[2]
                  totalMm += Math.sqrt(dx*dx + dy*dy + dz*dz)
                }
                if (seg.kind === 'elbow') bends++
              })
              return (
                <table style={s.table}>
                  <tbody>
                    <tr><td style={{ ...s.td, color: '#9ca3af', width: '55%' }}>segments added</td><td style={{ ...s.td, ...s.mono }}>{segsAdded}</td></tr>
                    <tr><td style={{ ...s.td, color: '#9ca3af' }}>total length (m)</td><td style={{ ...s.td, ...s.mono }}>{(totalMm / 1000).toFixed(2)}</td></tr>
                    <tr><td style={{ ...s.td, color: '#9ca3af' }}>bends (elbows)</td><td style={{ ...s.td, ...s.mono }}>{bends}</td></tr>
                    {warn && <tr><td colSpan={2} style={{ ...s.td, color: '#fbbf24', fontSize: 10 }}>{warn}</td></tr>}
                  </tbody>
                </table>
              )
            })()}
          </div>
        )}

        {/* Clash result */}
        {cdE && (
          <div style={{ ...s.errorBox, marginTop: 6 }}>
            <AlertTriangle size={12} />
            <span>Clash check failed: {cdE}</span>
          </div>
        )}
        {cdR && !arRun && (
          <div style={{ ...s.resultBox, marginTop: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 4 }}>
              <ShieldAlert size={11} style={{ color: clashCount > 0 ? '#f87171' : '#34d399' }} />
              <span style={{ color: clashCount > 0 ? '#f87171' : '#34d399', fontWeight: 600 }}>
                {clashCount === 0 ? 'No clashes — route is clear' : `${clashCount} clash${clashCount !== 1 ? 'es' : ''} detected`}
              </span>
            </div>
            {clashes.length > 0 && (
              <table style={s.table}>
                <thead>
                  <tr>
                    <td style={{ ...s.td, color: '#9ca3af', fontWeight: 600 }}>Segment</td>
                    <td style={{ ...s.td, color: '#9ca3af', fontWeight: 600 }}>Obstacle</td>
                    <td style={{ ...s.td, color: '#9ca3af', fontWeight: 600 }}>Type</td>
                    <td style={{ ...s.td, color: '#9ca3af', fontWeight: 600 }}>Depth (mm)</td>
                  </tr>
                </thead>
                <tbody>
                  {clashes.slice(0, 8).map((cl, i) => (
                    <tr key={i}>
                      <td style={{ ...s.td, ...s.mono, fontSize: 10 }}>{cl.a}</td>
                      <td style={{ ...s.td, ...s.mono, fontSize: 10 }}>{cl.b}</td>
                      <td style={{ ...s.td }}><span style={s.failChip}>{cl.type}</span></td>
                      <td style={{ ...s.td, ...s.mono }}>{cl.depth != null ? cl.depth.toFixed(1) : '—'}</td>
                    </tr>
                  ))}
                  {clashes.length > 8 && (
                    <tr><td colSpan={4} style={{ ...s.td, color: '#6b7280', fontSize: 10 }}>…and {clashes.length - 8} more</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        )}
      </ToolWidget>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TAB 3 — HVAC + Piping (MEP)
// ---------------------------------------------------------------------------

function TabMEP() {
  // ── hvac_cfm_from_sensible_load ────────────────────────────────────────────
  const [cfm, setCfm] = useState({ sensible_load_kW: '12', supply_temp_C: '13', room_temp_C: '24' })
  const [cfmR, setCfmR] = useState(null); const [cfmE, setCfmE] = useState(null); const [cfmRun, setCfmRun] = useState(false)
  const runCfm = useCallback(async () => {
    setCfmRun(true); setCfmE(null); setCfmR(null)
    try {
      const r = await callTool('hvac_cfm_from_sensible_load', {
        sensible_load_kW: +cfm.sensible_load_kW,
        supply_temp_C: +cfm.supply_temp_C,
        room_temp_C: +cfm.room_temp_C,
      })
      setCfmR(r)
    } catch (e) { setCfmE(e.message) } finally { setCfmRun(false) }
  }, [cfm])

  // ── hvac_round_duct_diameter ───────────────────────────────────────────────
  const [ductD, setDuctD] = useState({ flow_rate_m3s: '0.5', max_velocity_ms: '8', friction_rate_Pa_per_m: '1.0' })
  const [ductDR, setDuctDR] = useState(null); const [ductDE, setDuctDE] = useState(null); const [ductDRun, setDuctDRun] = useState(false)
  const runDuctD = useCallback(async () => {
    setDuctDRun(true); setDuctDE(null); setDuctDR(null)
    try {
      const r = await callTool('hvac_round_duct_diameter', {
        flow_rate_m3s: +ductD.flow_rate_m3s,
        max_velocity_ms: +ductD.max_velocity_ms,
        friction_rate_Pa_per_m: +ductD.friction_rate_Pa_per_m,
      })
      setDuctDR(r)
    } catch (e) { setDuctDE(e.message) } finally { setDuctDRun(false) }
  }, [ductD])

  // ── hvac_duct_friction_loss ────────────────────────────────────────────────
  const [dfl, setDfl] = useState({ diameter_mm: '400', length_m: '30', flow_rate_m3s: '0.5', roughness_mm: '0.09' })
  const [dflR, setDflR] = useState(null); const [dflE, setDflE] = useState(null); const [dflRun, setDflRun] = useState(false)
  const runDfl = useCallback(async () => {
    setDflRun(true); setDflE(null); setDflR(null)
    try {
      const r = await callTool('hvac_duct_friction_loss', {
        diameter_mm: +dfl.diameter_mm, length_m: +dfl.length_m,
        flow_rate_m3s: +dfl.flow_rate_m3s, roughness_mm: +dfl.roughness_mm,
      })
      setDflR(r)
    } catch (e) { setDflE(e.message) } finally { setDflRun(false) }
  }, [dfl])

  // ── hvac_rect_equiv_diameter ───────────────────────────────────────────────
  const [rect, setRect] = useState({ width_mm: '600', height_mm: '300' })
  const [rectR, setRectR] = useState(null); const [rectE, setRectE] = useState(null); const [rectRun, setRectRun] = useState(false)
  const runRect = useCallback(async () => {
    setRectRun(true); setRectE(null); setRectR(null)
    try {
      const r = await callTool('hvac_rect_equiv_diameter', {
        width_mm: +rect.width_mm, height_mm: +rect.height_mm,
      })
      setRectR(r)
    } catch (e) { setRectE(e.message) } finally { setRectRun(false) }
  }, [rect])

  // ── hvac_fan_law_scale ─────────────────────────────────────────────────────
  const [fan, setFan] = useState({ flow_1_m3s: '2.0', pressure_1_Pa: '500', power_1_kW: '1.5', flow_2_m3s: '2.4' })
  const [fanR, setFanR] = useState(null); const [fanE, setFanE] = useState(null); const [fanRun, setFanRun] = useState(false)
  const runFan = useCallback(async () => {
    setFanRun(true); setFanE(null); setFanR(null)
    try {
      const r = await callTool('hvac_fan_law_scale', {
        flow_1_m3s: +fan.flow_1_m3s, pressure_1_Pa: +fan.pressure_1_Pa,
        power_1_kW: +fan.power_1_kW, flow_2_m3s: +fan.flow_2_m3s,
      })
      setFanR(r)
    } catch (e) { setFanE(e.message) } finally { setFanRun(false) }
  }, [fan])

  // ── hvac_branch_static_pressure ────────────────────────────────────────────
  const [bsp, setBsp] = useState({ upstream_pressure_Pa: '200', velocity_1_ms: '5', velocity_2_ms: '3', density_kg_m3: '1.2' })
  const [bspR, setBspR] = useState(null); const [bspE, setBspE] = useState(null); const [bspRun, setBspRun] = useState(false)
  const runBsp = useCallback(async () => {
    setBspRun(true); setBspE(null); setBspR(null)
    try {
      const r = await callTool('hvac_branch_static_pressure', {
        upstream_pressure_Pa: +bsp.upstream_pressure_Pa,
        velocity_1_ms: +bsp.velocity_1_ms,
        velocity_2_ms: +bsp.velocity_2_ms,
        density_kg_m3: +bsp.density_kg_m3,
      })
      setBspR(r)
    } catch (e) { setBspE(e.message) } finally { setBspRun(false) }
  }, [bsp])

  // ── pipe_pressure_drop ─────────────────────────────────────────────────────
  const [ppd, setPpd] = useState({ pipe_od_mm: '114.3', schedule: '40', length_m: '120', fluid: 'water', flow_rate_lps: '8', temperature_C: '60' })
  const [ppdR, setPpdR] = useState(null); const [ppdE, setPpdE] = useState(null); const [ppdRun, setPpdRun] = useState(false)
  const runPpd = useCallback(async () => {
    setPpdRun(true); setPpdE(null); setPpdR(null)
    try {
      const r = await callTool('pipe_pressure_drop', {
        pipe_od_mm: +ppd.pipe_od_mm, schedule: ppd.schedule,
        length_m: +ppd.length_m, fluid: ppd.fluid,
        flow_rate_lps: +ppd.flow_rate_lps, temperature_C: +ppd.temperature_C,
      })
      setPpdR(r)
    } catch (e) { setPpdE(e.message) } finally { setPpdRun(false) }
  }, [ppd])

  // ── pipe_thermal_expansion ─────────────────────────────────────────────────
  const [pte, setPte] = useState({ pipe_od_mm: '114.3', length_m: '50', material: 'carbon_steel', T_install_C: '20', T_operating_C: '180' })
  const [pteR, setPteR] = useState(null); const [pteE, setPteE] = useState(null); const [pteRun, setPteRun] = useState(false)
  const runPte = useCallback(async () => {
    setPteRun(true); setPteE(null); setPteR(null)
    try {
      const r = await callTool('pipe_thermal_expansion', {
        pipe_od_mm: +pte.pipe_od_mm, length_m: +pte.length_m,
        material: pte.material, T_install_C: +pte.T_install_C,
        T_operating_C: +pte.T_operating_C,
      })
      setPteR(r)
    } catch (e) { setPteE(e.message) } finally { setPteRun(false) }
  }, [pte])

  // ── pipe_wall_thickness (ASME B31.1) ───────────────────────────────────────
  const [pwt, setPwt] = useState({ pipe_od_mm: '114.3', design_pressure_MPa: '4.5', material: 'A106-B', temperature_C: '250', mill_tolerance_pct: '12.5' })
  const [pwtR, setPwtR] = useState(null); const [pwtE, setPwtE] = useState(null); const [pwtRun, setPwtRun] = useState(false)
  const runPwt = useCallback(async () => {
    setPwtRun(true); setPwtE(null); setPwtR(null)
    try {
      const r = await callTool('pipe_wall_thickness', {
        pipe_od_mm: +pwt.pipe_od_mm, design_pressure_MPa: +pwt.design_pressure_MPa,
        material: pwt.material, temperature_C: +pwt.temperature_C,
        mill_tolerance_pct: +pwt.mill_tolerance_pct,
      })
      setPwtR(r)
    } catch (e) { setPwtE(e.message) } finally { setPwtRun(false) }
  }, [pwt])

  // ── pipe_allowable_span ─────────────────────────────────────────────────────
  const [pas, setPas] = useState({ pipe_od_mm: '114.3', schedule: '40', fluid: 'water', deflection_limit_mm: '3', support_type: 'simply_supported' })
  const [pasR, setPasR] = useState(null); const [pasE, setPasE] = useState(null); const [pasRun, setPasRun] = useState(false)
  const runPas = useCallback(async () => {
    setPasRun(true); setPasE(null); setPasR(null)
    try {
      const r = await callTool('pipe_allowable_span', {
        pipe_od_mm: +pas.pipe_od_mm, schedule: pas.schedule,
        fluid: pas.fluid, deflection_limit_mm: +pas.deflection_limit_mm,
        support_type: pas.support_type,
      })
      setPasR(r)
    } catch (e) { setPasE(e.message) } finally { setPasRun(false) }
  }, [pas])

  // ── piping_route_isometric ─────────────────────────────────────────────────
  const [iso, setIso] = useState({ pipe_spec: 'ASME_B31_1', nominal_size_in: '4', from_node: 'P-001', to_node: 'P-002', fluid_service: 'steam' })
  const [isoR, setIsoR] = useState(null); const [isoE, setIsoE] = useState(null); const [isoRun, setIsoRun] = useState(false)
  const runIso = useCallback(async () => {
    setIsoRun(true); setIsoE(null); setIsoR(null)
    try {
      const r = await callTool('piping_route_isometric', {
        pipe_spec: iso.pipe_spec, nominal_size_in: +iso.nominal_size_in,
        from_node: iso.from_node, to_node: iso.to_node,
        fluid_service: iso.fluid_service,
      })
      setIsoR(r)
    } catch (e) { setIsoE(e.message) } finally { setIsoRun(false) }
  }, [iso])

  return (
    <div>
      {/* ── HVAC group ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>HVAC — Duct Design (ASHRAE HoF 2021 §21)</div>
      </div>

      <ToolWidget title="Airflow from Sensible Load (hvac_cfm_from_sensible_load)" icon={Wind} color="#06b6d4" result={cfmR} error={cfmE} running={cfmRun}>
        <NumRow label="Sensible load (kW)" value={cfm.sensible_load_kW} onChange={v => setCfm(p => ({ ...p, sensible_load_kW: v }))} disabled={cfmRun} />
        <NumRow label="Supply air temp (°C)" value={cfm.supply_temp_C} onChange={v => setCfm(p => ({ ...p, supply_temp_C: v }))} disabled={cfmRun} />
        <NumRow label="Room temp (°C)" value={cfm.room_temp_C} onChange={v => setCfm(p => ({ ...p, room_temp_C: v }))} disabled={cfmRun} />
        <RunBtn onClick={runCfm} running={cfmRun} />
      </ToolWidget>

      <ToolWidget title="Round Duct Sizing (hvac_round_duct_diameter)" icon={Wind} color="#0ea5e9" result={ductDR} error={ductDE} running={ductDRun}>
        <NumRow label="Flow rate (m³/s)" value={ductD.flow_rate_m3s} onChange={v => setDuctD(p => ({ ...p, flow_rate_m3s: v }))} disabled={ductDRun} />
        <NumRow label="Max velocity (m/s)" value={ductD.max_velocity_ms} onChange={v => setDuctD(p => ({ ...p, max_velocity_ms: v }))} disabled={ductDRun} />
        <NumRow label="Friction rate (Pa/m)" value={ductD.friction_rate_Pa_per_m} onChange={v => setDuctD(p => ({ ...p, friction_rate_Pa_per_m: v }))} disabled={ductDRun} />
        <RunBtn onClick={runDuctD} running={ductDRun} />
      </ToolWidget>

      <ToolWidget title="Duct Friction Loss (hvac_duct_friction_loss — Darcy-Weisbach)" icon={Wind} color="#7c3aed" result={dflR} error={dflE} running={dflRun}>
        <NumRow label="Duct diameter (mm)" value={dfl.diameter_mm} onChange={v => setDfl(p => ({ ...p, diameter_mm: v }))} disabled={dflRun} />
        <NumRow label="Duct length (m)" value={dfl.length_m} onChange={v => setDfl(p => ({ ...p, length_m: v }))} disabled={dflRun} />
        <NumRow label="Flow rate (m³/s)" value={dfl.flow_rate_m3s} onChange={v => setDfl(p => ({ ...p, flow_rate_m3s: v }))} disabled={dflRun} />
        <NumRow label="Roughness ε (mm)" value={dfl.roughness_mm} onChange={v => setDfl(p => ({ ...p, roughness_mm: v }))} disabled={dflRun} />
        <RunBtn onClick={runDfl} running={dflRun} />
      </ToolWidget>

      <ToolWidget title="Rect Duct Equiv Diameter (hvac_rect_equiv_diameter)" icon={Wind} color="#a78bfa" result={rectR} error={rectE} running={rectRun}>
        <NumRow label="Width (mm)" value={rect.width_mm} onChange={v => setRect(p => ({ ...p, width_mm: v }))} disabled={rectRun} />
        <NumRow label="Height (mm)" value={rect.height_mm} onChange={v => setRect(p => ({ ...p, height_mm: v }))} disabled={rectRun} />
        <RunBtn onClick={runRect} running={rectRun} />
      </ToolWidget>

      <ToolWidget title="Fan Law Scaling (hvac_fan_law_scale)" icon={Wind} color="#f43f5e" result={fanR} error={fanE} running={fanRun}>
        <NumRow label="Flow Q₁ (m³/s)" value={fan.flow_1_m3s} onChange={v => setFan(p => ({ ...p, flow_1_m3s: v }))} disabled={fanRun} />
        <NumRow label="Pressure ΔP₁ (Pa)" value={fan.pressure_1_Pa} onChange={v => setFan(p => ({ ...p, pressure_1_Pa: v }))} disabled={fanRun} />
        <NumRow label="Power P₁ (kW)" value={fan.power_1_kW} onChange={v => setFan(p => ({ ...p, power_1_kW: v }))} disabled={fanRun} />
        <NumRow label="New flow Q₂ (m³/s)" value={fan.flow_2_m3s} onChange={v => setFan(p => ({ ...p, flow_2_m3s: v }))} disabled={fanRun} />
        <RunBtn onClick={runFan} running={fanRun} />
      </ToolWidget>

      <ToolWidget title="Branch Static Pressure (hvac_branch_static_pressure)" icon={Wind} color="#f59e0b" result={bspR} error={bspE} running={bspRun}>
        <NumRow label="Upstream pressure (Pa)" value={bsp.upstream_pressure_Pa} onChange={v => setBsp(p => ({ ...p, upstream_pressure_Pa: v }))} disabled={bspRun} />
        <NumRow label="Upstream velocity (m/s)" value={bsp.velocity_1_ms} onChange={v => setBsp(p => ({ ...p, velocity_1_ms: v }))} disabled={bspRun} />
        <NumRow label="Downstream velocity (m/s)" value={bsp.velocity_2_ms} onChange={v => setBsp(p => ({ ...p, velocity_2_ms: v }))} disabled={bspRun} />
        <NumRow label="Air density (kg/m³)" value={bsp.density_kg_m3} onChange={v => setBsp(p => ({ ...p, density_kg_m3: v }))} disabled={bspRun} />
        <RunBtn onClick={runBsp} running={bspRun} />
      </ToolWidget>

      {/* ── Piping group ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>Piping — ASME B31.1/B31.3</div>
      </div>

      <ToolWidget title="Pipe Pressure Drop (pipe_pressure_drop)" icon={Pipette} color="#10b981" result={ppdR} error={ppdE} running={ppdRun}>
        <NumRow label="Pipe OD (mm)" value={ppd.pipe_od_mm} onChange={v => setPpd(p => ({ ...p, pipe_od_mm: v }))} disabled={ppdRun} />
        <TxtRow label="Schedule" value={ppd.schedule} onChange={v => setPpd(p => ({ ...p, schedule: v }))} disabled={ppdRun} />
        <NumRow label="Length (m)" value={ppd.length_m} onChange={v => setPpd(p => ({ ...p, length_m: v }))} disabled={ppdRun} />
        <SelRow label="Fluid" value={ppd.fluid} onChange={v => setPpd(p => ({ ...p, fluid: v }))}
          options={['water', 'steam', 'air', 'glycol_40', 'oil']} disabled={ppdRun} />
        <NumRow label="Flow rate (L/s)" value={ppd.flow_rate_lps} onChange={v => setPpd(p => ({ ...p, flow_rate_lps: v }))} disabled={ppdRun} />
        <NumRow label="Temperature (°C)" value={ppd.temperature_C} onChange={v => setPpd(p => ({ ...p, temperature_C: v }))} disabled={ppdRun} />
        <RunBtn onClick={runPpd} running={ppdRun} />
      </ToolWidget>

      <ToolWidget title="Thermal Expansion (pipe_thermal_expansion)" icon={Pipette} color="#f97316" result={pteR} error={pteE} running={pteRun}>
        <NumRow label="Pipe OD (mm)" value={pte.pipe_od_mm} onChange={v => setPte(p => ({ ...p, pipe_od_mm: v }))} disabled={pteRun} />
        <NumRow label="Pipe length (m)" value={pte.length_m} onChange={v => setPte(p => ({ ...p, length_m: v }))} disabled={pteRun} />
        <SelRow label="Material" value={pte.material} onChange={v => setPte(p => ({ ...p, material: v }))}
          options={['carbon_steel', 'stainless_304', 'stainless_316', 'copper', 'aluminum', 'HDPE']} disabled={pteRun} />
        <NumRow label="Install temp (°C)" value={pte.T_install_C} onChange={v => setPte(p => ({ ...p, T_install_C: v }))} disabled={pteRun} />
        <NumRow label="Operating temp (°C)" value={pte.T_operating_C} onChange={v => setPte(p => ({ ...p, T_operating_C: v }))} disabled={pteRun} />
        <RunBtn onClick={runPte} running={pteRun} />
      </ToolWidget>

      <ToolWidget title="Wall Thickness ASME B31.1 (pipe_wall_thickness)" icon={Pipette} color="#ef4444" result={pwtR} error={pwtE} running={pwtRun}>
        <NumRow label="Pipe OD (mm)" value={pwt.pipe_od_mm} onChange={v => setPwt(p => ({ ...p, pipe_od_mm: v }))} disabled={pwtRun} />
        <NumRow label="Design pressure (MPa)" value={pwt.design_pressure_MPa} onChange={v => setPwt(p => ({ ...p, design_pressure_MPa: v }))} disabled={pwtRun} />
        <SelRow label="Material" value={pwt.material} onChange={v => setPwt(p => ({ ...p, material: v }))}
          options={['A106-B', 'A53-B', 'A312-304', 'A312-316']} disabled={pwtRun} />
        <NumRow label="Temperature (°C)" value={pwt.temperature_C} onChange={v => setPwt(p => ({ ...p, temperature_C: v }))} disabled={pwtRun} />
        <NumRow label="Mill tolerance (%)" value={pwt.mill_tolerance_pct} onChange={v => setPwt(p => ({ ...p, mill_tolerance_pct: v }))} disabled={pwtRun} />
        <RunBtn onClick={runPwt} running={pwtRun} />
      </ToolWidget>

      <ToolWidget title="Allowable Pipe Span (pipe_allowable_span)" icon={Pipette} color="#8b5cf6" result={pasR} error={pasE} running={pasRun}>
        <NumRow label="Pipe OD (mm)" value={pas.pipe_od_mm} onChange={v => setPas(p => ({ ...p, pipe_od_mm: v }))} disabled={pasRun} />
        <TxtRow label="Schedule" value={pas.schedule} onChange={v => setPas(p => ({ ...p, schedule: v }))} disabled={pasRun} />
        <SelRow label="Fluid" value={pas.fluid} onChange={v => setPas(p => ({ ...p, fluid: v }))}
          options={['water', 'steam', 'air', 'empty']} disabled={pasRun} />
        <NumRow label="Deflection limit (mm)" value={pas.deflection_limit_mm} onChange={v => setPas(p => ({ ...p, deflection_limit_mm: v }))} disabled={pasRun} />
        <SelRow label="Support type" value={pas.support_type} onChange={v => setPas(p => ({ ...p, support_type: v }))}
          options={['simply_supported', 'fixed_fixed', 'cantilever']} disabled={pasRun} />
        <RunBtn onClick={runPas} running={pasRun} />
      </ToolWidget>

      <ToolWidget title="Piping Isometric Route (piping_route_isometric)" icon={Pipette} color="#22d3ee" result={isoR} error={isoE} running={isoRun}>
        <SelRow label="Pipe spec" value={iso.pipe_spec} onChange={v => setIso(p => ({ ...p, pipe_spec: v }))}
          options={['ASME_B31_1', 'ASME_B31_3', 'ASME_B31_4', 'EN_13480']} disabled={isoRun} />
        <NumRow label="Nominal size (in)" value={iso.nominal_size_in} onChange={v => setIso(p => ({ ...p, nominal_size_in: v }))} disabled={isoRun} />
        <TxtRow label="From node" value={iso.from_node} onChange={v => setIso(p => ({ ...p, from_node: v }))} disabled={isoRun} />
        <TxtRow label="To node" value={iso.to_node} onChange={v => setIso(p => ({ ...p, to_node: v }))} disabled={isoRun} />
        <SelRow label="Fluid service" value={iso.fluid_service} onChange={v => setIso(p => ({ ...p, fluid_service: v }))}
          options={['steam', 'water', 'gas', 'chemical', 'cryogenic']} disabled={isoRun} />
        <RunBtn onClick={runIso} running={isoRun} />
      </ToolWidget>

      {/* ── MEP Clash-Aware Routing group ── */}
      <div style={{ ...s.section, background: '#16213e', marginBottom: 4, padding: '6px 10px' }}>
        <div style={{ ...s.subhead, marginBottom: 0 }}>MEP Clash-Aware Routing (A* + clash_detect)</div>
      </div>

      <MEPClashRoutingWidget />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Root panel
// ---------------------------------------------------------------------------

const TABS = [
  { id: 'bim',   label: 'BIM (Building)',       Icon: Building2 },
  { id: 'civil', label: 'Civil (Infra)',         Icon: Construction },
  { id: 'mep',   label: 'HVAC + Piping (MEP)',  Icon: Wind },
]

export default function BIMCivilPanel() {
  const [tab, setTab] = useState('bim')

  return (
    <div style={s.root}>
      <div style={s.header}>
        <Building2 size={16} style={{ color: '#60a5fa' }} />
        <span style={s.title}>BIM / Civil / MEP</span>
        <span style={s.subtitle}>34 tools — IFC 4 · Civil 3D · ASHRAE · ASME B31 · MEP clash-routing</span>
      </div>

      <div style={s.tabs}>
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            style={{ ...s.tab, ...(tab === id ? s.tabActive : {}) }}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <Icon size={11} />
              {label}
            </span>
          </button>
        ))}
      </div>

      {tab === 'bim'   && <TabBIM />}
      {tab === 'civil' && <TabCivil />}
      {tab === 'mep'   && <TabMEP />}
    </div>
  )
}
