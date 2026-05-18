/**
 * Silicon domain page — /domains/silicon
 *
 * Sections:
 *   1. Hero — "From RTL to GDS-II in a conversation"
 *   2. What you get — 3-bullet overview
 *   3. Capability grid — real kerf-silicon EDA modules
 *   4. File types / extensions
 *   5. Chat transcript — realistic LLM turn with actual tool names
 *   6. Standard interchange callout — GDS-II
 *   7. Open + scriptable — MIT, Python SDK, kerf-sdk
 *   8. CTA strip
 *
 * Metadata: see silicon.meta.js
 * Palette: ink-n/kerf-n/cyan-edge from src/index.css. No raster assets.
 */
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Github,
  Check,
  Cpu,
  Layers,
  Zap,
  Code2,
  Boxes,
  Activity,
  FileText,
  ChevronRight,
  Package,
} from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import Button from '../../components/Button.jsx'
import DomainSwitcher from '../../components/domains/DomainSwitcher.jsx'
import { TAGLINE } from './silicon.meta.js'

const GITHUB_URL = 'https://github.com/kerf-sh/kerf'

/* -------------------------------------------------------------------------- */
/* Hero illustration — RTL waveform + layout view                             */
/* -------------------------------------------------------------------------- */

function HeroIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 480 280"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="RTL waveform and GDS-II layout cell view with timing paths highlighted"
    >
      <defs>
        <linearGradient id="si-bg" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#0a0b0d" />
          <stop offset="100%" stopColor="#070809" />
        </linearGradient>
        <linearGradient id="si-stripe" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#ffd633" stopOpacity="0" />
          <stop offset="30%" stopColor="#ffd633" stopOpacity="0.8" />
          <stop offset="100%" stopColor="#ffd633" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="si-glow" cx="50%" cy="40%" r="45%">
          <stop offset="0%" stopColor="#ffd633" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#0a0b0d" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect width="480" height="280" fill="url(#si-bg)" />
      <rect width="480" height="280" fill="url(#si-glow)" />

      {/* GDS-II layout grid */}
      {Array.from({ length: 12 }, (_, i) => (
        <line key={`vg-${i}`} x1={20 + i * 38} y1={20} x2={20 + i * 38} y2={180}
          stroke="#1e2230" strokeWidth="0.6" />
      ))}
      {Array.from({ length: 8 }, (_, i) => (
        <line key={`hg-${i}`} x1={20} y1={20 + i * 22} x2={460} y2={20 + i * 22}
          stroke="#1e2230" strokeWidth="0.6" />
      ))}

      {/* Standard cells — coloured rectangles */}
      {[
        { x: 24, y: 26, w: 34, h: 18, color: '#ffd633', opacity: 0.7, label: 'INV_X2' },
        { x: 62, y: 26, w: 72, h: 18, color: '#6bd4ff', opacity: 0.5, label: 'DFF_X1' },
        { x: 138, y: 26, w: 34, h: 18, color: '#ffd633', opacity: 0.5, label: 'NAND2' },
        { x: 176, y: 26, w: 56, h: 18, color: '#6bd4ff', opacity: 0.4, label: 'DFF_X1' },
        { x: 24, y: 48, w: 56, h: 18, color: '#ffd633', opacity: 0.5, label: 'AND3' },
        { x: 84, y: 48, w: 34, h: 18, color: '#ffd633', opacity: 0.4, label: 'OR2' },
        { x: 122, y: 48, w: 92, h: 18, color: '#6bd4ff', opacity: 0.4, label: 'DFF_X2' },
        { x: 24, y: 70, w: 190, h: 18, color: '#ffd633', opacity: 0.3, label: 'SRAM_SP_256x8' },
        { x: 220, y: 26, w: 56, h: 62, color: '#ff6bd4', opacity: 0.2, label: 'PLL' },
      ].map((cell) => (
        <g key={cell.label}>
          <rect x={cell.x} y={cell.y} width={cell.w} height={cell.h}
            fill={cell.color} fillOpacity={cell.opacity}
            stroke={cell.color} strokeWidth="0.6" strokeOpacity="0.6" rx="1" />
          <text x={cell.x + 2} y={cell.y + 11} fontSize="6"
            fontFamily="ui-monospace, monospace" fill={cell.color} opacity="0.9">
            {cell.label}
          </text>
        </g>
      ))}

      {/* Critical timing path highlight */}
      <polyline points="80,35 138,35 176,35 220,35"
        fill="none" stroke="url(#si-stripe)" strokeWidth="1.5" />
      <circle cx="80" cy="35" r="2.5" fill="#ffd633" opacity="0.8" />
      <circle cx="220" cy="35" r="2.5" fill="#ffd633" opacity="0.8" />

      {/* Routing metal layers */}
      <line x1="24" y1="92" x2="240" y2="92" stroke="#6bd4ff" strokeWidth="1.2" opacity="0.4" />
      <line x1="80" y1="26" x2="80" y2="92" stroke="#6bd4ff" strokeWidth="1.2" opacity="0.3" />
      <line x1="176" y1="26" x2="176" y2="92" stroke="#6bd4ff" strokeWidth="1.2" opacity="0.3" />

      {/* Waveform section */}
      <rect x="0" y="192" width="480" height="88" fill="#050607" />
      <line x1="0" y1="192" x2="480" y2="192" stroke="#1e2230" strokeWidth="1" />

      {/* Signal labels */}
      {['clk', 'data_in', 'data_out', 'valid'].map((sig, i) => (
        <text key={sig} x="8" y={208 + i * 17} fontSize="8"
          fontFamily="ui-monospace, monospace" fill="#5a6275">
          {sig}
        </text>
      ))}

      {/* Waveforms */}
      {/* clk */}
      <polyline points="60,200 60,215 100,215 100,200 140,200 140,215 180,215 180,200 220,200 220,215 260,215 260,200 300,200 300,215 340,215 340,200 380,200 380,215 420,215 420,200 460,200"
        fill="none" stroke="#ffd633" strokeWidth="1" opacity="0.7" />
      {/* data_in */}
      <polyline points="60,225 100,225 100,216 140,216 140,225 220,225 220,216 260,216 260,225 340,225 340,216 380,216"
        fill="none" stroke="#6bd4ff" strokeWidth="1" opacity="0.6" />
      {/* data_out (delayed) */}
      <polyline points="60,242 140,242 140,233 180,233 180,242 260,242 260,233 300,233 300,242 380,242 380,233 420,233 420,242 460,242"
        fill="none" stroke="#6bd4ff" strokeWidth="1" opacity="0.5" />
      {/* valid */}
      <polyline points="60,258 180,258 180,248 380,248 380,258 460,258"
        fill="none" stroke="#ffd633" strokeWidth="1" opacity="0.4" />

      {/* Timing violation marker */}
      <line x1="260" y1="193" x2="260" y2="270" stroke="#ff6b6b" strokeWidth="0.8" strokeDasharray="3 2" />
      <text x="262" y="203" fontSize="7" fontFamily="ui-monospace, monospace" fill="#ff6b6b">setup −0.12ns</text>

      {/* Info chips */}
      <rect x="290" y="112" width="100" height="20" rx="4" fill="#1a1d24" stroke="#ffd633" strokeWidth="0.7" />
      <text x="340" y="125" textAnchor="middle" fontSize="8" fontFamily="ui-monospace, monospace" fill="#ffd633">
        DRC: 0 errors
      </text>
      <rect x="395" y="112" width="72" height="20" rx="4" fill="#1a1d24" stroke="#1e2230" />
      <text x="431" y="125" textAnchor="middle" fontSize="8" fontFamily="ui-monospace, monospace" fill="#8a93a6">
        GDS-II out
      </text>

      {/* Prompt bar */}
      <rect x="290" y="138" width="178" height="22" rx="4" fill="#0f1115" stroke="#1a1d24" />
      <text x="300" y="152" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275">›</text>
      <text x="312" y="152" fontSize="9" fontFamily="ui-monospace, monospace" fill="#8a93a6">
        run PnR, target 200 MHz
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
          className="absolute inset-0 opacity-[0.10]"
          style={{
            backgroundImage:
              'radial-gradient(circle at 1px 1px, rgba(255,214,51,0.6) 1px, transparent 0)',
            backgroundSize: '24px 24px',
            maskImage:
              'radial-gradient(ellipse 70% 60% at 50% 30%, black 30%, transparent 80%)',
            WebkitMaskImage:
              'radial-gradient(ellipse 70% 60% at 50% 30%, black 30%, transparent 80%)',
          }}
        />
        <div
          className="absolute -top-40 left-1/2 -translate-x-1/2 w-[1100px] h-[700px] opacity-40"
          style={{
            background:
              'radial-gradient(ellipse at center, rgba(255,214,51,0.10) 0%, rgba(255,214,51,0.02) 35%, transparent 70%)',
          }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6 pt-14 pb-16 sm:pt-16 lg:pt-20 lg:pb-20">
        <nav className="flex items-center gap-2 text-xs text-ink-500 font-mono mb-6">
          <Link to="/" className="hover:text-ink-300 transition-colors">kerf.sh</Link>
          <ChevronRight size={12} />
          <Link to="/domains" className="hover:text-ink-300 transition-colors">domains</Link>
          <ChevronRight size={12} />
          <span className="text-kerf-300">silicon</span>
        </nav>

        <div className="grid lg:grid-cols-[1fr_1.2fr] gap-8 lg:gap-12 items-center">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-ink-800 bg-ink-900/70 backdrop-blur px-3 py-1 text-xs text-ink-300 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-kerf-300 animate-pulse" />
              domain · silicon / IC design
            </span>

            <h1 className="mt-4 font-display text-[2.4rem] sm:text-5xl lg:text-[3.75rem] font-semibold tracking-[-0.03em] leading-[1.02]">
              Chip design
              <br />
              <span className="relative inline-block">
                <span className="relative z-10 text-kerf-300">that listens.</span>
                <span
                  aria-hidden
                  className="absolute left-0 right-0 -bottom-2 h-2 bg-kerf-300/10 -skew-x-12 rounded-sm"
                />
              </span>
            </h1>

            <p className="mt-4 text-lg text-ink-300 leading-relaxed max-w-xl">
              {TAGLINE} RTL synthesis, place-and-route, DRC/LVS, parasitic
              extraction and timing closure — all driven by chat. Open PDKs
              (Sky130, GF180MCU). GDS-II out.
            </p>

            {/* 3-bullet "what you get" */}
            <ul className="mt-5 flex flex-col gap-2">
              {[
                'Full RTL-to-GDS-II flow via Yosys + OpenROAD + KLayout',
                'DRC/LVS with Magic + Netgen, STA with OpenSTA',
                'GDS-II is the standard interchange — every EDA tool reads it',
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
              <Button as={Link} to="/docs/silicon" variant="outline" size="lg">
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
                open PDKs supported
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
              className="absolute -inset-6 -z-10 rounded-[2rem] bg-kerf-300/[0.04] blur-3xl"
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
  { ext: '.v / .sv', label: 'Verilog / SystemVerilog RTL' },
  { ext: '.gds', label: 'GDS-II layout stream' },
  { ext: '.def / .lef', label: 'Design/Library Exchange Format' },
  { ext: '.sdc', label: 'Synopsys Design Constraints' },
  { ext: '.spef', label: 'Standard Parasitic Exchange Format' },
  { ext: '.sp / .cir', label: 'SPICE netlist' },
  { ext: '.s8 / sky130', label: 'Sky130B PDK rule deck' },
  { ext: '.gf180mcu', label: 'GF180MCU PDK rule deck' },
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
    icon: Code2,
    title: 'RTL synthesis (Yosys)',
    body: 'Synthesise Verilog/SystemVerilog to a gate netlist. Technology mapping for Sky130, GF180MCU and nextpnr-compatible FPGA targets (iCE40, ECP5). Synth reports surfaced in chat.',
  },
  {
    icon: Cpu,
    title: 'Place & route (OpenROAD)',
    body: 'Floorplan, placement, CTS and global/detailed routing via OpenROAD. DEF/LEF round-trip. SDC/UPF constraints authored and applied in the same chat session.',
  },
  {
    icon: Activity,
    title: 'DRC + LVS (Magic / Netgen)',
    body: 'Layout versus schematic and design-rule checks. Sky130B and GF180MCU rule decks bundled. Violations shown inline with cell context, fix suggestions generated automatically.',
  },
  {
    icon: Layers,
    title: 'Parasitic extraction (OpenRCX → SPEF)',
    body: 'RC parasitics extracted from routed DEF. SPEF feeds back into STA and post-layout SPICE. Coupling caps included. Re-run automatically on each PnR iteration.',
  },
  {
    icon: Zap,
    title: 'Static timing analysis (OpenSTA)',
    body: 'Full STA: setup/hold slack, critical-path report, multi-corner MMMC. SDC edits made in chat; STA re-runs and worst-path delta is summarised in the reply.',
  },
  {
    icon: Boxes,
    title: 'Post-layout SPICE + waveforms',
    body: 'ngspice transient and AC sim on SPEF-annotated netlists. Waveforms and measurement expressions accessible in the chat loop. PDK device corners tracked automatically.',
  },
  {
    icon: FileText,
    title: 'GDS-II export (KLayout)',
    body: 'Final GDS-II stream via KLayout Python API. Top-cell merge, layer mapping, optional stream compression. Submit-ready for CMP / Efabless shuttle services.',
  },
  {
    icon: Activity,
    title: 'FPGA bitstream (nextpnr)',
    body: 'Yosys synthesis + nextpnr PnR for iCE40 and ECP5 targets. Pack → place → route → bitstream in one chat command. iceprog/openFPGALoader flash integration.',
  },
  {
    icon: Cpu,
    title: 'Interactive layout viewer',
    body: 'GDS-II and DEF rendered in-browser via KLayout WebAssembly. Layer visibility, ruler, LPP filter, DRC marker overlay. No external viewer install required.',
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
            Full RTL-to-GDS-II.
            <br />
            <span className="text-ink-300">Open PDKs. Open toolchain.</span>
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
    text: 'Synthesise the uart_rx module targeting Sky130. I want a gate-level netlist and a timing report.',
  },
  {
    role: 'assistant',
    tool: 'search_kerf_docs',
    args: 'query="yosys synthesis Sky130 PDK"',
    result: '4 results: rtl_synth, pdk_sky130, timing_report, export_netlist',
  },
  {
    role: 'assistant',
    tool: 'run_rtl_synth',
    args: 'module="uart_rx" pdk="sky130B" target_freq_mhz=100',
    result: 'Synthesis complete. 248 cells. Slack: setup +0.42 ns, hold +0.08 ns. Area: 1 842 µm².',
  },
  {
    role: 'user',
    text: 'Now run place-and-route. Core utilisation ≤ 60%. Then export GDS-II.',
  },
  {
    role: 'assistant',
    tool: 'run_pnr',
    args: 'module="uart_rx" utilisation=0.60 pdk="sky130B"',
    result: 'PnR complete. Util 54.3%. WNS +0.31 ns. DRC: 0 errors.',
  },
  {
    role: 'assistant',
    tool: 'export_gds',
    args: 'module="uart_rx" out="uart_rx.gds"',
    result: 'GDS-II written: uart_rx.gds (48 KB). Ready for CMP submission.',
  },
  {
    role: 'assistant',
    text: 'Done. uart_rx synthesised (248 cells, 1 842 µm²), PnR at 54.3% utilisation, WNS +0.31 ns — timing met. GDS-II exported as uart_rx.gds. Both GDS-II and SPEF are the standard interchange formats any EDA tool accepts.',
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
            RTL to tape-out in six turns.
          </h2>
          <p className="mt-3 text-ink-300 leading-relaxed">
            Real tool calls — run_rtl_synth, run_pnr, export_gds — from the
            kerf-silicon module surface.
          </p>
        </div>

        <div className="rounded-2xl border border-ink-800 bg-ink-950/70 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/60">
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="ml-2 font-mono text-xs text-ink-500">uart_rx.v — kerf chat</span>
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
            Both produce GDS-II — every EDA tool reads it.
          </h3>
          <p className="text-sm text-ink-300 leading-relaxed max-w-2xl">
            Whether you finish your design in Kerf or hand off a partial layout
            to Cadence Virtuoso, Synopsys IC Compiler, or KLayout, the GDS-II
            stream is the universal substrate. SPEF for parasitics and DEF for
            floorplan are equally standard — no vendor lock-in.
          </p>
          <ul className="mt-4 flex flex-wrap gap-3">
            {['GDS-II', 'DEF / LEF', 'SPEF', 'SPICE netlist', 'SDC constraints'].map((fmt) => (
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
              Every silicon capability is accessible through the{' '}
              <code className="text-kerf-300 font-mono text-sm">kerf-sdk</code>{' '}
              Python package on PyPI. Run synthesis sweeps, PnR corner
              analysis, and CI tape-out checks from your own machine over
              HTTP/JSON-RPC.
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
              <span className="ml-2 font-mono text-xs text-ink-500">corner_sweep.py</span>
            </div>
            <pre className="p-4 text-xs font-mono text-ink-300 leading-relaxed overflow-x-auto">
{`import kerf_sdk as kerf

client = kerf.Client()
project = client.projects.get("uart_rx")

for freq in [100, 150, 200]:          # MHz
    result = project.silicon.run_pnr(
        module="uart_rx",
        target_freq_mhz=freq,
        pdk="sky130B",
        utilisation=0.60,
    )
    print(f"{freq} MHz → WNS {result.wns:+.3f} ns")

# export final GDS-II
project.silicon.export_gds(out="./tapeout/")`}
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
            className="absolute -right-32 -top-32 w-96 h-96 rounded-full bg-kerf-300/[0.06] blur-3xl"
          />
          <div className="relative flex flex-col lg:flex-row lg:items-center lg:justify-between gap-5">
            <div>
              <h2 className="font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
                Tape out your first chip.
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

export default function Silicon() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />
      <Hero />
      <DomainSwitcher active="silicon" />
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
