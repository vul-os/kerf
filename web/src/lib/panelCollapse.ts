// panelCollapse — pure helpers for persisting editor panel collapsed state
// to localStorage. Shared by Editor.jsx (Chat panel + Git panel) so the
// localStorage key contract, default values, and serialisation are tested
// once rather than in-lined per panel.
//
// Convention (mirrors the existing Chat panel pattern):
//   key value '1' → collapsed  (panel hidden, canvas expands)
//   key value '0' → expanded   (panel visible)
//   key absent    → use the supplied defaultCollapsed
//
// Usage (in a React component):
//   const [collapsed, setCollapsed] = useState(
//     () => readCollapsed(CHAT_COLLAPSE_KEY, false),
//   )
//   useEffect(() => writeCollapsed(CHAT_COLLAPSE_KEY, collapsed), [collapsed])

export const CHAT_COLLAPSE_KEY = 'kerf:chatCollapsed'
export const GIT_COLLAPSE_KEY  = 'kerf:gitCollapsed'

/**
 * Read the persisted collapsed state for a panel.
 *
 * @param {string}  key              localStorage key
 * @param {boolean} defaultCollapsed Value to return when the key is absent
 * @returns {boolean}
 */
export function readCollapsed(key, defaultCollapsed) {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return defaultCollapsed
    return raw === '1'
  } catch {
    return defaultCollapsed
  }
}

/**
 * Persist the collapsed state for a panel.
 *
 * @param {string}  key       localStorage key
 * @param {boolean} collapsed Current collapsed state
 */
export function writeCollapsed(key, collapsed) {
  try {
    localStorage.setItem(key, collapsed ? '1' : '0')
  } catch {
    // localStorage unavailable (SSR, private browsing quota exceeded) — no-op.
  }
}

/**
 * Compute the CSS grid-template-columns value for the editor layout.
 *
 * The editor has three inline panes: file-tree (fixed 240 px), canvas (1fr),
 * and up to two optional right panels — Chat (380 px) and Git (384 px).
 * Each panel is only included in the template when it is not collapsed.
 *
 * @param {boolean} chatCollapsed
 * @param {boolean} gitCollapsed
 * @returns {string} Tailwind arbitrary-value class suffix, e.g. "240px_1fr_380px"
 */
export function editorGridCols(chatCollapsed, gitCollapsed) {
  const parts = ['240px', '1fr']
  if (!chatCollapsed) parts.push('380px')
  if (!gitCollapsed)  parts.push('384px')
  return parts.join('_')
}
