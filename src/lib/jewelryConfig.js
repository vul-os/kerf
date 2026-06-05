/**
 * jewelryConfig.js — Pure-JS jewelry configurator math library.
 *
 * Mirrors the Python back-end math in:
 *   - packages/kerf-cad-core/src/kerf_cad_core/jewelry/gemstones.py
 *   - packages/kerf-cad-core/src/kerf_cad_core/jewelry/ring.py
 *   - packages/kerf-cad-core/src/kerf_cad_core/jewelry/metal_cost.py
 *   - packages/kerf-cad-core/src/kerf_cad_core/jewelry/settings.py
 *
 * All unit tests in src/lib/jewelryConfig.test.js.
 * No external deps — pure ES module.
 *
 * Carat-weight formulae source:
 *   GIA Gemology Reference + Liddicoat "GIA Gem Reference Guide" (1995).
 *   carat = (dim_mm / ref_mm_diamond) ** 3   (volume-scaling approximation)
 *   Density correction: ref_mm_material = ref_mm_diamond * (rho_diamond/rho_material)^(1/3)
 *
 * Ring-size formulae source:
 *   US: Hoover & Strong; cross-checked Stuller 2024.
 *     ID_mm = 11.63 + 0.8128 * US_size
 *   UK/AU: ISO 8653 / Cookson Gold 2023.
 *   EU (ISO 8653): circumference in mm, integer 41–76.
 *   JP: circumference − 37 (approx); integer 1–30.
 *
 * Metal densities source:
 *   World Gold Council "Handbook on Gold Alloys" + Legor Group (2023);
 *   Platinum Guild International; Handy & Harman (silver); NIST (titanium).
 *
 * Prong/setting geometry source:
 *   Blaine Lewis / New Approach School of Jewellery; GIA stone-setting guides.
 *   Bezel wall = stone_diameter * 0.08–0.12 (typical 0.10);
 *   Prong diameter = stone_diameter * 0.15–0.20.
 */

// ---------------------------------------------------------------------------
// Gem densities (g/cm³) — matches GEMSTONE_DENSITIES in gemstones.py
// ---------------------------------------------------------------------------

export const GEM_DENSITIES = {
  diamond:       3.51,
  ruby:          4.00,
  sapphire:      4.00,
  emerald:       2.76,
  alexandrite:   3.73,
  aquamarine:    2.72,
  amethyst:      2.65,
  citrine:       2.65,
  tanzanite:     3.35,
  tourmaline:    3.06,
  opal:          2.10,
  garnet:        3.78,
  topaz:         3.53,
  peridot:       3.34,
  morganite:     2.80,
  kunzite:       3.18,
  iolite:        2.61,
  spinel:        3.60,
  zircon:        4.67,
  moissanite:    3.21,
  cubic_zirconia: 5.80,
  pearl:          2.71,
}

const DIAMOND_DENSITY = GEM_DENSITIES.diamond // 3.51

// ---------------------------------------------------------------------------
// Carat ↔ mm reference (ref_mm for 1 ct diamond, exponent 3)
// Matches _CARAT_REF in gemstones.py
// ---------------------------------------------------------------------------

const CARAT_REF = {
  round_brilliant: [6.5, 3],
  princess:        [5.5, 3],
  oval:            [7.7, 3],
  emerald:         [7.0, 3],
  marquise:        [10.0, 3],
  pear:            [8.0, 3],
  cushion:         [5.5, 3],
  radiant:         [6.0, 3],
  asscher:         [5.5, 3],
  trillion:        [7.0, 3],
  heart:           [6.5, 3],
  baguette:        [5.0, 3],
  briolette:       [5.5, 3],
  old_european:    [6.5, 3],
  old_mine:        [5.5, 3],
  rose_cut:        [7.8, 3],
  single_cut:      [4.1, 3],
  french_cut:      [5.0, 3],
  half_moon:       [8.5, 3],
  trapezoid:       [6.5, 3],
}

/**
 * Compute effective ref_mm for a cut + material density.
 * ref_mm_material = ref_mm_diamond × (rho_diamond / rho_material) ^ (1/3)
 *
 * @param {string} cut - gem cut name
 * @param {number} densityGcm3 - material density (g/cm³)
 * @returns {{ refMm: number, exponent: number }}
 */
function effectiveRefMm(cut, densityGcm3) {
  const [refDiamond, exp] = CARAT_REF[cut] ?? CARAT_REF.round_brilliant
  if (densityGcm3 === DIAMOND_DENSITY) return { refMm: refDiamond, exponent: exp }
  const refMm = refDiamond * Math.pow(DIAMOND_DENSITY / densityGcm3, 1 / 3)
  return { refMm, exponent: exp }
}

/**
 * Compute carat weight from principal dimension (mm) for a given cut + material.
 *
 * @param {number} dimMm - principal dimension in mm (diameter for round; long axis for oval/marquise/pear)
 * @param {string} [cut='round_brilliant']
 * @param {string|null} [material=null] - gem name (key of GEM_DENSITIES); null → diamond
 * @param {number|null} [densityGcm3=null] - explicit density; overrides material
 * @returns {number} carat weight
 */
export function caratFromMm(dimMm, cut = 'round_brilliant', material = null, densityGcm3 = null) {
  if (!(dimMm > 0)) return 0
  const rho = densityGcm3 ?? (material ? (GEM_DENSITIES[material] ?? DIAMOND_DENSITY) : DIAMOND_DENSITY)
  const { refMm, exponent } = effectiveRefMm(cut, rho)
  return Math.pow(dimMm / refMm, exponent)
}

/**
 * Compute principal dimension (mm) from carat weight for a given cut + material.
 *
 * @param {number} carat
 * @param {string} [cut='round_brilliant']
 * @param {string|null} [material=null]
 * @param {number|null} [densityGcm3=null]
 * @returns {number} mm
 */
export function mmFromCarat(carat, cut = 'round_brilliant', material = null, densityGcm3 = null) {
  if (!(carat > 0)) return 0
  const rho = densityGcm3 ?? (material ? (GEM_DENSITIES[material] ?? DIAMOND_DENSITY) : DIAMOND_DENSITY)
  const { refMm, exponent } = effectiveRefMm(cut, rho)
  return refMm * Math.pow(carat, 1 / exponent)
}

// ---------------------------------------------------------------------------
// Ring sizing
// ---------------------------------------------------------------------------

const PI = Math.PI

// US size formula: ID_mm = 11.63 + 0.8128 * US_size  (Hoover & Strong)
const US_ID_INTERCEPT = 11.63
const US_ID_SLOPE     = 0.8128

// US half-sizes 0 to 16 inclusive
export const US_SIZES = Array.from({ length: 33 }, (_, i) => i / 2)

// UK/AU sizes → circumference (mm), ISO 8653 + Cookson Gold 2023
export const UK_AU_SIZES = {
  'A': 37.8, 'A½': 38.4,
  'B': 39.1, 'B½': 39.7,
  'C': 40.4, 'C½': 41.1,
  'D': 41.7, 'D½': 42.4,
  'E': 43.0, 'E½': 43.7,
  'F': 44.2, 'F½': 44.8,
  'G': 45.5, 'G½': 46.1,
  'H': 46.8, 'H½': 47.4,
  'I': 48.0, 'I½': 48.7,
  'J': 49.3, 'J½': 50.0,
  'K': 50.6, 'K½': 51.2,
  'L': 51.9, 'L½': 52.5,
  'M': 53.1, 'M½': 53.8,
  'N': 54.4, 'N½': 55.1,
  'O': 55.7, 'O½': 56.3,
  'P': 57.0, 'P½': 57.6,
  'Q': 58.3, 'Q½': 58.9,
  'R': 59.5, 'R½': 60.2,
  'S': 60.8, 'S½': 61.4,
  'T': 62.1, 'T½': 62.7,
  'U': 63.4, 'U½': 64.0,
  'V': 64.6, 'V½': 65.3,
  'W': 65.9, 'W½': 66.6,
  'X': 67.2, 'X½': 67.8,
  'Y': 68.5, 'Y½': 69.1,
  'Z': 69.7, 'Z+1': 70.4, 'Z+2': 71.0, 'Z+3': 71.7,
}

// JP sizes: map to inner circumference in mm (JP_size = circumference - 37, approx)
// Precise table per JIS B 4902; JP size 1–30
export const JP_SIZES = Object.fromEntries(
  Array.from({ length: 30 }, (_, i) => {
    const jpSize = i + 1
    // circumference_mm = 37 + jpSize  (JIS B 4902 approximation)
    return [jpSize, 37.0 + jpSize]
  })
)

function _circToId(circMm) {
  return circMm / PI
}

/**
 * Convert a ring size to inner diameter (mm).
 *
 * @param {'US'|'UK'|'AU'|'EU'|'JP'} system
 * @param {number|string} size - US: numeric (0–16); UK/AU: letter string; EU: integer mm circumference; JP: integer 1–30
 * @returns {number} inner diameter in mm
 * @throws {Error} on unknown size/system
 */
export function ringSizeToDiameter(system, size) {
  const sys = String(system).toUpperCase()

  if (sys === 'US') {
    const s = parseFloat(size)
    if (isNaN(s) || s < 0 || s > 16) throw new Error(`Invalid US size: ${size}. Must be 0–16.`)
    return US_ID_INTERCEPT + US_ID_SLOPE * s
  }

  if (sys === 'UK' || sys === 'AU') {
    const key = String(size).trim()
    if (!(key in UK_AU_SIZES)) throw new Error(`Unknown UK/AU size: ${key}`)
    return _circToId(UK_AU_SIZES[key])
  }

  if (sys === 'EU') {
    // EU size = circumference in mm (integer 41–76)
    const s = parseInt(size, 10)
    if (isNaN(s) || s < 41 || s > 76) throw new Error(`Invalid EU size: ${size}. Must be 41–76 mm circumference.`)
    return _circToId(s)
  }

  if (sys === 'JP') {
    const s = parseInt(size, 10)
    if (isNaN(s) || s < 1 || s > 30) throw new Error(`Invalid JP size: ${size}. Must be 1–30.`)
    const circ = JP_SIZES[s]
    return _circToId(circ)
  }

  throw new Error(`Unknown ring size system: ${system}. Use US, UK, AU, EU, or JP.`)
}

/**
 * Convert inner diameter (mm) to the nearest ring size in the given system.
 *
 * @param {'US'|'UK'|'AU'|'EU'|'JP'} system
 * @param {number} diameterMm
 * @returns {number|string} size value
 */
export function ringDiameterToSize(system, diameterMm) {
  const circMm = PI * diameterMm
  const sys = String(system).toUpperCase()

  if (sys === 'US') {
    const raw = (diameterMm - US_ID_INTERCEPT) / US_ID_SLOPE
    // Nearest half-size
    const nearest = US_SIZES.reduce((best, s) => Math.abs(s - raw) < Math.abs(best - raw) ? s : best, US_SIZES[0])
    return nearest
  }

  if (sys === 'UK' || sys === 'AU') {
    const keys = Object.keys(UK_AU_SIZES)
    const nearest = keys.reduce((best, k) =>
      Math.abs(UK_AU_SIZES[k] - circMm) < Math.abs(UK_AU_SIZES[best] - circMm) ? k : best
    , keys[0])
    return nearest
  }

  if (sys === 'EU') {
    // Round to nearest integer
    return Math.round(circMm)
  }

  if (sys === 'JP') {
    const jpKeys = Object.keys(JP_SIZES).map(Number)
    const nearest = jpKeys.reduce((best, k) =>
      Math.abs(JP_SIZES[k] - circMm) < Math.abs(JP_SIZES[best] - circMm) ? k : best
    , jpKeys[0])
    return nearest
  }

  throw new Error(`Unknown ring size system: ${system}`)
}

// ---------------------------------------------------------------------------
// Metal densities and weight
// ---------------------------------------------------------------------------

/** Metal density table (g/cm³) — matches METAL_DENSITY_G_CM3 in metal_cost.py */
export const METAL_DENSITY = {
  '10k_yellow': 11.57, '14k_yellow': 13.07, '18k_yellow': 15.58,
  '22k_yellow': 17.80, '24k_yellow': 19.32,
  '10k_white':  11.61, '14k_white':  13.25, '18k_white':  15.60,
  '22k_white':  17.60,
  '10k_rose':   11.59, '14k_rose':   13.20, '18k_rose':   15.45,
  '22k_rose':   17.75,
  platinum_950: 21.40, platinum_900: 21.30,
  palladium_950: 11.00, palladium_500: 10.60,
  sterling_925: 10.36, fine_silver: 10.49, argentium_935: 10.40,
  titanium:     4.51,  brass:        8.53,  bronze:        8.78,
}

/** Hallmark values — matches METAL_HALLMARK in metal_cost.py */
export const METAL_HALLMARK = {
  '10k_yellow': 417, '14k_yellow': 583, '18k_yellow': 750,
  '22k_yellow': 917, '24k_yellow': 999,
  '10k_white':  417, '14k_white':  583, '18k_white':  750,
  '22k_white':  917,
  '10k_rose':   417, '14k_rose':   583, '18k_rose':   750,
  '22k_rose':   917,
  platinum_950: 950, platinum_900: 900,
  palladium_950: 950, palladium_500: 500,
  sterling_925: 925, fine_silver: 999, argentium_935: 935,
  titanium: null, brass: null, bronze: null,
}

const GRAMS_PER_DWT = 1.55517384
const GRAMS_PER_OZT = 31.1034768

/**
 * Compute metal weight from volume.
 *
 * @param {number} volumeMm3 - volume in mm³
 * @param {string} metal - key from METAL_DENSITY
 * @returns {{ netGrams: number, netDwt: number, netOzt: number } | null}
 */
export function metalWeight(volumeMm3, metal) {
  const d = METAL_DENSITY[metal]
  if (!d || !(volumeMm3 > 0)) return null
  const netGrams = d * (volumeMm3 / 1000) // mm³ → cm³
  return {
    netGrams,
    netDwt: netGrams / GRAMS_PER_DWT,
    netOzt: netGrams / GRAMS_PER_OZT,
  }
}

/**
 * Estimate gross (casting) weight including sprue allowance.
 *
 * @param {number} volumeMm3
 * @param {string} metal
 * @param {number} [allowancePct=15] - casting allowance %
 * @returns {{ netGrams: number, grossGrams: number, grossDwt: number, grossOzt: number } | null}
 */
export function castingWeight(volumeMm3, metal, allowancePct = 15) {
  const base = metalWeight(volumeMm3, metal)
  if (!base) return null
  const grossGrams = base.netGrams * (1 + allowancePct / 100)
  return {
    ...base,
    grossGrams,
    grossDwt: grossGrams / GRAMS_PER_DWT,
    grossOzt: grossGrams / GRAMS_PER_OZT,
    allowancePct,
  }
}

// ---------------------------------------------------------------------------
// Setting geometry
// ---------------------------------------------------------------------------

/**
 * Compute prong setting geometry for a round stone.
 *
 * Reference: Blaine Lewis / New Approach School of Jewellery;
 * GIA Stone Setting I (2020).
 *
 * Typical ratios (GIA):
 *   prong_diameter = stone_diameter × 0.18  (range 0.15–0.22)
 *   prong_height   = stone_diameter × 0.40  (range 0.35–0.50)
 *   prong_count    = 4 (princess/round) | 6 (round solitaire, >0.5 ct)
 *
 * @param {number} stoneDiamMm - stone girdle diameter in mm
 * @param {number} [prongCount=4]
 * @param {number} [prongDiamRatio=0.18]
 * @param {number} [prongHeightRatio=0.40]
 * @returns {{ prong_diameter_mm, prong_height_mm, prong_count, seat_depth_mm, girdle_clearance_mm }}
 */
export function computeProngParams(stoneDiamMm, prongCount = 4, prongDiamRatio = 0.18, prongHeightRatio = 0.40) {
  if (!(stoneDiamMm > 0)) throw new Error('stoneDiamMm must be > 0')
  if (prongCount < 3) throw new Error('prongCount must be >= 3')
  return {
    prong_diameter_mm:   parseFloat((stoneDiamMm * prongDiamRatio).toFixed(4)),
    prong_height_mm:     parseFloat((stoneDiamMm * prongHeightRatio).toFixed(4)),
    prong_count:         prongCount,
    seat_depth_mm:       parseFloat((stoneDiamMm * 0.10).toFixed(4)),  // girdle seat depth
    girdle_clearance_mm: parseFloat((stoneDiamMm * 0.05).toFixed(4)),  // above girdle to tip
  }
}

/**
 * Compute bezel setting geometry for a round stone.
 *
 * Reference: GIA Stone Setting I (2020); fabrication standards.
 *   bezel_wall_thickness = stone_diameter × 0.10  (range 0.08–0.12)
 *   bezel_height         = stone_depth × 0.85      (covers pavilion + girdle)
 *
 * @param {number} stoneDiamMm - stone girdle diameter in mm
 * @param {number} [stoneDepthMm] - stone depth; defaults to stone_diam × 0.61 (ideal brilliant)
 * @param {number} [wallThicknessRatio=0.10]
 * @returns {{ bezel_inner_diameter_mm, bezel_outer_diameter_mm, bezel_wall_mm, bezel_height_mm, seat_depth_mm }}
 */
export function computeBezelParams(stoneDiamMm, stoneDepthMm, wallThicknessRatio = 0.10) {
  if (!(stoneDiamMm > 0)) throw new Error('stoneDiamMm must be > 0')
  const depth = stoneDepthMm ?? stoneDiamMm * 0.61  // ideal Tolkowsky total depth ratio
  const wallMm = stoneDiamMm * wallThicknessRatio
  const innerDiam = stoneDiamMm + 0.05  // 0.05 mm clearance for stone drop-in
  const outerDiam = innerDiam + 2 * wallMm
  const bezHeight = depth * 0.85
  return {
    bezel_inner_diameter_mm: parseFloat(innerDiam.toFixed(4)),
    bezel_outer_diameter_mm: parseFloat(outerDiam.toFixed(4)),
    bezel_wall_mm:           parseFloat(wallMm.toFixed(4)),
    bezel_height_mm:         parseFloat(bezHeight.toFixed(4)),
    seat_depth_mm:           parseFloat((stoneDiamMm * 0.08).toFixed(4)),
  }
}

/**
 * Compute pavé layout for a strip of stones along a band.
 *
 * Reference: GIA Stone Setting I (2020); industry pavé spacing conventions.
 *   stone_spacing = stone_diameter × 1.05  (5% gap between stones)
 *   bead_diameter = stone_diameter × 0.25
 *   drill_depth   = stone_diameter × 0.50  (nominal seat depth for pavé)
 *
 * @param {number} stoneDiamMm - stone girdle diameter in mm
 * @param {number} bandLengthMm - length of the pavé strip in mm
 * @param {number} [rowCount=1]
 * @returns {{ stone_count, stone_spacing_mm, bead_diameter_mm, drill_depth_mm, row_count, total_strip_width_mm }}
 */
export function computePaveLayout(stoneDiamMm, bandLengthMm, rowCount = 1) {
  if (!(stoneDiamMm > 0)) throw new Error('stoneDiamMm must be > 0')
  if (!(bandLengthMm > 0)) throw new Error('bandLengthMm must be > 0')
  const spacing = stoneDiamMm * 1.05
  const stonesPerRow = Math.floor(bandLengthMm / spacing)
  return {
    stone_count:           stonesPerRow * rowCount,
    stones_per_row:        stonesPerRow,
    stone_spacing_mm:      parseFloat(spacing.toFixed(4)),
    bead_diameter_mm:      parseFloat((stoneDiamMm * 0.25).toFixed(4)),
    drill_depth_mm:        parseFloat((stoneDiamMm * 0.50).toFixed(4)),
    row_count:             rowCount,
    total_strip_width_mm:  parseFloat((stoneDiamMm * rowCount * 1.05).toFixed(4)),
  }
}

// ---------------------------------------------------------------------------
// Ring volume estimation (for weight calc before CAD model is ready)
// ---------------------------------------------------------------------------

/**
 * Estimate ring band volume from parametric spec.
 *
 * Uses a torus approximation: V = 2π² × R × r²
 * where R = centreline radius of the band, r = half the cross-section.
 *
 * For a flat band: r = sqrt(bandWidth × thickness / π) (equivalent circular
 * cross-section by area).
 *
 * @param {number} innerDiamMm - ring inner diameter (mm)
 * @param {number} bandWidthMm - band width (mm)
 * @param {number} thicknessMm - band wall thickness (mm)
 * @returns {number} approximate volume in mm³
 */
export function ringBandVolume(innerDiamMm, bandWidthMm, thicknessMm) {
  if (!(innerDiamMm > 0) || !(bandWidthMm > 0) || !(thicknessMm > 0)) return 0
  // Cross-section area = bandWidth × thickness (rectangular cross-section)
  const csArea = bandWidthMm * thicknessMm
  // Centreline radius = (innerDiam/2) + thickness/2
  const R = innerDiamMm / 2 + thicknessMm / 2
  // Volume = 2π × R × csArea  (Pappus' centroid theorem)
  return 2 * Math.PI * R * csArea
}

// ---------------------------------------------------------------------------
// Gem catalog (display metadata for the picker UI)
// ---------------------------------------------------------------------------

/**
 * Abbreviated gem catalog for the UI picker.
 * Full catalog in gemstones.py.
 * Months: 1–12 (birth months per GIA).
 * Mohs: [min, max] hardness range.
 */
export const GEM_CATALOG = [
  { name: 'diamond',     label: 'Diamond',      months: [4],         mohs: [10, 10],  ri: [2.417, 2.419], color: '#e8f0ff' },
  { name: 'ruby',        label: 'Ruby',         months: [7],         mohs: [9.0, 9.0], ri: [1.762, 1.770], color: '#cc0033' },
  { name: 'sapphire',    label: 'Sapphire',     months: [9],         mohs: [9.0, 9.0], ri: [1.762, 1.770], color: '#0033cc' },
  { name: 'emerald',     label: 'Emerald',      months: [5],         mohs: [7.5, 8.0], ri: [1.565, 1.602], color: '#009900' },
  { name: 'alexandrite', label: 'Alexandrite',  months: [6],         mohs: [8.5, 8.5], ri: [1.746, 1.755], color: '#6633cc' },
  { name: 'aquamarine',  label: 'Aquamarine',   months: [3],         mohs: [7.5, 8.0], ri: [1.564, 1.596], color: '#00cccc' },
  { name: 'amethyst',    label: 'Amethyst',     months: [2],         mohs: [7.0, 7.0], ri: [1.544, 1.553], color: '#9933cc' },
  { name: 'citrine',     label: 'Citrine',      months: [11],        mohs: [7.0, 7.0], ri: [1.544, 1.553], color: '#ffcc00' },
  { name: 'tanzanite',   label: 'Tanzanite',    months: [12],        mohs: [6.5, 7.0], ri: [1.691, 1.700], color: '#4433cc' },
  { name: 'tourmaline',  label: 'Tourmaline',   months: [10],        mohs: [7.0, 7.5], ri: [1.624, 1.644], color: '#cc6633' },
  { name: 'opal',        label: 'Opal',         months: [10],        mohs: [5.5, 6.5], ri: [1.370, 1.470], color: '#cccccc' },
  { name: 'garnet',      label: 'Garnet',       months: [1],         mohs: [6.5, 7.5], ri: [1.714, 1.888], color: '#990000' },
  { name: 'topaz',       label: 'Topaz',        months: [11],        mohs: [8.0, 8.0], ri: [1.619, 1.627], color: '#ffcc99' },
  { name: 'peridot',     label: 'Peridot',      months: [8],         mohs: [6.5, 7.0], ri: [1.654, 1.690], color: '#99cc00' },
  { name: 'morganite',   label: 'Morganite',    months: [10],        mohs: [7.5, 8.0], ri: [1.562, 1.602], color: '#ffaacc' },
  { name: 'moissanite',  label: 'Moissanite',   months: [],          mohs: [9.25, 9.5], ri: [2.648, 2.691], color: '#ddeeff' },
  { name: 'cubic_zirconia', label: 'Cubic Zirconia', months: [],     mohs: [8.0, 8.5], ri: [2.150, 2.180], color: '#eeeeff' },
]

/**
 * Look up a gem by name (case-insensitive substring match).
 * @param {string} query
 * @returns {Array} matching catalog entries
 */
export function gemCatalogSearch(query) {
  const q = query.trim().toLowerCase()
  if (!q) return GEM_CATALOG
  return GEM_CATALOG.filter(g => g.name.includes(q) || g.label.toLowerCase().includes(q))
}

/**
 * Return gems that have birthstone months matching the given month number (1–12).
 * @param {number} month
 * @returns {Array}
 */
export function gemsByBirthMonth(month) {
  return GEM_CATALOG.filter(g => g.months.includes(month))
}

// ---------------------------------------------------------------------------
// Cut catalog (display metadata for the gem picker)
// ---------------------------------------------------------------------------

export const CUT_CATALOG = [
  { name: 'round_brilliant', label: 'Round Brilliant', facets: '57–58', note: 'GIA standard; best brilliance' },
  { name: 'princess',        label: 'Princess',         facets: '57–76', note: 'Square modified brilliant' },
  { name: 'oval',            label: 'Oval',             facets: '56–58', note: 'Elliptical modified brilliant' },
  { name: 'emerald',         label: 'Emerald',          facets: '57–58', note: 'Rectangular step cut' },
  { name: 'marquise',        label: 'Marquise',         facets: '55–58', note: 'Boat-shaped modified brilliant' },
  { name: 'pear',            label: 'Pear',             facets: '56–58', note: 'Teardrop modified brilliant' },
  { name: 'cushion',         label: 'Cushion',          facets: '58–64', note: 'Square/rect cushion modified brilliant' },
  { name: 'radiant',         label: 'Radiant',          facets: '70',    note: 'Cropped-corner rectangular modified brilliant' },
  { name: 'asscher',         label: 'Asscher',          facets: '74',    note: 'Square step cut; high crown' },
  { name: 'heart',           label: 'Heart',            facets: '59',    note: 'Heart-shaped modified brilliant' },
  { name: 'trillion',        label: 'Trillion',         facets: '43',    note: 'Triangular modified brilliant' },
  { name: 'baguette',        label: 'Baguette',         facets: '14',    note: 'Rectangular step cut; narrow bar' },
  { name: 'rose_cut',        label: 'Rose Cut',         facets: '3–24',  note: 'Flat base, domed faceted top' },
  { name: 'old_european',    label: 'Old European',     facets: '58',    note: 'Historical round brilliant; high crown' },
  { name: 'briolette',       label: 'Briolette',        facets: 'all',   note: 'Elongated teardrop; no table' },
]

// ---------------------------------------------------------------------------
// Ideal proportion guide (for UI display)
// ---------------------------------------------------------------------------

/**
 * Return Tolkowsky/GIA ideal proportion ranges for a cut.
 * Sources:
 *   Round brilliant: Tolkowsky (1919), GIA cut grade; table% 53–58, crown 34.5°, pav 40.75°, depth 61–62%.
 *   Princess: GIA; table% 68–75, depth 68–75%.
 *   Emerald: table% 60–70, depth 58–66%.
 *   Other cuts: GIA Gem Encyclopedia + industry standards.
 */
export function idealProportions(cut) {
  const guide = {
    round_brilliant: {
      table_pct:          [53, 58],
      crown_angle_deg:    [33.7, 35.8],
      pavilion_angle_deg: [40.2, 41.25],
      total_depth_pct:    [59, 62.5],
      girdle_pct:         [0.7, 3.0],
      note: 'GIA Excellent cut grade ranges (2005 standard)',
    },
    princess: {
      table_pct:          [68, 75],
      pavilion_angle_deg: [40.0, 42.0],
      total_depth_pct:    [68, 75],
      note: 'GIA princess cut study; optimal sparkle range',
    },
    emerald: {
      table_pct:          [60, 70],
      crown_angle_deg:    [12, 18],
      total_depth_pct:    [58, 66],
      step_rows:          [3, 3],
      corner_cut_ratio:   [0.10, 0.20],
      note: 'GIA / Gemological Institute standard step-cut proportions',
    },
    oval: {
      table_pct:          [53, 63],
      crown_angle_deg:    [30, 35],
      pavilion_angle_deg: [40, 41],
      length_width_ratio: [1.3, 1.7],
      note: 'GIA oval; avoid bow-tie with LW 1.35–1.50',
    },
    cushion: {
      table_pct:          [58, 68],
      crown_angle_deg:    [31, 36],
      pavilion_angle_deg: [40, 42],
      total_depth_pct:    [61, 68],
      note: 'Cushion modified brilliant; deeper pavilion than round',
    },
    marquise: {
      table_pct:          [53, 63],
      crown_angle_deg:    [30, 35],
      length_width_ratio: [1.85, 2.10],
      note: 'GIA; LW 1.85–2.10 minimises bow-tie effect',
    },
  }
  return guide[cut] ?? null
}
