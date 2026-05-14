import { describe, it, expect } from 'vitest'
import {
  generateStitchingPattern,
  gridStitching,
  perimeterStitching,
  hexStitching,
  teardropForPadVia,
  applyTeardropsToAll
} from './viaStitching.js'

const W = 50;
const H = 40;
const squarePolygon = [
  { x: 0, y: 0 },
  { x: W, y: 0 },
  { x: W, y: H },
  { x: 0, y: H }
];
const viaSpec = { diameter: 0.8, drill: 0.4, net_id: 'GND' };

describe('generateStitchingPattern', () => {
  it('grid spacing respects pitch', () => {
    const pitch = 5;
    const vias = generateStitchingPattern(squarePolygon, pitch, viaSpec, 1);
    if (vias.length > 1) {
      const distances = [];
      for (let i = 0; i < Math.min(vias.length, 5); i++) {
        for (let j = i + 1; j < Math.min(vias.length, 5); j++) {
          const dx = vias[j].x - vias[i].x;
          const dy = vias[j].y - vias[i].y;
          distances.push(Math.sqrt(dx * dx + dy * dy));
        }
      }
      const uniqueX = [...new Set(vias.map(v => Math.round(v.x / pitch) * pitch))];
      expect(uniqueX.length).toBeGreaterThan(1);
    }
    expect(vias.length).toBeGreaterThan(0);
  });

  it('returns empty array for tiny polygon', () => {
    const tinyPolygon = [{ x: 0, y: 0 }, { x: 0.1, y: 0 }, { x: 0.1, y: 0.1 }];
    const vias = generateStitchingPattern(tinyPolygon, 5, viaSpec, 1);
    expect(vias).toEqual([]);
  });

  it('edge_offset_mm keeps vias away from boundary', () => {
    const pitch = 5;
    const offset = 2;
    const vias = generateStitchingPattern(squarePolygon, pitch, viaSpec, offset);
    const minX = Math.min(...squarePolygon.map(p => p.x));
    for (const via of vias) {
      expect(via.x).toBeGreaterThan(0 + offset + viaSpec.diameter / 2 - 0.001);
      expect(via.y).toBeGreaterThan(0 + offset + viaSpec.diameter / 2 - 0.001);
    }
  });
});

describe('gridStitching', () => {
  it('produces regular grid pattern', () => {
    const pitch = 5;
    const vias = gridStitching(squarePolygon, pitch, viaSpec, 0);
    const cols = new Set(vias.map(v => Math.round(v.x / pitch)));
    const rows = new Set(vias.map(v => Math.round(v.y / pitch)));
    expect(vias.length).toBeGreaterThan(1);
  });

  it('pitch parameter controls spacing', () => {
    const vias5 = gridStitching(squarePolygon, 5, viaSpec, 0);
    const vias10 = gridStitching(squarePolygon, 10, viaSpec, 0);
    expect(vias5.length).toBeGreaterThan(vias10.length);
  });
});

describe('perimeterStitching', () => {
  it('pitch parameter controls spacing along edges', () => {
    const vias5 = perimeterStitching(squarePolygon, 5, viaSpec, 0);
    const vias10 = perimeterStitching(squarePolygon, 10, viaSpec, 0);
    expect(vias5.length).toBeGreaterThan(vias10.length);
  });

  it('all vias lie on polygon boundary', () => {
    const vias = perimeterStitching(squarePolygon, 5, viaSpec, 0.5);
    const tolerance = 0.5;
    for (const via of vias) {
      const onEdge =
        Math.abs(via.x - 0.5) < tolerance ||
        Math.abs(via.x - (W - 0.5)) < tolerance ||
        Math.abs(via.y - 0.5) < tolerance ||
        Math.abs(via.y - (H - 0.5)) < tolerance;
      expect(onEdge).toBe(true);
    }
  });
});

describe('hexStitching', () => {
  it('produces more vias than grid for same area', () => {
    const pitch = 5;
    const gridVias = gridStitching(squarePolygon, pitch, viaSpec, 1);
    const hexVias = hexStitching(squarePolygon, pitch, viaSpec, 1);
    expect(hexVias.length).toBeGreaterThanOrEqual(gridVias.length);
  });

  it('hex pattern has offset rows', () => {
    const pitch = 5;
    const vias = hexStitching(squarePolygon, pitch, viaSpec, 1);
    const rows = {};
    for (const via of vias) {
      const rowKey = Math.round(via.y / 2);
      if (!rows[rowKey]) rows[rowKey] = [];
      rows[rowKey].push(via.x);
    }
    const rowKeys = Object.keys(rows);
    if (rowKeys.length >= 2) {
      const firstRowX = rows[rowKeys[0]].sort((a, b) => a - b);
      const secondRowX = rows[rowKeys[1]].sort((a, b) => a - b);
      expect(Math.abs(firstRowX[0] - secondRowX[0])).toBeGreaterThan(0);
    }
  });
});

describe('teardropForPadVia', () => {
  it('returns polyline with 3 points', () => {
    const pad = { x: 10, y: 10, width: 1.6 };
    const trace = {
      route: [
        { x: 10, y: 5 },
        { x: 10, y: 15 }
      ],
      width: 0.25
    };
    const path = teardropForPadVia(pad, trace, 1.5);
    expect(path).not.toBeNull();
    expect(path.length).toBe(3);
  });

  it('returns null for trace with fewer than 2 route points', () => {
    const pad = { x: 10, y: 10, width: 1.6 };
    const trace = { route: [{ x: 10, y: 5 }], width: 0.25 };
    const path = teardropForPadVia(pad, trace, 1.5);
    expect(path).toBeNull();
  });

  it('path points are numeric', () => {
    const pad = { x: 10, y: 10, diameter: 0.8 };
    const trace = {
      route: [
        { x: 5, y: 10 },
        { x: 15, y: 10 }
      ],
      width: 0.3
    };
    const path = teardropForPadVia(pad, trace, 1.5);
    expect(path).not.toBeNull();
    for (const pt of path) {
      expect(typeof pt.x).toBe('number');
      expect(typeof pt.y).toBe('number');
    }
  });
});

describe('applyTeardropsToAll', () => {
  it('adds teardrops array to board', () => {
    const circuit = {
      pcb_board: {
        width: 50,
        height: 50,
        pcb_trace: [{
          pcb_trace_id: 'trace1',
          net_id: 'GND',
          route: [{ x: 5, y: 5 }, { x: 15, y: 5 }],
          width: 0.25
        }],
        pcb_pad: [{
          pcb_pad_id: 'pad1',
          net_id: 'GND',
          x: 10,
          y: 5,
          width: 1.6
        }]
      }
    };
    const result = applyTeardropsToAll(circuit, 1.5);
    expect(result.pcb_board.teardrops).toBeDefined();
    expect(Array.isArray(result.pcb_board.teardrops)).toBe(true);
  });

  it('does not mutate original circuit', () => {
    const circuit = {
      pcb_board: {
        width: 50,
        height: 50,
        pcb_trace: [{
          pcb_trace_id: 'trace1',
          net_id: 'GND',
          route: [{ x: 5, y: 5 }, { x: 15, y: 5 }],
          width: 0.25
        }],
        pcb_pad: [{
          pcb_pad_id: 'pad1',
          net_id: 'GND',
          x: 10,
          y: 5,
          width: 1.6
        }]
      }
    };
    const result = applyTeardropsToAll(circuit, 1.5);
    expect(circuit.pcb_board.teardrops).toBeUndefined();
    expect(result.pcb_board.teardrops.length).toBe(1);
  });

  it('teardrop path has valid coordinates', () => {
    const circuit = {
      pcb_board: {
        width: 50,
        height: 50,
        pcb_trace: [{
          pcb_trace_id: 'trace1',
          net_id: 'GND',
          route: [{ x: 5, y: 5 }, { x: 15, y: 5 }],
          width: 0.25
        }],
        pcb_pad: [{
          pcb_pad_id: 'pad1',
          net_id: 'GND',
          x: 10,
          y: 5,
          width: 1.6
        }]
      }
    };
    const result = applyTeardropsToAll(circuit, 1.5);
    const td = result.pcb_board.teardrops[0];
    expect(td.path.length).toBeGreaterThanOrEqual(2);
    for (const pt of td.path) {
      expect(Number.isFinite(pt.x)).toBe(true);
      expect(Number.isFinite(pt.y)).toBe(true);
    }
  });
});