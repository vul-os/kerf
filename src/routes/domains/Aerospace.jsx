/**
 * Aerospace domain page — /domains/aerospace
 *
 * Sections:
 *   1. Hero — "From airframe sketch to STEP and Mystran in a conversation"
 *   2. What you get — 3-bullet overview
 *   3. File types / extensions
 *   4. Capability grid — real kerf-aerospace modules
 *   5. Chat transcript — realistic LLM turn with actual tool names
 *   6. Standard interchange callout — STEP/Mystran
 *   7. Open + scriptable — MIT, Python SDK, kerf-sdk
 *   8. CTA strip
 *
 * Metadata: see aerospace.meta.js
 * Palette: ink-n/kerf-n/cyan-edge from src/index.css. No raster assets.
 */
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Github,
  Check,
  Layers,
  Zap,
  Code2,
  Activity,
  FileText,
  ChevronRight,
  Package,
  Workflow,
  PenTool,
} from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import Button from '../../components/Button.jsx'
import DomainSwitcher from '../../components/domains/DomainSwitcher.jsx'
import { TAGLINE } from './aerospace.meta.js'
import { TopoIllustration } from '../../components/illustrations/index.js'

export const HERO_ILLUSTRATION = TopoIllustration

const GITHUB_URL = 'https://github.com/kerf-sh/kerf'

/* -------------------------------------------------------------------------- */
/* Hero illustration — airframe cross-section + FEM stress overlay            */
/* -------------------------------------------------------------------------- */

function HeroIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 480 280"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Aerospace wing cross-section with rib-and-spar structure and FEM stress colouring"
    >
      <defs>
        <linearGradient id="ae-bg" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#08090c" />
          <stop offset="100%" stopColor="#050607" />
        </linearGradient>
        <linearGradient id="ae-skin" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#1c2030" />
          <stop offset="100%" stopColor="#141720" />
        </linearGradient>
        <linearGradient id="ae-stress" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#6bd4ff" />
          <stop offset="50%" stopColor="#ffd633" />
          <stop offset="100%" stopColor="#ff6b6b" />
        </linearGradient>
        <radialGradient id="ae-glow" cx="50%" cy="40%" r="45%">
          <stop offset="0%" stopColor="#ffd633" stopOpacity="0.05" />
          <stop offset="100%" stopColor="#050607" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect width="480" height="280" fill="url(#ae-bg)" />
      <rect width="480" height="280" fill="url(#ae-glow)" />

      {/* Wing planform outline */}
      <path
        d="M 20,200 L 20,90 C 80,70 140,60 220,58 C 320,56 400,64 460,80 L 460,110 C 400,100 320,96 220,98 C 140,99 80,106 20,120 Z"
        fill="url(#ae-skin)"
        stroke="#2d3545"
        strokeWidth="1"
      />

      {/* Spars (vertical lines) */}
      {[80, 180, 320, 420].map((x) => (
        <line key={`spar-${x}`}
          x1={x} y1={x === 80 ? 72 : x === 180 ? 60 : x === 320 ? 58 : 72}
          x2={x} y2={x === 80 ? 115 : x === 180 ? 97 : x === 320 ? 97 : 108}
          stroke="#ffd633" strokeWidth={x === 80 || x === 180 ? 2 : 1}
          strokeOpacity={x === 80 || x === 180 ? 0.7 : 0.4}
        />
      ))}

      {/* Ribs (horizontal sections) */}
      {[60, 100, 140, 200, 260, 340, 400].map((x) => (
        <line key={`rib-${x}`}
          x1={x} y1={62 + (x - 60) * 0.05}
          x2={x} y2={114 + (x - 60) * 0.04}
          stroke="#2d3545" strokeWidth="1" strokeOpacity="0.8"
        />
      ))}

      {/* Spar labels */}
      <text x="80" y="130" textAnchor="middle" fontSize="7"
        fontFamily="ui-monospace, monospace" fill="#ffd633" opacity="0.8">
        Front spar
      </text>
      <text x="180" y="130" textAnchor="middle" fontSize="7"
        fontFamily="ui-monospace, monospace" fill="#ffd633" opacity="0.6">
        Rear spar
      </text>

      {/* FEM stress colour bar — leading edge region */}
      <path
        d="M 20,96 C 40,88 60,83 80,81 C 120,78 160,77 200,77 L 200,82 C 160,82 120,83 80,86 C 60,88 40,92 20,100 Z"
        fill="url(#ae-stress)"
        opacity="0.55"
      />

      {/* Stress legend */}
      <rect x="20" y="140" width="160" height="14" rx="3"
        fill="url(#ae-stress)" opacity="0.7" />
      <text x="20" y="165" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#6bd4ff">0</text>
      <text x="88" y="165" textAnchor="middle" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#ffd633">σ_max/2</text>
      <text x="180" y="165" textAnchor="end" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#ff6b6b">σ_max</text>

      {/* GD&T callout */}
      <rect x="310" y="120" width="150" height="48" rx="4" fill="#0f1115" stroke="#2d3545" />
      <line x1="310" y1="132" x2="460" y2="132" stroke="#2d3545" />
      <line x1="350" y1="120" x2="350" y2="168" stroke="#2d3545" />
      <text x="330" y="129" textAnchor="middle" fontSize="7" fontFamily="ui-monospace, monospace" fill="#8a93a6">⌀ true pos</text>
      <text x="405" y="129" textAnchor="middle" fontSize="7" fontFamily="ui-monospace, monospace" fill="#8a93a6">AS9100</text>
      <text x="330" y="152" textAnchor="middle" fontSize="9" fontFamily="ui-monospace, monospace" fill="#ffd633">0.05</text>
      <text x="405" y="152" textAnchor="middle" fontSize="7.5" fontFamily="ui-monospace, monospace" fill="#8a93a6">A|B|C</text>

      {/* Section: FEM output panel */}
      <rect x="0" y="195" width="480" height="85" fill="#040506" />
      <line x1="0" y1="195" x2="480" y2="195" stroke="#1a1d24" strokeWidth="1" />

      {[
        { x: 10, col: '#5a6275', text: '── FEM result ── FEniCSx + Mystran' },
        { x: 10, col: '#6bd4ff', text: 'max von Mises: 312 MPa  (Al 7075-T6 Ftu 572 MPa)' },
        { x: 10, col: '#ffd633', text: 'margin of safety: +0.83' },
        { x: 10, col: '#4ade80', text: '✓ No failure predicted at 2.5g load case' },
        { x: 10, col: '#8a93a6', text: 'mass: 4.82 kg   CG: (1.24, 0.00, 0.38) m' },
      ].map((row, i) => (
        <text key={i} x={row.x} y={212 + i * 14} fontSize="8.5"
          fontFamily="ui-monospace, monospace" fill={row.col}>
          {row.text}
        </text>
      ))}

      {/* STEP badge */}
      <rect x="360" y="248" width="108" height="24" rx="4" fill="#1a1d24" stroke="#ffd633" strokeWidth="0.7" />
      <text x="414" y="263" textAnchor="middle" fontSize="8.5" fontFamily="ui-monospace, monospace" fill="#ffd633">
        STEP AP242 out
      </text>
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Section: Hero                                                               */
/* -------------------------------------------------------------------------- */

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.09]"
          style={{
            backgroundImage:
              'radial-gradient(circle at 1px 1px, rgba(255,255,255,0.4) 1px, transparent 0)',
            backgroundSize: '28px 28px',
            maskImage:
              'radial-gradient(ellipse 70% 60% at 50% 30%, black 30%, transparent 80%)',
            WebkitMaskImage:
              'radial-gradient(ellipse 70% 60% at 50% 30%, black 30%, transparent 80%)',
          }}
        />
        <div
          className="absolute -top-40 left-1/2 -translate-x-1/2 w-[1100px] h-[700px] opacity-30"
          style={{
            background:
              'radial-gradient(ellipse at center, rgba(255,214,51,0.09) 0%, rgba(107,212,255,0.04) 35%, transparent 70%)',
          }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6 pt-14 pb-16 sm:pt-16 lg:pt-20 lg:pb-20">
        <nav className="flex items-center gap-2 text-xs text-ink-500 font-mono mb-6">
          <Link to="/" className="hover:text-ink-300 transition-colors">kerf.sh</Link>
          <ChevronRight size={12} />
          <Link to="/domains" className="hover:text-ink-300 transition-colors">domains</Link>
          <ChevronRight size={12} />
          <span className="text-kerf-300">aerospace</span>
        </nav>

        <div className="grid lg:grid-cols-[1fr_1.2fr] gap-8 lg:gap-12 items-center">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-ink-800 bg-ink-900/70 backdrop-blur px-3 py-1 text-xs text-ink-300 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-kerf-300 animate-pulse" />
              domain · aerospace structural
            </span>

            <h1 className="mt-4 font-display text-[2.4rem] sm:text-5xl lg:text-[3.75rem] font-semibold tracking-[-0.03em] leading-[1.02]">
              Airframe design
              <br />
              <span className="relative inline-block">
                <span className="relative z-10 text-kerf-300">that analyses.</span>
                <span
                  aria-hidden
                  className="absolute left-0 right-0 -bottom-2 h-2 bg-kerf-300/10 -skew-x-12 rounded-sm"
                />
              </span>
            </h1>

            <p className="mt-4 text-lg text-ink-300 leading-relaxed max-w-xl">
              {TAGLINE} Parametric airframes, FEM with FEniCSx and Mystran,
              composites lay-up, CFD mesh prep, GD&T per AS9100 — STEP AP242
              and Mystran BDF out.
            </p>

            {/* 3-bullet "what you get" */}
            <ul className="mt-5 flex flex-col gap-2">
              {[
                'Parametric wing, fuselage, control surfaces + automated rib/spar placement',
                'Structural FEM via FEniCSx (shell/beam/solid) with Mystran BDF export',
                'STEP AP242 and Mystran are the standard interchange — every aerospace tool reads them',
              ].map((pt) => (
                <li key={pt} className="flex items-start gap-2.5 text-sm text-ink-300">
                  <Check size={13} className="mt-0.5 text-kerf-300 shrink-0" />
                  <span>{pt}</span>
                </li>
              ))}
            </ul>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button as={Link} to="/signup" variant="primary" size="lg">
                Try it free
                <ArrowRight size={16} />
              </Button>
              <Button as={Link} to="/docs/aerospace" variant="outline" size="lg">
                Read the docs
              </Button>
            </div>

            <ul className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-ink-400 font-mono">
              <li className="flex items-center gap-1.5">
                <span className="w-1 h-1 rounded-full bg-ink-500" />
                MIT licensed
              </li>
              <li className="flex items-center gap-1.5">
                <span className="w-1 h-1 rounded-full bg-ink-500" />
                STEP AP242 via OpenCascade
              </li>
              <li className="flex items-center gap-1.5">
                <span className="w-1 h-1 rounded-full bg-ink-500" />
                kerf-sdk on PyPI
              </li>
            </ul>
          </div>

          <div className="relative hidden md:block">
            <div className="relative rounded-2xl border border-ink-800 bg-ink-900/40 backdrop-blur shadow-2xl shadow-black/60 overflow-hidden aspect-[16/10]">
              <HeroIllustration className="block w-full h-full" />
            </div>
            <div
              aria-hidden
              className="absolute -inset-6 -z-10 rounded-[2rem] bg-kerf-300/[0.03] blur-3xl"
            />
          </div>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Section: File types                                                         */
/* -------------------------------------------------------------------------- */

const FILE_TYPES = [
  { ext: '.step / .stp', label: 'STEP AP214 / AP242' },
  { ext: '.bdf / .nas', label: 'Mystran / Nastran bulk data' },
  { ext: '.iges', label: 'IGES 5.3 legacy exchange' },
  { ext: '.su2', label: 'SU2 CFD config + mesh' },
  { ext: '.foam', label: 'OpenFOAM case directory' },
  { ext: '.dxf', label: 'DXF 2D profile export' },
  { ext: '.csv', label: 'Mass budget / BOM export' },
  { ext: '.pdf', label: 'AS9100-compliant drawing sheets' },
]

function FileTypes() {
  return (
    <section className="relative border-t border-ink-900 bg-ink-950/40">
      <div className="mx-auto max-w-7xl px-6 py-8 lg:py-10">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink-500 mb-4">
          Files Kerf reads and writes
        </p>
        <ul className="flex flex-wrap gap-2">
          {FILE_TYPES.map((f) => (
            <li
              key={f.ext}
              className="inline-flex items-center gap-2 rounded-md border border-ink-800 bg-ink-900/50 px-2.5 py-1"
            >
              <span className="font-mono text-xs text-kerf-300">{f.ext}</span>
              <span className="font-mono text-[10px] text-ink-500">{f.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Section: Capability grid                                                    */
/* -------------------------------------------------------------------------- */

const CAPABILITIES = [
  {
    icon: PenTool,
    title: 'Parametric airframe modelling',
    body: 'Wing, fuselage, tail and control-surface geometry driven by span, chord, sweep, dihedral and taper. NACA and custom aerofoil sections. Automatic rib, spar and stringer placement from a load envelope.',
  },
  {
    icon: Activity,
    title: 'Structural FEM (FEniCSx + Mystran)',
    body: 'Linear static and modal FEM via FEniCSx with shell, beam and solid elements. Mystran BDF deck generation. Stress/displacement overlay in the viewport. Margin of safety computed automatically.',
  },
  {
    icon: Layers,
    title: 'Composites lay-up (CFRP / GFRP)',
    body: 'Ply stack-up definition per zone: fibre angle, thickness, material. Laminate stiffness matrix (ABD) computed analytically. Interlaminar shear checks. Draping simulation flags manufacturability issues.',
  },
  {
    icon: Workflow,
    title: 'CFD mesh preparation (SU2 / OpenFOAM)',
    body: 'Surface mesh from STEP geometry. Boundary layer growth for viscous simulations. SU2 config generation for inviscid/viscous compressible flows. OpenFOAM blockMesh + snappyHexMesh integration.',
  },
  {
    icon: FileText,
    title: 'GD&T per AS9100 / Y14.5',
    body: 'Geometric tolerances on drawings conforming to ASME Y14.5 and AS9100 Rev D. Datum structure, feature control frames, tolerance stacks and first-article inspection callouts generated in chat.',
  },
  {
    icon: Code2,
    title: 'STEP AP242 + IGES export',
    body: 'STEP AP214 and AP242 (with PMI) via OpenCascade. IGES 5.3 for legacy toolchain compatibility. PMI — product and manufacturing information — embedded in the AP242 stream.',
  },
  {
    icon: Zap,
    title: 'Mystran solver integration',
    body: 'Direct Mystran BDF deck generation. GRID, CQUAD4, CTRIA3, CBAR, MAT1/MAT8, PSHELL, SPC and LOAD bulk data sections. Results read back into Kerf for post-processing and report generation.',
  },
  {
    icon: Activity,
    title: 'Mass & CG budget',
    body: 'Per-component density and thickness drive a mass breakdown structure. CG tracking updates live as geometry changes. Weight-budget table exports as CSV for PDR/CDR deliverables.',
  },
  {
    icon: FileText,
    title: 'Fatigue life estimation',
    body: 'S-N curve database for aerospace alloys (Al 7075, Ti-6Al-4V, CFRP). Rainflow cycle counting on load histories. Miner rule damage accumulation and inspection interval suggestion.',
  },
]

function CapabilityCard({ icon: Icon, title, body }) {
  return (
    <article className="rounded-2xl border border-ink-800 bg-ink-900/40 p-5 hover:border-ink-700 hover:bg-ink-900/60 transition-colors">
      <div className="flex items-center gap-2.5 mb-2">
        <span className="grid place-items-center w-7 h-7 rounded-md bg-kerf-300/10 border border-kerf-300/30 text-kerf-300">
          <Icon size={13} />
        </span>
        <h3 className="font-display text-base font-semibold tracking-tight text-ink-100">
          {title}
        </h3>
      </div>
      <p className="text-sm text-ink-300 leading-relaxed">{body}</p>
    </article>
  )
}

function CapabilityGrid() {
  return (
    <section className="relative border-t border-ink-900">
      <div className="mx-auto max-w-7xl px-6 py-12 lg:py-14">
        <div className="max-w-2xl mb-8">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300">
            Key tools &amp; LLM functions
          </p>
          <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
            Structural + aero + composites.
            <br />
            <span className="text-ink-300">One open workspace.</span>
          </h2>
          <p className="mt-3 text-ink-300 leading-relaxed">
            Every module ships in the MIT-licensed binary — no add-ons, no tiers.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {CAPABILITIES.map((c) => (
            <CapabilityCard key={c.title} {...c} />
          ))}
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Section: Chat transcript                                                    */
/* -------------------------------------------------------------------------- */

const TRANSCRIPT = [
  {
    role: 'user',
    text: 'Run a 2.5g pull-up FEM on the main wing. Material Al 7075-T6. Report margin of safety and flag any rib buckle risk.',
  },
  {
    role: 'assistant',
    tool: 'search_kerf_docs',
    args: 'query="FEniCSx wing FEM shell element Al 7075"',
    result: '4 results: fem_run, material_library, shell_element, margin_of_safety',
  },
  {
    role: 'assistant',
    tool: 'read_file',
    args: 'path="wing_v3.step"',
    result: 'STEP AP242 loaded: 1 solid, 14 faces, 6 ribs, 2 spars. Mass 4.82 kg.',
  },
  {
    role: 'assistant',
    tool: 'run_fem',
    args: 'load_case="2.5g_pullup" material="Al_7075_T6" element_type="shell"',
    result: 'FEM complete. Max σ_von_Mises 312 MPa. MOS +0.83. Rib R3 buckle factor 2.1 — OK.',
  },
  {
    role: 'assistant',
    tool: 'export_mystran',
    args: 'out="wing_v3_2g5.bdf"',
    result: 'Mystran BDF written: wing_v3_2g5.bdf. GRID/CQUAD4/MAT1/PSHELL/SPC/LOAD sections.',
  },
  {
    role: 'assistant',
    text: 'FEM complete at 2.5g. Max von Mises 312 MPa against Al 7075-T6 Ftu 572 MPa — MOS +0.83. All ribs buckle-safe (lowest factor 2.1). Mystran BDF exported as wing_v3_2g5.bdf. Both STEP AP242 and Mystran BDF are the standard interchange formats every aerospace structural tool accepts.',
  },
]

function ChatTranscript() {
  return (
    <section className="relative border-t border-ink-900 bg-gradient-to-b from-ink-950 to-ink-900/30">
      <div className="mx-auto max-w-4xl px-6 py-12 lg:py-14">
        <div className="max-w-2xl mb-8">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300">
            In practice
          </p>
          <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
            Wing FEM to Mystran in five turns.
          </h2>
          <p className="mt-3 text-ink-300 leading-relaxed">
            Real tool calls — search_kerf_docs, read_file, run_fem,
            export_mystran — from the kerf-aerospace module surface.
          </p>
        </div>

        <div className="rounded-2xl border border-ink-800 bg-ink-950/70 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/60">
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="ml-2 font-mono text-xs text-ink-500">wing_v3.step — kerf chat</span>
          </div>

          <div className="p-4 flex flex-col gap-3">
            {TRANSCRIPT.map((turn, i) => {
              if (turn.role === 'user') {
                return (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[85%] rounded-xl rounded-tr-sm bg-ink-800 border border-ink-700 px-3.5 py-2.5">
                      <p className="text-sm text-ink-100 leading-relaxed">{turn.text}</p>
                    </div>
                  </div>
                )
              }
              if (turn.tool) {
                return (
                  <div key={i} className="rounded-lg border border-ink-800 bg-ink-900/50 px-3.5 py-2.5 font-mono">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-[10px] uppercase tracking-widest text-kerf-300 border border-kerf-300/30 rounded px-1.5 py-0.5">
                        tool
                      </span>
                      <span className="text-sm text-ink-200">{turn.tool}</span>
                    </div>
                    <p className="text-xs text-ink-500 truncate">{turn.args}</p>
                    <p className="text-xs text-emerald-400/80 mt-1">{turn.result}</p>
                  </div>
                )
              }
              return (
                <div key={i} className="flex gap-2.5">
                  <span className="mt-1 w-5 h-5 rounded-full bg-kerf-300/20 border border-kerf-300/30 grid place-items-center text-kerf-300 shrink-0">
                    <span className="text-[9px] font-mono font-bold">K</span>
                  </span>
                  <div className="flex-1 rounded-xl rounded-tl-sm border border-ink-800 bg-ink-900/40 px-3.5 py-2.5">
                    <p className="text-sm text-ink-200 leading-relaxed">{turn.text}</p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Section: Standard interchange callout                                       */
/* -------------------------------------------------------------------------- */

function InterchangeCallout() {
  return (
    <section className="relative border-t border-ink-900 bg-ink-950/60">
      <div className="mx-auto max-w-4xl px-6 py-10 lg:py-12">
        <div className="rounded-2xl border border-kerf-300/20 bg-kerf-300/5 p-6 lg:p-8">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-kerf-300 mb-2">
            Standard interchange
          </p>
          <h3 className="font-display text-xl sm:text-2xl font-semibold tracking-tight text-ink-100 mb-3">
            Both produce STEP AP242 and Mystran — every aerospace tool reads them.
          </h3>
          <p className="text-sm text-ink-300 leading-relaxed max-w-2xl">
            Hand a STEP AP242 to CATIA, Siemens NX, or any DMU tool. Feed the
            Mystran BDF to any Nastran-compatible solver — MSC Nastran, NX
            Nastran, or the open-source Mystran itself. The interchange formats
            are universal; Kerf does not require a proprietary handshake.
          </p>
          <ul className="mt-4 flex flex-wrap gap-3">
            {['STEP AP214 / AP242', 'Mystran / Nastran BDF', 'IGES 5.3', 'SU2 CFD mesh', 'DXF flat patterns'].map((fmt) => (
              <li
                key={fmt}
                className="inline-flex items-center gap-1.5 rounded-md border border-kerf-300/30 bg-kerf-300/5 px-2.5 py-1 font-mono text-xs text-kerf-300"
              >
                <Check size={10} strokeWidth={3} />
                {fmt}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Section: Open + scriptable                                                  */
/* -------------------------------------------------------------------------- */

function OpenAndScriptable() {
  return (
    <section className="relative border-t border-ink-900">
      <div className="mx-auto max-w-6xl px-6 py-12 lg:py-14">
        <div className="grid lg:grid-cols-2 gap-10 items-center">
          <div>
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-kerf-300">
              Open + scriptable
            </p>
            <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
              kerf-sdk on PyPI.
              <br />
              <span className="text-ink-300">MIT root.</span>
            </h2>
            <p className="mt-4 text-ink-300 leading-relaxed">
              Every aerospace capability is accessible through the{' '}
              <code className="text-kerf-300 font-mono text-sm">kerf-sdk</code>{' '}
              Python package on PyPI. Automate full design loops — geometry
              sweep, FEM, mass budget — in a script or CI pipeline.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Button
                as="a"
                href="https://pypi.org/project/kerf-sdk/"
                target="_blank"
                rel="noreferrer"
                variant="outline"
                size="md"
              >
                <Package size={14} />
                kerf-sdk on PyPI
              </Button>
              <Button
                as="a"
                href={GITHUB_URL}
                target="_blank"
                rel="noreferrer"
                variant="outline"
                size="md"
              >
                <Github size={14} />
                GitHub
              </Button>
            </div>
          </div>

          <div className="rounded-2xl border border-ink-800 bg-ink-950 overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/60">
              <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
              <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
              <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
              <span className="ml-2 font-mono text-xs text-ink-500">aero_sweep.py</span>
            </div>
            <pre className="p-4 text-xs font-mono text-ink-300 leading-relaxed overflow-x-auto">
{`import kerf_sdk as kerf

client = kerf.Client()
project = client.projects.get("main_wing")

for camber in [6, 8, 10, 12]:        # % chord
    project.set_param("aerofoil_camber", camber)
    result = project.aerospace.run_fem(
        load_case="2.5g_pullup",
        material="Al_7075_T6",
    )
    print(f"camber {camber}%: MOS {result.margin_of_safety:+.2f}")

# export final STEP for supplier
project.export_step(out="./release/wing_final.step")`}
            </pre>
          </div>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Section: CTA strip                                                          */
/* -------------------------------------------------------------------------- */

function CTAStrip() {
  return (
    <section className="relative border-t border-ink-900">
      <div className="mx-auto max-w-5xl px-6 py-12 lg:py-14">
        <div className="rounded-2xl border border-ink-800 bg-gradient-to-br from-ink-900 via-ink-900 to-ink-950 p-7 lg:p-10 relative overflow-hidden">
          <div
            aria-hidden
            className="absolute -right-32 -top-32 w-96 h-96 rounded-full bg-kerf-300/[0.05] blur-3xl"
          />
          <div className="relative flex flex-col lg:flex-row lg:items-center lg:justify-between gap-5">
            <div>
              <h2 className="font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
                Analyse your first airframe.
              </h2>
              <p className="mt-2 text-ink-300 max-w-xl">
                Sign up free — no card required. Or clone the repo and
                self-host. Both paths are first-class.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button as={Link} to="/signup" variant="primary" size="lg">
                Try it free
                <ArrowRight size={16} />
              </Button>
              <Button
                as="a"
                href={GITHUB_URL}
                target="_blank"
                rel="noreferrer"
                variant="outline"
                size="lg"
              >
                <Github size={16} />
                GitHub
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export default function Aerospace() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />
      <Hero />
      <DomainSwitcher active="aerospace" />
      <FileTypes />
      <CapabilityGrid />
      <ChatTranscript />
      <InterchangeCallout />
      <OpenAndScriptable />
      <CTAStrip />
      <Footer />
    </div>
  )
}
