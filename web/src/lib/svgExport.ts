// SVG / PNG / PDF export helpers for the drawing view.
//
// PDF lazy-imports jspdf + svg2pdf.js so neither lands in the main bundle —
// only when the user actually clicks the PDF button.

import { sheetDimensions, SHEET_SIZES } from './sheetFrames.js'

/** A drawing sheet ref/size argument accepted by {@link exportPdf} (via resolvePdfSize). */
export type SheetSizeArg =
  | string
  | { size?: string; orientation?: string }
  | { width_mm: number; height_mm: number }
  | null
  | undefined

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // Revoke after a tick so the click has time to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// Serialize an SVGElement to a standalone .svg file. We strip event handlers
// and inject the xmlns attribute if missing so the result opens in any
// viewer (Inkscape, browser tab, etc.).
export function exportSvg(svgElement: SVGElement | null | undefined, filename = 'drawing.svg'): void {
  if (!svgElement) return
  const clone = svgElement.cloneNode(true) as SVGElement
  if (!clone.getAttribute('xmlns')) {
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  }
  clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
  const xml = new XMLSerializer().serializeToString(clone)
  const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
  downloadBlob(blob, filename)
}

// Rasterize the SVG to PNG via a data-URL → Image → canvas roundtrip.
// `scale` multiplies the SVG's intrinsic pixel dimensions for crispness on
// HiDPI screens (default 2× DPI). Returns a promise that resolves once the
// download has been triggered.
export function exportPng(svgElement: SVGElement | null | undefined, filename = 'drawing.png', scale = 2): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!svgElement) {
      resolve()
      return
    }
    const clone = svgElement.cloneNode(true) as SVGElement
    if (!clone.getAttribute('xmlns')) {
      clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    }
    // Determine pixel size from viewBox or width/height attributes.
    const vb = clone.getAttribute('viewBox')
    let w = parseFloat(clone.getAttribute('width') || '') || 0
    let h = parseFloat(clone.getAttribute('height') || '') || 0
    if ((!w || !h) && vb) {
      const parts = vb.split(/\s+/).map(Number)
      if (parts.length === 4) {
        w = parts[2]
        h = parts[3]
      }
    }
    if (!w || !h) {
      reject(new Error('SVG has no intrinsic size'))
      return
    }
    const xml = new XMLSerializer().serializeToString(clone)
    const svgBlob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' })
    const url = URL.createObjectURL(svgBlob)
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = Math.ceil(w * scale)
      canvas.height = Math.ceil(h * scale)
      const ctx = canvas.getContext('2d')!
      // White background — drawings are normally on a sheet of paper.
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      canvas.toBlob((blob) => {
        if (!blob) {
          reject(new Error('canvas.toBlob failed'))
          return
        }
        downloadBlob(blob, filename)
        resolve()
      }, 'image/png')
    }
    img.onerror = (err) => {
      URL.revokeObjectURL(url)
      reject(err instanceof Error ? err : new Error('Failed to load SVG into Image'))
    }
    img.src = url
  })
}

// Render the SVG into a single-page PDF sized to the sheet. `sheetSize` may
// be:
//   - {size: 'A4'|'A3'|...|'A0', orientation: 'landscape'|'portrait'}
//   - {width_mm: number, height_mm: number}                    // custom
//   - undefined → A3 landscape default
// jspdf + svg2pdf.js are both lazy-imported (~150KB combined gz) so they
// don't bloat the main bundle.
export async function exportPdf(svgElement: SVGElement | null | undefined, filename = 'drawing.pdf', sheetSize?: SheetSizeArg): Promise<void> {
  if (!svgElement) return
  const { width, height, orientation } = resolvePdfSize(sheetSize)
  const [{ jsPDF }, svg2pdfMod] = await Promise.all([
    import('jspdf'),
    import('svg2pdf.js'),
  ])
  // svg2pdf.js exposes either a default function or a named `svg2pdf` export
  // depending on the build; tolerate both. The declared types only cover the named
  // export, so the `.default` fallback (an actual runtime possibility depending on
  // bundler interop) isn't a callable per the .d.ts — cast to the shape both branches
  // are actually called with.
  const svg2pdf = (svg2pdfMod.svg2pdf || svg2pdfMod.default) as unknown as
    (element: Element, pdf: InstanceType<typeof jsPDF>, options?: { x: number; y: number; width: number; height: number }) => Promise<unknown>
  const doc = new jsPDF({
    orientation: (orientation || (width >= height ? 'landscape' : 'portrait')) as 'landscape' | 'portrait',
    unit: 'mm',
    format: [width, height],
  })
  // Clone the SVG and ensure xmlns are set (svg2pdf is strict about it).
  const clone = svgElement.cloneNode(true) as SVGElement
  if (!clone.getAttribute('xmlns')) {
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  }
  clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
  await svg2pdf(clone, doc, { x: 0, y: 0, width, height })
  doc.save(filename)
}

interface ResolvedPdfSize {
  width: number
  height: number
  orientation?: string
}

function resolvePdfSize(sz: SheetSizeArg): ResolvedPdfSize {
  if (!sz) {
    const d = sheetDimensions('A3', 'landscape')
    return { width: d.w, height: d.h, orientation: 'landscape' }
  }
  if (typeof sz === 'object' && Number.isFinite((sz as { width_mm: number }).width_mm) && Number.isFinite((sz as { height_mm: number }).height_mm)) {
    const s = sz as { width_mm: number; height_mm: number }
    return { width: s.width_mm, height: s.height_mm }
  }
  if (typeof sz === 'object' && SHEET_SIZES[(sz as { size?: string }).size ?? '']) {
    const s = sz as { size: string; orientation?: string }
    const d = sheetDimensions(s.size, s.orientation || 'landscape')
    return { width: d.w, height: d.h, orientation: s.orientation || 'landscape' }
  }
  if (typeof sz === 'string' && SHEET_SIZES[sz]) {
    const d = sheetDimensions(sz, 'landscape')
    return { width: d.w, height: d.h, orientation: 'landscape' }
  }
  // Fallback: treat anything else as A3 landscape.
  const d = sheetDimensions('A3', 'landscape')
  return { width: d.w, height: d.h, orientation: 'landscape' }
}
