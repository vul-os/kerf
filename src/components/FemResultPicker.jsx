// TODO(parent-integration): Wire FemResultPicker into FEMDeformedShape's
// parent (e.g. FEMPanel or the analysis result drawer).  Pass `result` from
// the API response (after parseFEMResult), and forward `field` + `scaleName`
// to FEMDeformedShape as `colorMode` and whichever colour-scale lookup the
// parent exposes.  Example:
//
//   const [field, setField] = useState('displacement')
//   const [palette, setPalette] = useState('viridis')
//
//   <FemResultPicker
//     result={femResult}
//     field={field}
//     scaleName={palette}
//     onChange={({ field, scaleName }) => { setField(field); setPalette(scaleName) }}
//   />
//   <FEMDeformedShape
//     nodeDisplacements={femResult.nodeDisplacements}
//     stresses={femResult.stresses}
//     colorMode={field}
//     maxDisplacement={femResult.maxDisplacement}
//     maxStress={femResult.maxVonmises}
//     ...
//   />

import { useMemo } from 'react'
import {
  availableFields,
  pickColorConfig,
  fieldLabel,
  FIELD_DISPLACEMENT,
} from '../lib/femResults.js'
import { COLOR_SCALE_NAMES, scaleToCSS } from '../lib/femColorScales.js'

// ── prop defaults ─────────────────────────────────────────────────────────────

const DEFAULT_FIELD = FIELD_DISPLACEMENT
const DEFAULT_SCALE = 'viridis'

// ── component ─────────────────────────────────────────────────────────────────

/**
 * FemResultPicker — small UI strip for selecting which FEM result field to
 * visualise (displacement / von Mises / temperature / modal) and which colour
 * palette to use.
 *
 * Props:
 *   result      NormalisedFEMResult (from parseFEMResult)   required
 *   field       string  currently selected field name        optional
 *   scaleName   string  currently selected palette name      optional
 *   onChange    ({field, scaleName}) => void                 optional
 *   compact     boolean  render in single-row compact mode   optional
 */
export default function FemResultPicker({
  result,
  field = DEFAULT_FIELD,
  scaleName = DEFAULT_SCALE,
  onChange,
  compact = false,
}) {
  const fields = useMemo(() => availableFields(result), [result])
  const colorConfig = useMemo(
    () => result ? pickColorConfig(result, field, scaleName) : null,
    [result, field, scaleName]
  )

  function handleFieldChange(e) {
    const nextField = e.target.value
    onChange?.({ field: nextField, scaleName })
  }

  function handleScaleChange(e) {
    const nextScale = e.target.value
    onChange?.({ field, scaleName: nextScale })
  }

  if (!result || fields.length === 0) {
    return (
      <div style={styles.empty}>
        <span style={styles.emptyText}>No result data available</span>
      </div>
    )
  }

  // Gradient preview strip using the current palette
  const gradientStops = Array.from({ length: 7 }, (_, i) => scaleToCSS(scaleName, i / 6))
  const gradient = `linear-gradient(to right, ${gradientStops.join(', ')})`

  return (
    <div
      style={compact ? styles.wrapperCompact : styles.wrapper}
      role="group"
      aria-label="FEM result display options"
    >
      {/* Field selector */}
      <div style={compact ? styles.rowCompact : styles.row}>
        <label style={styles.label} htmlFor="fem-field-select">
          Field
        </label>
        <select
          id="fem-field-select"
          value={field}
          onChange={handleFieldChange}
          style={styles.select}
          aria-label="Result field"
        >
          {fields.map(f => (
            <option key={f} value={f}>
              {fieldLabel(f)}
            </option>
          ))}
        </select>
      </div>

      {/* Palette selector */}
      <div style={compact ? styles.rowCompact : styles.row}>
        <label style={styles.label} htmlFor="fem-scale-select">
          Palette
        </label>
        <select
          id="fem-scale-select"
          value={scaleName}
          onChange={handleScaleChange}
          style={styles.select}
          aria-label="Colour palette"
        >
          {COLOR_SCALE_NAMES.map(name => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      {/* Gradient preview + range */}
      {colorConfig && (
        <div style={styles.colorBarWrap} aria-hidden="true">
          <span style={styles.rangeLabel}>
            {fmtValue(colorConfig.minValue, colorConfig.unit)}
          </span>
          <div style={{ ...styles.colorBar, background: gradient }} />
          <span style={styles.rangeLabel}>
            {fmtValue(colorConfig.maxValue, colorConfig.unit)}
          </span>
        </div>
      )}
    </div>
  )
}

// ── formatting ────────────────────────────────────────────────────────────────

function fmtValue(value, unit) {
  if (value == null || !isFinite(value)) return '—'
  switch (unit) {
    case 'mm':  return (value * 1e3).toFixed(3) + ' mm'
    case 'MPa': return (value / 1e6).toFixed(2) + ' MPa'
    case 'K':   return value.toFixed(1) + ' K'
    default:    return value.toPrecision(3)
  }
}

// ── styles ────────────────────────────────────────────────────────────────────

const styles = {
  wrapper: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    padding: '6px 0',
  },
  wrapperCompact: {
    display: 'flex',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    alignItems: 'center',
    padding: '4px 0',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  rowCompact: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  label: {
    fontSize: 11,
    color: '#9ca3af',
    minWidth: 42,
    fontFamily: 'inherit',
  },
  select: {
    fontSize: 11,
    color: '#e5e7eb',
    background: '#1f2937',
    border: '1px solid #374151',
    borderRadius: 4,
    padding: '2px 4px',
    cursor: 'pointer',
    outline: 'none',
    fontFamily: 'inherit',
  },
  colorBarWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    marginTop: 2,
  },
  colorBar: {
    flex: 1,
    height: 8,
    borderRadius: 3,
  },
  rangeLabel: {
    fontSize: 10,
    color: '#6b7280',
    fontFamily: 'monospace',
    whiteSpace: 'nowrap',
    minWidth: 48,
  },
  empty: {
    padding: '4px 0',
  },
  emptyText: {
    fontSize: 11,
    color: '#6b7280',
    fontStyle: 'italic',
  },
}
