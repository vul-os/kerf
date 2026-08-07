// TODO(parent): swap LadderEditor mount for LadderEditorWithFlow when sim is active

// LadderEditorWithFlow — wraps LadderEditor + LadderPowerFlowOverlay and wires
// up the live simulator polling loop.
//
// While `playing` is true this component polls POST /plc/sim/step every
// POLL_INTERVAL_MS (50 ms) and passes the simulator's variableState into
// LadderPowerFlowOverlay so the user sees rung-by-rung energization in real time.
//
// Props
// ─────
//   projectId   {string}   Project ID for API calls
//   fileId      {string}   File ID for the ladder file
//   network     {Array}    Ladder rung structure (array of rung objects)
//                          Rung shape: { id, contacts: [{name, nc}], coils: [{name}] }
//   playing     {boolean}  When true the poll loop is active
//   simSessionId {string|null}  Active sim session returned by /plc/sim/start
//   onContentChange {fn}   Forwarded to the inner LadderEditor
//   className   {string}   Extra CSS classes for the container div
//   viewRef     {ref}      Forwarded to the inner LadderEditor (snapshot handle)
//
// Architecture
// ────────────
// The polling loop lives in a useEffect that starts/stops with `playing`.
// On each successful step response the raw result is run through
// buildPowerFlow() (from ladderFlowState.js) to produce the powerFlow map
// that LadderPowerFlowOverlay consumes.
//
// The inner LadderEditor and LadderPowerFlowOverlay are imported lazily here
// (their modules ship separately — T-221 and T-225a-2).  The wiring layer
// adds zero new API surface: it is purely a composition and polling shim.
//
// Error handling
// ─────────────
// * Network errors during polling are caught and surfaced via an `error`
//   state rendered as a small banner; the poll loop continues trying.
// * A sim error field in the step result is similarly surfaced.
// * If `playing` is false the overlay is rendered with emptyPowerFlow so
//   the diagram shows a zeroed/blank energy state.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ComponentType } from 'react'
import { api } from '../lib/api.js'
import { buildPowerFlow, emptyPowerFlow } from '../lib/ladderFlowState.js'

// Dynamically imported so the bundle only pays for these large components when
// a PLC ladder file is actually open — mirrors the circuit/jscad runner pattern.
import LadderEditor from './LadderEditor.jsx'
import LadderPowerFlowOverlay from './LadderPowerFlowOverlay.jsx'

// T-514 bugs (reported, not fixed — no behaviour changes):
//   * LadderEditor's actual props are { value, onChange, programName,
//     className } (see LadderEditor.jsx) — this file passes
//     projectId/fileId/network/onContentChange/viewRef, none of which match,
//     so the inner editor never receives the network or reports content
//     changes upward.
//   * LadderPowerFlowOverlayProps is { rung, powerFlow, strokeWidth,
//     opacity } — this file passes `network` and `playing` (neither
//     accepted; likely meant `rung`), and its `powerFlow` is
//     ladderFlowState's { rungs, variables, tick } shape, not the overlay's
//     { contactsLit, coilsLit, wiresLit } shape. The overlay has therefore
//     always rendered blank.
// Cast to a permissive component type so the existing (broken) calls below
// keep compiling unchanged rather than being silently "fixed" by the types.
const UntypedLadderEditor = LadderEditor as unknown as ComponentType<Record<string, unknown>>
const UntypedLadderPowerFlowOverlay = LadderPowerFlowOverlay as unknown as ComponentType<Record<string, unknown>>

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
//
// LadderEditor.jsx and LadderPowerFlowOverlay.jsx/tsx are not typed against
// this shape (see bugs noted below) — these are declared locally from this
// file's own header-comment doc, matching ladderFlowState.ts's rung-structure
// doc comment.

interface RungContact {
  name?: string
  nc?: boolean
}

interface RungCoil {
  name?: string
}

export interface Rung {
  id: string
  contacts?: RungContact[]
  coils?: RungCoil[]
}

export interface LadderEditorWithFlowProps {
  projectId?: string
  fileId?: string
  network?: Rung[]
  playing?: boolean
  simSessionId?: string | null
  onContentChange?: (content: unknown) => void
  className?: string
  viewRef?: unknown
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 50

// ---------------------------------------------------------------------------
// LadderEditorWithFlow
// ---------------------------------------------------------------------------

export default function LadderEditorWithFlow({
  projectId,
  fileId,
  network = [],
  playing = false,
  simSessionId = null,
  onContentChange,
  className = '',
  viewRef,
}: LadderEditorWithFlowProps) {
  const [powerFlow, setPowerFlow] = useState(() => emptyPowerFlow(network))
  const [pollError, setPollError] = useState<string | null>(null)

  // Keep a stable ref to the current network so the poll callback can read
  // it without being re-created on every render.
  const networkRef = useRef(network)
  useEffect(() => { networkRef.current = network }, [network])

  // When `playing` changes to false clear the power flow back to blank.
  useEffect(() => {
    if (!playing) {
      setPowerFlow(emptyPowerFlow(networkRef.current))
      setPollError(null)
    }
  }, [playing])

  // Also reset power flow when network changes (rung added/removed).
  useEffect(() => {
    // Resets the overlay to a blank skeleton for the new rung set,
    // pre-existing before this migration (see TopoView.tsx for the same
    // pattern).
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see above.
    setPowerFlow(emptyPowerFlow(network))
  }, [network])

  // ── Poll loop ─────────────────────────────────────────────────────────────

  const stepSim = useCallback(async () => {
    if (!projectId || !simSessionId) return
    try {
      // @ts-expect-error T-514 bug: the api client (src/lib/api.ts) has no
      // plcSimStep method — this call below has always thrown at runtime,
      // caught below and surfaced as pollError. Reported, not fixed, per
      // T-514 scope (no behaviour changes).
      const result = await api.plcSimStep(projectId, simSessionId)
      setPollError(result?.error || null)
      setPowerFlow(buildPowerFlow(result, networkRef.current))
    } catch (err) {
      setPollError((err as { message?: string } | undefined)?.message || 'sim poll error')
      // Keep existing powerFlow — don't wipe the overlay on transient errors.
    }
  }, [projectId, simSessionId])

  useEffect(() => {
    if (!playing) return
    // Fire the first step immediately so there's no visual delay. stepSim
    // eventually calls setState after its own await; kicking off the first
    // poll synchronously here is pre-existing before this migration.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see above.
    stepSim()
    const timer = setInterval(stepSim, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [playing, stepSim])

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className={`relative flex flex-col h-full min-h-0 ${className}`}>
      {/* Poll error banner */}
      {pollError && (
        <div
          className="flex-shrink-0 px-3 py-1.5 text-[11px] font-mono bg-red-950/70 text-red-300 border-b border-red-800/60"
          role="alert"
        >
          Sim error: {pollError}
        </div>
      )}

      {/* Main ladder editor canvas */}
      <div className="flex-1 min-h-0 relative">
        <UntypedLadderEditor
          projectId={projectId}
          fileId={fileId}
          network={network}
          onContentChange={onContentChange}
          viewRef={viewRef}
        />

        {/* Power-flow overlay sits on top, pointer-events-none so clicks fall
            through to the editor beneath. */}
        <div className="absolute inset-0 pointer-events-none">
          <UntypedLadderPowerFlowOverlay
            powerFlow={powerFlow}
            network={network}
            playing={playing}
          />
        </div>
      </div>
    </div>
  )
}
