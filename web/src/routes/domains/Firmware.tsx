/**
 * Firmware domain page — /domains/firmware
 *
 * Sections:
 *   1. Hero — "From bare metal to .hex in a conversation"
 *   2. What you get — 3-bullet overview
 *   3. File types / extensions
 *   4. Capability grid — real kerf-firmware modules
 *   5. Chat transcript — realistic LLM turn with actual tool names
 *   6. Standard interchange callout — .hex/.elf
 *   7. Open + scriptable — MIT, Python SDK, kerf-sdk
 *   8. CTA strip
 *
 * Metadata: see firmware.meta.js
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
  Activity,
  FileText,
  ChevronRight,
  Package,
  Terminal,
} from 'lucide-react'
import Header from '../../components/Header.jsx'
import Footer from '../../components/Footer.jsx'
import Button from '../../components/Button.jsx'
import DomainSwitcher from '../../components/domains/DomainSwitcher.jsx'
import { TAGLINE } from './firmware.meta.js'
import { ScriptingIllustration } from '../../components/illustrations/index.js'

// Exported so tests and parent pages can reference the illustration mapping
export const HERO_ILLUSTRATION = ScriptingIllustration

const GITHUB_URL = 'https://github.com/kerf-sh/kerf'

/* -------------------------------------------------------------------------- */
/* Hero illustration — disassembly + RTOS task diagram                        */
/* -------------------------------------------------------------------------- */

function HeroIllustration({ className = '' }) {
  return (
    <svg
      viewBox="0 0 480 280"
      preserveAspectRatio="xMidYMid meet"
      className={className}
      role="img"
      aria-label="Embedded firmware build log with RTOS task timeline and memory map"
    >
      <defs>
        <linearGradient id="fw-bg" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#0a0b0d" />
          <stop offset="100%" stopColor="#060708" />
        </linearGradient>
        <radialGradient id="fw-glow" cx="30%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#6bd4ff" stopOpacity="0.05" />
          <stop offset="100%" stopColor="#060708" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect width="480" height="280" fill="url(#fw-bg)" />
      <rect width="480" height="280" fill="url(#fw-glow)" />

      {/* Left panel: build output */}
      <rect x="0" y="0" width="230" height="280" fill="#050607" />
      <rect x="0" y="0" width="230" height="26" fill="#0d0e11" />
      <text x="10" y="17" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275">
        make flash · STM32F4
      </text>

      {[
        { y: 40,  col: '#6bd4ff', text: '[CC]  src/main.c' },
        { y: 55,  col: '#6bd4ff', text: '[CC]  src/uart.c' },
        { y: 70,  col: '#6bd4ff', text: '[CC]  freertos/tasks.c' },
        { y: 85,  col: '#6bd4ff', text: '[LD]  firmware.elf' },
        { y: 100, col: '#5a6275', text: '      text   data   bss' },
        { y: 115, col: '#8a93a6', text: '      14208    256  1024' },
        { y: 130, col: '#ffd633', text: '✓ Size OK  (64 KB flash)' },
        { y: 145, col: '#6bd4ff', text: '[OBJCOPY] firmware.hex' },
        { y: 160, col: '#6bd4ff', text: '[FLASH] openocd -f ...' },
        { y: 175, col: '#8a93a6', text: 'target halted (Cortex-M4)' },
        { y: 190, col: '#ffd633', text: '✓ Flashed OK' },
        { y: 210, col: '#5a6275', text: '── cppcheck ──' },
        { y: 225, col: '#8a93a6', text: '[cppcheck] main.c' },
        { y: 240, col: '#4ade80', text: '0 errors, 0 warnings' },
      ].map((row, i) => (
        <text key={i} x="10" y={row.y} fontSize="8.5"
          fontFamily="ui-monospace, monospace" fill={row.col}>
          {row.text}
        </text>
      ))}

      {/* Right panel: RTOS task timeline */}
      <rect x="234" y="0" width="246" height="140" fill="#060708" />
      <text x="244" y="17" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275">
        RTOS scheduler · 1 ms ticks
      </text>

      {/* Tick marks */}
      {Array.from({ length: 10 }, (_, i) => (
        <g key={i}>
          <line x1={244 + i * 22} y1="24" x2={244 + i * 22} y2="130"
            stroke="#1a1d24" strokeWidth="0.6" />
          <text x={244 + i * 22} y="22" textAnchor="middle" fontSize="7"
            fontFamily="ui-monospace, monospace" fill="#3a4150">
            {i}ms
          </text>
        </g>
      ))}

      {/* Task bars */}
      {[
        { y: 32, h: 12, label: 'uart_task', bars: [[0, 2], [5, 2], [10, 2]], color: '#6bd4ff' },
        { y: 52, h: 12, label: 'sensor_task', bars: [[2, 3], [7, 3]], color: '#ffd633' },
        { y: 72, h: 12, label: 'ctrl_task', bars: [[3, 1], [8, 1]], color: '#ff6bd4' },
        { y: 92, h: 12, label: 'idle', bars: [[1, 1], [4, 1], [6, 1], [9, 1]], color: '#2d323d' },
      ].map((task) => (
        <g key={task.label}>
          <text x="234" y={task.y + 10} fontSize="7.5"
            fontFamily="ui-monospace, monospace" fill="#5a6275"
            textAnchor="end" dominantBaseline="middle">
          </text>
          {task.bars.map(([start, dur], j) => (
            <rect key={j}
              x={244 + start * 22} y={task.y}
              width={dur * 22} height={task.h}
              fill={task.color} fillOpacity="0.55" rx="2" />
          ))}
          <text x={244} y={task.y + 9} fontSize="7.5"
            fontFamily="ui-monospace, monospace" fill={task.color}>
            {task.label}
          </text>
        </g>
      ))}

      {/* Memory map */}
      <rect x="234" y="145" width="246" height="135" fill="#050607" />
      <line x1="234" y1="145" x2="480" y2="145" stroke="#1a1d24" strokeWidth="1" />
      <text x="244" y="160" fontSize="9" fontFamily="ui-monospace, monospace" fill="#5a6275">
        Linker memory map
      </text>

      {[
        { label: '.text', size: '14 208 B', color: '#6bd4ff', pct: 55 },
        { label: '.data', size: '256 B', color: '#ffd633', pct: 5 },
        { label: '.bss', size: '1 024 B', color: '#ff6bd4', pct: 10 },
        { label: '.stack', size: '2 048 B', color: '#8a93a6', pct: 20 },
        { label: '.heap', size: '8 192 B', color: '#4ade80', pct: 10 },
      ].map((seg, i) => (
        <g key={seg.label}>
          <text x="244" y={177 + i * 18} fontSize="8"
            fontFamily="ui-monospace, monospace" fill={seg.color}>
            {seg.label}
          </text>
          <rect x="290" y={167 + i * 18} width={seg.pct * 1.6} height="10"
            fill={seg.color} fillOpacity="0.4" rx="2" />
          <text x="300" y={177 + i * 18} fontSize="7.5"
            fontFamily="ui-monospace, monospace" fill={seg.color} opacity="0.9">
            {seg.size}
          </text>
        </g>
      ))}
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
              'radial-gradient(circle at 1px 1px, rgba(107,212,255,0.6) 1px, transparent 0)',
            backgroundSize: '24px 24px',
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
              'radial-gradient(ellipse at center, rgba(107,212,255,0.10) 0%, rgba(107,212,255,0.02) 35%, transparent 70%)',
          }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6 pt-14 pb-16 sm:pt-16 lg:pt-20 lg:pb-20">
        <nav className="flex items-center gap-2 text-xs text-ink-500 font-mono mb-6">
          <Link to="/" className="hover:text-ink-300 transition-colors">kerf.sh</Link>
          <ChevronRight size={12} />
          <Link to="/domains" className="hover:text-ink-300 transition-colors">domains</Link>
          <ChevronRight size={12} />
          <span className="text-cyan-edge">firmware</span>
        </nav>

        <div className="grid lg:grid-cols-[1fr_1.2fr] gap-8 lg:gap-12 items-center">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-ink-800 bg-ink-900/70 backdrop-blur px-3 py-1 text-xs text-ink-300 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-edge animate-pulse" />
              domain · embedded firmware
            </span>

            <h1 className="mt-4 font-display text-[2.4rem] sm:text-5xl lg:text-[3.75rem] font-semibold tracking-[-0.03em] leading-[1.02]">
              Firmware
              <br />
              <span className="relative inline-block">
                <span className="relative z-10 text-cyan-edge">that compiles.</span>
                <span
                  aria-hidden
                  className="absolute left-0 right-0 -bottom-2 h-2 bg-cyan-edge/10 -skew-x-12 rounded-sm"
                />
              </span>
            </h1>

            <p className="mt-4 text-lg text-ink-300 leading-relaxed max-w-xl">
              {TAGLINE} C / C++ / Rust on ARM Cortex-M and RISC-V. RTOS
              scaffolding, static analysis, linker scripts, flash and debug —
              all from a chat conversation. .hex and .elf out.
            </p>

            {/* 3-bullet "what you get" */}
            <ul className="mt-5 flex flex-col gap-2">
              {[
                'Full build pipeline: compile → link → flash via OpenOCD / pyOCD',
                'Static analysis with cppcheck + clang-tidy on every build turn',
                '.hex and .elf are universal — load them on any debugger or bootloader',
              ].map((pt) => (
                <li key={pt} className="flex items-start gap-2.5 text-sm text-ink-300">
                  <Check size={13} className="mt-0.5 text-cyan-edge shrink-0" />
                  <span>{pt}</span>
                </li>
              ))}
            </ul>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Button as={Link} to="/signup" variant="primary" size="lg">
                Try it free
                <ArrowRight size={16} />
              </Button>
              <Button as={Link} to="/docs/firmware" variant="outline" size="lg">
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
                ARM + RISC-V toolchains
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
              className="absolute -inset-6 -z-10 rounded-[2rem] bg-cyan-edge/[0.04] blur-3xl"
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
  { ext: '.c / .cpp', label: 'C / C++ source' },
  { ext: '.rs', label: 'Rust source (cargo cross)' },
  { ext: '.hex', label: 'Intel HEX flash image' },
  { ext: '.elf', label: 'ELF with debug symbols' },
  { ext: '.bin', label: 'Raw binary for bootloader' },
  { ext: '.ld', label: 'GNU linker script' },
  { ext: '.dts / .overlay', label: 'Zephyr devicetree' },
  { ext: 'Kconfig', label: 'Kconfig build options' },
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
              <span className="font-mono text-xs text-cyan-edge">{f.ext}</span>
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
    title: 'C / C++ / Rust toolchain (ARM + RISC-V)',
    body: 'arm-none-eabi-gcc, arm-none-eabi-g++, and cargo cross. Build configs for STM32, RP2040, ESP32, nRF52 and GD32 families. Cortex-A64 Linux targets supported.',
  },
  {
    icon: Cpu,
    title: 'RTOS configuration (FreeRTOS / Zephyr)',
    body: 'FreeRTOS task, queue, semaphore and timer scaffolding generated in chat. Zephyr DTS and Kconfig authoring with LLM awareness of binding schemas. West build wired end-to-end.',
  },
  {
    icon: Activity,
    title: 'Static analysis (cppcheck + clang-tidy)',
    body: 'cppcheck and clang-tidy on every compile turn. MISRA-C 2012 advisory subset via cppcheck addons. Findings shown inline with source context — fix suggestions generated automatically.',
  },
  {
    icon: FileText,
    title: 'Linker script authoring',
    body: 'Memory region tables (.text, .bss, .data, .stack, .heap) authored and validated in chat. GNU ld script syntax with size-budget callout after each link. Scatter files for armlink also supported.',
  },
  {
    icon: Terminal,
    title: 'Flash + debug (OpenOCD / pyOCD)',
    body: 'OpenOCD and pyOCD flash programming and SWD/JTAG debug. GDB server wired through the chat loop: set breakpoints, inspect memory and registers — from a conversation.',
  },
  {
    icon: Zap,
    title: '.hex / .elf / .bin output',
    body: 'Intel HEX, ELF with full debug symbols and raw .bin for bootloader consumption. objcopy, objdump and nm cross-references embedded in the chat diff.',
  },
  {
    icon: Layers,
    title: 'Peripheral HAL scaffolding',
    body: 'Generate HAL init code for GPIO, UART, SPI, I2C, ADC, DAC, DMA and timers. Vendor cube/HAL wrappers or bare CMSIS depending on target. Register-level code where no HAL exists.',
  },
  {
    icon: Activity,
    title: 'Unit testing (Unity / Ceedling)',
    body: 'Unity test framework and Ceedling runner. Mock generation for peripheral HALs. Tests run on host x86 via cross-compile shim — no hardware required for logic-layer tests.',
  },
  {
    icon: Cpu,
    title: 'Bootloader (MCUboot / U-Boot)',
    body: 'MCUboot slot configuration for OTA on ARM Cortex-M. U-Boot config for embedded Linux targets (AM335x, i.MX8, Raspberry Pi CM). Signed image pipeline wired to kerf git.',
  },
]

function CapabilityCard({ icon: Icon, title, body }) {
  return (
    <article className="rounded-2xl border border-ink-800 bg-ink-900/40 p-5 hover:border-ink-700 hover:bg-ink-900/60 transition-colors">
      <div className="flex items-center gap-2.5 mb-2">
        <span className="grid place-items-center w-7 h-7 rounded-md bg-cyan-edge/10 border border-cyan-edge/30 text-cyan-edge">
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
            Key tools &amp; LLM functions
          </p>
          <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
            Bare metal to RTOS.
            <br />
            <span className="text-ink-300">Open toolchains, no lock-in.</span>
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
    text: 'Add a FreeRTOS task for UART receive on USART2. DMA-driven, 115 200 baud. Store received bytes in a ring buffer shared with the control task.',
  },
  {
    role: 'assistant',
    tool: 'search_kerf_docs',
    args: 'query="FreeRTOS UART DMA ring buffer STM32"',
    result: '5 results: freertos_task, dma_uart, ring_buffer, hal_uart, peripheral_hal',
  },
  {
    role: 'assistant',
    tool: 'read_file',
    args: 'path="src/main.c"',
    result: '184 lines — USART2 init at line 62; FreeRTOS tasks list at line 140',
  },
  {
    role: 'assistant',
    tool: 'write_file',
    args: 'path="src/uart_task.c"',
    result: 'uart_rx_task created: USART2 DMA circular, 256-byte ring buffer, FreeRTOS stream buffer handoff.',
  },
  {
    role: 'assistant',
    tool: 'run_build',
    args: 'target="STM32F446RE" optimisation="Os"',
    result: 'Build OK. .text 15 344 B, .bss 1 280 B. cppcheck: 0 errors. Flash: firmware.hex.',
  },
  {
    role: 'assistant',
    text: 'Done. uart_rx_task added: USART2 DMA circular at 115 200 baud, 256-byte ring buffer. Stream buffer shared with ctrl_task. Build clean — .hex and .elf ready to flash. Both .hex and .elf are universal interchange formats any debugger accepts.',
  },
]

function ChatTranscript() {
  return (
    <section className="relative border-t border-ink-900 bg-gradient-to-b from-ink-950 to-ink-900/30">
      <div className="mx-auto max-w-4xl px-6 py-12 lg:py-14">
        <div className="max-w-2xl mb-8">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-edge">
            In practice
          </p>
          <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
            Peripheral to .hex in five turns.
          </h2>
          <p className="mt-3 text-ink-300 leading-relaxed">
            Real tool calls — search_kerf_docs, read_file, write_file,
            run_build — from the kerf-firmware module surface.
          </p>
        </div>

        <div className="rounded-2xl border border-ink-800 bg-ink-950/70 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/60">
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="w-2.5 h-2.5 rounded-full bg-ink-700" />
            <span className="ml-2 font-mono text-xs text-ink-500">src/main.c — kerf chat</span>
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
                      <span className="text-[10px] uppercase tracking-widest text-cyan-edge border border-cyan-edge/30 rounded px-1.5 py-0.5">
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
                  <span className="mt-1 w-5 h-5 rounded-full bg-cyan-edge/20 border border-cyan-edge/30 grid place-items-center text-cyan-edge shrink-0">
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
        <div className="rounded-2xl border border-cyan-edge/20 bg-cyan-edge/5 p-6 lg:p-8">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-cyan-edge mb-2">
            Standard interchange
          </p>
          <h3 className="font-display text-xl sm:text-2xl font-semibold tracking-tight text-ink-100 mb-3">
            Both produce .hex and .elf — every programmer reads them.
          </h3>
          <p className="text-sm text-ink-300 leading-relaxed max-w-2xl">
            Whether you flash from Kerf, hand the .hex to a production
            programmer, or load the .elf into GDB on a JTAG probe — the
            interchange formats are universal. No vendor-specific image
            format, no proprietary flashing protocol required.
          </p>
          <ul className="mt-4 flex flex-wrap gap-3">
            {['.hex (Intel HEX)', '.elf (DWARF debug)', '.bin (raw binary)', 'SPEF via linker map', 'Unified Kconfig'].map((fmt) => (
              <li
                key={fmt}
                className="inline-flex items-center gap-1.5 rounded-md border border-cyan-edge/30 bg-cyan-edge/5 px-2.5 py-1 font-mono text-xs text-cyan-edge"
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
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-cyan-edge">
              Open + scriptable
            </p>
            <h2 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
              kerf-sdk on PyPI.
              <br />
              <span className="text-ink-300">MIT root.</span>
            </h2>
            <p className="mt-4 text-ink-300 leading-relaxed">
              Every firmware capability is accessible through the{' '}
              <code className="text-cyan-edge font-mono text-sm">kerf-sdk</code>{' '}
              Python package on PyPI. Run build matrices across toolchain
              versions and target families from a script or CI pipeline.
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
              <span className="ml-2 font-mono text-xs text-ink-500">ci_build.py</span>
            </div>
            <pre className="p-4 text-xs font-mono text-ink-300 leading-relaxed overflow-x-auto">
{`import kerf_sdk as kerf

client = kerf.Client()
project = client.projects.get("motor_ctrl")

targets = ["STM32F446RE", "STM32H743ZI", "RP2040"]

for target in targets:
    result = project.firmware.run_build(
        target=target,
        optimisation="Os",
    )
    print(f"{target}: {result.size_text} B text")
    assert result.errors == 0

# export .hex for production flashing
project.firmware.export_hex(out="./release/")`}
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
            className="absolute -right-32 -top-32 w-96 h-96 rounded-full bg-cyan-edge/[0.05] blur-3xl"
          />
          <div className="relative flex flex-col lg:flex-row lg:items-center lg:justify-between gap-5">
            <div>
              <h2 className="font-display text-3xl sm:text-4xl font-semibold tracking-[-0.02em]">
                Flash your first firmware.
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

export default function Firmware() {
  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      <Header />
      <Hero />
      <DomainSwitcher active="firmware" />
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
