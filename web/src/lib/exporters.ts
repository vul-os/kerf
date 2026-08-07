// Multi-format export for Kerf parts.
//
// Public surface:
//   FORMATS              — list of {id, label, ext, acceptsAll, jscadOnly?}
//   exportParts(parts, format, opts) → {blob, filename}
//   downloadBlob(blob, filename) — triggers a transient anchor download
//
// Each part is `{id, geom}` where `geom` is either a JSCAD `Geom3` (with a
// `.polygons` array) or a `THREE.BufferGeometry` (e.g. STEP-derived). We
// normalise to a temporary `THREE.Group` of meshes, then hand that to the
// relevant Three.js exporter. The JSCAD-native JSON path skips the group
// entirely and serialises the original polygons (only available when the
// source is a Geom3 — STEP parts can't round-trip).
//
// Three.js exporters used:
//   STLExporter    — binary + ASCII STL
//   OBJExporter    — OBJ (no MTL in v1)
//   GLTFExporter   — glTF JSON + GLB binary
//   PLYExporter    — PLY binary, with normals + colors
//
// 3MF is hand-rolled with `fflate` (zip writer). The minimum viable schema:
//   [Content_Types].xml  → MIME types for .model and .rels
//   _rels/.rels          → root relationship to 3D/3dmodel.model
//   3D/3dmodel.model     → XML mesh per object, single build item per object
//
// `three` ships no type declarations in this project, so every `THREE.*`
// reference below resolves to `any` — annotated anyway for documentation.
import * as THREE from 'three'
import { STLExporter } from 'three/examples/jsm/exporters/STLExporter.js'
import { OBJExporter } from 'three/examples/jsm/exporters/OBJExporter.js'
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js'
import { PLYExporter } from 'three/examples/jsm/exporters/PLYExporter.js'
import { zipSync, strToU8 } from 'fflate'
import { geom3ToBufferGeometry } from './geom3.js'
import type { Geom3 } from '../types/geometry.js'

// A part's geom is either a JSCAD Geom3 (has `.polygons`, e.g. from jscadRunner)
// or a THREE.BufferGeometry (e.g. STEP-derived, from stepLoader) — mirrors
// src/types/geometry.ts's JscadPart but widened since exporters must also
// accept the BufferGeometry-only (STEP) case that JscadPart doesn't cover.
export interface ExportPart {
  id?: string | null
  geom: Geom3 | THREE.BufferGeometry
  color?: number | null
}

export interface ExportFormat {
  id: string
  label: string
  ext: string
  acceptsAll: boolean
  jscadOnly?: boolean
}

export interface ExportOpts {
  baseName?: string
  singlePartId?: string | null
}

export interface ExportResult {
  blob: Blob
  filename: string
}

// Must match Renderer.jsx so exported colors match what the user sees.
const PALETTE = [0xc9a96b, 0x6b9bc9, 0xc96b89, 0x89c96b, 0xc9b86b, 0x9b6bc9]

export const FORMATS: ExportFormat[] = [
  { id: 'stl-binary', label: 'STL (binary)', ext: 'stl',  acceptsAll: true },
  { id: 'stl-ascii',  label: 'STL (ASCII)',  ext: 'stl',  acceptsAll: true },
  { id: 'obj',        label: 'OBJ',          ext: 'obj',  acceptsAll: true },
  { id: 'glb',        label: 'glTF (GLB)',   ext: 'glb',  acceptsAll: true },
  { id: 'gltf',       label: 'glTF (JSON)',  ext: 'gltf', acceptsAll: true },
  { id: 'ply',        label: 'PLY',          ext: 'ply',  acceptsAll: true },
  { id: '3mf',        label: '3MF',          ext: '3mf',  acceptsAll: true },
  { id: 'jscad-json', label: 'JSCAD JSON',   ext: 'json', acceptsAll: true, jscadOnly: true },
]

const FORMAT_BY_ID: Record<string, ExportFormat> = Object.fromEntries(FORMATS.map((f) => [f.id, f]))

// ---------- helpers ----------

// Sanitise unsafe filename characters. Browsers tolerate most things but we
// prefer something that doesn't get mangled by user shells either.
export function sanitizeFilename(name: unknown): string {
  if (!name) return 'untitled'
  return String(name)
    .replace(/[/\\?%*:|"<>]/g, '_')
    .replace(/\s+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '') || 'untitled'
}

// Strip a known extension from a basename (case-insensitive). Used so we get
// `cube.stl` instead of `cube.jscad.stl`.
function stripExtension(name: string): string {
  if (!name) return ''
  return name.replace(/\.[^./\\]+$/, '')
}

function pickColor(part: ExportPart, index: number): number {
  if (part && part.color != null) return part.color
  return PALETTE[index % PALETTE.length]
}

// Coerce a part's geom into a Three.BufferGeometry. Returns null if the geom
// is missing or empty.
function partToBufferGeometry(part: ExportPart | null | undefined): THREE.BufferGeometry | null {
  const g = part?.geom
  if (!g) return null
  if ((g as THREE.BufferGeometry).isBufferGeometry) return g as THREE.BufferGeometry
  if (Array.isArray((g as Geom3).polygons)) return geom3ToBufferGeometry(g as Geom3)
  return null
}

interface BuiltGroup {
  group: THREE.Group
  ownedGeoms: THREE.BufferGeometry[]
  ownedMats: THREE.Material[]
}

// Build a temporary THREE.Group containing one Mesh per part. Caller owns
// disposal of the materials/geometries that we *create* here (the BufferGeometry
// for JSCAD parts, and all materials).
function buildGroup(parts: ExportPart[]): BuiltGroup {
  const group = new THREE.Group()
  group.name = 'kerf-export'
  const ownedGeoms: THREE.BufferGeometry[] = []
  const ownedMats: THREE.Material[] = []
  parts.forEach((part, i) => {
    const bg = partToBufferGeometry(part)
    if (!bg) return
    // For JSCAD parts we built a fresh BufferGeometry; track for disposal.
    if (!(part.geom as THREE.BufferGeometry).isBufferGeometry) ownedGeoms.push(bg)
    const colorInt = pickColor(part, i)
    const material = new THREE.MeshStandardMaterial({
      color: colorInt,
      metalness: 0.1,
      roughness: 0.7,
    })
    ownedMats.push(material)
    const mesh = new THREE.Mesh(bg, material)
    mesh.name = part.id || `part-${i}`
    group.add(mesh)
  })
  return { group, ownedGeoms, ownedMats }
}

function disposeOwned({ ownedGeoms, ownedMats }: BuiltGroup): void {
  for (const g of ownedGeoms) g.dispose?.()
  for (const m of ownedMats) m.dispose?.()
}

// Trigger a download via a transient anchor.
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // Defer revoke so the browser actually starts the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ---------- per-format exporters ----------

function exportSTL(parts: ExportPart[], { binary = true }: { binary?: boolean } = {}): Blob {
  const owned = buildGroup(parts)
  try {
    const exporter = new STLExporter()
    const data = exporter.parse(owned.group, { binary })
    if (binary) {
      // parse() returns a DataView for binary STL.
      const dv = data as unknown as DataView
      const ab = dv.buffer.slice(dv.byteOffset, dv.byteOffset + dv.byteLength) as ArrayBuffer
      return new Blob([ab], { type: 'application/sla' })
    }
    return new Blob([data as unknown as string], { type: 'application/sla' })
  } finally {
    disposeOwned(owned)
  }
}

function exportOBJ(parts: ExportPart[]): Blob {
  const owned = buildGroup(parts)
  try {
    const exporter = new OBJExporter()
    const text = exporter.parse(owned.group)
    return new Blob([text], { type: 'text/plain' })
  } finally {
    disposeOwned(owned)
  }
}

function exportPLY(parts: ExportPart[]): Promise<Blob> {
  const owned = buildGroup(parts)
  try {
    const exporter = new PLYExporter()
    return new Promise((resolve) => {
      exporter.parse(
        owned.group,
        (result: ArrayBuffer | string) => {
          // Binary PLY → ArrayBuffer; ASCII would be a string. We pass binary:true.
          const blob = result instanceof ArrayBuffer
            ? new Blob([result], { type: 'application/octet-stream' })
            : new Blob([result], { type: 'text/plain' })
          disposeOwned(owned)
          resolve(blob)
        },
        { binary: true },
      )
    })
  } catch (err) {
    disposeOwned(owned)
    throw err
  }
}

function exportGLTF(parts: ExportPart[], { binary = true }: { binary?: boolean } = {}): Promise<Blob> {
  const owned = buildGroup(parts)
  return new Promise((resolve, reject) => {
    const exporter = new GLTFExporter()
    exporter.parse(
      owned.group,
      (result: ArrayBuffer | object) => {
        try {
          if (binary) {
            // result is an ArrayBuffer.
            resolve(new Blob([result as ArrayBuffer], { type: 'model/gltf-binary' }))
          } else {
            const text = JSON.stringify(result, null, 2)
            resolve(new Blob([text], { type: 'model/gltf+json' }))
          }
        } finally {
          disposeOwned(owned)
        }
      },
      (err: unknown) => {
        disposeOwned(owned)
        reject(err)
      },
      { binary },
    )
  })
}

// JSCAD-native: serialise polygons directly. Only works for parts whose source
// was a Geom3 — STEP parts have only a BufferGeometry and would lose fidelity.
function exportJscadJson(parts: ExportPart[]): Blob {
  const out: { format: string; version: number; parts: Array<{ id?: string | null; color: number | null; polygons: Array<{ vertices: number[][] }> }> } =
    { format: 'kerf-jscad-json', version: 1, parts: [] }
  for (const p of parts) {
    const g = p.geom as Geom3
    if (!g || !Array.isArray(g.polygons)) {
      throw new Error(
        `Part "${p.id}" is not a JSCAD Geom3 (likely from a STEP file). ` +
        `Use STL or GLB instead.`,
      )
    }
    out.parts.push({
      id: p.id,
      color: p.color != null ? p.color : null,
      polygons: g.polygons.map((poly) => ({
        vertices: poly.vertices.map((v) => [v[0], v[1], v[2]]),
      })),
    })
  }
  return new Blob([JSON.stringify(out)], { type: 'application/json' })
}

// ---------- 3MF (hand-rolled) ----------
//
// We tessellate every part into triangles, then emit one <object> per part
// inside <resources>, with a <build> block referencing each. Vertex colors are
// not encoded — 3MF supports them via materials but it's significantly more
// XML; v1 keeps the geometry and lets the consumer assign materials.

interface Tessellation {
  vertices: number[][]
  triangles: number[][]
}

function tessellateForThreeMF(part: ExportPart): Tessellation | null {
  const bg = partToBufferGeometry(part)
  if (!bg) return null
  const posAttr = bg.getAttribute('position')
  if (!posAttr) return null

  const vertices: number[][] = []
  const triangles: number[][] = []
  const indexAttr = bg.getIndex()
  // Dedupe vertices using a simple key-string map; 3MF files are smaller and
  // most CAD viewers prefer indexed meshes anyway.
  const keyToIndex = new Map<string, number>()
  function pushVertex(x: number, y: number, z: number): number {
    // Round to 6 decimals so floating-point near-duplicates collapse.
    const k = `${x.toFixed(6)},${y.toFixed(6)},${z.toFixed(6)}`
    let idx = keyToIndex.get(k)
    if (idx === undefined) {
      idx = vertices.length
      vertices.push([x, y, z])
      keyToIndex.set(k, idx)
    }
    return idx
  }
  if (indexAttr) {
    const idx = indexAttr.array
    for (let i = 0; i < idx.length; i += 3) {
      const a = idx[i], b = idx[i + 1], c = idx[i + 2]
      const v1 = pushVertex(posAttr.getX(a), posAttr.getY(a), posAttr.getZ(a))
      const v2 = pushVertex(posAttr.getX(b), posAttr.getY(b), posAttr.getZ(b))
      const v3 = pushVertex(posAttr.getX(c), posAttr.getY(c), posAttr.getZ(c))
      triangles.push([v1, v2, v3])
    }
  } else {
    const count = posAttr.count
    for (let i = 0; i < count; i += 3) {
      const v1 = pushVertex(posAttr.getX(i),     posAttr.getY(i),     posAttr.getZ(i))
      const v2 = pushVertex(posAttr.getX(i + 1), posAttr.getY(i + 1), posAttr.getZ(i + 1))
      const v3 = pushVertex(posAttr.getX(i + 2), posAttr.getY(i + 2), posAttr.getZ(i + 2))
      triangles.push([v1, v2, v3])
    }
  }
  // If we created a geom for a JSCAD part, dispose it now — we copied the data.
  if (!(part.geom as THREE.BufferGeometry).isBufferGeometry) bg.dispose?.()
  return { vertices, triangles }
}

function escapeXml(s: unknown): string {
  return String(s).replace(/[<>&"']/g, (c) => ({
    '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', '\'': '&apos;',
  }[c] as string))
}

function buildThreeMFModelXml(parts: ExportPart[]): string {
  const objectsXml: string[] = []
  const buildItems: string[] = []
  let nextId = 1
  for (const p of parts) {
    const tess = tessellateForThreeMF(p)
    if (!tess || tess.vertices.length === 0 || tess.triangles.length === 0) continue
    const objectId = nextId++
    const verticesXml = tess.vertices
      .map(([x, y, z]) => `<vertex x="${x}" y="${y}" z="${z}"/>`)
      .join('')
    const trianglesXml = tess.triangles
      .map(([a, b, c]) => `<triangle v1="${a}" v2="${b}" v3="${c}"/>`)
      .join('')
    objectsXml.push(
      `<object id="${objectId}" type="model" name="${escapeXml(p.id || `part-${objectId}`)}">` +
        '<mesh>' +
          `<vertices>${verticesXml}</vertices>` +
          `<triangles>${trianglesXml}</triangles>` +
        '</mesh>' +
      '</object>',
    )
    buildItems.push(`<item objectid="${objectId}"/>`)
  }
  return (
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<model unit="millimeter" xml:lang="en-US"' +
      ' xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">' +
      '<resources>' + objectsXml.join('') + '</resources>' +
      '<build>' + buildItems.join('') + '</build>' +
    '</model>'
  )
}

function exportThreeMF(parts: ExportPart[]): Blob {
  const modelXml = buildThreeMFModelXml(parts)
  const contentTypesXml =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>' +
    '</Types>'
  const relsXml =
    '<?xml version="1.0" encoding="UTF-8"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rel0" Target="/3D/3dmodel.model"' +
      ' Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>' +
    '</Relationships>'

  const zipped = zipSync({
    '[Content_Types].xml': strToU8(contentTypesXml),
    '_rels/.rels':         strToU8(relsXml),
    '3D/3dmodel.model':    strToU8(modelXml),
  })
  return new Blob([zipped as BlobPart], { type: 'model/3mf' })
}

// ---------- public entry ----------

export async function exportParts(parts: ExportPart[], format: string, opts: ExportOpts = {}): Promise<ExportResult> {
  const fmt = FORMAT_BY_ID[format]
  if (!fmt) throw new Error(`Unknown export format: ${format}`)
  if (!Array.isArray(parts) || parts.length === 0) {
    throw new Error('No parts to export.')
  }

  const { baseName = 'export', singlePartId = null } = opts
  const stem = sanitizeFilename(stripExtension(baseName) || baseName)
  const filename = singlePartId
    ? `${stem}-${sanitizeFilename(singlePartId)}.${fmt.ext}`
    : `${stem}.${fmt.ext}`

  let blob: Blob
  switch (format) {
    case 'stl-binary': blob = exportSTL(parts, { binary: true });  break
    case 'stl-ascii':  blob = exportSTL(parts, { binary: false }); break
    case 'obj':        blob = exportOBJ(parts);                    break
    case 'glb':        blob = await exportGLTF(parts, { binary: true });  break
    case 'gltf':       blob = await exportGLTF(parts, { binary: false }); break
    case 'ply':        blob = await exportPLY(parts);              break
    case '3mf':        blob = exportThreeMF(parts);                break
    case 'jscad-json': blob = exportJscadJson(parts);              break
    default:
      throw new Error(`Unhandled format: ${format}`)
  }
  return { blob, filename }
}
