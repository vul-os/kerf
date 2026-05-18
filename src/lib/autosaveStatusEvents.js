// autosaveStatusEvents — singleton EventTarget that carries autosave lifecycle
// events to any subscriber (e.g. AutosaveStatus.jsx).
//
// Events emitted (CustomEvent, detail: { workspaceId, filePath }):
//   dirty   — a file has been marked dirty (edit received)
//   saving  — a flush is about to hit the server
//   saved   — server returned 2xx; file is persisted
//   error   — flush failed; will retry
//
// Consumers:
//   autosaveStatusEvents.addEventListener('saved', handler)
//   autosaveStatusEvents.removeEventListener('saved', handler)

class AutosaveStatusBus extends EventTarget {
  emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }))
  }
}

export const autosaveStatus = new AutosaveStatusBus()
