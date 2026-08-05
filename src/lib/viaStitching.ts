function generateStitchingPattern(polygon, pitch_mm, via_spec, edge_offset_mm = 0) {
  const { diameter, drill, net_id } = via_spec;
  const radius = diameter / 2;

  const minX = Math.min(...polygon.map(p => p.x));
  const maxX = Math.max(...polygon.map(p => p.x));
  const minY = Math.min(...polygon.map(p => p.y));
  const maxY = Math.max(...polygon.map(p => p.y));

  const offset = edge_offset_mm + radius;
  const innerMinX = minX + offset;
  const innerMaxX = maxX - offset;
  const innerMinY = minY + offset;
  const innerMaxY = maxY - offset;

  if (innerMaxX <= innerMinX || innerMaxY <= innerMinY) {
    return [];
  }

  const cols = Math.floor((innerMaxX - innerMinX) / pitch_mm) + 1;
  const rows = Math.floor((innerMaxY - innerMinY) / pitch_mm) + 1;

  const vias = [];
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const x = innerMinX + col * pitch_mm;
      const y = innerMinY + row * pitch_mm;
      if (x <= maxX - radius && y <= maxY - radius) {
        vias.push({ x, y, net_id, diameter, drill });
      }
    }
  }
  return vias;
}

function gridStitching(polygon, pitch_mm, via_spec, edge_offset_mm = 0) {
  return generateStitchingPattern(polygon, pitch_mm, via_spec, edge_offset_mm);
}

function perimeterStitching(polygon, pitch_mm, via_spec, edge_offset_mm = 0) {
  const { diameter, drill, net_id } = via_spec;
  const radius = diameter / 2;
  const offset = edge_offset_mm + radius;

  const minX = Math.min(...polygon.map(p => p.x));
  const maxX = Math.max(...polygon.map(p => p.x));
  const minY = Math.min(...polygon.map(p => p.y));
  const maxY = Math.max(...polygon.map(p => p.y));

  const leftEdge = minX + offset;
  const rightEdge = maxX - offset;
  const bottomEdge = minY + offset;
  const topEdge = maxY - offset;

  const width = rightEdge - leftEdge;
  const height = topEdge - bottomEdge;

  if (width <= 0 || height <= 0) {
    return [];
  }

  const vias = [];

  const numRight = Math.floor(height / pitch_mm) + 1;
  for (let i = 0; i <= numRight; i++) {
    const y = bottomEdge + i * pitch_mm;
    if (y <= topEdge) {
      vias.push({ x: rightEdge, y, net_id, diameter, drill });
    }
  }

  const numLeft = Math.floor(height / pitch_mm) + 1;
  for (let i = 0; i <= numLeft; i++) {
    const y = bottomEdge + i * pitch_mm;
    if (y <= topEdge) {
      vias.push({ x: leftEdge, y, net_id, diameter, drill });
    }
  }

  const numTop = Math.floor(width / pitch_mm) + 1;
  for (let i = 1; i < numTop; i++) {
    const x = leftEdge + i * pitch_mm;
    if (x < rightEdge) {
      vias.push({ x, y: topEdge, net_id, diameter, drill });
    }
  }

  const numBottom = Math.floor(width / pitch_mm) + 1;
  for (let i = 1; i < numBottom; i++) {
    const x = leftEdge + i * pitch_mm;
    if (x < rightEdge) {
      vias.push({ x, y: bottomEdge, net_id, diameter, drill });
    }
  }

  return vias;
}

function hexStitching(polygon, pitch_mm, via_spec, edge_offset_mm = 0) {
  const { diameter, drill, net_id } = via_spec;
  const radius = diameter / 2;
  const offset = edge_offset_mm + radius;

  const minX = Math.min(...polygon.map(p => p.x));
  const maxX = Math.max(...polygon.map(p => p.x));
  const minY = Math.min(...polygon.map(p => p.y));
  const maxY = Math.max(...polygon.map(p => p.y));

  const innerMinX = minX + offset;
  const innerMaxX = maxX - offset;
  const innerMinY = minY + offset;
  const innerMaxY = maxY - offset;

  if (innerMaxX <= innerMinX || innerMaxY <= innerMinY) {
    return [];
  }

  const rowPitch = pitch_mm * Math.sqrt(3) / 2;
  const colPitch = pitch_mm;

  const width = innerMaxX - innerMinX;
  const height = innerMaxY - innerMinY;

  const cols = Math.floor(width / colPitch) + 2;
  const rows = Math.floor(height / rowPitch) + 2;

  const vias = [];
  for (let row = 0; row < rows; row++) {
    const rowOffset = (row % 2) * (colPitch / 2);
    const y = innerMinY + row * rowPitch;
    const startCol = row % 2 === 0 ? 0 : 1;
    for (let col = startCol; col < cols; col++) {
      const x = innerMinX + col * colPitch + rowOffset;
      if (x >= minX + radius && x <= maxX - radius && y >= minY + radius && y <= maxY - radius) {
        vias.push({ x, y, net_id, diameter, drill });
      }
    }
  }
  return vias;
}

function teardropForPadVia(pad_or_via, trace, radius_factor = 1.5) {
  const px = pad_or_via.x;
  const py = pad_or_via.y;
  const padRadius = (pad_or_via.width || pad_or_via.diameter || 1) / 2;
  const traceWidth = trace.width || 0.25;
  const teardropRadius = traceWidth * radius_factor;

  const route = trace.route || [];
  if (route.length < 2) {
    return null;
  }

  let closestIdx = 0;
  let closestDist = Infinity;
  for (let i = 0; i < route.length; i++) {
    const dx = route[i].x - px;
    const dy = route[i].y - py;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < closestDist) {
      closestDist = dist;
      closestIdx = i;
    }
  }

  const pt = route[closestIdx];
  const dx = px - pt.x;
  const dy = py - pt.y;
  const dist = Math.sqrt(dx * dx + dy * dy);

  if (dist < 0.001) {
    const segIdx = Math.max(0, closestIdx - 1);
    const segPt = route[segIdx];
    const segDx = pt.x - segPt.x;
    const segDy = pt.y - segPt.y;
    const segLen = Math.sqrt(segDx * segDx + segDy * segDy);
    if (segLen > 0.001) {
      const nx = -segDy / segLen;
      const ny = segDx / segLen;
      const baseX = pt.x + nx * traceWidth / 2;
      const baseY = pt.y + ny * traceWidth / 2;
      const tipX = px - nx * teardropRadius;
      const tipY = py - ny * teardropRadius;
      return [
        { x: baseX, y: baseY },
        { x: px, y: py },
        { x: pt.x - nx * traceWidth / 2, y: pt.y - ny * traceWidth / 2 }
      ];
    }
    return null;
  }

  const nx = dx / dist;
  const ny = dy / dist;
  const baseX = pt.x + nx * traceWidth / 2;
  const baseY = pt.y + ny * traceWidth / 2;
  const tipX = px - nx * teardropRadius;
  const tipY = py - ny * teardropRadius;

  return [
    { x: baseX, y: baseY },
    { x: tipX, y: tipY },
    { x: pt.x - nx * traceWidth / 2, y: pt.y - ny * traceWidth / 2 }
  ];
}

function applyTeardropsToAll(circuit_json, radius_factor = 1.5) {
  const circuit = JSON.parse(JSON.stringify(circuit_json));
  const board = circuit.pcb_board || circuit.board;

  if (!board) {
    return circuit;
  }

  if (!board.teardrops) {
    board.teardrops = [];
  }

  const traces = (board.pcb_trace || []).filter(t => t.route && t.route.length >= 2);
  const pads = board.pcb_pad || [];
  const vias = board.pcb_via || [];

  for (const pad of pads) {
    for (const trace of traces) {
      if (trace.net_id === pad.net_id) {
        const path = teardropForPadVia(pad, trace, radius_factor);
        if (path && path.length >= 2) {
          board.teardrops.push({
            pad_id_or_via_id: pad.pcb_pad_id,
            trace_id: trace.pcb_trace_id,
            radius_factor,
            path
          });
        }
      }
    }
  }

  for (const via of vias) {
    for (const trace of traces) {
      if (trace.net_id === via.net_id) {
        const path = teardropForPadVia(via, trace, radius_factor);
        if (path && path.length >= 2) {
          board.teardrops.push({
            pad_id_or_via_id: via.pcb_via_id,
            trace_id: trace.pcb_trace_id,
            radius_factor,
            path
          });
        }
      }
    }
  }

  return circuit;
}

export {
  generateStitchingPattern,
  gridStitching,
  perimeterStitching,
  hexStitching,
  teardropForPadVia,
  applyTeardropsToAll
};