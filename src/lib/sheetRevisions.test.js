/**
 * sheetRevisions.test.js — vitest suite for sheet revision utilities.
 */
import { describe, it, expect } from "vitest";
import {
  addRevision,
  nextRevisionLetter,
  setActiveRevision,
  getRevisionHistory,
  validateRevisionList,
  _nextLetter,
} from "./sheetRevisions.js";

describe("nextRevisionLetter", () => {
  it("returns A for empty sheet", () => {
    expect(nextRevisionLetter({})).toBe("A");
  });

  it("returns B after A", () => {
    expect(nextRevisionLetter({ revisions: [{ letter: "A" }] })).toBe("B");
  });

  it("returns Z after Y", () => {
    expect(nextRevisionLetter({ revisions: [{ letter: "Y" }] })).toBe("Z");
  });

  it("returns AA after Z", () => {
    expect(nextRevisionLetter({ revisions: [{ letter: "Z" }] })).toBe("AA");
  });

  it("returns AB after AA", () => {
    expect(nextRevisionLetter({ revisions: [{ letter: "AA" }] })).toBe("AB");
  });

  it("returns BA after AZ", () => {
    expect(nextRevisionLetter({ revisions: [{ letter: "AZ" }] })).toBe("BA");
  });

  it("returns AAAA after ZZZ", () => {
    expect(nextRevisionLetter({ revisions: [{ letter: "ZZZ" }] })).toBe("AAAA");
  });

  it("is case-insensitive", () => {
    expect(nextRevisionLetter({ revisions: [{ letter: "b" }] })).toBe("C");
  });
});

describe("addRevision", () => {
  it("creates revisions array if missing", () => {
    const sheet = {};
    addRevision(sheet, { letter: "A", date: "2026-05-14", description: "Initial", by: "Jane" });
    expect(sheet.revisions).toHaveLength(1);
    expect(sheet.revisions[0].letter).toBe("A");
  });

  it("appends to existing revisions", () => {
    const sheet = { revisions: [{ letter: "A", date: "2026-05-01", description: "Init", by: "Jane" }] };
    addRevision(sheet, { letter: "B", date: "2026-05-14", description: "Second", by: "Bob" });
    expect(sheet.revisions).toHaveLength(2);
    expect(sheet.revisions[1].letter).toBe("B");
  });

  it("uppercases the letter", () => {
    const sheet = {};
    addRevision(sheet, { letter: "a", date: "", description: "", by: "" });
    expect(sheet.revisions[0].letter).toBe("A");
  });
});

describe("setActiveRevision", () => {
  it("sets titleblock.revision", () => {
    const sheet = { titleblock: {} };
    setActiveRevision(sheet, "B");
    expect(sheet.titleblock.revision).toBe("B");
  });

  it("creates titleblock if missing", () => {
    const sheet = {};
    setActiveRevision(sheet, "C");
    expect(sheet.titleblock.revision).toBe("C");
  });

  it("uppercases the letter", () => {
    const sheet = {};
    setActiveRevision(sheet, "c");
    expect(sheet.titleblock.revision).toBe("C");
  });
});

describe("getRevisionHistory", () => {
  it("returns empty array when no revisions", () => {
    expect(getRevisionHistory({})).toEqual([]);
  });

  it("returns sorted revisions", () => {
    const sheet = { revisions: [{ letter: "B" }, { letter: "A" }, { letter: "C" }] };
    const hist = getRevisionHistory(sheet);
    expect(hist.map(r => r.letter)).toEqual(["A", "B", "C"]);
  });

  it("does not mutate original array", () => {
    const sheet = { revisions: [{ letter: "B" }, { letter: "A" }] };
    getRevisionHistory(sheet);
    expect(sheet.revisions[0].letter).toBe("B");
  });
});

describe("validateRevisionList", () => {
  it("returns ok for valid sheet", () => {
    const sheet = {
      titleblock: { revision: "A" },
      revisions: [{ letter: "A", date: "2026-05-14", description: "Init", by: "Jane" }],
    };
    expect(validateRevisionList(sheet)).toEqual({ ok: true, errors: [] });
  });

  it("rejects duplicate letters", () => {
    const sheet = {
      revisions: [{ letter: "A" }, { letter: "A" }],
    };
    const result = validateRevisionList(sheet);
    expect(result.ok).toBe(false);
    expect(result.errors.some(e => e.includes("Duplicate"))).toBe(true);
  });

  it("rejects missing letter field", () => {
    const sheet = { revisions: [{ date: "2026-05-14" }] };
    const result = validateRevisionList(sheet);
    expect(result.ok).toBe(false);
    expect(result.errors.some(e => e.includes("letter"))).toBe(true);
  });

  it("rejects active revision not in list", () => {
    const sheet = {
      titleblock: { revision: "B" },
      revisions: [{ letter: "A" }],
    };
    const result = validateRevisionList(sheet);
    expect(result.ok).toBe(false);
    expect(result.errors.some(e => e.includes("not in the revisions"))).toBe(true);
  });
});

describe("_nextLetter", () => {
  it("A→B", () => expect(_nextLetter("A")).toBe("B"));
  it("Z→AA", () => expect(_nextLetter("Z")).toBe("AA"));
  it("AA→AB", () => expect(_nextLetter("AA")).toBe("AB"));
  it("AZ→BA", () => expect(_nextLetter("AZ")).toBe("BA"));
  it("ZZZ→AAAA", () => expect(_nextLetter("ZZZ")).toBe("AAAA"));
});