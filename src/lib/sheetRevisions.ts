/**
 * sheetRevisions.ts — pure JS revision tracking for .sheet.json files.
 * Each sheet may carry a `revisions` array alongside its `titleblock`.
 *
 * Schema extension (partial):
 * {
 *   "revisions": [
 *     { "letter": "A", "date": "2026-05-14", "description": "Initial issue", "by": "Jane Smith" }
 *   ]
 * }
 *
 * NOTE: none of this module's exports are imported anywhere outside its own test file
 * (verified via repo-wide grep during the T-505 migration) — `sheetFrames.ts`'s title-block
 * layouts have a `sheet_number`/`revision` cell but no drawing UI wires up add/validate/history
 * for a revisions list. Reported as dead code, left as found per migration convention.
 */

export interface Revision {
  letter: string
  date?: string
  description?: string
  by?: string
}

export interface RevisionSheet {
  revisions?: Revision[]
  titleblock?: {
    revision?: string
    [key: string]: unknown
  }
  [key: string]: unknown
}

export interface ValidateRevisionListResult {
  ok: boolean
  errors: string[]
}

/**
 * Return the next alphabetic revision letter after the given list.
 * A → B → … → Z → AA → AB → … → AZ → BA → …
 */
function _nextLetter(existing: string): string {
  if (!existing || existing.length === 0) return "A";

  const MAX_CHAR = "Z".charCodeAt(0);

  const chars = existing.toUpperCase().split("");

  for (let i = chars.length - 1; i >= 0; i--) {
    const code = chars[i].charCodeAt(0);
    if (code < MAX_CHAR) {
      chars[i] = String.fromCharCode(code + 1);
      return chars.join("");
    }
    chars[i] = "A";
  }

  return "A".repeat(chars.length + 1);
}

/**
 * Append a new revision entry to sheet.revisions.
 * @returns the appended revision object
 */
function addRevision(sheet: RevisionSheet, { letter, date, description, by }: Partial<Revision>): Revision {
  if (!sheet.revisions) sheet.revisions = [];
  const entry: Revision = { letter: (letter || "").toUpperCase(), date: date || "", description: description || "", by: by || "" };
  sheet.revisions.push(entry);
  return entry;
}

/**
 * Return the next revision letter that should be assigned.
 * @returns next available letter
 */
function nextRevisionLetter(sheet: RevisionSheet): string {
  const revs = (sheet.revisions || []).map(r => r.letter).filter(Boolean);
  if (revs.length === 0) return "A";
  revs.sort();
  return _nextLetter(revs[revs.length - 1]);
}

/**
 * Set the active revision (titleblock.revision) by letter.
 */
function setActiveRevision(sheet: RevisionSheet, letter: string): void {
  if (!sheet.titleblock) sheet.titleblock = {};
  sheet.titleblock.revision = (letter || "").toUpperCase();
}

/**
 * Return the revision history sorted by letter order.
 */
function getRevisionHistory(sheet: RevisionSheet): Revision[] {
  if (!sheet.revisions || !Array.isArray(sheet.revisions)) return [];
  return [...sheet.revisions].sort((a, b) => a.letter.localeCompare(b.letter, undefined, { sensitivity: "base" }));
}

/**
 * Validate the revisions array:
 * - must be an array
 * - each entry must have a letter
 * - no duplicate letters
 * - active revision (titleblock.revision) must exist in revisions list
 */
function validateRevisionList(sheet: RevisionSheet): ValidateRevisionListResult {
  const errors: string[] = [];

  if (!Array.isArray(sheet.revisions)) {
    errors.push("sheet.revisions must be an array");
    return { ok: false, errors };
  }

  const seen = new Set<string>();
  for (const rev of sheet.revisions) {
    if (!rev.letter) {
      errors.push("Each revision entry must have a 'letter' field");
    } else {
      const l = rev.letter.toUpperCase();
      if (seen.has(l)) errors.push(`Duplicate revision letter: ${rev.letter}`);
      seen.add(l);
    }
  }

  const active = sheet.titleblock?.revision;
  if (active) {
    const activeUpper = active.toUpperCase();
    if (!seen.has(activeUpper)) {
      errors.push(`Active revision '${active}' is not in the revisions list`);
    }
  }

  return { ok: errors.length === 0, errors };
}

export {
  addRevision,
  nextRevisionLetter,
  setActiveRevision,
  getRevisionHistory,
  validateRevisionList,
  _nextLetter,
};
