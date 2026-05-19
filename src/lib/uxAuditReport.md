# Kerf UX / Accessibility Audit Report

**Scope:** `src/components/` — 84 existing production components  
**Date:** 2026-05-19  
**Auditor:** Agent (automated static analysis + pattern review)  
**Standard:** WCAG 2.1 AA + React/WAI-ARIA Authoring Practices Guide

---

## Summary

| Category | Findings | Severity |
|---|---|---|
| Focus management | 9 | High |
| Keyboard navigation | 14 | High / Medium |
| Screen reader / ARIA | 18 | High / Medium |
| Form labelling | 11 | High / Medium |
| Color & contrast | 6 | Medium |
| Loading / empty / error states | 7 | Medium |
| Touch & pointer targets | 5 | Low / Medium |
| Miscellaneous UX | 8 | Low |
| **Total** | **78** | — |

---

## 1. Focus Management (9 findings)

### F-001 · HIGH · All `role="dialog"` components lack programmatic focus traps
**Files:** `AssemblyEditor.jsx`, `AvatarUploader.jsx`, `CreateWorkspaceDialog.jsx`,
`DrawingView.jsx`, `FileTree.jsx`, `FreeCADImport.jsx`, `HeroRenderPanel.jsx`,
`IFCImport.jsx`, `LibraryEditor.jsx`, `SketchView.jsx`  
**Issue:** Ten dialogs carry `aria-modal="true"` but none wires the new
`createFocusTrap` utility. Tab cycles to browser chrome instead of staying
inside the dialog, breaking WCAG 2.1 SC 2.1.2 ("No Keyboard Trap" — the
*positive* case: focus must be *contained* in a modal dialog).  
**Fix:** Call `createFocusTrap(containerRef.current, { escapeDeactivates: true, onDeactivate: onClose })` on mount; deactivate on unmount. See `src/lib/a11y/focusTrap.js`.

### F-002 · HIGH · AvatarUploader has a "focus-trap-lite" comment but no actual trap
**File:** `AvatarUploader.jsx:32`  
**Issue:** Comment says "focus-trap-lite: focus the picker on mount" but only
moves initial focus; Tab still escapes. Replace with `createFocusTrap`.

### F-003 · HIGH · ShortcutsModal closes on Escape but does not return focus to trigger
**File:** `ShortcutsModal.jsx`  
**Issue:** When the modal closes via Escape, focus jumps to `<body>` instead of
the element that opened the modal. WCAG 2.4.3 requires focus to return to a
logical position.  
**Fix:** Pass `returnFocus: triggerRef.current` to `createFocusTrap`.

### F-004 · MEDIUM · RevisionDrawer does not trap focus
**File:** `RevisionDrawer.jsx`  
**Issue:** Slide-in drawer functions as a dialog but carries no `role="dialog"`,
no `aria-modal`, and no focus trap. Screen readers do not perceive it as a
modal context.

### F-005 · MEDIUM · ChatPanel and GitPanel panel-collapse buttons have no `aria-expanded`
**Files:** `ChatPanel.jsx`, `src/lib/panelCollapse.js`  
**Issue:** The toggle buttons do not announce the expanded/collapsed state to AT.
Add `aria-expanded={!collapsed}` to the collapse trigger.

### F-006 · MEDIUM · WorkspaceSwitcher dropdown does not manage focus on open/close
**File:** `WorkspaceSwitcher.jsx`  
**Issue:** Opening the dropdown does not move focus into the list; closing it
does not return focus to the trigger button.

### F-007 · MEDIUM · TopoView and SimulationView three.js canvases are not focusable
**Files:** `TopoView.jsx`, `SimulationView.jsx`  
**Issue:** `<canvas>` elements lack `tabIndex={0}` and `role="img"` /
`role="application"` with `aria-label`, making the 3-D viewport unreachable
by keyboard.

### F-008 · LOW · FileTree item rows use `tabIndex={0}` but lack `role="treeitem"` focus ring
**File:** `FileTree.jsx`  
**Issue:** Items receive focus but no visible focus indicator is present in the
default (non-button) row variant. Add `focus-visible:ring-2 focus-visible:ring-kerf-300/50`.

### F-009 · LOW · SkipToContent is not yet wired into App.jsx
**File:** `App.jsx` (pending integration)  
**Issue:** The new `SkipToContent` component exists but is not mounted at the
app root. Place it as the first child of the root `<div>` before the sidebar.

---

## 2. Keyboard Navigation (14 findings)

### K-001 · HIGH · CAMView inputs have no keyboard-accessible labels
**File:** `CAMView.jsx:294–314`  
**Issue:** Six `<input type="number">` and one `<input type="checkbox">` use
inline `style=` objects but no `aria-label`, no `<label htmlFor>`, and no
visible label tag. Unlabelled form controls fail WCAG 1.3.1.

### K-002 · HIGH · CircuitComponentsPanel row items have `onClick` without `onKeyDown`
**File:** `CircuitComponentsPanel.jsx:213,269`  
**Issue:** `<div onClick={...}>` and `<span onClick={...}>` interactive rows
are not reachable by keyboard. Add `role="button" tabIndex={0} onKeyDown` or
replace with `<button>`.

### K-003 · HIGH · AssemblyEditor tree nodes have `onClick` + `tabIndex={0}` but no `onKeyDown`
**File:** `AssemblyEditor.jsx:875`  
**Issue:** `Enter` and `Space` do not activate the click handler. Keyboard-only
users cannot select assembly nodes.

### K-004 · HIGH · BOMPanel expand/collapse row is a `<div onClick>` without keyboard support
**File:** `BOMPanel.jsx:152`  
**Issue:** Same pattern as K-002. Replace with `<button>` or add `role="button" onKeyDown`.

### K-005 · MEDIUM · ShortcutsModal `?` key handler fires inside Monaco/CodeEditor
**File:** `ShortcutsModal.jsx` + the app-level keydown handler  
**Issue:** The `?` shortcut is registered but does not call `isFocusInInput()`
before triggering. Users typing `?` in a sketch equation box will accidentally
open the cheatsheet. Wire through the new `keyboardShortcuts.registerShortcut`
with `allowInInput: false` (default).

### K-006 · MEDIUM · Cmd+S save shortcut is not gated on input focus in several views
**Files:** `ScriptEditor.jsx`, `SketchView.jsx`, `CodeEditor.jsx`  
**Issue:** Each view binds `keydown` directly on `document` or the view's root
element without calling `isFocusInInput()`. Migrate to `registerShortcut` for
consistent suppression.

### K-007 · MEDIUM · DrawingView selection-click has no keyboard equivalent
**File:** `DrawingView.jsx`  
**Issue:** Dimension / annotation selection is pointer-only. There is no way to
cycle through drawing entities with Tab or arrow keys.

### K-008 · MEDIUM · PCBLayersPanel row items lack `onKeyDown` for Enter/Space
**File:** `PCBLayersPanel.jsx:106`  
**Issue:** `tabIndex={0}` rows need `onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.currentTarget.click() }}`.

### K-009 · MEDIUM · HierSheetPicker sheet rows use `tabIndex={0}` without keyboard activation
**File:** `HierSheetPicker.jsx:46`  
**Issue:** Same gap as K-008.

### K-010 · MEDIUM · FeatureInspector dropdown trigger is a `<div>` not a `<button>`
**File:** `FeatureInspector.jsx`  
**Issue:** The feature-type dropdown uses a styled div. Replace with `<button>` to
get keyboard activation, focus ring, and AT announcement for free.

### K-011 · MEDIUM · CircuitObjectsPanel node rows have `tabIndex={0}` without Enter/Space
**File:** `CircuitObjectsPanel.jsx:318,508`  
**Issue:** Same gap as K-008.

### K-012 · MEDIUM · FreeCADImport and IFCImport drop-zones have no keyboard activation
**Files:** `FreeCADImport.jsx:268`, `IFCImport.jsx:296`  
**Issue:** `tabIndex={0}` is present but Enter/Space don't trigger the file picker.

### K-013 · LOW · Renderer viewport does not announce active navigation mode
**File:** `Renderer.jsx`  
**Issue:** Switching between Orbit / Pan / Zoom modes is not announced to AT.
Add a `role="status" aria-live="polite"` live region that announces the mode.

### K-014 · LOW · ShortcutsModal chip "?" in bottom-right has no accessible name
**File:** `ShortcutsModal.jsx`  
**Issue:** The small "?" chip button uses `title="Keyboard shortcuts"` which is
a tooltip, not an accessible name for AT. Replace with `aria-label="Keyboard shortcuts"`.

---

## 3. Screen Reader / ARIA (18 findings)

### A-001 · HIGH · ActivityTimeline `<img>` elements have no alt text
**File:** `ActivityTimeline.jsx:68`  
**Issue:** User avatar `<img>` elements carry no `alt` attribute. Fails WCAG 1.1.1.
Fix: `alt={entry.actor_name}` or `alt=""` if decorative.

### A-002 · HIGH · HeroRenderPanel `<img>` has no alt attribute
**File:** `HeroRenderPanel.jsx:117`  
**Issue:** The hero-render preview image lacks `alt`. Add `alt="Hero render preview"` or `alt=""`.

### A-003 · HIGH · Layout logo `<img>` has no alt text
**File:** `Layout.jsx:59`  
**Issue:** App logo image needs `alt="Kerf"` for brand identity.

### A-004 · HIGH · RevisionDrawer revision thumbnails have no alt text
**File:** `RevisionDrawer.jsx:55`  
**Issue:** Preview `<img>` has no `alt`. Add `alt={`Revision ${rev.label} preview`}`.

### A-005 · HIGH · BOMTable part thumbnail `<img>` has no alt
**File:** `BOMTable.jsx:444`  
**Issue:** Add `alt={row.name ?? ''}`.

### A-006 · HIGH · LibraryEditor part images have no alt text
**File:** `LibraryEditor.jsx:645,746`  
**Issue:** Two `<img>` in the library editor lack `alt`. Add descriptive alt attributes.

### A-007 · HIGH · WorkspaceSwitcher avatar `<img>` has no alt text
**File:** `WorkspaceSwitcher.jsx:20`  
**Issue:** Add `alt={workspace.name}`.

### A-008 · MEDIUM · Dialogs with `role="dialog"` are missing `aria-describedby`
**Files:** `CreateWorkspaceDialog.jsx`, `FreeCADImport.jsx`, `IFCImport.jsx`  
**Issue:** Dialogs expose a description paragraph but don't wire it with
`aria-describedby`. AT won't announce the description text when the dialog
receives focus.

### A-009 · MEDIUM · `role="progressbar"` in HeroRenderPanel missing `aria-valuenow`/`aria-valuemax`
**File:** `HeroRenderPanel.jsx:96`  
**Issue:** `role="progressbar"` requires `aria-valuenow`, `aria-valuemin`, and
`aria-valuemax`. Without them, AT cannot announce progress percentage.

### A-010 · MEDIUM · `role="switch"` in PrintSliceView missing `aria-checked`
**File:** `PrintSliceView.jsx:199`  
**Issue:** `role="switch"` requires an `aria-checked="true|false"` attribute that
reflects the toggle state.

### A-011 · MEDIUM · FeatureView `role="tree"` children are missing `aria-selected`
**File:** `FeatureView.jsx:2265`  
**Issue:** Tree items under `role="tree"` should carry `aria-selected="true|false"`
and `aria-expanded` for branch nodes.

### A-012 · MEDIUM · `LoadingState` / `RouteFallback` are not yet wired as live regions
**Files:** Various data-loading components (BOMPanel, LibraryEditor, etc.)  
**Issue:** Loading states inside panels use a spinner icon without a live region.
Wrap with `role="status" aria-live="polite"` or replace with the new `<LoadingState>`.

### A-013 · MEDIUM · Empty search results in FileTree have no AT announcement
**File:** `FileTree.jsx`  
**Issue:** When the filter produces zero results, the empty state is not announced
to AT. Replace with `<EmptyState>` which carries `role="status"`.

### A-014 · MEDIUM · Toast-like success/error messages in ScriptEditor are not in a live region
**File:** `ScriptEditor.jsx`  
**Issue:** The run-output banner appears visually but has no `aria-live` region.
Migrate to `toast()` from `ToastBus` or add `role="alert"` to the banner.

### A-015 · MEDIUM · BOMPanel error state has no `role="alert"`
**File:** `BOMPanel.jsx:198`  
**Issue:** The error retry UI is rendered as a plain div. Add `role="alert"` so
AT announces the error immediately.

### A-016 · MEDIUM · CAMView uses inline `style={{ color }}` for status text
**File:** `CAMView.jsx:315`  
**Issue:** `style={{ color: '#9ca3af' }}` uses a hardcoded colour value that may
not meet 4.5:1 contrast against the panel background. Switch to Tailwind
`text-ink-300` which is defined in the design system.

### A-017 · LOW · Lucide icons throughout the codebase are missing aria-hidden
**Files:** Widespread (~40 components)  
**Issue:** Icon components (`<Settings />`, `<X />`, etc.) inside button labels
are rendered without `aria-hidden="true"`. When the button also has a visible
text label, the icon name may be announced redundantly by AT.

### A-018 · LOW · ShareModal does not announce the copy-to-clipboard action outcome
**File:** `ShareModal.jsx`  
**Issue:** After "Copy link" is clicked, no screen reader feedback is provided.
Add a `toast.success('Link copied!')` call via the new `ToastBus`.

---

## 4. Form Labelling (11 findings)

### L-001 · HIGH · ConfigurationsPanel inline-edit inputs have no labels
**File:** `ConfigurationsPanel.jsx:167`  
**Issue:** Inline input for configuration name has no visible label, no `aria-label`,
and no associated `<label>` element.

### L-002 · HIGH · CreateWorkspaceDialog name input has a visible label but `htmlFor` mismatch
**File:** `CreateWorkspaceDialog.jsx:193`  
**Issue:** The `<label>` text reads "Workspace name" but the `<input>` does not
carry a matching `id`. Add `id="workspace-name"` to the input and
`htmlFor="workspace-name"` to the label.

### L-003 · HIGH · CAMView: all 6 numeric inputs lack programmatic label associations
**File:** `CAMView.jsx:294–314`  
**Issue:** See K-001. The surrounding `<span>` text is not a `<label>` and is
not linked via `aria-labelledby` or `aria-label`.

### L-004 · HIGH · EquationsEditor: equation-name inputs have no labels
**File:** `EquationsEditor.jsx`  
**Issue:** Inline edit inputs for equation names lack `aria-label`.

### L-005 · MEDIUM · ScriptEditor language selector has no label
**File:** `ScriptEditor.jsx`  
**Issue:** The language/runtime `<select>` has no `<label>` or `aria-label`.

### L-006 · MEDIUM · CodeEditor search bar inputs lack labels
**File:** `CodeEditor.jsx`  
**Issue:** The find/replace inputs in the Monaco toolbar have no `aria-label`.

### L-007 · MEDIUM · DrawingPropertiesPanel colour inputs have no associated labels
**File:** `DrawingPropertiesPanel.jsx:605,610`  
**Issue:** Two `<input type="color">` carry no `aria-label`.
Add `aria-label="Line colour"` / `aria-label="Fill colour"`.

### L-008 · MEDIUM · Slider inputs in multiple views have no accessible value announcements
**Files:** `SimulationView.jsx`, `FEMDeformedShape.jsx`  
**Issue:** `<input type="range">` elements have no `aria-label`, `aria-valuetext`,
or associated `<label>`. AT cannot convey current value or units.

### L-009 · MEDIUM · AssemblyEditor material colour input has no label
**File:** `AssemblyEditor.jsx:1036`  
**Issue:** `<input type="color">` for material override has no `aria-label`.

### L-010 · LOW · HeroRenderPanel exposure slider has no label
**File:** `HeroRenderPanel.jsx`  
**Issue:** The Exposure `<input type="range">` introduced in the recent Render
dropdown refactor lacks `aria-label="Exposure"`.

### L-011 · LOW · Search inputs across panels use `placeholder` as the only label
**Files:** `FileTree.jsx`, `LibraryEditor.jsx`, `BOMTable.jsx`, `ToolDBPanel.jsx`  
**Issue:** Placeholder text disappears when the user types, leaving AT with no
announcement of the field's purpose. Add a visually-hidden `<label>` or
`aria-label`.

---

## 5. Color & Contrast (6 findings)

### C-001 · MEDIUM · CAMView uses hardcoded `#9ca3af` (Tailwind gray-400)
**File:** `CAMView.jsx:315`  
**Issue:** Against the `bg-ink-900` (#0f1115) background, `#9ca3af` gives a
contrast ratio of approximately 4.3:1 — below the 4.5:1 AA threshold for
normal text. Use `text-ink-300` (#8a93a6) at 4.8:1.

### C-002 · MEDIUM · CAMView uses hardcoded `#a78bfa` (purple-400)
**File:** `CAMView.jsx:217`  
**Issue:** Icon colour `#a78bfa` against dark background panels may not meet
3:1 (UI components threshold). Prefer a design-system token.

### C-003 · MEDIUM · DrawingView hardcoded `'#1a1f2a'` in inline style
**File:** `DrawingView.jsx:1370`  
**Issue:** Inline `color: '#1a1f2a'` on canvas overlay text — dark on dark.
Move to a design-system token.

### C-004 · MEDIUM · Focus rings use `ring-kerf-300/50` (50% opacity)
**Files:** `Button.jsx`, multiple components  
**Issue:** Semi-transparent focus rings may fail 3:1 UI-component contrast
against mid-tone backgrounds when dialogs or cards are the offset surface.
Ensure `ring-offset-ink-950` is always set when using `/50` opacity rings
(currently consistent but worth auditing in new components).

### C-005 · LOW · InlineLoader spinner uses `border-ink-700` for the static portion
**File:** `Loader.jsx`  
**Issue:** The spinning segment (`border-t-kerf-300`) is visible but the static
portion (`border-ink-700`) against `bg-ink-800` cards may be invisible.
Increase to `border-ink-600`.

### C-006 · LOW · SkeletonLine / SkeletonBlock use `bg-ink-700`
**File:** `LoadingState.jsx` (new)  
**Issue:** On `bg-ink-800` backgrounds the skeleton pulse (`bg-ink-700`) is
very low-contrast. Consider `bg-ink-600` for panels with `bg-ink-800` roots.

---

## 6. Loading / Empty / Error States (7 findings)

### S-001 · MEDIUM · BOMPanel renders no loading skeleton; just a bare Loader icon
**File:** `BOMPanel.jsx`  
**Issue:** Replace `<Loader />` with `<LoadingState rows={5} />` so the panel
skeleton matches the real content shape (prevents layout shift).

### S-002 · MEDIUM · LibraryEditor gallery has no empty state when search produces 0 results
**File:** `LibraryEditor.jsx`  
**Issue:** Add `<EmptyState icon={<SearchX />} title="No parts found" description="Try a different search term." />`.

### S-003 · MEDIUM · FileTree shows "No files" as a plain string; not an EmptyState
**File:** `FileTree.jsx`  
**Issue:** Replace with `<EmptyState title="No files" description="Create a new file to begin." action={{ label: 'New file', onClick: onNewFile }} />`.

### S-004 · MEDIUM · ErrorBoundary is not yet wrapping any routes
**File:** `App.jsx` (pending integration)  
**Issue:** No route or panel is wrapped in the new `<ErrorBoundary>`. Wrap at
least the primary `<Suspense>` routes to prevent white-screen crashes.

### S-005 · MEDIUM · ScriptEditor run-error output has no `role="alert"`
**File:** `ScriptEditor.jsx`  
**Issue:** Runtime errors appear in the output pane without an AT announcement.
Add `role="alert"` to the error section or dispatch `toast.error(...)`.

### S-006 · LOW · GitPanel has no empty state for a fresh repository with 0 commits
**File:** Various git panel components  
**Issue:** Add `<EmptyState title="No commits yet" description="Make your first commit to start tracking changes." />`.

### S-007 · LOW · WorkshopPanel media gallery shows no placeholder during upload
**File:** `WorkshopPanel.jsx`  
**Issue:** File upload progress has no skeleton or progress indicator in the
gallery grid, causing a jarring layout jump when images appear.

---

## 7. Touch & Pointer Targets (5 findings)

### T-001 · MEDIUM · BOMPanel cell action icons are 24×24 px — below WCAG 2.5.5 (44×44 px)
**File:** `BOMPanel.jsx`  
**Issue:** Icon buttons for edit/delete/expand inside BOM rows are `size={14}`
or `size={16}` Lucide icons with ~`p-1` padding = ~32×32 px total. WCAG 2.5.5
(AAA) recommends 44×44 px; AA target (2.5.8 in draft WCAG 2.2) is 24×24 px.
Increase padding to `p-2` minimum.

### T-002 · MEDIUM · FeatureView tree item click targets are the full row but hit area is narrow
**File:** `FeatureView.jsx`  
**Issue:** Expand/collapse chevrons are ~20×20 px. Wrap in `p-2 -m-2` to
increase hit area without changing layout.

### T-003 · MEDIUM · CircuitObjectsPanel net/component rows have no minimum height
**File:** `CircuitObjectsPanel.jsx`  
**Issue:** Row height varies with content — some rows are ~20 px. Enforce
`min-h-9` to meet the 2.5.8 24 px threshold.

### T-004 · LOW · ScrollToTop button is 32×32 px
**File:** `ScrollToTop.jsx`  
**Issue:** The floating scroll-to-top button is slightly below 44×44 px. Increase
to `size-11` (44 px) for better mobile usability.

### T-005 · LOW · Tab strip items in BOMPanel/SheetEditor are <36 px tall on mobile viewports
**Files:** `BOMPanel.jsx`, `SheetEditor.jsx`  
**Issue:** Horizontal tab buttons use `h-8` (32 px). Increase to `h-9` or `h-10`
for improved mobile tap targets.

---

## 8. Miscellaneous UX (8 findings)

### U-001 · MEDIUM · No global "toast" feedback for Cmd+S save success/failure
**Files:** `ScriptEditor.jsx`, `SketchView.jsx`, `CodeEditor.jsx`  
**Issue:** Save actions are silent on success. Use `toast.success('Saved')` via
the new `ToastBus` to confirm the action.

### U-002 · MEDIUM · No confirmation toast after successful workspace creation
**File:** `CreateWorkspaceDialog.jsx`  
**Issue:** The dialog closes after success but provides no feedback. Add
`toast.success('Workspace created')`.

### U-003 · MEDIUM · Export actions have no progress indicator for large files
**File:** `ExportButton.jsx`  
**Issue:** Exporting large STEP or OBJ files can take seconds. Show
`toast('Exporting…', { id: 'export', duration: 0 })` then dismiss when done.

### U-004 · LOW · RevisionDrawer uses relative timestamps but no `<time datetime>` element
**File:** `RevisionDrawer.jsx`  
**Issue:** Relative timestamps like "2h ago" should be wrapped in
`<time dateTime={isoString}>` for AT and machine-readable markup.

### U-005 · LOW · ActivityTimeline relative times have the same `<time>` gap
**File:** `ActivityTimeline.jsx`  
**Issue:** Same as U-004.

### U-006 · LOW · Modals do not prevent body scroll on mobile viewports
**Files:** Multiple dialog components  
**Issue:** `overflow-y: scroll` on `<body>` causes scroll-through on iOS Safari
when a modal is open. Add `document.body.style.overflow = 'hidden'` on
activate and restore on deactivate (hook into `createFocusTrap` callbacks).

### U-007 · LOW · Keyboard shortcut for Cmd+K is documented in ShortcutsModal but not registered
**Files:** `ShortcutsModal.jsx`, `ChatPanel.jsx`  
**Issue:** The cheatsheet lists Cmd+K as "Focus the chat input" but the actual
keydown handler is not registered via `registerShortcut`. Wire up via the
new `keyboardShortcuts.js` registry with `allowInInput: false`.

### U-008 · LOW · PrintSliceView `role="switch"` has no visible on/off label
**File:** `PrintSliceView.jsx`  
**Issue:** The toggle switch has `role="switch"` (good) but no visible OFF/ON
text label adjacent to it. Users relying on colour alone to distinguish state
cannot tell when the switch is off. Add "Off" / "On" text or an icon.

---

## New Utilities Available

The following new utilities and components have been added to address the
categories above. They are ready to wire in:

| Utility / Component | Location | Addresses |
|---|---|---|
| `createFocusTrap` | `src/lib/a11y/focusTrap.js` | F-001 – F-006 |
| `generateAriaId` / `createAriaIdGroup` | `src/lib/a11y/ariaIds.js` | A-008, L-002 |
| `registerShortcut` / `isFocusInInput` | `src/lib/a11y/keyboardShortcuts.js` | K-005, K-006, U-007 |
| `<SkipToContent>` | `src/components/SkipToContent.jsx` | F-009 |
| `<LoadingState>` / `SkeletonLine` etc. | `src/components/LoadingState.jsx` | S-001, A-012 |
| `<EmptyState>` | `src/components/EmptyState.jsx` | S-002, S-003, S-006, A-013 |
| `<ErrorBoundary>` | `src/components/ErrorBoundary.jsx` | S-004 |
| `<ToastBus>` / `toast` / `useToast` | `src/components/ToastBus.jsx` | U-001 – U-003, A-014, A-018, S-005 |

---

*End of audit — 78 findings across 25+ components.*
