/**
 * layoutPalette.js — Layer-id → colour maps for supported PDKs.
 *
 * Each palette entry is { fill: string (rgba), stroke: string (rgba) }.
 * Colours approximate those used by KLayout's built-in SKY130 / GF180MCU
 * layer views, but are kerf-internal and can be overridden by the user.
 *
 * Usage:
 *   import { sky130Palette, gf180Palette, getPaletteColor } from './layoutPalette.js'
 *   const { fill, stroke } = getPaletteColor(sky130Palette, layerId) ?? defaultColor
 */

// ── SKY130 layer palette ──────────────────────────────────────────────────────

/**
 * SKY130 layer map.  Key is `${layer_number}/${datatype}` per Skywater GDS
 * stream IDs; secondary keys use the canonical layer name for convenience.
 * The name property is informational only.
 */
export const sky130Palette = {
  // nwell  (64/20)
  nwell:        { name: 'nwell',        layerNum: 64, datatype: 20, fill: 'rgba(0,100,200,0.25)',    stroke: 'rgba(0,100,200,0.9)' },
  // pwell  (122/16)
  pwell:        { name: 'pwell',        layerNum: 122, datatype: 16, fill: 'rgba(100,80,0,0.20)',    stroke: 'rgba(100,80,0,0.9)' },
  // diff   (65/20)
  diff:         { name: 'diff',         layerNum: 65,  datatype: 20, fill: 'rgba(100,200,100,0.40)', stroke: 'rgba(60,160,60,1.0)' },
  // tap    (65/44)
  tap:          { name: 'tap',          layerNum: 65,  datatype: 44, fill: 'rgba(0,180,80,0.35)',    stroke: 'rgba(0,140,60,1.0)' },
  // poly   (66/20)
  poly:         { name: 'poly',         layerNum: 66,  datatype: 20, fill: 'rgba(220,50,50,0.45)',   stroke: 'rgba(200,0,0,1.0)' },
  // hvtp   (78/44)
  hvtp:         { name: 'hvtp',         layerNum: 78,  datatype: 44, fill: 'rgba(180,50,220,0.20)',  stroke: 'rgba(150,0,200,0.8)' },
  // licon1 (66/44)
  licon1:       { name: 'licon1',       layerNum: 66,  datatype: 44, fill: 'rgba(240,200,50,0.60)',  stroke: 'rgba(200,160,0,1.0)' },
  // npc    (95/20)
  npc:          { name: 'npc',          layerNum: 95,  datatype: 20, fill: 'rgba(255,200,100,0.25)', stroke: 'rgba(200,140,0,0.8)' },
  // li1    (67/20)
  li1:          { name: 'li1',          layerNum: 67,  datatype: 20, fill: 'rgba(100,200,255,0.45)', stroke: 'rgba(0,160,220,1.0)' },
  // mcon   (67/44)
  mcon:         { name: 'mcon',         layerNum: 67,  datatype: 44, fill: 'rgba(80,160,255,0.65)',  stroke: 'rgba(0,120,200,1.0)' },
  // met1   (68/20)
  met1:         { name: 'met1',         layerNum: 68,  datatype: 20, fill: 'rgba(100,100,220,0.50)', stroke: 'rgba(60,60,200,1.0)' },
  // via1   (68/44)
  via1:         { name: 'via1',         layerNum: 68,  datatype: 44, fill: 'rgba(150,100,255,0.65)', stroke: 'rgba(120,60,240,1.0)' },
  // met2   (69/20)
  met2:         { name: 'met2',         layerNum: 69,  datatype: 20, fill: 'rgba(50,200,200,0.50)',  stroke: 'rgba(0,160,160,1.0)' },
  // via2   (69/44)
  via2:         { name: 'via2',         layerNum: 69,  datatype: 44, fill: 'rgba(0,200,180,0.65)',   stroke: 'rgba(0,160,140,1.0)' },
  // met3   (70/20)
  met3:         { name: 'met3',         layerNum: 70,  datatype: 20, fill: 'rgba(220,180,50,0.50)',  stroke: 'rgba(180,140,0,1.0)' },
  // via3   (70/44)
  via3:         { name: 'via3',         layerNum: 70,  datatype: 44, fill: 'rgba(240,200,0,0.65)',   stroke: 'rgba(200,160,0,1.0)' },
  // met4   (71/20)
  met4:         { name: 'met4',         layerNum: 71,  datatype: 20, fill: 'rgba(200,100,50,0.50)',  stroke: 'rgba(180,60,0,1.0)' },
  // via4   (71/44)
  via4:         { name: 'via4',         layerNum: 71,  datatype: 44, fill: 'rgba(240,120,40,0.65)',  stroke: 'rgba(210,80,0,1.0)' },
  // met5   (72/20)
  met5:         { name: 'met5',         layerNum: 72,  datatype: 20, fill: 'rgba(180,50,100,0.50)',  stroke: 'rgba(160,0,80,1.0)' },
  // pad    (76/20)
  pad:          { name: 'pad',          layerNum: 76,  datatype: 20, fill: 'rgba(220,220,220,0.60)', stroke: 'rgba(180,180,180,1.0)' },
  // rdl    (74/20)
  rdl:          { name: 'rdl',          layerNum: 74,  datatype: 20, fill: 'rgba(200,0,200,0.40)',   stroke: 'rgba(160,0,160,1.0)' },
  // nsm    (61/20)
  nsm:          { name: 'nsm',          layerNum: 61,  datatype: 20, fill: 'rgba(160,220,60,0.20)',  stroke: 'rgba(120,180,20,0.7)' },
  // dnwell (64/18)
  dnwell:       { name: 'dnwell',       layerNum: 64,  datatype: 18, fill: 'rgba(0,60,180,0.20)',    stroke: 'rgba(0,40,160,0.8)' },
  // hvi    (75/20)
  hvi:          { name: 'hvi',          layerNum: 75,  datatype: 20, fill: 'rgba(255,120,0,0.20)',   stroke: 'rgba(220,80,0,0.7)' },
  // cfom   (22/20)
  cfom:         { name: 'cfom',         layerNum: 22,  datatype: 20, fill: 'rgba(80,180,80,0.20)',   stroke: 'rgba(40,140,40,0.7)' },
  // pwbm   (19/44)
  pwbm:         { name: 'pwbm',         layerNum: 19,  datatype: 44, fill: 'rgba(160,120,60,0.20)',  stroke: 'rgba(120,80,20,0.7)' },
  // rpm    (86/20)
  rpm:          { name: 'rpm',          layerNum: 86,  datatype: 20, fill: 'rgba(220,80,160,0.20)',  stroke: 'rgba(180,40,120,0.7)' },
  // urpm   (79/20)
  urpm:         { name: 'urpm',         layerNum: 79,  datatype: 20, fill: 'rgba(180,80,220,0.20)',  stroke: 'rgba(140,40,180,0.7)' },
  // vhvi   (74/21)
  vhvi:         { name: 'vhvi',         layerNum: 74,  datatype: 21, fill: 'rgba(255,160,40,0.20)',  stroke: 'rgba(220,120,0,0.7)' },
  // prb    (3/0)
  prb:          { name: 'prb',          layerNum: 3,   datatype: 0,  fill: 'rgba(255,0,0,0.15)',     stroke: 'rgba(200,0,0,0.6)' },
  // areaid (81/4)
  areaid_sc:    { name: 'areaid_sc',    layerNum: 81,  datatype: 4,  fill: 'rgba(220,220,50,0.10)',  stroke: 'rgba(180,180,0,0.5)' },
}

// ── GF180MCU layer palette ────────────────────────────────────────────────────

/**
 * GlobalFoundries GF180MCU layer map.
 * Layer numbers follow the GF180MCU GDS stream layer spec.
 */
export const gf180Palette = {
  // nwell  (21/0)
  nwell:        { name: 'nwell',        layerNum: 21,  datatype: 0,  fill: 'rgba(0,100,220,0.25)',    stroke: 'rgba(0,80,200,0.9)' },
  // pwell  (204/0)
  pwell:        { name: 'pwell',        layerNum: 204, datatype: 0,  fill: 'rgba(120,80,0,0.20)',     stroke: 'rgba(100,60,0,0.9)' },
  // dnwell (12/0)
  dnwell:       { name: 'dnwell',       layerNum: 12,  datatype: 0,  fill: 'rgba(0,50,180,0.15)',     stroke: 'rgba(0,30,150,0.7)' },
  // comp   (22/0)
  comp:         { name: 'comp',         layerNum: 22,  datatype: 0,  fill: 'rgba(80,220,80,0.45)',    stroke: 'rgba(40,180,40,1.0)' },
  // poly2  (30/0)
  poly2:        { name: 'poly2',        layerNum: 30,  datatype: 0,  fill: 'rgba(240,60,60,0.50)',    stroke: 'rgba(200,0,0,1.0)' },
  // contact(33/0)
  contact:      { name: 'contact',      layerNum: 33,  datatype: 0,  fill: 'rgba(220,200,50,0.65)',   stroke: 'rgba(180,160,0,1.0)' },
  // metal1 (34/0)
  metal1:       { name: 'metal1',       layerNum: 34,  datatype: 0,  fill: 'rgba(100,110,230,0.55)',  stroke: 'rgba(60,70,200,1.0)' },
  // via1   (35/0)
  via1:         { name: 'via1',         layerNum: 35,  datatype: 0,  fill: 'rgba(140,100,255,0.65)',  stroke: 'rgba(110,60,240,1.0)' },
  // metal2 (36/0)
  metal2:       { name: 'metal2',       layerNum: 36,  datatype: 0,  fill: 'rgba(50,210,210,0.55)',   stroke: 'rgba(0,170,170,1.0)' },
  // via2   (38/0)
  via2:         { name: 'via2',         layerNum: 38,  datatype: 0,  fill: 'rgba(0,210,190,0.65)',    stroke: 'rgba(0,170,150,1.0)' },
  // metal3 (42/0)
  metal3:       { name: 'metal3',       layerNum: 42,  datatype: 0,  fill: 'rgba(220,190,50,0.55)',   stroke: 'rgba(180,150,0,1.0)' },
  // via3   (40/0)
  via3:         { name: 'via3',         layerNum: 40,  datatype: 0,  fill: 'rgba(240,210,0,0.65)',    stroke: 'rgba(200,170,0,1.0)' },
  // metal4 (46/0)
  metal4:       { name: 'metal4',       layerNum: 46,  datatype: 0,  fill: 'rgba(210,110,50,0.55)',   stroke: 'rgba(180,70,0,1.0)' },
  // via4   (41/0)
  via4:         { name: 'via4',         layerNum: 41,  datatype: 0,  fill: 'rgba(240,130,40,0.65)',   stroke: 'rgba(210,90,0,1.0)' },
  // metal5 (81/0)
  metal5:       { name: 'metal5',       layerNum: 81,  datatype: 0,  fill: 'rgba(190,50,110,0.55)',   stroke: 'rgba(160,0,90,1.0)' },
  // via5   (82/0)
  via5:         { name: 'via5',         layerNum: 82,  datatype: 0,  fill: 'rgba(210,70,140,0.65)',   stroke: 'rgba(180,0,110,1.0)' },
  // metaltop (53/0)
  metaltop:     { name: 'metaltop',     layerNum: 53,  datatype: 0,  fill: 'rgba(200,200,100,0.55)',  stroke: 'rgba(160,160,60,1.0)' },
  // topmetal1 (59/0)
  topmetal1:    { name: 'topmetal1',    layerNum: 59,  datatype: 0,  fill: 'rgba(220,220,50,0.50)',   stroke: 'rgba(180,180,0,1.0)' },
  // topmetal2 (60/0)
  topmetal2:    { name: 'topmetal2',    layerNum: 60,  datatype: 0,  fill: 'rgba(240,220,80,0.50)',   stroke: 'rgba(200,180,0,1.0)' },
  // pad    (37/0)
  pad:          { name: 'pad',          layerNum: 37,  datatype: 0,  fill: 'rgba(220,220,220,0.60)',  stroke: 'rgba(180,180,180,1.0)' },
  // nplus  (32/0)
  nplus:        { name: 'nplus',        layerNum: 32,  datatype: 0,  fill: 'rgba(0,180,100,0.25)',    stroke: 'rgba(0,140,70,0.8)' },
  // pplus  (31/0)
  pplus:        { name: 'pplus',        layerNum: 31,  datatype: 0,  fill: 'rgba(200,100,60,0.25)',   stroke: 'rgba(160,60,20,0.8)' },
  // sab    (49/0)
  sab:          { name: 'sab',          layerNum: 49,  datatype: 0,  fill: 'rgba(180,0,180,0.20)',    stroke: 'rgba(140,0,140,0.7)' },
  // esd    (24/0)
  esd:          { name: 'esd',          layerNum: 24,  datatype: 0,  fill: 'rgba(255,60,60,0.20)',    stroke: 'rgba(220,0,0,0.6)' },
  // res_mk (110/5)
  res_mk:       { name: 'res_mk',       layerNum: 110, datatype: 5,  fill: 'rgba(200,160,0,0.20)',    stroke: 'rgba(160,120,0,0.6)' },
  // resistor(62/0)
  resistor:     { name: 'resistor',     layerNum: 62,  datatype: 0,  fill: 'rgba(200,150,0,0.20)',    stroke: 'rgba(160,110,0,0.6)' },
  // hres   (50/0)
  hres:         { name: 'hres',         layerNum: 50,  datatype: 0,  fill: 'rgba(200,140,20,0.20)',   stroke: 'rgba(160,100,0,0.6)' },
  // cap_mk (117/5)
  cap_mk:       { name: 'cap_mk',       layerNum: 117, datatype: 5,  fill: 'rgba(0,200,200,0.15)',    stroke: 'rgba(0,160,160,0.6)' },
  // mim_l  (99/0)
  mim_l:        { name: 'mim_l',        layerNum: 99,  datatype: 0,  fill: 'rgba(80,180,220,0.25)',   stroke: 'rgba(40,140,180,0.7)' },
}

// ── Fallback colour ──────────────────────────────────────────────────────────

export const defaultLayerColor = {
  fill: 'rgba(180,180,180,0.30)',
  stroke: 'rgba(120,120,120,0.80)',
}

// ── Lookup helpers ───────────────────────────────────────────────────────────

/**
 * Return { fill, stroke } for a layer in the given palette.
 *
 * Accepts:
 *   - a string key (e.g. 'met1')
 *   - an object { layerNum, datatype }
 *
 * Returns null when the layer is not in the palette (caller should fall back to
 * defaultLayerColor).
 */
export function getPaletteColor(palette, layerIdOrObj) {
  if (typeof layerIdOrObj === 'string') {
    const entry = palette[layerIdOrObj]
    return entry ? { fill: entry.fill, stroke: entry.stroke } : null
  }
  // Search by numeric id
  if (layerIdOrObj && typeof layerIdOrObj === 'object') {
    const { layerNum, datatype } = layerIdOrObj
    for (const entry of Object.values(palette)) {
      if (entry.layerNum === layerNum && entry.datatype === datatype) {
        return { fill: entry.fill, stroke: entry.stroke }
      }
    }
  }
  return null
}
