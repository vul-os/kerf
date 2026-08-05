export function setPadMaskOverride(pad, expansion_mm) {
  pad.mask_override = { expansion_mm }
}

export function setPadPasteOverride(pad, scaleOrOffset) {
  if (typeof scaleOrOffset === 'number') {
    pad.paste_override = { scale: scaleOrOffset }
  } else if (scaleOrOffset && typeof scaleOrOffset === 'object') {
    pad.paste_override = { ...scaleOrOffset }
  }
}

export function getEffectivePadMask(pad, board_defaults) {
  const expansion = pad.mask_override?.expansion_mm ??
    (board_defaults == null ? 0.05 : board_defaults.mask_expansion_mm !== undefined ? board_defaults.mask_expansion_mm : 0)
  const w = pad.width ?? pad.pad_diameter ?? 0
  const h = pad.height ?? pad.pad_diameter ?? 0
  const x = pad.x ?? 0
  const y = pad.y ?? 0
  return [
    [x - w / 2 - expansion, y - h / 2 - expansion],
    [x + w / 2 + expansion, y - h / 2 - expansion],
    [x + w / 2 + expansion, y + h / 2 + expansion],
    [x - w / 2 - expansion, y + h / 2 + expansion],
  ]
}

export function getEffectivePadPaste(pad, board_defaults) {
  const override = pad.paste_override
  const defaultScale = board_defaults?.paste_scale ?? 1.0

  if (override?.polygon) {
    return override.polygon
  }

  const scale = override?.scale ?? defaultScale
  const offset = override?.offset_mm ?? 0
  const w = pad.width ?? pad.pad_diameter ?? 0
  const h = pad.height ?? pad.pad_diameter ?? 0
  const x = pad.x ?? 0
  const y = pad.y ?? 0

  const sw = w * scale
  const sh = h * scale

  return [
    [x - sw / 2 + offset, y - sh / 2 + offset],
    [x + sw / 2 + offset, y - sh / 2 + offset],
    [x + sw / 2 + offset, y + sh / 2 + offset],
    [x - sw / 2 + offset, y + sh / 2 + offset],
  ]
}

export function validatePadOverrides(pad) {
  const errors = []
  if (!pad) {
    errors.push('pad is required')
    return errors
  }
  if (pad.mask_override !== undefined) {
    if (typeof pad.mask_override.expansion_mm !== 'number' || pad.mask_override.expansion_mm < 0) {
      errors.push('mask_override.expansion_mm must be a non-negative number')
    }
  }
  if (pad.paste_override !== undefined) {
    const po = pad.paste_override
    if (po.scale !== undefined && (typeof po.scale !== 'number' || po.scale < 0)) {
      errors.push('paste_override.scale must be a non-negative number')
    }
    if (po.offset_mm !== undefined && typeof po.offset_mm !== 'number') {
      errors.push('paste_override.offset_mm must be a number')
    }
    if (po.polygon !== undefined) {
      if (!Array.isArray(po.polygon) || po.polygon.length < 3) {
        errors.push('paste_override.polygon must be an array of at least 3 points')
      }
    }
  }
  return errors
}