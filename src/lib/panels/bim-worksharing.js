/**
 * bim-worksharing.js — panel-registry fragment for BIM Worksharing and
 * Federated XRef (hotlinked modules) panels.
 *
 * Worksharing panel: displays element ownership/borrow status, sync-to-central
 * button, and conflict list.  Content shape (from LLM tool results):
 *   bim_worksharing_status result → { project_id, worksets, borrows_by_user,
 *     active_borrow_count, central_element_count, last_sync_iso }
 *   bim_worksharing_sync result   → { synced_elements, pulled_elements,
 *     conflicts, released_borrows, message }
 *
 * XRef Manager panel: lists linked models with freshness status and reload
 * action.  Content shape (from LLM tool results):
 *   bim_list_xrefs result         → { refs: [{source_path, discipline,
 *     reference_origin_xyz_mm, reference_rotation_deg, last_loaded_hash}] }
 *   bim_check_xref_status result  → { status: { is_stale, status_label,
 *     num_elements, source_exists } }
 *
 * Honest note: worksharing is a checkout/borrow/sync model (matching Revit's
 * actual Worksharing mechanism), NOT live real-time co-editing.
 */

export default [
  // ── BIM: Worksharing Panel ───────────────────────────────────────────────
  {
    id: 'bim_worksharing',
    kinds: ['bim_worksharing', 'bim_worksharing_status', 'bim_worksharing_sync'],
    exts: ['.bimws'],
    label: 'BIM Worksharing',
    load: () => import('../../components/bim/WorksharingPanel.jsx'),
  },

  // ── BIM: XRef / Federated Model Manager ─────────────────────────────────
  {
    id: 'bim_xref_manager',
    kinds: ['bim_xref_manager', 'bim_xref_list', 'bim_federated'],
    exts: ['.bimxref'],
    label: 'Federated XRef Manager',
    load: () => import('../../components/bim/XRefManagerPanel.jsx'),
  },
]
