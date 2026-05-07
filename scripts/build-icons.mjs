#!/usr/bin/env node
// Generates the full Kerf icon + social-preview asset set from the source
// SVGs in `public/`. Run manually (or via `npm run build:icons`) whenever the
// brand mark changes — the rendered PNGs and ICO are committed to the repo
// and served as static assets.
//
// Inputs:
//   public/favicon.svg     — 32×32 brand mark
//   public/og-image.svg    — 1200×630 social card (read for color cues only;
//                            we synthesise a purpose-built card here so the
//                            text doesn't depend on any specific installed
//                            font on the host that runs the script).
//
// Outputs (all under public/):
//   favicon-16.png, favicon-32.png, favicon-48.png
//   favicon.ico             (multi-res 16/32/48)
//   apple-touch-icon.png    180×180 with inset margin (iOS rounds corners)
//   icon-192.png            Android home-screen / PWA
//   icon-512.png            PWA splash
//   icon-maskable.png       512×512 with the mark inside the inner 80%
//   og-image.png            1200×630 social-preview card
//   twitter-card.png        1200×600 same card, tighter aspect
//
// Design constants reused from the brand:
//   ink-950    #0a0b0d   page surface
//   kerf-300   #ffd633   yellow mark / theme color
//   ink-200    #e2e6ee   light text
//   ink-500    #8a93a6   muted text
//   ink-700    #232730   hairline rules

import fs from 'node:fs/promises'
import path from 'node:path'
import url from 'node:url'
import sharp from 'sharp'

const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const PUBLIC = path.join(ROOT, 'public')

const COLORS = {
  ink950: '#0a0b0d',
  ink900: '#0e0f12',
  ink700: '#232730',
  ink500: '#8a93a6',
  ink300: '#a3a8b3',
  ink200: '#e2e6ee',
  kerf300: '#ffd633',
}

// ---------------------------------------------------------------------------
// SVG helpers
// ---------------------------------------------------------------------------

// The Kerf mark, drawn at any scale. `viewBox` of the favicon is 32×32; the
// mark is positioned so the rounded background card fills the box with a
// 0px margin. For the maskable icon, we drop the rounded corners and let the
// caller pad around it.
function kerfMarkSvg({ size = 512, rounded = true, bg = COLORS.ink950, padding = 0 } = {}) {
  // Inner viewBox is always 32 units; we just scale the wrapper.
  const radius = rounded ? Math.round(size * (6 / 32)) : 0
  const inset = padding
  const inner = size - 2 * padding
  return `
<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" shape-rendering="geometricPrecision">
  <rect x="${inset}" y="${inset}" width="${inner}" height="${inner}" rx="${radius}" fill="${bg}"/>
  <g transform="translate(${inset} ${inset}) scale(${inner / 32})">
    <path d="M5 5 H24 L5 24 Z" fill="${COLORS.kerf300}"/>
    <path d="M27 8 V27 H8 Z" fill="${COLORS.kerf300}"/>
  </g>
</svg>`
}

// A maskable icon needs the mark inside the inner 80% of the canvas, with a
// solid background tile filling the full square (so platforms can crop into
// any shape — circle, squircle, rounded-rect — without revealing transparent
// edges). Per spec: safe zone is the central circle of radius 40% of the
// shortest edge. We pad by 10% on each side so the 32-unit mark lands
// comfortably inside the inner 80×80% region.
function maskableSvg(size = 512) {
  const pad = Math.round(size * 0.18) // a touch more than 10% so the mark sits in the safe circle
  const inner = size - 2 * pad
  return `
<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" shape-rendering="geometricPrecision">
  <rect x="0" y="0" width="${size}" height="${size}" fill="${COLORS.kerf300}"/>
  <g transform="translate(${pad} ${pad}) scale(${inner / 32})">
    <!-- On the yellow tile we invert: dark mark for contrast -->
    <rect width="32" height="32" rx="6" fill="${COLORS.ink950}"/>
    <path d="M5 5 H24 L5 24 Z" fill="${COLORS.kerf300}"/>
    <path d="M27 8 V27 H8 Z" fill="${COLORS.kerf300}"/>
  </g>
</svg>`
}

// Apple touch icon. iOS auto-rounds the corners and applies a subtle gloss;
// we leave a small inner padding so the mark isn't crowded against the edge.
function appleTouchSvg(size = 180) {
  const pad = Math.round(size * 0.10)
  const inner = size - 2 * pad
  return `
<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" shape-rendering="geometricPrecision">
  <rect width="${size}" height="${size}" fill="${COLORS.ink950}"/>
  <g transform="translate(${pad} ${pad}) scale(${inner / 32})">
    <path d="M5 5 H24 L5 24 Z" fill="${COLORS.kerf300}"/>
    <path d="M27 8 V27 H8 Z" fill="${COLORS.kerf300}"/>
  </g>
</svg>`
}

// Social-preview card. Generated fresh here (rather than rasterising
// og-image.svg) because the source SVG depends on Geist/JetBrains-Mono
// being installed on the rendering host, which isn't guaranteed. We use
// system-ui-ish stacks and fall back gracefully; resvg substitutes a
// reasonable sans-serif. Visually: dark surface + diagonal kerf hairline +
// big yellow mark on the left + wordmark/tagline on the right + small
// "MIT licensed" pill bottom-right + "Built in Durban" line bottom-left +
// faint dot grid behind everything.
function socialCardSvg({ width = 1200, height = 630 } = {}) {
  // Dot grid: 24px pitch, low opacity. Generated via <pattern>.
  // Mark sits centered in the left 600px column at scale ~14× the favicon.
  // viewBox of the mark is 32; we scale by 14 → 448px tall. Left/top at
  // (height - 448)/2 within the left half.
  const markScale = 14
  const markPx = 32 * markScale
  const markX = (width / 2 - markPx) / 2
  const markY = (height - markPx) / 2

  return `
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" shape-rendering="geometricPrecision">
  <defs>
    <radialGradient id="vignette" cx="50%" cy="50%" r="75%">
      <stop offset="0%"   stop-color="#14171c" stop-opacity="0.7"/>
      <stop offset="100%" stop-color="${COLORS.ink900}" stop-opacity="0"/>
    </radialGradient>
    <pattern id="dots" x="0" y="0" width="24" height="24" patternUnits="userSpaceOnUse">
      <circle cx="1" cy="1" r="1" fill="${COLORS.ink700}" opacity="0.55"/>
    </pattern>
    <linearGradient id="surface" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="${COLORS.ink900}"/>
      <stop offset="100%" stop-color="${COLORS.ink950}"/>
    </linearGradient>
  </defs>

  <!-- Background -->
  <rect width="${width}" height="${height}" fill="url(#surface)"/>
  <rect width="${width}" height="${height}" fill="url(#dots)"/>
  <rect width="${width}" height="${height}" fill="url(#vignette)"/>

  <!-- Diagonal kerf-line accent across the whole card -->
  <line x1="-40" y1="${height + 60}" x2="${width + 40}" y2="-60"
        stroke="${COLORS.kerf300}" stroke-width="1.5" opacity="0.18"/>

  <!-- Logomark (left half) -->
  <g transform="translate(${markX} ${markY}) scale(${markScale})">
    <path d="M5 5 H24 L5 24 Z" fill="${COLORS.kerf300}"/>
    <path d="M27 8 V27 H8 Z" fill="${COLORS.kerf300}"/>
  </g>

  <!-- Hairline divider -->
  <line x1="${width / 2}" y1="190" x2="${width / 2}" y2="${height - 190}"
        stroke="${COLORS.ink700}" stroke-width="1"/>

  <!-- Wordmark + tagline -->
  <g font-family="ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif" fill="${COLORS.ink200}">
    <text x="${width / 2 + 60}" y="${height / 2 + 10}"
          font-size="180" font-weight="700" letter-spacing="-6"
          fill="${COLORS.ink200}">kerf</text>
    <text x="${width / 2 + 64}" y="${height / 2 + 70}"
          font-size="32" font-weight="400" letter-spacing="2"
          fill="${COLORS.ink300}">chat-driven CAD</text>
    <text x="${width / 2 + 64}" y="${height / 2 + 130}"
          font-family="ui-monospace, SFMono-Regular, Menlo, monospace"
          font-size="20" fill="${COLORS.kerf300}" opacity="0.85">&gt; sketch · cut · refine</text>
  </g>

  <!-- Bottom-left: built in Durban -->
  <g font-family="ui-sans-serif, system-ui, -apple-system, sans-serif">
    <text x="48" y="${height - 36}" font-size="18" fill="${COLORS.ink500}">
      Built in Durban · South Africa
    </text>
  </g>

  <!-- Bottom-right: MIT pill -->
  <g transform="translate(${width - 48 - 140} ${height - 56})">
    <rect x="0" y="0" width="140" height="34" rx="17"
          fill="none" stroke="${COLORS.ink700}" stroke-width="1"/>
    <text x="70" y="22" text-anchor="middle"
          font-family="ui-sans-serif, system-ui, -apple-system, sans-serif"
          font-size="14" font-weight="500" fill="${COLORS.ink300}"
          letter-spacing="1">MIT LICENSED</text>
  </g>
</svg>`
}

// ---------------------------------------------------------------------------
// ICO writer
// ---------------------------------------------------------------------------
// Build a multi-resolution .ico from raw PNG buffers. The ICO container is
// a small header + one ICONDIRENTRY per image + the embedded PNG bytes.
// We embed PNGs (Vista+) rather than uncompressed BMPs — every modern
// browser, OS, and reasonable bot understands PNG-in-ICO.
function buildIco(pngEntries) {
  // pngEntries: [{ size: 16|32|48, buf: Buffer }]
  const count = pngEntries.length
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0) // reserved
  header.writeUInt16LE(1, 2) // type: 1 = icon
  header.writeUInt16LE(count, 4) // image count

  const entries = Buffer.alloc(16 * count)
  const dataChunks = []
  let offset = 6 + 16 * count

  pngEntries.forEach((entry, i) => {
    const { size, buf } = entry
    const e = entries.subarray(i * 16, (i + 1) * 16)
    e.writeUInt8(size === 256 ? 0 : size, 0) // width (0 = 256)
    e.writeUInt8(size === 256 ? 0 : size, 1) // height
    e.writeUInt8(0, 2) // palette
    e.writeUInt8(0, 3) // reserved
    e.writeUInt16LE(1, 4) // color planes
    e.writeUInt16LE(32, 6) // bpp
    e.writeUInt32LE(buf.length, 8) // size of image data
    e.writeUInt32LE(offset, 12) // offset to image data
    dataChunks.push(buf)
    offset += buf.length
  })

  return Buffer.concat([header, entries, ...dataChunks])
}

// ---------------------------------------------------------------------------
// Render pipeline
// ---------------------------------------------------------------------------
// Render an SVG to a PNG at a precise output size. We rasterise at high
// density (for crisp sub-pixel detail), then resize to the exact target.
// This avoids sharp's density-based scaling producing oversized PNGs when
// the SVG already declares its own width/height.
async function renderSvgToPng(svgString, outPath, { width, height, density = 768 } = {}) {
  let pipe = sharp(Buffer.from(svgString), { density }).png({ compressionLevel: 9 })
  if (width || height) pipe = pipe.resize(width, height, { fit: 'fill' })
  const buf = await pipe.toBuffer()
  await fs.writeFile(outPath, buf)
  return buf
}

async function main() {
  const out = (name) => path.join(PUBLIC, name)

  console.log('[build-icons] writing favicon PNGs')
  await renderSvgToPng(kerfMarkSvg({ size: 16 }), out('favicon-16.png'), { width: 16, height: 16, density: 2048 })
  await renderSvgToPng(kerfMarkSvg({ size: 32 }), out('favicon-32.png'), { width: 32, height: 32, density: 1536 })
  await renderSvgToPng(kerfMarkSvg({ size: 48 }), out('favicon-48.png'), { width: 48, height: 48, density: 1024 })

  console.log('[build-icons] building favicon.ico (16/32/48)')
  // ICO entries should be encoded at their actual pixel size — re-encode
  // straight from the source SVG at each size for crispest output.
  const ico16 = await sharp(Buffer.from(kerfMarkSvg({ size: 16 })), { density: 1536 })
    .resize(16, 16).png().toBuffer()
  const ico32 = await sharp(Buffer.from(kerfMarkSvg({ size: 32 })), { density: 1024 })
    .resize(32, 32).png().toBuffer()
  const ico48 = await sharp(Buffer.from(kerfMarkSvg({ size: 48 })), { density: 768 })
    .resize(48, 48).png().toBuffer()
  const ico = buildIco([
    { size: 16, buf: ico16 },
    { size: 32, buf: ico32 },
    { size: 48, buf: ico48 },
  ])
  await fs.writeFile(out('favicon.ico'), ico)

  console.log('[build-icons] writing apple-touch-icon (180×180)')
  await renderSvgToPng(appleTouchSvg(180), out('apple-touch-icon.png'), { width: 180, height: 180, density: 512 })

  console.log('[build-icons] writing icon-192 / icon-512')
  await renderSvgToPng(kerfMarkSvg({ size: 192 }), out('icon-192.png'), { width: 192, height: 192, density: 384 })
  await renderSvgToPng(kerfMarkSvg({ size: 512 }), out('icon-512.png'), { width: 512, height: 512, density: 256 })

  console.log('[build-icons] writing icon-maskable (512×512, 80% safe zone)')
  await renderSvgToPng(maskableSvg(512), out('icon-maskable.png'), { width: 512, height: 512, density: 256 })

  console.log('[build-icons] writing og-image.png (1200×630)')
  await renderSvgToPng(socialCardSvg({ width: 1200, height: 630 }), out('og-image.png'), { width: 1200, height: 630, density: 192 })

  console.log('[build-icons] writing twitter-card.png (1200×600)')
  await renderSvgToPng(socialCardSvg({ width: 1200, height: 600 }), out('twitter-card.png'), { width: 1200, height: 600, density: 192 })

  console.log('[build-icons] done — wrote 11 assets to public/')
}

main().catch((err) => {
  console.error('[build-icons] failed:', err)
  process.exit(1)
})
