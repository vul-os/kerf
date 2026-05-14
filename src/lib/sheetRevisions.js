/**
 * sheetRevisions.js — pure JS revision tracking for .sheet.json files.
 * Each sheet may carry a `revisions` array alongside its `titleblock`.
 *
 * Schema extension (partial):
 * {
 *   "revisions": [
 *     { "letter": "A", "date": "2026-05-14", "description": "Initial issue", "by": "Jane Smith" }
 *   ]
 * }
 */

/**
 * Return the next alphabetic revision letter after the given list.
 * A → B → … → Z → AA → AB → … → AZ → BA → …
 */
function _nextLetter(existing) {
  if (!existing || existing.length === 0) return "A";

  const MAX_CHAR = "Z".charCodeAt(0);
  const A_CHAR = "A".charCodeAt(0);

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

function _revIndex(sheet) {
  if (!sheet.revisions || !Array.isArray(sheet.revisions)) return -1;
  return sheet.revisions.findIndex(r => r.letter === sheet.titleblock?.revision);
}

/**
 * Append a new revision entry to sheet.revisions.
 * @param {object} sheet
 * @param {{letter: string, date: string, description: string, by: string}} opts
 * @returns {object} the appended revision object
 */
function addRevision(sheet, { letter, date, description, by }) {
  if (!sheet.revisions) sheet.revisions = [];
  const entry = { letter: (letter || "").toUpperCase(), date: date || "", description: description || "", by: by || "" };
  sheet.revisions.push(entry);
  return entry;
}

/**
 * Return the next revision letter that should be assigned.
 * @param {object} sheet
 * @returns {string} next available letter
 */
function nextRevisionLetter(sheet) {
  const revs = (sheet.revisions || []).map(r => r.letter).filter(Boolean);
  if (revs.length === 0) return "A";
  revs.sort();
  return _nextLetter(revs[revs.length - 1]);
}

/**
 * Set the active revision (titleblock.revision) by letter.
 * @param {object} sheet
 * @param {string} letter
 */
function setActiveRevision(sheet, letter) {
  if (!sheet.titleblock) sheet.titleblock = {};
  sheet.titleblock.revision = (letter || "").toUpperCase();
}

/**
 * Return the revision history sorted by letter order.
 * @param {object} sheet
 * @returns {Array<object>}
 */
function getRevisionHistory(sheet) {
  if (!sheet.revisions || !Array.isArray(sheet.revisions)) return [];
  return [...sheet.revisions].sort((a, b) => a.letter.localeCompare(b.letter, undefined, { sensitivity: "base" }));
}

/**
 * Validate the revisions array:
 * - must be an array
 * - each entry must have a letter
 * - no duplicate letters
 * - active revision (titleblock.revision) must exist in revisions list
 * @param {object} sheet
 * @returns {{ok: boolean, errors: string[]}}
 */
function validateRevisionList(sheet) {
  const errors = [];

  if (!Array.isArray(sheet.revisions)) {
    errors.push("sheet.revisions must be an array");
    return { ok: false, errors };
  }

  const seen = new Set();
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

module.exports = {
  addRevision,
  nextRevisionLetter,
  setActiveRevision,
  getRevisionHistory,
  validateRevisionList,
  _nextLetter,
};