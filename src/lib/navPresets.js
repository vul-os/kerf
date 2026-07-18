// Viewport navigation presets — "make the mouse behave like the CAD tool I
// already know".
//
// Mappings follow FreeCAD's navigation styles, which are the de-facto reference
// implementations of each vendor's scheme:
//   https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Mouse_navigation.md
//
// Why a resolver function instead of a static table
// -------------------------------------------------
// three.js OrbitControls has ONE static `mouseButtons` map and no notion of
// modifier keys — it cannot express "Alt+LMB orbits, plain LMB selects". So a
// preset is a function of the modifiers currently held, and the Renderer
// reassigns controls.mouseButtons on keydown/keyup. That is what makes Maya
// (Alt-gated) and Blender/Revit/SolidWorks (Shift/Ctrl-gated) possible at all.
//
// Actions are strings here, not THREE.MOUSE constants, to keep this module pure
// and unit-testable; the Renderer maps them.
//   'rotate' | 'pan' | 'dolly' | null   (null = button does nothing → free to select)
//
// Note on selection: a button mapped to null is ignored by OrbitControls, so a
// click on it still reaches our picker. A button mapped to an action still
// selects on a CLICK — only a DRAG is treated as navigation (the 6 px tap
// threshold in Renderer). So selection survives in every preset.

export const NAV_PRESET_IDS = [
  'standard',
  'blender',
  'maya',
  'revit',
  'solidworks',
  'touchpad',
]

export const DEFAULT_NAV_PRESET = 'standard'

// Each preset resolves { LEFT, MIDDLE, RIGHT } from the modifiers held.
// `mods` is { alt, shift, ctrl }.
export const NAV_PRESETS = {
  standard: {
    id: 'standard',
    name: 'Standard CAD',
    hint: 'Kerf default',
    // Left-drag orbits, right-drag pans, wheel zooms. Right-CLICK (no drag)
    // still opens the object menu.
    rows: [
      ['Select', 'Left click'],
      ['Orbit', 'Left drag'],
      ['Pan', 'Right drag'],
      ['Zoom', 'Wheel'],
    ],
    resolve: () => ({ LEFT: 'rotate', MIDDLE: 'dolly', RIGHT: 'pan' }),
  },

  blender: {
    id: 'blender',
    name: 'Blender',
    hint: 'MMB orbits',
    rows: [
      ['Select', 'Left click'],
      ['Orbit', 'Middle drag'],
      ['Pan', 'Shift + middle drag'],
      ['Zoom', 'Wheel / Ctrl + middle drag'],
    ],
    resolve: (m) => ({
      LEFT: null, // left is select-only, as in Blender
      MIDDLE: m.shift ? 'pan' : m.ctrl ? 'dolly' : 'rotate',
      RIGHT: null,
    }),
  },

  maya: {
    id: 'maya',
    name: 'Autodesk Maya',
    hint: 'Alt-gated',
    rows: [
      ['Select', 'Left click'],
      ['Orbit', 'Alt + left drag'],
      ['Pan', 'Alt + middle drag'],
      ['Zoom', 'Alt + right drag / Wheel'],
    ],
    // Nothing navigates unless Alt is held — Maya's defining trait.
    resolve: (m) =>
      m.alt
        ? { LEFT: 'rotate', MIDDLE: 'pan', RIGHT: 'dolly' }
        : { LEFT: null, MIDDLE: null, RIGHT: null },
  },

  revit: {
    id: 'revit',
    name: 'AutoCAD & Revit',
    hint: 'MMB pans',
    rows: [
      ['Select', 'Left click'],
      ['Pan', 'Middle drag'],
      ['Orbit', 'Shift + middle drag'],
      ['Zoom', 'Wheel'],
    ],
    resolve: (m) => ({
      LEFT: null,
      MIDDLE: m.shift ? 'rotate' : 'pan',
      RIGHT: null,
    }),
  },

  solidworks: {
    id: 'solidworks',
    name: 'SolidWorks',
    hint: 'MMB rotates',
    rows: [
      ['Select', 'Left click'],
      ['Orbit', 'Middle drag'],
      ['Pan', 'Ctrl + middle drag'],
      ['Zoom', 'Shift + middle drag / Wheel'],
    ],
    resolve: (m) => ({
      LEFT: null,
      MIDDLE: m.ctrl ? 'pan' : m.shift ? 'dolly' : 'rotate',
      RIGHT: null,
    }),
  },

  touchpad: {
    id: 'touchpad',
    name: 'Touchpad (gesture)',
    hint: 'No middle button',
    // A laptop touchpad has no usable middle button, so everything hangs off the
    // left button plus a modifier, and two-finger scroll drives zoom.
    rows: [
      ['Select', 'Left click'],
      ['Orbit', 'Left drag'],
      ['Pan', 'Shift + left drag'],
      ['Zoom', 'Two-finger scroll / pinch'],
    ],
    resolve: (m) => ({
      LEFT: m.shift ? 'pan' : 'rotate',
      MIDDLE: 'pan',
      RIGHT: 'pan',
    }),
  },
}

/** Ordered list for the UI. */
export const NAV_PRESET_LIST = NAV_PRESET_IDS.map((id) => NAV_PRESETS[id])

/**
 * Resolve a preset + held modifiers to an OrbitControls button map.
 * Unknown ids fall back to the default rather than throwing — a stale value in
 * localStorage must not break the viewport.
 */
export function resolveButtons(presetId, mods = {}) {
  const preset = NAV_PRESETS[presetId] || NAV_PRESETS[DEFAULT_NAV_PRESET]
  return preset.resolve({
    alt: !!mods.alt,
    shift: !!mods.shift,
    ctrl: !!mods.ctrl,
  })
}

const STORAGE_KEY = 'kerf.navPreset'

export function loadNavPreset() {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY)
    return NAV_PRESETS[v] ? v : DEFAULT_NAV_PRESET
  } catch {
    return DEFAULT_NAV_PRESET
  }
}

export function saveNavPreset(id) {
  try {
    if (NAV_PRESETS[id]) window.localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // Private browsing / storage disabled — the choice just won't persist.
  }
}
