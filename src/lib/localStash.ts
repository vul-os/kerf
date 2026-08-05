/**
 * localStash.ts — IndexedDB-backed L1 local stash for the editor working copy.
 *
 * Object store: 'stash'
 * Key:   `${workspaceId}/${filePath}`
 * Value: { bytes, mtime, flushedToL2 }
 *
 * Exposed API
 * -----------
 * stash(workspaceId, filePath, bytes)          — write entry; caller debounces
 * markFlushed(workspaceId, filePath)           — flip flushedToL2 = true
 * listDirty()                                  — all entries with flushedToL2 === false
 * reconcile(workspaceId, sendToServer)         — flush dirty entries for a workspace;
 *                                                on per-entry success, calls markFlushed
 *
 * The Zustand selector useDirtyL1Count() lives in src/stores/dirtyStore.js
 * and is notified via the _notify helper exported below.
 *
 * `listUnflushed()`'s return shape matches `UnsavedEntry` as consumed by
 * `src/store/workspace.ts` (`bytes: Uint8Array`, not `unknown`) — `src/lib`
 * must not import that type, so it's restated locally as `StashUnflushedEntry`.
 */

const DB_NAME = 'kerf-l1-stash'
const DB_VERSION = 1
const STORE_NAME = 'stash'

/** Value shape stored under each `${workspaceId}/${filePath}` key. */
interface StashValue {
  bytes: Uint8Array
  mtime: number
  flushedToL2: boolean
}

let _db: IDBDatabase | null = null
// Allow tests to inject a custom IDBFactory (e.g. fake-indexeddb).
let _idbFactory: IDBFactory | null = null

export function _setIDBFactory(factory: IDBFactory): void {
  _idbFactory = factory
}

function getIDBFactory(): IDBFactory {
  return _idbFactory ?? globalThis.indexedDB
}

function openDB(): Promise<IDBDatabase> {
  if (_db) return Promise.resolve(_db)
  return new Promise((resolve, reject) => {
    const req = getIDBFactory().open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME)
      }
    }
    req.onsuccess = () => {
      _db = req.result
      resolve(_db)
    }
    req.onerror = () => reject(req.error)
  })
}

function key(workspaceId: string, filePath: string): string {
  return `${workspaceId}/${filePath}`
}

// Callbacks registered by the dirty store so it stays in sync.
type Listener = () => void
const _listeners = new Set<Listener>()

export function _addListener(fn: Listener): () => void {
  _listeners.add(fn)
  return () => _listeners.delete(fn)
}

function _notify(): void {
  for (const fn of _listeners) fn()
}

/**
 * Write (or overwrite) a stash entry. The caller is responsible for debouncing.
 */
export async function stash(workspaceId: string, filePath: string, bytes: Uint8Array): Promise<void> {
  const db = await openDB()
  const value: StashValue = { bytes, mtime: Date.now(), flushedToL2: false }
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const req = tx.objectStore(STORE_NAME).put(value, key(workspaceId, filePath))
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  })
  _notify()
}

/**
 * Mark a specific entry as flushed to L2 (server file_revisions).
 */
export async function markFlushed(workspaceId: string, filePath: string): Promise<void> {
  const db = await openDB()
  const k = key(workspaceId, filePath)
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const getReq = store.get(k)
    getReq.onsuccess = () => {
      const existing = getReq.result as StashValue | undefined
      if (!existing) {
        resolve()
        return
      }
      const putReq = store.put({ ...existing, flushedToL2: true }, k)
      putReq.onsuccess = () => resolve()
      putReq.onerror = () => reject(putReq.error)
    }
    getReq.onerror = () => reject(getReq.error)
  })
  _notify()
}

/**
 * Read back the bytes last stashed for a given (workspaceId, filePath) pair.
 * Returns null if no entry exists or the entry has been flushed.
 */
export async function getBytes(workspaceId: string, filePath: string): Promise<Uint8Array | null> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const req = tx.objectStore(STORE_NAME).get(key(workspaceId, filePath))
    req.onsuccess = () => {
      const value = req.result as StashValue | undefined
      resolve(value ? value.bytes : null)
    }
    req.onerror = () => reject(req.error)
  })
}

/** One entry as returned by `listUnflushed()` — matches `UnsavedEntry` (minus `_error`) in src/store/workspace.ts. */
export interface StashUnflushedEntry {
  path: string
  bytes: Uint8Array
  stashed_at: number
}

/**
 * Return all unflushed entries for a specific workspace.
 * Returns an array of { path, bytes, stashed_at }, sorted ascending by stash time.
 */
export async function listUnflushed(workspaceId: string): Promise<StashUnflushedEntry[]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const store = tx.objectStore(STORE_NAME)
    const results: StashUnflushedEntry[] = []
    const req = store.openCursor()
    req.onsuccess = () => {
      const cursor = req.result
      if (!cursor) {
        // Sort ascending by stash time before returning.
        results.sort((a, b) => a.stashed_at - b.stashed_at)
        resolve(results)
        return
      }
      const k = cursor.key as string
      const slashIdx = k.indexOf('/')
      const entryWorkspaceId = k.slice(0, slashIdx)
      const value = cursor.value as StashValue
      if (entryWorkspaceId === workspaceId && value.flushedToL2 === false) {
        results.push({
          path: k.slice(slashIdx + 1),
          bytes: value.bytes,
          stashed_at: value.mtime,
        })
      }
      cursor.continue()
    }
    req.onerror = () => reject(req.error)
  })
}

/** One entry as returned by `listDirty()`. */
export interface StashDirtyEntry {
  workspaceId: string
  filePath: string
  bytes: Uint8Array
  mtime: number
}

/**
 * Return all stash entries that have not yet been flushed to L2.
 * Returns an array of { workspaceId, filePath, bytes, mtime }.
 */
export async function listDirty(): Promise<StashDirtyEntry[]> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly')
    const store = tx.objectStore(STORE_NAME)
    const results: StashDirtyEntry[] = []
    const req = store.openCursor()
    req.onsuccess = () => {
      const cursor = req.result
      if (!cursor) {
        resolve(results)
        return
      }
      const value = cursor.value as StashValue
      if (value.flushedToL2 === false) {
        // Reverse the composite key to recover workspaceId + filePath.
        const k = cursor.key as string
        const slashIdx = k.indexOf('/')
        results.push({
          workspaceId: k.slice(0, slashIdx),
          filePath: k.slice(slashIdx + 1),
          bytes: value.bytes,
          mtime: value.mtime,
        })
      }
      cursor.continue()
    }
    req.onerror = () => reject(req.error)
  })
}

/**
 * Reconcile all dirty entries for a workspace against the server.
 *
 * @param workspaceId
 * @param sendToServer  async (filePath, bytes) => void — must throw on failure
 *
 * Entries for which sendToServer resolves successfully are marked flushed.
 * Entries for which sendToServer throws are left dirty (caller can retry).
 */
export async function reconcile(
  workspaceId: string,
  sendToServer: (filePath: string, bytes: Uint8Array) => Promise<void>,
): Promise<void> {
  const dirty = await listDirty()
  const mine = dirty.filter((e) => e.workspaceId === workspaceId)
  await Promise.allSettled(
    mine.map(async (entry) => {
      try {
        await sendToServer(entry.filePath, entry.bytes)
        await markFlushed(workspaceId, entry.filePath)
      } catch {
        // Leave dirty; caller retries.
      }
    }),
  )
}

// Reset the singleton DB reference (used by tests to get a clean state).
export function _resetForTest(): void {
  _db = null
}
