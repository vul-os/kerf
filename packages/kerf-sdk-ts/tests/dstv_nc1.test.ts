/**
 * Vitest tests for the DSTV NC1 TypeScript client module.
 *
 * Tests: fmtNum helper, writeNC1 writer (block structure, round-trip),
 * parseNC1Header parser, panel state helpers.
 *
 * Oracle member: HEB 200, 5000 mm, 4 holes on face 'o', 1 AK cope on face 'v'.
 *
 * DSTV NC standard: Datenaustausch für numerisch gesteuerte Maschinen,
 * Deutscher Stahlbau-Verband (DSTV), §3 File Structure.
 */

import { describe, it, expect } from "vitest";
import {
  fmtNum,
  writeNC1,
  parseNC1Header,
  createDefaultPanelState,
  runClientExport,
  VALID_FACES,
  FACE_LABELS,
  type NC1MemberSpec,
  type FaceId,
} from "../src/dstv_nc1.js";

// ---------------------------------------------------------------------------
// Oracle fixture
// ---------------------------------------------------------------------------

function heb200Member(): NC1MemberSpec {
  return {
    order_no: "ORD-001",
    drawing_no: "DWG-A1",
    pos_no: "P100",
    quantity: 4,
    profile: "I HEB 200",
    material: "S355JR",
    length_mm: 5000,
    flange_width_mm: 200,
    flange_thickness_mm: 15,
    web_height_mm: 200,
    web_thickness_mm: 9,
    holes: [
      { face: "o", x_mm: 250,  y_mm:  75,  diameter_mm: 22 },
      { face: "o", x_mm: 250,  y_mm: -75,  diameter_mm: 22 },
      { face: "o", x_mm: 500,  y_mm:  75,  diameter_mm: 22 },
      { face: "o", x_mm: 500,  y_mm: -75,  diameter_mm: 22 },
    ],
    outer_contours: [
      {
        face: "v",
        points: [
          { x_mm: 0,   y_mm: 0  },
          { x_mm: 100, y_mm: 0  },
          { x_mm: 100, y_mm: 50 },
          { x_mm: 0,   y_mm: 50 },
        ],
      },
    ],
    stamps: [
      { face: "o", x_mm: 2500, y_mm: 0, text: "P100", size_mm: 10 },
    ],
  };
}

// ---------------------------------------------------------------------------
// 1. fmtNum helper
// ---------------------------------------------------------------------------

describe("fmtNum", () => {
  it("formats integer with no decimal point", () => {
    expect(fmtNum(22)).toBe("22");
  });

  it("strips trailing zeros from decimal", () => {
    expect(fmtNum(22.500)).toBe("22.5");
  });

  it("preserves up to 3 decimal places", () => {
    expect(fmtNum(22.125)).toBe("22.125");
  });

  it("formats zero as '0'", () => {
    expect(fmtNum(0)).toBe("0");
  });

  it("handles negative integers", () => {
    expect(fmtNum(-75)).toBe("-75");
  });

  it("handles negative decimals", () => {
    expect(fmtNum(-75.5)).toBe("-75.5");
  });

  it("rounds to 3 decimal places", () => {
    // 1.0016 rounds to 1.002 at 3dp (avoids IEEE 754 banker's-rounding edge)
    const s = fmtNum(1.0016);
    expect(parseFloat(s)).toBeCloseTo(1.002, 3);
  });
});

// ---------------------------------------------------------------------------
// 2. VALID_FACES and FACE_LABELS
// ---------------------------------------------------------------------------

describe("VALID_FACES and FACE_LABELS", () => {
  it("contains exactly 6 face ids", () => {
    expect(VALID_FACES.size).toBe(6);
  });

  it("contains o, u, v, h, a, e", () => {
    for (const f of ["o", "u", "v", "h", "a", "e"]) {
      expect(VALID_FACES.has(f)).toBe(true);
    }
  });

  it("FACE_LABELS has an entry for each valid face", () => {
    for (const f of VALID_FACES) {
      expect(FACE_LABELS[f as FaceId]).toBeTruthy();
    }
  });
});

// ---------------------------------------------------------------------------
// 3. writeNC1 — ST block round-trips
// ---------------------------------------------------------------------------

describe("writeNC1 → parseNC1Header round-trip", () => {
  it("order_no round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.order_no).toBe("ORD-001");
  });

  it("drawing_no round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.drawing_no).toBe("DWG-A1");
  });

  it("pos_no round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.pos_no).toBe("P100");
  });

  it("quantity round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.quantity).toBe(4);
  });

  it("profile round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.profile).toBe("I HEB 200");
  });

  it("material round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.material).toBe("S355JR");
  });

  it("length_mm round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.length_mm).toBeCloseTo(5000, 3);
  });

  it("saw_length_mm defaults to length_mm", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.saw_length_mm).toBeCloseTo(5000, 3);
  });

  it("saw_length_mm override round-trips", () => {
    const m = { ...heb200Member(), saw_length_mm: 5010.5 };
    const hdr = parseNC1Header(writeNC1(m));
    expect(hdr.saw_length_mm).toBeCloseTo(5010.5, 3);
  });

  it("flange_width_mm round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.flange_width_mm).toBeCloseTo(200, 3);
  });

  it("flange_thickness_mm round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.flange_thickness_mm).toBeCloseTo(15, 3);
  });

  it("web_height_mm round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.web_height_mm).toBeCloseTo(200, 3);
  });

  it("web_thickness_mm round-trips", () => {
    const hdr = parseNC1Header(writeNC1(heb200Member()));
    expect(hdr.web_thickness_mm).toBeCloseTo(9, 3);
  });

  it("fractional length round-trips to 3dp", () => {
    const m = { ...heb200Member(), length_mm: 4567.125 };
    const hdr = parseNC1Header(writeNC1(m));
    expect(hdr.length_mm).toBeCloseTo(4567.125, 3);
  });

  it("parseNC1Header throws on missing ST block", () => {
    expect(() => parseNC1Header("not valid nc1\n")).toThrow("No ST block");
  });
});

// ---------------------------------------------------------------------------
// 4. BO block — holes on correct face
// ---------------------------------------------------------------------------

describe("writeNC1 BO block", () => {
  function getBoLines(nc1: string): string[] {
    const lines = nc1.split("\n");
    const boIdx = lines.findIndex((l) => l.trim() === "BO");
    if (boIdx < 0) return [];
    const result: string[] = [];
    for (const ln of lines.slice(boIdx + 1)) {
      const s = ln.trim();
      if (!s) continue;
      // Stop at next block keyword (exactly 2 uppercase letters)
      if (/^(ST|BO|AK|IK|SI|EN)(\s|$)/.test(s)) break;
      result.push(s);
    }
    return result;
  }

  it("BO block is present", () => {
    const nc1 = writeNC1(heb200Member());
    expect(nc1).toContain("\nBO\n");
  });

  it("contains 4 hole lines", () => {
    expect(getBoLines(writeNC1(heb200Member()))).toHaveLength(4);
  });

  it("all holes are on face o", () => {
    for (const line of getBoLines(writeNC1(heb200Member()))) {
      expect(line.startsWith("o")).toBe(true);
    }
  });

  it("first hole x=250, y=75, d=22", () => {
    const parts = getBoLines(writeNC1(heb200Member()))[0].split(/\s+/);
    expect(parts[0]).toBe("o");
    expect(parseFloat(parts[1])).toBeCloseTo(250);
    expect(parseFloat(parts[2])).toBeCloseTo(75);
    expect(parseFloat(parts[3])).toBeCloseTo(22);
  });

  it("second hole has y=-75 (negative coordinate preserved)", () => {
    const parts = getBoLines(writeNC1(heb200Member()))[1].split(/\s+/);
    expect(parseFloat(parts[2])).toBeCloseTo(-75);
  });

  it("BO block absent when no holes", () => {
    const m = { ...heb200Member(), holes: [] };
    expect(writeNC1(m)).not.toContain("BO");
  });

  it("slotted hole writes 5 fields", () => {
    const m: NC1MemberSpec = {
      ...heb200Member(),
      holes: [{ face: "o", x_mm: 300, y_mm: 0, diameter_mm: 22, slot_length_mm: 40 }],
    };
    const boLines = getBoLines(writeNC1(m));
    expect(boLines[0].split(/\s+/)).toHaveLength(5);
    expect(parseFloat(boLines[0].split(/\s+/)[4])).toBeCloseTo(40);
  });

  it("web face v hole written with v identifier", () => {
    const m: NC1MemberSpec = {
      ...heb200Member(),
      holes: [{ face: "v", x_mm: 1000, y_mm: 0, diameter_mm: 26 }],
    };
    const boLines = getBoLines(writeNC1(m));
    expect(boLines[0].startsWith("v")).toBe(true);
  });

  it("end plate face a hole written with a identifier", () => {
    const m: NC1MemberSpec = {
      ...heb200Member(),
      holes: [{ face: "a", x_mm: 0, y_mm: 50, diameter_mm: 22 }],
    };
    const boLines = getBoLines(writeNC1(m));
    expect(boLines[0].startsWith("a")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 5. AK block — outer contours
// ---------------------------------------------------------------------------

describe("writeNC1 AK block", () => {
  it("AK block is present for oracle member", () => {
    expect(writeNC1(heb200Member())).toContain("AK v");
  });

  it("AK block has 4 vertices for rectangular cope", () => {
    const nc1 = writeNC1(heb200Member());
    const lines = nc1.split("\n");
    const akIdx = lines.findIndex((l) => l.trim() === "AK v");
    const vertices: string[] = [];
    for (const ln of lines.slice(akIdx + 1)) {
      const s = ln.trim();
      if (!s || /^[A-Z]{2}(\s|$)/.test(s)) break;
      vertices.push(s);
    }
    expect(vertices).toHaveLength(4);
  });

  it("AK first vertex at (0, 0)", () => {
    const nc1 = writeNC1(heb200Member());
    const lines = nc1.split("\n");
    const akIdx = lines.findIndex((l) => l.trim() === "AK v");
    const parts = lines[akIdx + 1].trim().split(/\s+/);
    expect(parseFloat(parts[0])).toBeCloseTo(0);
    expect(parseFloat(parts[1])).toBeCloseTo(0);
  });

  it("AK second vertex x=100", () => {
    const nc1 = writeNC1(heb200Member());
    const lines = nc1.split("\n");
    const akIdx = lines.findIndex((l) => l.trim() === "AK v");
    const parts = lines[akIdx + 2].trim().split(/\s+/);
    expect(parseFloat(parts[0])).toBeCloseTo(100);
  });

  it("AK absent when no outer contours", () => {
    const m = { ...heb200Member(), outer_contours: [] };
    expect(writeNC1(m)).not.toContain("AK");
  });

  it("arc bulge written as third field when non-zero", () => {
    const m: NC1MemberSpec = {
      ...heb200Member(),
      outer_contours: [
        {
          face: "v" as FaceId,
          points: [
            { x_mm: 0, y_mm: 0, arc_bulge: 0.5 },
            { x_mm: 100, y_mm: 0 },
            { x_mm: 100, y_mm: 50 },
          ],
        },
      ],
    };
    const nc1 = writeNC1(m);
    const lines = nc1.split("\n");
    const akIdx = lines.findIndex((l) => l.trim() === "AK v");
    const firstVertexParts = lines[akIdx + 1].trim().split(/\s+/);
    expect(firstVertexParts).toHaveLength(3);
    expect(parseFloat(firstVertexParts[2])).toBeCloseTo(0.5);
  });
});

// ---------------------------------------------------------------------------
// 6. IK block — inner contours
// ---------------------------------------------------------------------------

describe("writeNC1 IK block", () => {
  it("IK block written when inner contours present", () => {
    const m: NC1MemberSpec = {
      ...heb200Member(),
      inner_contours: [
        {
          face: "v" as FaceId,
          points: [
            { x_mm: 500, y_mm: -40 },
            { x_mm: 700, y_mm: -40 },
            { x_mm: 700, y_mm:  40 },
            { x_mm: 500, y_mm:  40 },
          ],
        },
      ],
    };
    expect(writeNC1(m)).toContain("IK v");
  });

  it("IK absent when no inner contours", () => {
    const m = { ...heb200Member(), inner_contours: [] };
    expect(writeNC1(m)).not.toContain("IK");
  });
});

// ---------------------------------------------------------------------------
// 7. SI block — stamps
// ---------------------------------------------------------------------------

describe("writeNC1 SI block", () => {
  it("SI block is present", () => {
    expect(writeNC1(heb200Member())).toContain("\nSI\n");
  });

  it("stamp text appears in output", () => {
    expect(writeNC1(heb200Member())).toContain("P100");
  });

  it("stamp line starts with face id 'o'", () => {
    const nc1 = writeNC1(heb200Member());
    const lines = nc1.split("\n");
    const siIdx = lines.findIndex((l) => l.trim() === "SI");
    expect(lines[siIdx + 1].trim().startsWith("o")).toBe(true);
  });

  it("stamp x=2500, y=0", () => {
    const nc1 = writeNC1(heb200Member());
    const lines = nc1.split("\n");
    const siIdx = lines.findIndex((l) => l.trim() === "SI");
    const parts = lines[siIdx + 1].trim().split(/\s+/);
    expect(parseFloat(parts[1])).toBeCloseTo(2500);
    expect(parseFloat(parts[2])).toBeCloseTo(0);
  });

  it("stamp size=10", () => {
    const nc1 = writeNC1(heb200Member());
    const lines = nc1.split("\n");
    const siIdx = lines.findIndex((l) => l.trim() === "SI");
    const parts = lines[siIdx + 1].trim().split(/\s+/);
    expect(parseFloat(parts[3])).toBeCloseTo(10);
  });

  it("SI absent when no stamps", () => {
    const m = { ...heb200Member(), stamps: [] };
    expect(writeNC1(m)).not.toContain("SI");
  });
});

// ---------------------------------------------------------------------------
// 8. Block order and EN terminator
// ---------------------------------------------------------------------------

describe("writeNC1 block order and terminator", () => {
  function blockPos(nc1: string, kw: string): number {
    return nc1.split("\n").findIndex((l) => l.trim() === kw || l.trim().startsWith(kw + " "));
  }

  it("ST before BO", () => {
    const nc1 = writeNC1(heb200Member());
    expect(blockPos(nc1, "ST")).toBeLessThan(blockPos(nc1, "BO"));
  });

  it("BO before AK", () => {
    const nc1 = writeNC1(heb200Member());
    expect(blockPos(nc1, "BO")).toBeLessThan(blockPos(nc1, "AK"));
  });

  it("AK before SI", () => {
    const nc1 = writeNC1(heb200Member());
    expect(blockPos(nc1, "AK")).toBeLessThan(blockPos(nc1, "SI"));
  });

  it("SI before EN", () => {
    const nc1 = writeNC1(heb200Member());
    expect(blockPos(nc1, "SI")).toBeLessThan(blockPos(nc1, "EN"));
  });

  it("EN is the last non-empty line", () => {
    const nc1 = writeNC1(heb200Member());
    const nonEmpty = nc1.split("\n").filter((l) => l.trim());
    expect(nonEmpty.at(-1)?.trim()).toBe("EN");
  });

  it("file ends with newline", () => {
    expect(writeNC1(heb200Member()).endsWith("\n")).toBe(true);
  });

  it("minimal member has only ST and EN", () => {
    const m: NC1MemberSpec = {
      order_no: "X",
      drawing_no: "X",
      pos_no: "1",
      profile: "FL 100x10",
      material: "S235JR",
      length_mm: 1000,
      web_height_mm: 100,
    };
    const nc1 = writeNC1(m);
    expect(nc1).not.toContain("BO");
    expect(nc1).not.toContain("AK");
    expect(nc1).not.toContain("IK");
    expect(nc1).not.toContain("SI");
    expect(nc1.trim().startsWith("ST")).toBe(true);
    expect(nc1.trim().endsWith("EN")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 9. Panel state helpers
// ---------------------------------------------------------------------------

describe("createDefaultPanelState", () => {
  it("returns isExporting=false", () => {
    const s = createDefaultPanelState();
    expect(s.isExporting).toBe(false);
  });

  it("returns nc1Text=null initially", () => {
    const s = createDefaultPanelState();
    expect(s.nc1Text).toBeNull();
  });

  it("accepts profile override", () => {
    const s = createDefaultPanelState({ profile: "I IPE 300" });
    expect(s.spec.profile).toBe("I IPE 300");
  });

  it("default profile is I HEB 200", () => {
    const s = createDefaultPanelState();
    expect(s.spec.profile).toBe("I HEB 200");
  });
});

describe("runClientExport", () => {
  it("generates nc1Text on success", () => {
    const state = createDefaultPanelState({ profile: "I HEB 200", length_mm: 3000 });
    const next = runClientExport(state);
    expect(next.nc1Text).not.toBeNull();
    expect(next.nc1Text).toContain("ST");
    expect(next.nc1Text).toContain("EN");
  });

  it("sets error to null on success", () => {
    const state = createDefaultPanelState();
    const next = runClientExport(state);
    expect(next.error).toBeNull();
  });

  it("round-trips profile through export + parse", () => {
    const state = createDefaultPanelState({ profile: "I IPE 450", length_mm: 7200 });
    const next = runClientExport(state);
    const hdr = parseNC1Header(next.nc1Text!);
    expect(hdr.profile).toBe("I IPE 450");
    expect(hdr.length_mm).toBeCloseTo(7200, 3);
  });

  it("preserves existing state shape keys", () => {
    const state = createDefaultPanelState();
    const next = runClientExport(state);
    expect(next).toHaveProperty("isExporting");
    expect(next).toHaveProperty("spec");
    expect(next).toHaveProperty("error");
    expect(next).toHaveProperty("nc1Text");
  });
});

// ---------------------------------------------------------------------------
// 10. Multi-face hole distribution
// ---------------------------------------------------------------------------

describe("multi-face holes", () => {
  it("holes on o, u, v, h all appear with correct face id", () => {
    const m: NC1MemberSpec = {
      ...heb200Member(),
      holes: [
        { face: "o", x_mm: 500,  y_mm:  100, diameter_mm: 22 },
        { face: "u", x_mm: 500,  y_mm:  100, diameter_mm: 22 },
        { face: "v", x_mm: 1000, y_mm:    0, diameter_mm: 26 },
        { face: "h", x_mm: 1000, y_mm:    0, diameter_mm: 26 },
      ],
    };
    const nc1 = writeNC1(m);
    const lines = nc1.split("\n");
    const boIdx = lines.findIndex((l) => l.trim() === "BO");
    const facesFound = new Set<string>();
    for (const ln of lines.slice(boIdx + 1)) {
      const s = ln.trim();
      if (!s || /^[A-Z]{2}(\s|$)/.test(s)) break;
      facesFound.add(s[0]);
    }
    expect(facesFound).toEqual(new Set(["o", "u", "v", "h"]));
  });

  it("8 holes produce 8 BO data lines", () => {
    const holes = Array.from({ length: 8 }, (_, i) => ({
      face: "o" as FaceId,
      x_mm: (i + 1) * 200,
      y_mm: 50,
      diameter_mm: 22,
    }));
    const m: NC1MemberSpec = { ...heb200Member(), holes };
    const nc1 = writeNC1(m);
    const lines = nc1.split("\n");
    const boIdx = lines.findIndex((l) => l.trim() === "BO");
    let count = 0;
    for (const ln of lines.slice(boIdx + 1)) {
      const s = ln.trim();
      if (!s || /^[A-Z]{2}(\s|$)/.test(s)) break;
      count++;
    }
    expect(count).toBe(8);
  });
});
