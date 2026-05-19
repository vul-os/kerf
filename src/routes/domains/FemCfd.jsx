/**
 * FemCfd domain page — /domains/femcfd
 *
 * Sections (top → bottom):
 *   1. Hero — eyebrow / tagline / title / body
 *   2. Capability grid — 3-card module overview
 *   3. File types strip
 *   4. LLM-prompt example
 *   5. Interchange callout
 *
 * Palette: ink-* / kerf-* / cyan-edge from src/index.css. No raster assets.
 */
import { Link } from 'react-router-dom'
import { ArrowRight, Github, Activity, Layers, Cog } from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import Button from '../../components/Button.jsx'
import DomainSwitcher from '../../components/domains/DomainSwitcher.jsx'
import { meta } from './femcfd.meta.js'

const GITHUB_URL = 'https://github.com/kerf-sh/kerf'

/* -------------------------------------------------------------------------- */
/* Hero                                                                        */
/* -------------------------------------------------------------------------- */

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.12]"
          style={{
            backgroundImage:
              'radial-gradient(circle at 1px 1px, rgba(107,212,255,0.6) 1px, transparent 0)',
            backgroundSize: '28px 28px',
            maskImage:
              'radial-gradient(ellipse 70% 60% at 50% 30%, black 30%, transparent 80%)',
            WebkitMaskImage:
              'radial-gradient(ellipse 70% 60% at 50% 30%, black 30%, transparent 80%)',
          }}
        />
        <div
          className="absolute -top-40 left-1/3 -translate-x-1/2 w-[900px] h-[600px] opacity-40"
          style={{
            background:
              'radial-gradient(ellipse at center, rgba(107,212,255,0.12) 0%, rgba(107,212,255,0.03) 35%, transparent 70%)',
          }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6 pt-14 pb-16 sm:pt-16 lg:pt-20 lg:pb-20">
        <div className="max-w-3xl">
          <span className="inline-flex items-center gap-2 rounded-full border border-ink-800 bg-ink-900/70 backdrop-blur px-3 py-1 text-xs text-ink-300 font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-edge animate-pulse" />
            domain · FEM &amp; CFD simulation
          </span>

          <h1 className="mt-4 font-display text-[2.6rem] sm:text-5xl lg:text-[4rem] font-semibold tracking-[-0.03em] leading-[1.02]">
            FEM &amp; CFD
            <br />
            <span className="relative inline-block">
              <span className="relative z-10 text-cyan-edge">in one workspace.</span>
              <span
                aria-hidden
                className="absolute left-0 right-0 -bottom-2 h-2.5 bg-cyan-edge/10 -skew-x-12 rounded-sm"
              />
            </span>
          </h1>

          <p className="mt-5 text-lg text-ink-300 leading-relaxed max-w-2xl">
            Linear static, modal, thermal, and fluid-flow analysis — all from a
            single conversation. FEniCSx drives structural and thermal FEM;
            OpenFOAM handles incompressible CFD. One open-source binary, zero
            licence fees, full Python SDK.
          </p>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button as={Link} to="/signup" variant="primary" size="lg">
              Start analysing free
              <ArrowRight size={16} />
            </Button>
            <Button as={Link} to="/docs/femcfd" variant="outline" size="lg">
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
              FEniCSx + OpenFOAM
            </li>
            <li className="flex items-center gap-1.5">
              <span className="w-1 h-1 rounded-full bg-ink-500" />
              kerf-sdk on PyPI
            </li>
          </ul>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Capability grid (3 cards)                                                   */
/* -------------------------------------------------------------------------- */

const CAPABILITIES = [
  {
    icon: Activity,
    title: 'Structural FEM',
    body: 'Linear static and modal analysis via FEniCSx. Multi-body bonded contact. Deformed-shape 3D overlay with von Mises stress colouring. CalculiX as a second solver for cross-validation.',
  },
  {
    icon: Layers,
    title: 'Thermal analysis',
    body: 'Steady-state and transient heat transfer with convection and radiation boundary conditions. Coupled thermo-structural runs for thermal stress. Results exported as VTK for ParaView post-processing.',
  },
  {
    icon: Cog,
    title: 'CFD — incompressible flow',
    body: 'OpenFOAM-backed incompressible Navier-Stokes. Turbulence modelling (k-ε, k-ω SST). Residual monitoring streamed into chat. Pressure and velocity fields visualised in the viewport.',
  },
]

function CapabilityCard({ icon: Icon, title, body }) {
  return (
    <article className="group relative rounded-2xl border border-ink-800 bg-ink-900/40 p-5 transition-colors hover:border-ink-700 hover:bg-ink-900/60">
      <div className="flex items-center gap-2.5 mb-2">
        <span className="grid place-items-center w-7 h-7 rounded-md bg-cyan-edge/10 border border-cyan-edge/30 text-cyan-edge group-hover:bg-cyan-edge/20 transition-colors">
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
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-edge">
            What&apos;s included
          </p>
          <h2 className="mt-2 font-display text-3xl sm:text-4xl lg:text-5xl font-semibold tracking-[-0.02em]">
            Structural, thermal, fluid.
            <br />
            <span className="text-ink-300">Chat-native.</span>
          </h2>
          <p className="mt-3 text-ink-300 leading-relaxed">
            Every simulation module ships in the same MIT-licensed binary — no add-ons,
            no tier gates.
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
/* File types strip                                                             */
/* -------------------------------------------------------------------------- */

const FILE_TYPES = [
  '.vtk', '.vtu', '.xdmf', '.h5', '.foam', '.step (mesh import)', '.csv (results)',
]

function FileTypesStrip() {
  return (
    <section className="relative border-t border-ink-900 bg-ink-950/50">
      <div className="mx-auto max-w-7xl px-6 py-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-500 mr-2">
            File types
          </span>
          {FILE_TYPES.map((f) => (
            <span
              key={f}
              className="rounded-md border border-ink-800 bg-ink-900/60 px-2.5 py-1 font-mono text-[11px] text-ink-300"
            >
              {f}
            </span>
          ))}
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* LLM prompt example                                                          */
/* -------------------------------------------------------------------------- */

function PromptExample() {
  return (
    <section className="relative border-t border-ink-900 bg-gradient-to-b from-ink-950 to-ink-900/30">
      <div className="mx-auto max-w-4xl px-6 py-12 lg:py-14">
        <div className="max-w-2xl mb-8">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-edge">
            In practice
          </p>
          <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
            Describe the load case. Get the result.
          </h2>
        </div>

        <div className="rounded-2xl border border-ink-800 bg-ink-950/70 backdrop-blur overflow-hidden">
          <div className="border-b border-ink-800 px-4 py-2.5 flex items-center gap-2 bg-ink-900/60">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/70" aria-hidden />
            <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/70" aria-hidden />
            <span className="w-2.5 h-2.5 rounded-full bg-green-500/70" aria-hidden />
            <span className="ml-2 font-mono text-xs text-ink-400">bracket_v2.step — kerf chat</span>
          </div>

          <div className="p-5 flex flex-col gap-4">
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-xl rounded-tr-sm bg-ink-800 border border-ink-700 px-3.5 py-2.5">
                <p className="text-sm text-ink-100 leading-relaxed">
                  Run a linear-static FEM on the bracket with a 500 N downward load on the
                  top face and fixed supports on the two bolt holes. Show me where the
                  stress peaks and the maximum deflection.
                </p>
              </div>
            </div>

            <div className="rounded-lg border border-ink-800 bg-ink-900/50 px-3.5 py-2.5 font-mono">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[10px] uppercase tracking-widest text-cyan-edge border border-cyan-edge/30 rounded px-1.5 py-0.5">
                  tool
                </span>
                <span className="text-sm text-ink-200">fem.run_linear_static</span>
              </div>
              <p className="text-xs text-emerald-400/80 mt-1">
                Solved — 14 832 DoF, 0.4 s. Peak von Mises: 187 MPa at fillet. Max deflection: 0.31 mm. VTK exported.
              </p>
            </div>

            <div className="flex gap-2.5">
              <span className="mt-1 w-5 h-5 rounded-full bg-cyan-edge/20 border border-cyan-edge/30 grid place-items-center text-cyan-edge shrink-0">
                <span className="text-[9px] font-mono font-bold">K</span>
              </span>
              <div className="flex-1 rounded-xl rounded-tl-sm border border-ink-800 bg-ink-900/40 px-3.5 py-2.5">
                <p className="text-sm text-ink-200 leading-relaxed">
                  FEM complete. Peak von Mises stress is 187 MPa, concentrated at the inner
                  fillet radius — consider increasing the fillet from 2 mm to 4 mm to reduce
                  it below the 165 MPa yield limit of Al 6061-T6. Max deflection is 0.31 mm at
                  the load face. Deformed shape and stress overlay are live in the viewport.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Interchange callout                                                         */
/* -------------------------------------------------------------------------- */

function InterchangeCallout() {
  return (
    <section className="relative border-t border-ink-900">
      <div className="mx-auto max-w-7xl px-6 py-12 lg:py-14">
        <div className="rounded-2xl border border-cyan-edge/20 bg-cyan-edge/5 p-6 lg:p-8">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-edge mb-3">
            Both produce VTK + XDMF
          </p>
          <h3 className="font-display text-2xl font-semibold tracking-[-0.02em]">
            FEM and CFD results in the same open interchange format.
          </h3>
          <p className="mt-3 text-ink-300 leading-relaxed max-w-3xl">
            Whether you run structural FEM or incompressible CFD, Kerf exports
            results as VTK and XDMF — the open standards ParaView, VisIt, and
            most post-processors consume natively. Cross your FEM stress field
            with your CFD pressure map in the same ParaView session without
            format conversion.
          </p>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* CTA strip                                                                   */
/* -------------------------------------------------------------------------- */

function CTAStrip() {
  return (
    <section className="relative border-t border-ink-900">
      <div className="mx-auto max-w-7xl px-6 py-12 lg:py-14">
        <div className="rounded-2xl border border-ink-800 bg-gradient-to-br from-ink-900 via-ink-900 to-ink-950 p-7 lg:p-10 relative overflow-hidden">
          <div
            aria-hidden
            className="absolute -right-32 -top-32 w-96 h-96 rounded-full bg-cyan-edge/[0.07] blur-3xl"
          />
          <div className="relative flex flex-col lg:flex-row lg:items-center lg:justify-between gap-5">
            <div>
              <h2 className="font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
                Solve your first load case.
              </h2>
              <p className="mt-2 text-ink-300 max-w-xl">
                Sign up free and run a FEM or CFD analysis in your next session — or
                clone the repo and self-host. Both paths are first-class.
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

export default function FemCfd() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />
      <Hero />
      <DomainSwitcher active="femcfd" />
      <CapabilityGrid />
      <FileTypesStrip />
      <PromptExample />
      <InterchangeCallout />
      <CTAStrip />
      <Footer />
    </div>
  )
}
