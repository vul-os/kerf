import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'
import { listDirty } from './lib/localStash.js'

// ── L1 stash: beforeunload guard ──────────────────────────────────────────────
// Fire the browser "unsaved changes" prompt ONLY when L1 has dirty entries.
// Browsers no longer honour custom messages; just triggering preventDefault
// is enough to show the native dialog.
//
// Note: the T-309 autosave wiring (editContent → schedulerMarkDirty → stash)
// writes to IDB synchronously before the network round-trip, so any keystroke
// that didn't make it to the server will already have an IDB entry here.
// The listDirty() check below catches those entries.
window.addEventListener('beforeunload', (event) => {
  listDirty().then((dirty) => {
    if (dirty.length > 0) {
      event.preventDefault()
    }
  })
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
