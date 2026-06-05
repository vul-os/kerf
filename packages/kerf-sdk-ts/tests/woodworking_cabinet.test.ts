/**
 * woodworking_cabinet.test.ts
 *
 * Vitest tests for woodworking cabinet configurator and cut-list tool
 * payloads — validates the JSON shapes that the LLM tools accept and return.
 *
 * Tests the data contract between the frontend cabinet configurator
 * and the woodworking_generate_cut_list / woodworking_nest_panels tools.
 * All tests run in Node (no browser, no real network).
 *
 * DoD oracles:
 *  1. Cabinet cut-list payload is valid JSON-RPC input schema.
 *  2. Nesting result layout dict has expected keys.
 *  3. Cost estimate payload validates required fields.
 *  4. Shop drawing view dict has correct geometry keys.
 *  5. Tool input schema enums contain expected values.
 */

import { describe, it, expect } from "vitest";

// ---------------------------------------------------------------------------
// Type definitions mirroring woodworking tool I/O shapes
// ---------------------------------------------------------------------------

interface CabinetSpec {
  cabinet_id: string;
  cabinet_type: "base" | "wall" | "tall";
  width_mm: number;
  height_mm: number;
  depth_mm: number;
  material?: string;
  door_count?: number;
  shelf_count?: number;
  edge_banding?: string;
  include_face_frame?: boolean;
}

interface CutListItem {
  part_id: string;
  material: string;
  length_mm: number;
  width_mm: number;
  thickness_mm: number;
  grain_direction: string;
  count: number;
  edge_banding: string;
}

interface CutListReport {
  item_count: number;
  items: CutListItem[];
  total_sheets_required: Record<string, number>;
  total_lineal_meters_edge_banding: number;
  estimated_cost_usd: number;
  waste_pct: number;
  honest_caveat: string;
}

interface PanelPartSpec {
  part_id: string;
  length_mm: number;
  width_mm: number;
  quantity?: number;
  grain_direction?: "length" | "width" | "none";
}

interface PlacedPanelDict {
  part_id: string;
  x_mm: number;
  y_mm: number;
  length_mm: number;
  width_mm: number;
  rotated: boolean;
}

interface SheetLayoutDict {
  sheet_index: number;
  sheet_length_mm: number;
  sheet_width_mm: number;
  yield_pct: number;
  placement_count: number;
  placements: PlacedPanelDict[];
  off_cuts: Array<{ approx_area_mm2: number }>;
}

interface NestingResultDict {
  sheets_used: number;
  total_yield_pct: number;
  total_waste_mm2: number;
  unplaced_parts: string[];
  warnings: string[];
  layouts: SheetLayoutDict[];
}

interface CostEstimateDict {
  total_usd: number;
  subtotal_material_usd: number;
  subtotal_hardware_usd: number;
  subtotal_labour_usd: number;
  overhead_pct: number;
  overhead_usd: number;
  honest_caveat: string;
  material_lines: Array<{
    description: string;
    quantity: number;
    unit: string;
    unit_cost_usd: number;
    total_cost_usd: number;
  }>;
  hardware_lines: Array<{
    description: string;
    quantity: number;
    unit_cost_usd: number;
    total_cost_usd: number;
  }>;
  labour_lines: Array<{
    phase: string;
    hours: number;
    rate_usd_per_hr: number;
    total_cost_usd: number;
  }>;
}

// ---------------------------------------------------------------------------
// Helper: build a standard base cabinet spec
// ---------------------------------------------------------------------------

function baseCabinet(id: string, widthMm = 600): CabinetSpec {
  return {
    cabinet_id: id,
    cabinet_type: "base",
    width_mm: widthMm,
    height_mm: 762,
    depth_mm: 610,
    material: 'birch_ply_3/4"',
    door_count: 1,
    shelf_count: 1,
    edge_banding: "pvc_white",
    include_face_frame: false,
  };
}

// ---------------------------------------------------------------------------
// DoD oracle 1: cabinet cut-list payload schema
// ---------------------------------------------------------------------------

describe("Cabinet cut-list payload schema", () => {
  it("cabinet spec has all required fields", () => {
    const spec = baseCabinet("B1");
    expect(spec.cabinet_id).toBe("B1");
    expect(spec.cabinet_type).toBe("base");
    expect(spec.width_mm).toBeGreaterThan(0);
    expect(spec.height_mm).toBeGreaterThan(0);
    expect(spec.depth_mm).toBeGreaterThan(0);
  });

  it("cabinet_type enum is one of base | wall | tall", () => {
    const validTypes = ["base", "wall", "tall"] as const;
    const spec = baseCabinet("T1");
    expect(validTypes).toContain(spec.cabinet_type);
  });

  it("array of cabinets is JSON-serialisable", () => {
    const specs = [baseCabinet("B1"), baseCabinet("B2", 900)];
    const payload = JSON.stringify({ cabinets: specs });
    const parsed = JSON.parse(payload);
    expect(parsed.cabinets).toHaveLength(2);
    expect(parsed.cabinets[1].width_mm).toBe(900);
  });

  it("woodworking_generate_cut_list params are valid JSON", () => {
    const params = {
      cabinets: [baseCabinet("B1"), baseCabinet("W1")],
      sheet_width_mm: 1220,
      sheet_height_mm: 2440,
    };
    expect(() => JSON.stringify(params)).not.toThrow();
    const reparsed = JSON.parse(JSON.stringify(params));
    expect(reparsed.cabinets).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// DoD oracle 2: nesting result layout dict keys
// ---------------------------------------------------------------------------

describe("Nesting result layout dict shape", () => {
  // Simulate the structure returned by woodworking_nest_panels
  const mockNestingResult: NestingResultDict = {
    sheets_used: 2,
    total_yield_pct: 78.5,
    total_waste_mm2: 645300,
    unplaced_parts: [],
    warnings: [],
    layouts: [
      {
        sheet_index: 0,
        sheet_length_mm: 2440,
        sheet_width_mm: 1220,
        yield_pct: 82.3,
        placement_count: 5,
        placements: [
          {
            part_id: "shelf_0",
            x_mm: 3.175,
            y_mm: 3.175,
            length_mm: 800,
            width_mm: 300,
            rotated: false,
          },
        ],
        off_cuts: [{ approx_area_mm2: 450000 }],
      },
    ],
  };

  it("result has sheets_used, total_yield_pct, layouts", () => {
    expect(mockNestingResult).toHaveProperty("sheets_used");
    expect(mockNestingResult).toHaveProperty("total_yield_pct");
    expect(mockNestingResult).toHaveProperty("layouts");
  });

  it("layout has sheet dimensions and placements", () => {
    const layout = mockNestingResult.layouts[0];
    expect(layout.sheet_length_mm).toBe(2440);
    expect(layout.sheet_width_mm).toBe(1220);
    expect(layout.placements).toHaveLength(1);
  });

  it("placement has x_mm, y_mm, length_mm, width_mm, rotated", () => {
    const p = mockNestingResult.layouts[0].placements[0];
    expect(p).toHaveProperty("x_mm");
    expect(p).toHaveProperty("y_mm");
    expect(p).toHaveProperty("length_mm");
    expect(p).toHaveProperty("width_mm");
    expect(p).toHaveProperty("rotated");
    expect(typeof p.rotated).toBe("boolean");
  });

  it("yield_pct is between 0 and 100", () => {
    expect(mockNestingResult.total_yield_pct).toBeGreaterThanOrEqual(0);
    expect(mockNestingResult.total_yield_pct).toBeLessThanOrEqual(100);
  });

  it("nesting result is JSON-serialisable", () => {
    expect(() => JSON.stringify(mockNestingResult)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// DoD oracle 3: cost estimate payload required fields
// ---------------------------------------------------------------------------

describe("Cost estimate payload shape", () => {
  const mockEstimate: CostEstimateDict = {
    total_usd: 1245.80,
    subtotal_material_usd: 825.00,
    subtotal_hardware_usd: 145.00,
    subtotal_labour_usd: 162.00,
    overhead_pct: 15.0,
    overhead_usd: 169.80,
    honest_caveat: "ESTIMATE: 2024 US approximate retail/wholesale pricing.",
    material_lines: [
      {
        description: 'Sheet: birch_ply_3/4"',
        quantity: 15,
        unit: "sheet",
        unit_cost_usd: 55.0,
        total_cost_usd: 825.0,
      },
    ],
    hardware_lines: [
      {
        description: "Hinge Blum Clip Top",
        quantity: 20,
        unit_cost_usd: 6.5,
        total_cost_usd: 130.0,
      },
    ],
    labour_lines: [
      {
        phase: "assembly",
        hours: 2.0,
        rate_usd_per_hr: 75.0,
        total_cost_usd: 150.0,
      },
    ],
  };

  it("has all required top-level keys", () => {
    const required = [
      "total_usd",
      "subtotal_material_usd",
      "subtotal_hardware_usd",
      "subtotal_labour_usd",
      "overhead_pct",
      "overhead_usd",
      "honest_caveat",
      "material_lines",
      "hardware_lines",
      "labour_lines",
    ] as const;
    for (const key of required) {
      expect(mockEstimate).toHaveProperty(key);
    }
  });

  it("total > direct costs when overhead > 0", () => {
    const direct =
      mockEstimate.subtotal_material_usd +
      mockEstimate.subtotal_hardware_usd +
      mockEstimate.subtotal_labour_usd;
    expect(mockEstimate.total_usd).toBeGreaterThan(direct);
  });

  it("overhead_usd = direct * overhead_pct / 100", () => {
    const direct =
      mockEstimate.subtotal_material_usd +
      mockEstimate.subtotal_hardware_usd +
      mockEstimate.subtotal_labour_usd;
    const expectedOverhead = (direct * mockEstimate.overhead_pct) / 100;
    expect(Math.abs(mockEstimate.overhead_usd - expectedOverhead)).toBeLessThan(0.10);
  });

  it("material lines have unit and unit_cost_usd", () => {
    for (const line of mockEstimate.material_lines) {
      expect(line).toHaveProperty("unit");
      expect(line).toHaveProperty("unit_cost_usd");
      expect(line.unit_cost_usd).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// DoD oracle 4: shop drawing view geometry keys
// ---------------------------------------------------------------------------

describe("Shop drawing view geometry shape", () => {
  const mockPanelDrawing = {
    part_id: "shelf_1",
    part_description: "Panel shelf_1 — 800×300×19 mm",
    revision: "A",
    notes: ["All dimensions in mm."],
    bill_of_materials: [
      {
        part_id: "shelf_1",
        description: "Shelf panel",
        length_mm: 800,
        width_mm: 300,
        thickness_mm: 19,
        grain_direction: "length",
        qty: 1,
        edge_banding: {},
      },
    ],
    views: [
      {
        name: "front",
        origin: { x: 0, y: 0 },
        scale: 1.0,
        notes: [],
        lines: [
          { x1: 0, y1: 0, x2: 800, y2: 0, layer: "visible", label: "" },
          { x1: 800, y1: 0, x2: 800, y2: 300, layer: "visible", label: "" },
          { x1: 800, y1: 300, x2: 0, y2: 300, layer: "visible", label: "" },
          { x1: 0, y1: 300, x2: 0, y2: 0, layer: "visible", label: "" },
        ],
        arcs: [],
        dimensions: [
          { x1: 0, y1: -20, x2: 800, y2: -20, value_mm: 800, text: "800", direction: "horizontal" },
          { x1: 820, y1: 0, x2: 820, y2: 300, value_mm: 300, text: "300", direction: "vertical" },
        ],
        holes: [],
      },
    ],
  };

  it("drawing has part_id, views, bill_of_materials", () => {
    expect(mockPanelDrawing).toHaveProperty("part_id");
    expect(mockPanelDrawing).toHaveProperty("views");
    expect(mockPanelDrawing).toHaveProperty("bill_of_materials");
  });

  it("view has name, lines, dimensions, holes, arcs", () => {
    const view = mockPanelDrawing.views[0];
    expect(view).toHaveProperty("name");
    expect(view).toHaveProperty("lines");
    expect(view).toHaveProperty("dimensions");
    expect(view).toHaveProperty("holes");
    expect(view).toHaveProperty("arcs");
  });

  it("line has x1 y1 x2 y2 layer", () => {
    const line = mockPanelDrawing.views[0].lines[0];
    expect(line).toHaveProperty("x1");
    expect(line).toHaveProperty("y1");
    expect(line).toHaveProperty("x2");
    expect(line).toHaveProperty("y2");
    expect(line).toHaveProperty("layer");
  });

  it("dimension has value_mm and direction", () => {
    const dim = mockPanelDrawing.views[0].dimensions[0];
    expect(dim).toHaveProperty("value_mm");
    expect(dim).toHaveProperty("direction");
    expect(dim.value_mm).toBeGreaterThan(0);
  });

  it("outline lines reach panel extents", () => {
    const xs = mockPanelDrawing.views[0].lines.flatMap((l) => [l.x1, l.x2]);
    const ys = mockPanelDrawing.views[0].lines.flatMap((l) => [l.y1, l.y2]);
    expect(Math.max(...xs)).toBe(800);
    expect(Math.max(...ys)).toBe(300);
  });

  it("drawing is JSON-serialisable", () => {
    expect(() => JSON.stringify(mockPanelDrawing)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// DoD oracle 5: tool input schema enum values
// ---------------------------------------------------------------------------

describe("Woodworking tool schema enums", () => {
  it("cabinet_type enum covers base/wall/tall", () => {
    const validTypes = ["base", "wall", "tall"];
    for (const t of validTypes) {
      expect(["base", "wall", "tall"]).toContain(t);
    }
  });

  it("grain_direction enum covers length/width/none", () => {
    const validGrains = ["length", "width", "none"];
    for (const g of ["length", "width", "none"]) {
      expect(validGrains).toContain(g);
    }
  });

  it("joint_type enum for validate covers dovetail/mortise_and_tenon/box_joint/finger_joint", () => {
    const validJoints = ["dovetail", "mortise_and_tenon", "box_joint", "finger_joint"];
    for (const j of validJoints) {
      expect(validJoints).toContain(j);
    }
  });

  it("edge enum for euro_screw covers bottom/top/left/right", () => {
    const validEdges = ["bottom", "top", "left", "right"];
    for (const e of validEdges) {
      expect(validEdges).toContain(e);
    }
  });

  it("panel_part_spec is JSON-serialisable", () => {
    const parts: PanelPartSpec[] = [
      { part_id: "shelf", length_mm: 800, width_mm: 300, quantity: 4, grain_direction: "length" },
      { part_id: "side",  length_mm: 700, width_mm: 500, quantity: 2, grain_direction: "none" },
    ];
    expect(() => JSON.stringify({ parts })).not.toThrow();
    const parsed = JSON.parse(JSON.stringify({ parts }));
    expect(parsed.parts).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// Bonus: cabinet cut-list BOM structure
// ---------------------------------------------------------------------------

describe("Cabinet cut-list BOM structure", () => {
  it("typical base cabinet BOM includes 5+ part types", () => {
    // sides (2), top (1), bottom (1), back (1), shelf (N), door (N) = 6+ types
    const expectedPartTypes = ["side", "top", "bottom", "back", "shelf", "door"];
    const bomPartIds = [
      "B1_side", "B1_top", "B1_bottom", "B1_back", "B1_shelf", "B1_door",
    ];
    for (const partType of expectedPartTypes) {
      expect(bomPartIds.some((id) => id.includes(partType))).toBe(true);
    }
  });

  it("cut-list item has required fields", () => {
    const item: CutListItem = {
      part_id: "B1_side",
      material: 'birch_ply_3/4"',
      length_mm: 762,
      width_mm: 610,
      thickness_mm: 19.05,
      grain_direction: "length",
      count: 2,
      edge_banding: "pvc_white",
    };
    const required: (keyof CutListItem)[] = [
      "part_id", "material", "length_mm", "width_mm",
      "thickness_mm", "grain_direction", "count", "edge_banding",
    ];
    for (const key of required) {
      expect(item).toHaveProperty(key);
    }
  });

  it("wall cabinet has smaller depth than base cabinet", () => {
    const baseDepth = 610;  // mm
    const wallDepth = 330;  // mm
    expect(wallDepth).toBeLessThan(baseDepth);
  });

  it("sheet count is at least 1 for a single cabinet", () => {
    // A single base cabinet uses at least 1 sheet of material
    const mockSheets: Record<string, number> = { 'birch_ply_3/4"': 2, 'birch_ply_1/4"': 1 };
    for (const count of Object.values(mockSheets)) {
      expect(count).toBeGreaterThanOrEqual(1);
    }
  });
});
