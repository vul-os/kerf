export interface PadMaskOverride {
  expansion_mm: number
}

export interface PadPasteOverride {
  scale?: number
  offset_mm?: number
  polygon?: Array<[number, number]>
}

export interface Pad {
  pcb_smtpad_id?: string
  x?: number
  y?: number
  width?: number
  height?: number
  pad_diameter?: number
  mask_override?: PadMaskOverride
  paste_override?: PadPasteOverride
  [key: string]: any
}

export interface BoardDefaults {
  mask_expansion_mm?: number
  paste_scale?: number
}

export function setPadMaskOverride(pad: Pad, expansion_mm: number): void {
  pad.mask_override = { expansion_mm }
}

export function setPadPasteOverride(pad: Pad, scaleOrOffset: number | PadPasteOverride): void {
  if (typeof scaleOrOffset === 'number') {
    pad.paste_override = { scale: scaleOrOffset }
  } else if (scaleOrOffset && typeof scaleOrOffset === 'object') {
    pad.paste_override = { ...scaleOrOffset }
  }
}

export function getEffectivePadMask(pad: Pad, board_defaults: BoardDefaults | null | undefined): Array<[number, number]> {
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

export function getEffectivePadPaste(pad: Pad, board_defaults: BoardDefaults | null | undefined): Array<[number, number]> {
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

export function validatePadOverrides(pad: Pad | null | undefined): string[] {
  const errors: string[] = []
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