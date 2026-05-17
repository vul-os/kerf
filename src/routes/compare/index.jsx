/**
 * /compare — hub page linking to each tool comparison.
 *
 * Cards (grouped by category): Mechanical · Electronic · BIM · Jewelry · DCC.
 * No raster assets; inline SVG iconography via Lucide. Shares the same
 * prominent fairness note as every comparison page.
 */
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Code2,
  CircuitBoard,
  Gem,
  Building2,
  Cloud,
  Box,
  Cog,
  PencilRuler,
  Mountain,
  Film,
  Sparkles,
} from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import { FairnessNote } from './Freecad.jsx'

const CARDS = [
  // — Mechanical CAD
  {
    slug: 'freecad',
    icon: Code2,
    label: 'FreeCAD',
    category: 'Mechanical',
    tagline: 'Open-source parametric B-rep modeller',
    blurb:
      'FreeCAD 1.0 is a mature, LGPL, desktop parametric CAD package with a built-in Assembly workbench, FEM, and a decade-old workbench community. We compare it honestly against Kerf.',
  },
  {
    slug: 'fusion',
    icon: Cloud,
    label: 'Fusion 360',
    category: 'Mechanical',
    tagline: 'Cloud-connected mechanical CAD',
    blurb:
      "Fusion 360 pioneered cloud-connected parametric CAD with CAM, FEM, and generative design. See where it leads and where Kerf's open-core, chat-driven approach differs.",
  },
  {
    slug: 'solidworks',
    icon: Cog,
    label: 'SOLIDWORKS',
    category: 'Mechanical',
    tagline: 'Industry-standard mechanical CAD',
    blurb:
      "SOLIDWORKS is the dominant Parasolid-kernel mech CAD with a 30-year vendor lead. We document the maturity gap and where Kerf's multi-discipline scope earns its keep.",
  },
  {
    slug: 'onshape',
    icon: Cloud,
    label: 'Onshape',
    category: 'Mechanical',
    tagline: 'Browser-native real-time-collab CAD',
    blurb:
      "Onshape pioneered real-time multi-user CAD in the browser with proprietary FeatureScript. The closest peer to Kerf in shape — see where the open-core MIT model and chat-driven UX differ.",
  },
  {
    slug: 'inventor',
    icon: Cog,
    label: 'Inventor',
    category: 'Mechanical',
    tagline: "Autodesk's mechanical CAD",
    blurb:
      "Inventor is Autodesk's professional mech CAD with Dynamic Simulation, Frame Generator, Tube & Pipe, and a deep PDM ecosystem. Honest gap analysis vs Kerf's open-core multi-discipline scope.",
  },
  {
    slug: 'autocad',
    icon: PencilRuler,
    label: 'AutoCAD',
    category: 'Drafting',
    tagline: 'Industry-standard 2D drafting + 3D modelling',
    blurb:
      "AutoCAD owns 2D drafting and .dwg interchange after 40+ years. Kerf's 3D-first parametric workspace is a different shape — see how they overlap and where each wins.",
  },

  // — Electronic CAD
  {
    slug: 'kicad',
    icon: CircuitBoard,
    label: 'KiCad',
    category: 'Electronic',
    tagline: 'Open-source EDA suite',
    blurb:
      "KiCad 10 (2026) is a deep, free EDA suite with native IPC-2581/ODB++ and a huge library. See where it leads and where Kerf's unified electronics + mechanical workspace differs.",
  },
  {
    slug: 'altium',
    icon: CircuitBoard,
    label: 'Altium Designer',
    category: 'Electronic',
    tagline: 'Industrial-grade PCB design',
    blurb:
      "Altium Designer is the industrial reference for PCB layout — interactive push-and-shove routing, HDI/RF specialization. We document the gaps and where Kerf's integrated SI/EMC/PDN/thermal pre-compliance differs.",
  },

  // — BIM + civil
  {
    slug: 'revit',
    icon: Building2,
    label: 'Revit',
    category: 'BIM',
    tagline: 'Industry-standard BIM platform',
    blurb:
      "Revit is Autodesk's dominant BIM platform for AEC, with full MEP and family authoring. We compare its depth with Kerf's lighter, IFC-capable open-core workspace.",
  },
  {
    slug: 'civil3d',
    icon: Mountain,
    label: 'Civil 3D',
    category: 'BIM',
    tagline: 'Civil infrastructure design',
    blurb:
      "Civil 3D owns corridor modelling, pipe networks, and surveying in the AEC stack. See where Kerf's civil-engineering calc modules (hydrology / geotech / pavement / surveying) complement.",
  },

  // — Jewelry
  {
    slug: 'rhino',
    icon: Gem,
    label: 'Rhino',
    category: 'Jewelry / NURBS',
    tagline: 'NURBS & jewelry CAD (MatrixGold / RhinoGold)',
    blurb:
      'Rhino 8 with MatrixGold / RhinoGold is the professional reference for NURBS surfacing and jewelry. Honest gaps and real capabilities on both sides.',
  },
  {
    slug: 'matrixgold',
    icon: Sparkles,
    label: 'MatrixGold',
    category: 'Jewelry / NURBS',
    tagline: 'Industry-standard jewelry CAD',
    blurb:
      "MatrixGold is the industry-standard jewelry plugin stack on Rhino. We document its setting/casting depth and where Kerf's 40-module retail workflow (appraisal / repair / mount-finder) differs.",
  },

  // — DCC (mesh / render)
  {
    slug: 'blender',
    icon: Box,
    label: 'Blender',
    category: 'DCC',
    tagline: 'Mesh / DCC tool (not a B-rep CAD)',
    blurb:
      "Blender is a world-class mesh / DCC tool with Cycles + Geometry Nodes. Different category from Kerf — we show where they overlap for product visualisation and where each wins.",
  },
  {
    slug: 'max3ds',
    icon: Film,
    label: '3ds Max',
    category: 'DCC',
    tagline: 'Archviz & game-art DCC',
    blurb:
      "3ds Max with Arnold / V-Ray / Corona is the archviz + game-art standard. We document the render-depth gap and where Kerf's engineering-CAD workflow earns its place.",
  },
]

const CATEGORY_ORDER = ['Mechanical', 'Drafting', 'Electronic', 'BIM', 'Jewelry / NURBS', 'DCC']

function CompareCard({ slug, icon: Icon, label, tagline, blurb }) {
  return (
    <Link
      to={`/compare/${slug}`}
      className="group relative flex flex-col rounded-2xl border border-ink-800 bg-ink-900/40 p-5 sm:p-6 hover:border-ink-700 hover:bg-ink-900/70 transition-colors"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <span className="grid place-items-center w-9 h-9 rounded-lg bg-kerf-300/10 border border-kerf-300/30 text-kerf-300 shrink-0">
            <Icon size={16} />
          </span>
          <div>
            <h2 className="font-display text-base font-semibold tracking-tight text-ink-100">
              Kerf vs {label}
            </h2>
            <p className="text-xs text-ink-400 font-mono mt-0.5">{tagline}</p>
          </div>
        </div>
        <ArrowRight
          size={15}
          className="text-ink-500 group-hover:text-kerf-300 group-hover:translate-x-0.5 transition-all shrink-0 mt-1"
        />
      </div>
      <p className="text-sm text-ink-300 leading-relaxed">{blurb}</p>
    </Link>
  )
}

export default function CompareHub() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />

      <main className="mx-auto max-w-4xl px-6 pt-14 pb-20">
        {/* Hero */}
        <div className="mb-10">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Compare
          </p>
          <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em] leading-tight">
            How does Kerf compare?
          </h1>
          <p className="mt-4 text-ink-300 leading-relaxed max-w-2xl">
            These tools are genuinely excellent — many are decades old, deeply
            validated, and free or affordable. Kerf is young by comparison.
            These pages credit each competitor's real strengths first and
            generously, state Kerf's gaps without spin, and use a comprehensive
            side-by-side table where the competitor often wins. The aim is an
            honest decision aid, not marketing.
          </p>
        </div>

        {/* Cards grid — grouped by category */}
        {CATEGORY_ORDER.map((category) => {
          const cards = CARDS.filter((c) => c.category === category)
          if (cards.length === 0) return null
          return (
            <section key={category} className="mb-10 last:mb-0" aria-label={category}>
              <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-ink-400 mb-3">
                {category}
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {cards.map((card) => (
                  <CompareCard key={card.slug} {...card} />
                ))}
              </div>
            </section>
          )
        })}

        {/* Fairness footer — same component used on every comparison page */}
        <FairnessNote />
      </main>

      <Footer />
    </div>
  )
}
