/**
 * compareMeta.js — shared SEO meta + JSON-LD generator for /compare/* pages.
 *
 * Usage:
 *   import { makeCompareMeta } from './compareMeta.js'
 *   const meta = makeCompareMeta('freecad')
 *
 *   <head>
 *     <title>{meta.title}</title>
 *     <meta name="description" content={meta.description} />
 *     <link rel="canonical" href={meta.canonical} />
 *     ...
 *   </head>
 */

const BASE = 'https://kerf.sh'

/** Per-slug SEO data (title ≤60 chars, description ≤155 chars). */
const PAGES = {
  freecad: {
    title: 'Kerf vs FreeCAD — chat-driven CAD compared',
    description:
      'FreeCAD is the gold standard for open-source parametric B-rep CAD. ' +
      "See how Kerf's chat-native workflow and MIT open-core stack compare.",
    slug: 'freecad',
    product: 'FreeCAD',
  },
  kicad: {
    title: 'Kerf vs KiCad — PCB design tools compared',
    description:
      "KiCad is the leading open-source EDA suite. Compare KiCad's mature " +
      "tooling against Kerf's integrated electronics + mechanical workflow.",
    slug: 'kicad',
    product: 'KiCad',
  },
  rhino: {
    title: 'Kerf vs Rhino — NURBS & jewelry CAD compared',
    description:
      'Rhino (with RhinoGold / Matrix) sets the bar for NURBS surfacing and ' +
      "jewelry CAD. See where Kerf's open-core approach stands today.",
    slug: 'rhino',
    product: 'Rhino',
  },
  revit: {
    title: 'Kerf vs Revit — architecture BIM compared',
    description:
      'Revit is the industry-standard BIM platform for architecture. Compare ' +
      "its deep BIM toolset against Kerf's IFC-capable open-core workspace.",
    slug: 'revit',
    product: 'Revit',
  },
  fusion: {
    title: 'Kerf vs Fusion 360 — cloud CAD compared',
    description:
      "Fusion 360 pioneered cloud-connected mechanical CAD. See how Kerf's " +
      'MIT open-core, chat-driven approach compares on features and pricing.',
    slug: 'fusion',
    product: 'Fusion 360',
  },
}

/**
 * Returns title, description, canonical URL, OG image URL, and a JSON-LD
 * WebPage schema string for the given slug.
 */
export function makeCompareMeta(slug) {
  const page = PAGES[slug]
  if (!page) throw new Error(`Unknown compare slug: ${slug}`)

  const canonical = `${BASE}/compare/${slug}`
  const ogImage = `${BASE}/og/compare-${slug}.png`

  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: page.title,
    description: page.description,
    url: canonical,
    image: ogImage,
    publisher: {
      '@type': 'Organization',
      name: 'Kerf',
      url: BASE,
    },
  })

  return {
    title: page.title,
    description: page.description,
    canonical,
    ogImage,
    jsonLd,
    product: page.product,
    slug,
  }
}

export { PAGES }
