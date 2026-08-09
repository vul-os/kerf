# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: jscad.spec.ts >> JSCAD editor (local mode) >> add .jscad file — 3D canvas renders a mesh
- Location: specs/jscad.spec.ts:45:7

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('button', { name: 'New', exact: true })
Expected: visible
Timeout: 20000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 20000ms
  - waiting for getByRole('button', { name: 'New', exact: true })

```

# Test source

```ts
  1   | /**
  2   |  * Page-object model for /projects/:projectId (the Editor view).
  3   |  *
  4   |  * The editor has three main panels:
  5   |  *   - File tree (left sidebar)  — FileTree.jsx
  6   |  *   - Editor/viewer (center)    — varies by file kind
  7   |  *   - Inspector (right sidebar) — FeatureInspector, chat, etc.
  8   |  *
  9   |  * Selectors are intentionally coarse (text / title) to survive minor
  10  |  * class-name refactors. Data-testid attributes are added where needed; for
  11  |  * now we use accessible names and visible text.
  12  |  */
  13  | 
  14  | import { Page, Locator, expect } from '@playwright/test'
  15  | 
  16  | export class EditorPage {
  17  |   readonly page: Page
  18  | 
  19  |   // File tree
  20  |   readonly fileTreePanel: Locator
  21  |   readonly newFileDropdownButton: Locator
  22  | 
  23  |   constructor(page: Page) {
  24  |     this.page = page
  25  | 
  26  |     this.fileTreePanel = page.locator('.bg-ink-900').first()
  27  |     // The "+ New" button in the FileTree header. Matched by role+name rather
  28  |     // than by its title attribute — the title copy has already drifted once
  29  |     // ("…import a STEP file" → "…import CAD"), silently breaking every spec
  30  |     // that calls waitForLoad().
  31  |     this.newFileDropdownButton = page.getByRole('button', {
  32  |       name: 'New',
  33  |       exact: true,
  34  |     })
  35  |   }
  36  | 
  37  |   /** Wait for the editor page to be fully loaded (file tree visible). */
  38  |   async waitForLoad() {
> 39  |     await expect(this.newFileDropdownButton).toBeVisible({ timeout: 20_000 })
      |                                              ^ Error: expect(locator).toBeVisible() failed
  40  |   }
  41  | 
  42  |   /**
  43  |    * Open the "+ New" dropdown and click a specific kind label.
  44  |    * @param kind  The label shown in the dropdown, e.g. 'Sketch', 'File', 'Drawing'
  45  |    */
  46  |   async createFile(kind: 'File' | 'Sketch' | 'Drawing' | 'Feature' | 'Assembly' | 'Part') {
  47  |     await this.newFileDropdownButton.click()
  48  |     // "+ New" opens a dialog of CreateCard tiles, each a <button> whose
  49  |     // accessible name starts with the kind label (the hint text follows).
  50  |     const dialog = this.page.getByRole('dialog', { name: 'New file' })
  51  |     await dialog.waitFor({ state: 'visible', timeout: 10_000 })
  52  |     // Each tile's accessible name is "<Kind> <hint>", e.g.
  53  |     // "File Generic .jscad code module". Anchor on the leading kind so
  54  |     // "File" doesn't also match "Folder".
  55  |     await dialog
  56  |       .getByRole('button', { name: new RegExp(`^${kind}\\b`) })
  57  |       .first()
  58  |       .click()
  59  |   }
  60  | 
  61  |   /**
  62  |    * Click a file in the file tree by its displayed name.
  63  |    */
  64  |   async openFile(name: string) {
  65  |     await this.page.getByText(name, { exact: true }).first().click()
  66  |   }
  67  | 
  68  |   /**
  69  |    * Rename a file via the tree's context menu.
  70  |    *
  71  |    * Used to reach kinds that have no "+ New" entry — BIM is one: Editor.jsx
  72  |    * routes to BIMFileView on the `.bim` extension (isBIMFile()), so a .bim is
  73  |    * authored by creating a generic file and renaming it.
  74  |    *
  75  |    * The inline input seeds with the old name, so we select-all before typing.
  76  |    */
  77  |   async renameFile(from: string, to: string) {
  78  |     // Double-click the row — FileTree's onDoubleClick puts it straight into
  79  |     // inline-rename mode (same as the context menu's "Rename (F2)").
  80  |     await this.page
  81  |       .locator('span.font-mono')
  82  |       .filter({ hasText: from })
  83  |       .first()
  84  |       .dblclick()
  85  | 
  86  |     const input = this.page.getByTestId('rename-input')
  87  |     await input.waitFor({ state: 'visible', timeout: 10_000 })
  88  |     await input.fill(to)
  89  |     await input.press('Enter')
  90  | 
  91  |     await expect(this.page.getByText(to, { exact: true }).first()).toBeVisible({
  92  |       timeout: 10_000,
  93  |     })
  94  |   }
  95  | 
  96  |   /**
  97  |    * Wait for the Monaco editor to appear and type code into it.
  98  |    * Replaces all existing content.
  99  |    */
  100 |   async typeInMonaco(code: string) {
  101 |     const container = this.page.locator('.monaco-editor').first()
  102 |     await container.waitFor({ state: 'visible', timeout: 15_000 })
  103 | 
  104 |     // Click the editor body to focus it. Do NOT focus('.monaco-editor textarea'):
  105 |     // this Monaco build uses the native EditContext API, so that textarea is a
  106 |     // vestigial node that receives nothing — focusing it silently swallows every
  107 |     // keystroke and the file saves empty.
  108 |     await container.click()
  109 |     await this.page.keyboard.press('ControlOrMeta+a')
  110 | 
  111 |     // Paste, don't type. Both keyboard.type() and keyboard.insertText() are
  112 |     // treated by Monaco as typing, so auto-indent and auto-closing brackets fire
  113 |     // and corrupt structured content — a pasted JSON doc comes back with runaway
  114 |     // indentation and a duplicated trailing `}`, which then fails to parse.
  115 |     // A clipboard paste is applied verbatim as a single edit.
  116 |     await this.page
  117 |       .context()
  118 |       .grantPermissions(['clipboard-read', 'clipboard-write'])
  119 |     await this.page.evaluate((t) => navigator.clipboard.writeText(t), code)
  120 |     await this.page.keyboard.press('ControlOrMeta+v')
  121 |   }
  122 | 
  123 |   /**
  124 |    * Wait for the Three.js canvas (used by the JSCAD renderer) to appear
  125 |    * and contain non-trivial pixel data.
  126 |    *
  127 |    * The canvas is injected by Renderer.jsx into a container div. We check
  128 |    * that at least one pixel in the canvas is non-black as a proxy for
  129 |    * "the render produced something".
  130 |    */
  131 |   async expectCanvasRendered(timeout = 30_000) {
  132 |     const canvas = this.page.locator('canvas').first()
  133 |     await expect(canvas).toBeVisible({ timeout })
  134 | 
  135 |     // Poll until a non-trivial render appears (canvas has at least one
  136 |     // non-black pixel). Playwright's evaluateHandle lets us inspect pixel data.
  137 |     await expect
  138 |       .poll(
  139 |         async () => {
```