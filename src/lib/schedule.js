export function defaultSchedule() {
  return {
    version: 1,
    name: "Untitled Schedule",
    target_category: "Wall",
    filters: [],
    columns: [],
    group_by: null,
    sort_by: null,
  };
}

export function validateSchedule(s) {
  const errors = [];
  if (!s) {
    errors.push("schedule is null or undefined");
    return { ok: false, errors };
  }
  if (typeof s.version !== "number") errors.push("version must be a number");
  if (s.version !== 1) errors.push("version must be 1");
  if (typeof s.name !== "string" || !s.name) errors.push("name must be a non-empty string");
  const validCategories = ["Wall", "Door", "Window", "Room", "Slab", "Space", "Opening", "Level", "Site"];
  if (!validCategories.includes(s.target_category)) {
    errors.push(`target_category must be one of: ${validCategories.join(", ")}`);
  }
  if (!Array.isArray(s.filters)) errors.push("filters must be an array");
  else {
    s.filters.forEach((f, i) => {
      if (!f.field || typeof f.field !== "string") errors.push(`filters[${i}].field must be a string`);
      const validOps = ["eq", "ne", "gt", "lt", "gte", "lte", "in", "contains"];
      if (!validOps.includes(f.op)) errors.push(`filters[${i}].op must be one of: ${validOps.join(", ")}`);
      if (f.value === undefined) errors.push(`filters[${i}].value is required`);
    });
  }
  if (!Array.isArray(s.columns)) errors.push("columns must be an array");
  else {
    s.columns.forEach((c, i) => {
      if (!c.field || typeof c.field !== "string") errors.push(`columns[${i}].field must be a string`);
    });
  }
  if (s.group_by !== null && s.group_by !== undefined && typeof s.group_by !== "string") {
    errors.push("group_by must be a string or null");
  }
  if (s.sort_by !== null && s.sort_by !== undefined && typeof s.sort_by !== "string") {
    errors.push("sort_by must be a string or null");
  }
  return { ok: errors.length === 0, errors };
}

function applyFilter(element, filter) {
  const fieldValue = getNestedValue(element, filter.field);
  const filterValue = filter.value;

  switch (filter.op) {
    case "eq":
      return fieldValue === filterValue;
    case "ne":
      return fieldValue !== filterValue;
    case "gt":
      return fieldValue > filterValue;
    case "lt":
      return fieldValue < filterValue;
    case "gte":
      return fieldValue >= filterValue;
    case "lte":
      return fieldValue <= filterValue;
    case "in":
      if (Array.isArray(filterValue)) return filterValue.includes(fieldValue);
      return false;
    case "contains":
      if (typeof fieldValue === "string") return fieldValue.includes(filterValue);
      if (Array.isArray(fieldValue)) return fieldValue.includes(filterValue);
      return false;
    default:
      return true;
  }
}

function getNestedValue(obj, path) {
  if (!path) return undefined;
  const keys = path.split(".");
  let value = obj;
  for (const key of keys) {
    if (value === null || value === undefined) return undefined;
    value = value[key];
  }
  return value;
}

function getElementsByCategory(bimDoc, category) {
  if (!bimDoc) return [];
  const elements = bimDoc.elements || [];
  const pluralMap = {
    Wall: "walls",
    Door: "doors",
    Window: "windows",
    Room: "rooms",
    Slab: "slabs",
    Space: "spaces",
    Opening: "openings",
    Level: "levels",
    Site: "site",
  };
  const key = pluralMap[category];
  if (!key) return [];
  if (category === "Site") {
    return bimDoc.site ? [bimDoc.site] : [];
  }
  return elements.filter((el) => {
    const elCategory = getNestedValue(el, "category") || getNestedValue(el, "type");
    return elCategory === category || el.type === category;
  });
}

function applyGroupBy(rows, groupBy) {
  if (!groupBy) return rows.map((r) => [r]);
  const groups = {};
  for (const row of rows) {
    const key = getNestedValue(row, groupBy) || "(empty)";
    if (!groups[key]) groups[key] = [];
    groups[key].push(row);
  }
  return Object.values(groups);
}

function sortRows(rows, sortBy) {
  if (!sortBy) return rows;
  const [field, direction = "asc"] = sortBy.split(":");
  return [...rows].sort((a, b) => {
    const aVal = getNestedValue(a, field) || "";
    const bVal = getNestedValue(b, field) || "";
    let cmp = 0;
    if (typeof aVal === "number" && typeof bVal === "number") {
      cmp = aVal - bVal;
    } else {
      cmp = String(aVal).localeCompare(String(bVal));
    }
    return direction === "desc" ? -cmp : cmp;
  });
}

export function runSchedule(scheduleDoc, bimDoc) {
  if (!scheduleDoc || !bimDoc) {
    return { columns: [], rows: [] };
  }

  const { target_category, filters = [], columns = [], group_by, sort_by } = scheduleDoc;

  let elements = getElementsByCategory(bimDoc, target_category);

  for (const filter of filters) {
    elements = elements.filter((el) => applyFilter(el, filter));
  }

  const processedRows = elements.map((el) => {
    const row = {};
    for (const col of columns) {
      const value = getNestedValue(el, col.field);
      row[col.field] = value !== undefined ? value : null;
    }
    return row;
  });

  const sortedRows = sortRows(processedRows, sort_by);
  const groupedRows = applyGroupBy(sortedRows, group_by);

  const outputColumns = columns.map((col) => ({
    field: col.field,
    label: col.label || col.field,
    format: col.format || null,
  }));

  return {
    columns: outputColumns,
    rows: groupedRows,
  };
}