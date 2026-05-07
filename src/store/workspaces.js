import { create } from 'zustand'
import { api } from '../lib/api.js'

const CURRENT_KEY = 'kerf:currentWorkspaceSlug'

function loadStoredSlug() {
  try { return localStorage.getItem(CURRENT_KEY) || null } catch { return null }
}
function persistSlug(slug) {
  try {
    if (slug) localStorage.setItem(CURRENT_KEY, slug)
    else localStorage.removeItem(CURRENT_KEY)
  } catch {}
}

export const useWorkspaces = create((set, get) => ({
  workspaces: [],
  currentSlug: loadStoredSlug(),
  loading: false,
  loaded: false,
  error: null,

  loadAll: async () => {
    if (get().loading) return get().workspaces
    set({ loading: true, error: null })
    try {
      const list = await api.listWorkspaces()
      const arr = Array.isArray(list) ? list : (list?.workspaces || [])
      set({ workspaces: arr, loading: false, loaded: true })
      const cur = get().currentSlug
      if (arr.length > 0 && (!cur || !arr.some((w) => w.slug === cur))) {
        get().setCurrent(arr[0].slug)
      }
      return arr
    } catch (err) {
      set({ loading: false, loaded: true, error: err?.message || String(err) })
      return []
    }
  },

  setCurrent: (slug) => {
    persistSlug(slug)
    set({ currentSlug: slug })
  },

  create: async ({ name, slug }) => {
    const created = await api.createWorkspace({ name, slug })
    set((s) => ({ workspaces: [created, ...s.workspaces] }))
    get().setCurrent(created.slug)
    return created
  },
}))

export function currentWorkspace() {
  const { workspaces, currentSlug } = useWorkspaces.getState()
  return workspaces.find((w) => w.slug === currentSlug) || null
}
