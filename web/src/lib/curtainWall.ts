/**
 * curtainWall.js — Pure JS parametric curtain wall (Revit-style panel grid).
 *
 * u and v are normalized coordinates in [0, 1].
 * All dimensions in millimetres.
 */

export function defaultCurtainWall(base_curve_or_wall_id) {
  return {
    version: 1,
    name: 'Curtain Wall',
    base_curve_or_wall_id,
    height_mm: 3000,
    u_divisions: [{ type: 'count', value: 4 }],
    v_divisions: [{ type: 'count', value: 6 }],
    panel_type: {
      kind: 'glass',
      material_id: null,
      color: null,
    },
    mullion_type: {
      profile: 'square',
      size_mm: 50,
      color: null,
    },
    top_rail: {
      profile: 'square',
      size_mm: 50,
      visible: true,
    },
    bottom_rail: {
      profile: 'square',
      size_mm: 50,
      visible: true,
    },
  }
}

export function validateCurtainWall(cw) {
  const errors = []

  if (!cw || typeof cw !== 'object') {
    errors.push('curtain wall must be an object')
    return { ok: false, errors }
  }

  if (cw.version !== 1) {
    errors.push(`version must be 1, got ${cw.version}`)
  }

  const h = cw.height_mm
  if (typeof h !== 'number' || h <= 0) {
    errors.push(`height_mm (${h}) must be a positive number`)
  }

  for (const axis of ['u_divisions', 'v_divisions']) {
    const divs = cw[axis]
    if (!Array.isArray(divs) || divs.length === 0) {
      errors.push(`${axis} must be a non-empty array`)
      continue
    }
    for (let i = 0; i < divs.length; i++) {
      const d = divs[i]
      if (!d || typeof d !== 'object') {
        errors.push(`${axis}[${i}] must be an object`)
        continue
      }
      if (!['count', 'spacing', 'mixed'].includes(d.type)) {
        errors.push(`${axis}[${i}].type must be 'count', 'spacing', or 'mixed'`)
      }
      if (d.type === 'count' && (typeof d.value !== 'number' || !Number.isInteger(d.value) || d.value < 1)) {
        errors.push(`${axis}[${i}].value must be a positive integer for type='count'`)
      }
      if (d.type === 'spacing' && (typeof d.value !== 'number' || d.value <= 0)) {
        errors.push(`${axis}[${i}].value must be a positive number for type='spacing'`)
      }
      if (d.type === 'mixed' && !Array.isArray(d.value)) {
        errors.push(`${axis}[${i}].value must be an array for type='mixed'`)
      }
    }
  }

  const pt = cw.panel_type || {}
  if (!['glass', 'solid', 'opening'].includes(pt.kind)) {
    errors.push(`panel_type.kind must be 'glass', 'solid', or 'opening'`)
  }

  const mt = cw.mullion_type || {}
  if (!['square', 'round'].includes(mt.profile)) {
    errors.push(`mullion_type.profile must be 'square' or 'round'`)
  }
  if (typeof mt.size_mm !== 'number' || mt.size_mm <= 0) {
    errors.push(`mullion_type.size_mm must be a positive number`)
  }

  return { ok: errors.length === 0, errors }
}

function _computeLines(divisions, length) {
  const lines = [0]
  for (const div of divisions) {
    const last = lines[lines.length - 1]
    if (div.type === 'count') {
      const step = 1 / div.value
      for (let i = 1; i <= div.value; i++) {
        lines.push(Math.min(last + step * i, 1))
      }
    } else if (div.type === 'spacing') {
      const spacing_normalized = div.value / length
      let pos = last + spacing_normalized
      while (pos <= 1 + 1e-9) {
        lines.push(Math.min(pos, 1))
        pos += spacing_normalized
      }
    } else if (div.type === 'mixed') {
      let running = last
      for (const sub of div.value) {
        if (sub.type === 'count') {
          const step = 1 / (div.value.length * sub.value)
          for (let i = 1; i <= sub.value; i++) {
            running += step
            lines.push(running)
          }
        } else if (sub.type === 'spacing') {
          const spacing_normalized = sub.value / length
          running += spacing_normalized
          lines.push(Math.min(running, 1))
        }
      }
    }
  }
  return lines
}

export function computeGrid(cw, base_curve_length, height) {
  const u_lines = _computeLines(cw.u_divisions, base_curve_length)
  const v_lines = _computeLines(cw.v_divisions, height)
  return { u_lines, v_lines }
}

export function generatePanels(cw) {
  const length = 10000
  const height = cw.height_mm
  const { u_lines, v_lines } = computeGrid(cw, length, height)

  const panels = []
  for (let i = 0; i < u_lines.length - 1; i++) {
    for (let j = 0; j < v_lines.length - 1; j++) {
      panels.push({
        bounds: [[u_lines[i], v_lines[j]], [u_lines[i + 1], v_lines[j + 1]]],
        type: cw.panel_type.kind,
        position_3d: [
          [(u_lines[i] + u_lines[i + 1]) / 2, 0, (v_lines[j] + v_lines[j + 1]) / 2],
          [(u_lines[i] + u_lines[i + 1]) / 2, 0, (v_lines[j] + v_lines[j + 1]) / 2],
        ],
      })
    }
  }
  return panels
}

export function generateMullions(cw) {
  const length = 10000
  const height = cw.height_mm
  const { u_lines, v_lines } = computeGrid(cw, length, height)

  const mullions = []
  const { profile, size_mm, color } = cw.mullion_type

  for (let i = 0; i < u_lines.length; i++) {
    mullions.push({
      start: [u_lines[i], 0, 0],
      end: [u_lines[i], 0, height],
      profile,
      size_mm,
      color,
    })
  }

  for (let j = 0; j < v_lines.length; j++) {
    mullions.push({
      start: [0, 0, v_lines[j]],
      end: [length, 0, v_lines[j]],
      profile,
      size_mm,
      color,
    })
  }

  return mullions
}

export function setDivisionScheme(cw, axis, divisions) {
  if (axis !== 'u' && axis !== 'v') {
    throw new Error("axis must be 'u' or 'v'")
  }
  const key = axis === 'u' ? 'u_divisions' : 'v_divisions'
  return { ...cw, [key]: divisions }
}

export function setPanelType(cw, panelTypeObj) {
  return { ...cw, panel_type: { ...cw.panel_type, ...panelTypeObj } }
}
