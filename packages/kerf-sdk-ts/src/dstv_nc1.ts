/**
 * DSTV NC1 steel-fabrication export — TypeScript client module.
 *
 * Provides typed wrappers for the `steel_export_dstv_nc1` LLM tool,
 * and a pure-TS implementation of the NC1 file writer so the panel can
 * generate preview text client-side before hitting the server.
 *
 * Standard reference
 * ------------------
 * DSTV NC — Datenaustausch für numerisch gesteuerte Maschinen,
 * Deutscher Stahlbau-Verband (DSTV), §3 File Structure.
 * DIN 18800-7:2002 Stahlbauten: Ausführung und Herstellerqualifikation.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Face identifiers per DSTV NC §4. */
export type FaceId = "o" | "u" | "v" | "h" | "a" | "e";

/** Valid face set for runtime validation. */
export const VALID_FACES: ReadonlySet<string> = new Set<string>([
  "o", "u", "v", "h", "a", "e",
]);

/** Human-readable face descriptions. */
export const FACE_LABELS: Record<FaceId, string> = {
  o: "Top (Oben)",
  u: "Bottom (Unten)",
  v: "Front web (Vorne)",
  h: "Back web (Hinten)",
  a: "Start end (Anfang)",
  e: "Finish end (Ende)",
};

/** A single drilled/punched hole. */
export interface NC1Hole {
  face: FaceId;
  /** Longitudinal coordinate from member start (mm). */
  x_mm: number;
  /** Transverse coordinate from face centreline (mm). */
  y_mm: number;
  /** Nominal bolt-hole diameter (mm). */
  diameter_mm: number;
  /** Slot length for slotted holes (mm); omit or 0 for round holes. */
  slot_length_mm?: number;
}

/** A single vertex of an AK/IK contour polygon. */
export interface NC1ContourPoint {
  x_mm: number;
  y_mm: number;
  /** Bulge factor for arc segments (0 = straight, default). */
  arc_bulge?: number;
}

/** An outer (AK) or inner (IK) contour polygon. */
export interface NC1Contour {
  face: FaceId;
  points: NC1ContourPoint[];
}

/** Part mark / stamp (SI block). */
export interface NC1Stamp {
  face: FaceId;
  x_mm: number;
  y_mm: number;
  text: string;
  /** Character height (mm), default 10. */
  size_mm?: number;
}

/** Complete member description for NC1 export. */
export interface NC1MemberSpec {
  order_no: string;
  drawing_no: string;
  pos_no: string;
  quantity?: number;
  /** DSTV profile designation, e.g. "I HEB 200", "I IPE 300", "U UPN 200". */
  profile: string;
  /** Steel grade, e.g. "S355JR", "S275JR". */
  material: string;
  /** Cut length (mm). */
  length_mm: number;
  /** Profile flange width (mm); 0 for round sections. */
  flange_width_mm?: number;
  /** Flange thickness (mm). */
  flange_thickness_mm?: number;
  /** Profile height / outer diameter (mm). */
  web_height_mm: number;
  /** Web thickness (mm). */
  web_thickness_mm?: number;
  /** Saw-cut length when different from length_mm. */
  saw_length_mm?: number;
  holes?: NC1Hole[];
  outer_contours?: NC1Contour[];
  inner_contours?: NC1Contour[];
  stamps?: NC1Stamp[];
}

// ---------------------------------------------------------------------------
// Number formatting — DSTV NC §3.2
// ---------------------------------------------------------------------------

/**
 * Format a number per DSTV NC §3.2: up to 3 decimal places, no trailing
 * zeros, period as decimal separator.
 */
export function fmtNum(value: number): string {
  const raw = value.toFixed(3);
  // Strip trailing zeros and optional trailing decimal point
  return raw.replace(/\.?0+$/, "");
}

// ---------------------------------------------------------------------------
// Pure client-side NC1 writer
// ---------------------------------------------------------------------------

function writeST(m: NC1MemberSpec): string {
  const sawLen = m.saw_length_mm ?? m.length_mm;
  const lines = [
    "ST",
    m.order_no.slice(0, 20).padEnd(20),
    m.drawing_no.slice(0, 20).padEnd(20),
    m.pos_no.slice(0, 20).padEnd(20),
    String(Math.max(1, Math.round(m.quantity ?? 1))),
    m.profile.slice(0, 30).padEnd(30),
    m.material.slice(0, 8).padEnd(8),
    fmtNum(m.length_mm),
    fmtNum(sawLen),
    fmtNum(m.flange_width_mm ?? 0),
    fmtNum(m.flange_thickness_mm ?? 0),
    fmtNum(m.web_height_mm),
    fmtNum(m.web_thickness_mm ?? 0),
  ];
  return lines.join("\n");
}

function writeBO(holes: NC1Hole[]): string {
  if (!holes.length) return "";
  const rows = ["BO"];
  for (const h of holes) {
    const slot = h.slot_length_mm ?? 0;
    if (slot > 0) {
      rows.push(`${h.face}  ${fmtNum(h.x_mm)}  ${fmtNum(h.y_mm)}  ${fmtNum(h.diameter_mm)}  ${fmtNum(slot)}`);
    } else {
      rows.push(`${h.face}  ${fmtNum(h.x_mm)}  ${fmtNum(h.y_mm)}  ${fmtNum(h.diameter_mm)}`);
    }
  }
  return rows.join("\n");
}

function writeContours(contours: NC1Contour[], keyword: "AK" | "IK"): string {
  if (!contours.length) return "";
  const rows: string[] = [];
  for (const c of contours) {
    rows.push(`${keyword} ${c.face}`);
    for (const pt of c.points) {
      const bulge = pt.arc_bulge ?? 0;
      if (bulge !== 0) {
        rows.push(`${fmtNum(pt.x_mm)}  ${fmtNum(pt.y_mm)}  ${fmtNum(bulge)}`);
      } else {
        rows.push(`${fmtNum(pt.x_mm)}  ${fmtNum(pt.y_mm)}`);
      }
    }
  }
  return rows.join("\n");
}

function writeSI(stamps: NC1Stamp[]): string {
  if (!stamps.length) return "";
  const rows = ["SI"];
  for (const s of stamps) {
    rows.push(
      `${s.face}  ${fmtNum(s.x_mm)}  ${fmtNum(s.y_mm)}  ${fmtNum(s.size_mm ?? 10)}  ${s.text}`,
    );
  }
  return rows.join("\n");
}

/**
 * Generate a DSTV NC1 file string from a member spec.
 *
 * Conforms to DSTV NC §3: ST → BO → AK → IK → SI → EN.
 * Empty optional blocks are omitted.
 */
export function writeNC1(member: NC1MemberSpec): string {
  const parts: string[] = [];
  parts.push(writeST(member));

  const bo = writeBO(member.holes ?? []);
  if (bo) parts.push(bo);

  const ak = writeContours(member.outer_contours ?? [], "AK");
  if (ak) parts.push(ak);

  const ik = writeContours(member.inner_contours ?? [], "IK");
  if (ik) parts.push(ik);

  const si = writeSI(member.stamps ?? []);
  if (si) parts.push(si);

  parts.push("EN");
  return parts.join("\n") + "\n";
}

// ---------------------------------------------------------------------------
// Parse ST block (round-trip support)
// ---------------------------------------------------------------------------

export interface NC1Header {
  order_no: string;
  drawing_no: string;
  pos_no: string;
  quantity: number;
  profile: string;
  material: string;
  length_mm: number;
  saw_length_mm: number;
  flange_width_mm: number;
  flange_thickness_mm: number;
  web_height_mm: number;
  web_thickness_mm: number;
}

/**
 * Parse the ST block fields from an NC1 string.
 * Throws if no ST block is found or it has insufficient data lines.
 */
export function parseNC1Header(nc1Text: string): NC1Header {
  const lines = nc1Text.split("\n");
  const stIdx = lines.findIndex((l) => l.trim() === "ST");
  if (stIdx < 0) throw new Error("No ST block found in NC1 text");
  const data = lines.slice(stIdx + 1, stIdx + 13);
  if (data.length < 12)
    throw new Error(`ST block too short: expected 12 data lines, got ${data.length}`);
  return {
    order_no: data[0].trim(),
    drawing_no: data[1].trim(),
    pos_no: data[2].trim(),
    quantity: parseInt(data[3].trim(), 10),
    profile: data[4].trim(),
    material: data[5].trim(),
    length_mm: parseFloat(data[6].trim()),
    saw_length_mm: parseFloat(data[7].trim()),
    flange_width_mm: parseFloat(data[8].trim()),
    flange_thickness_mm: parseFloat(data[9].trim()),
    web_height_mm: parseFloat(data[10].trim()),
    web_thickness_mm: parseFloat(data[11].trim()),
  };
}

// ---------------------------------------------------------------------------
// React export panel helpers (framework-agnostic state shape)
// ---------------------------------------------------------------------------

/**
 * State shape for the DSTV NC1 export panel.
 * Use with your preferred state management (useState, Zustand, etc.).
 */
export interface DSTVExportPanelState {
  /** Whether the export is in progress. */
  isExporting: boolean;
  /** Generated NC1 text (null until exported). */
  nc1Text: string | null;
  /** Error message, if any. */
  error: string | null;
  /** Member spec being edited. */
  spec: NC1MemberSpec;
}

/** Initial state for a blank HEB 200 member. */
export function createDefaultPanelState(
  overrides?: Partial<NC1MemberSpec>,
): DSTVExportPanelState {
  return {
    isExporting: false,
    nc1Text: null,
    error: null,
    spec: {
      order_no: "",
      drawing_no: "",
      pos_no: "1",
      quantity: 1,
      profile: "I HEB 200",
      material: "S355JR",
      length_mm: 5000,
      flange_width_mm: 200,
      flange_thickness_mm: 15,
      web_height_mm: 200,
      web_thickness_mm: 9,
      holes: [],
      outer_contours: [],
      inner_contours: [],
      stamps: [],
      ...overrides,
    },
  };
}

/**
 * Generate NC1 client-side (no server call needed) and return updated panel state.
 *
 * Usage (React):
 *   const [state, setState] = useState(createDefaultPanelState());
 *   const handleExport = () => setState(runClientExport(state));
 */
export function runClientExport(
  state: DSTVExportPanelState,
): DSTVExportPanelState {
  try {
    const nc1Text = writeNC1(state.spec);
    return { ...state, nc1Text, error: null, isExporting: false };
  } catch (err) {
    return {
      ...state,
      nc1Text: null,
      error: err instanceof Error ? err.message : String(err),
      isExporting: false,
    };
  }
}

/**
 * Trigger a browser file download of the NC1 content.
 * Call this in a click handler after `runClientExport`.
 */
export function downloadNC1(nc1Text: string, filename = "member.nc1"): void {
  const blob = new Blob([nc1Text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
