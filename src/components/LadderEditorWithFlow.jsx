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
import { api } from '../lib/api.js'
import { buildPowerFlow, emptyPowerFlow } from '../lib/ladderFlowState.js'

// Dynamically imported so the bundle only pays for these large components when
// a PLC ladder file is actually open — mirrors the circuit/jscad runner pattern.
import LadderEditor from './LadderEditor.jsx'
import LadderPowerFlowOverlay from './LadderPowerFlowOverlay.jsx'

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
}) {
  const [powerFlow, setPowerFlow] = useState(() => emptyPowerFlow(network))
  const [pollError, setPollError] = useState(null)

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
    setPowerFlow(emptyPowerFlow(network))
  }, [network])

  // ── Poll loop ─────────────────────────────────────────────────────────────

  const stepSim = useCallback(async () => {
    if (!projectId || !simSessionId) return
    try {
      const result = await api.plcSimStep(projectId, simSessionId)
      setPollError(result?.error || null)
      setPowerFlow(buildPowerFlow(result, networkRef.current))
    } catch (err) {
      setPollError(err?.message || 'sim poll error')
      // Keep existing powerFlow — don't wipe the overlay on transient errors.
    }
  }, [projectId, simSessionId])

  useEffect(() => {
    if (!playing) return
    // Fire the first step immediately so there's no visual delay.
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
        <LadderEditor
          projectId={projectId}
          fileId={fileId}
          network={network}
          onContentChange={onContentChange}
          viewRef={viewRef}
        />

        {/* Power-flow overlay sits on top, pointer-events-none so clicks fall
            through to the editor beneath. */}
        <div className="absolute inset-0 pointer-events-none">
          <LadderPowerFlowOverlay
            powerFlow={powerFlow}
            network={network}
            playing={playing}
          />
        </div>
      </div>
    </div>
  )
}
