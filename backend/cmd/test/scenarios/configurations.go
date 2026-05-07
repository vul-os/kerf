package scenarios

// Configurations / variants scenario — exercises per-file parameter
// overrides end-to-end:
//   - Part file is created with three configurations (M3 / M4 / M5).
//   - The configurations round-trip through GET (server stores the JSON
//     verbatim).
//   - An assembly references the part with components pinned to M4 and M5.
//   - GET /api/projects/:id/bom returns TWO rows (one per pinned config),
//     each carrying config_id + config_label so the frontend can render
//     them distinctly.
//   - `add_configuration` LLM tool appends an M6 row in place.
//   - `set_active_config` LLM tool re-pins the M4 component to M5 (the
//     M5 row's count goes up, the M4 row disappears).

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/google/uuid"

	"github.com/imranp/kerf/backend/cmd/test/runner"
	"github.com/imranp/kerf/backend/internal/tools"
)

// Configurations is registered in main.go's allScenarios.
func Configurations(s *runner.Suite, env *runner.Env) {
	c := env.Client
	ctx := context.Background()

	owner, status, raw := registerWS(c, "configs-owner@example.com", "configspass99hunter", "Configurations Owner")
	if !s.Status("register configurations owner", status, 201, raw) {
		return
	}
	if !s.True("configs owner default_workspace present", owner.DefaultWorkspace != nil,
		"expected default_workspace on register response") {
		return
	}

	var proj struct {
		ID   string   `json:"id"`
		Tags []string `json:"tags"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects", map[string]any{
		"workspace_id": owner.DefaultWorkspace.ID,
		"name":         "Configurations smoke",
		"tags":         []string{"mechanical"},
		"starter":      "jscad",
	}, owner.AccessToken, &proj)
	if !s.Status("create configurations project", status, 201, raw) {
		return
	}
	pid := proj.ID
	pc := tools.ProjectCtx{
		Pool:      env.Pool,
		ProjectID: uuid.MustParse(pid),
		UserID:    uuid.MustParse(owner.User.ID),
		Role:      "owner",
	}

	// --- 1. Create a Part file with three configurations + an MPN so the
	// BOM aggregator has a stable key. ---
	partJSON := `{
  "version": 1,
  "name": "Cap screw",
  "manufacturer": "McMaster-Carr",
  "mpn": "92290A115",
  "distributors": [
    { "name": "mcmaster", "url": "https://mcmaster.com/92290A115/", "price_usd": 0.42 }
  ],
  "default_config": "M3",
  "configurations": [
    { "id": "M3", "label": "M3 x 8mm",  "params": { "d": 3, "L": 8  } },
    { "id": "M4", "label": "M4 x 10mm", "params": { "d": 4, "L": 10 } },
    { "id": "M5", "label": "M5 x 12mm", "params": { "d": 5, "L": 12 } }
  ]
}`
	var partRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
		Name string `json:"name"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "cap-screw.part",
			"kind":      "part",
			"parent_id": nil,
			"content":   partJSON,
		}, owner.AccessToken, &partRow)
	if !s.Status("create part file", status, 201, raw) {
		return
	}
	s.Equal("part.kind", partRow.Kind, "part")

	// --- 2. Round-trip the configurations array. ---
	var partGet struct {
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+partRow.ID, nil,
		owner.AccessToken, &partGet)
	if s.Status("get part file", status, 200, raw) {
		s.Contains("part configs round-trip M3", partGet.Content, "M3")
		s.Contains("part configs round-trip M5", partGet.Content, "M5")
		s.Contains("part default_config round-trip", partGet.Content, "default_config")
	}

	// --- 3. Create an assembly that references the part with components
	// pinned to M4 and M5. ---
	identityXform := []float64{
		1, 0, 0, 0,
		0, 1, 0, 0,
		0, 0, 1, 0,
		0, 0, 0, 1,
	}
	asmDoc := map[string]any{
		"components": []any{
			map[string]any{
				"id":        "screw-a",
				"file_id":   partRow.ID,
				"object_id": "Cap screw",
				"config_id": "M4",
				"transform": identityXform,
			},
			map[string]any{
				"id":        "screw-b",
				"file_id":   partRow.ID,
				"object_id": "Cap screw",
				"config_id": "M5",
				"transform": identityXform,
			},
		},
	}
	asmContent, _ := json.MarshalIndent(asmDoc, "", "  ")

	var asmRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "main.assembly",
			"kind":      "assembly",
			"parent_id": nil,
			"content":   string(asmContent),
		}, owner.AccessToken, &asmRow)
	if !s.Status("create assembly", status, 201, raw) {
		return
	}
	s.Equal("assembly.kind", asmRow.Kind, "assembly")

	// --- 4. Round-trip: assembly content keeps the config_id pins. ---
	var asmGet struct {
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+asmRow.ID, nil,
		owner.AccessToken, &asmGet)
	if s.Status("get assembly", status, 200, raw) {
		s.Contains("assembly carries config_id M4", asmGet.Content, `"config_id": "M4"`)
		s.Contains("assembly carries config_id M5", asmGet.Content, `"config_id": "M5"`)
	}

	// --- 5. GET /bom — expect TWO rows (one per pinned config), each
	// labelled correctly. ---
	type bomRow struct {
		Part struct {
			Name string `json:"name"`
			MPN  string `json:"mpn"`
		} `json:"part"`
		FileID      string `json:"file_id"`
		Count       int    `json:"count"`
		ConfigID    string `json:"config_id"`
		ConfigLabel string `json:"config_label"`
	}
	type bomResp struct {
		Rows []bomRow `json:"rows"`
	}
	var bom bomResp
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/bom", nil, owner.AccessToken, &bom)
	if s.Status("get bom", status, 200, raw) {
		s.Equal("bom row count = 2", len(bom.Rows), 2)
		seen := map[string]bomRow{}
		for _, r := range bom.Rows {
			seen[r.ConfigID] = r
		}
		if r4, ok := seen["M4"]; s.True("bom has M4 row", ok, "missing M4 row in %s", string(raw)) {
			s.Equal("M4 row file_id", r4.FileID, partRow.ID)
			s.Equal("M4 row count", r4.Count, 1)
			s.Equal("M4 row label", r4.ConfigLabel, "M4 x 10mm")
			s.Equal("M4 row part name", r4.Part.Name, "Cap screw")
			s.Equal("M4 row mpn", r4.Part.MPN, "92290A115")
		}
		if r5, ok := seen["M5"]; s.True("bom has M5 row", ok, "missing M5 row in %s", string(raw)) {
			s.Equal("M5 row file_id", r5.FileID, partRow.ID)
			s.Equal("M5 row count", r5.Count, 1)
			s.Equal("M5 row label", r5.ConfigLabel, "M5 x 12mm")
		}
	}

	// --- 6. add_configuration LLM tool — append an M6 row. ---
	addOut := runTool(s, ctx, pc, "add_configuration", map[string]any{
		"file_id": partRow.ID,
		"id":      "M6",
		"label":   "M6 x 16mm",
		"params":  map[string]any{"d": 6, "L": 16},
	})
	if _, isErr := addOut["code"]; isErr {
		s.Fail("add_configuration", "expected success, got code="+asString(addOut["code"])+
			" error="+asString(addOut["error"]))
	} else {
		s.Equal("add_configuration echoed id", addOut["id"], "M6")
		s.Equal("add_configuration not an update", addOut["updated"], false)
	}

	// Verify the file content has the new row.
	var partAfterAdd struct {
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+partRow.ID, nil,
		owner.AccessToken, &partAfterAdd)
	if s.Status("get part after add_configuration", status, 200, raw) {
		s.Contains("part has M6 row", partAfterAdd.Content, "M6")
		s.Contains("part has M6 label", partAfterAdd.Content, "M6 x 16mm")
	}

	// Re-running add_configuration with the same id should update in place.
	addOut2 := runTool(s, ctx, pc, "add_configuration", map[string]any{
		"file_id": partRow.ID,
		"id":      "M6",
		"label":   "M6 x 20mm",
		"params":  map[string]any{"d": 6, "L": 20},
	})
	s.Equal("add_configuration update echoed id", addOut2["id"], "M6")
	s.Equal("add_configuration is an update", addOut2["updated"], true)

	var partAfterUpdate struct {
		Content string `json:"content"`
	}
	_, _, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+partRow.ID, nil,
		owner.AccessToken, &partAfterUpdate)
	s.Contains("M6 row label updated", partAfterUpdate.Content, "M6 x 20mm")
	s.True("old M6 label gone",
		!strings.Contains(partAfterUpdate.Content, "M6 x 16mm"),
		"expected old label replaced; content=%s", partAfterUpdate.Content)

	// --- 7. set_active_config LLM tool — repin screw-a (M4 → M5). ---
	setOut := runTool(s, ctx, pc, "set_active_config", map[string]any{
		"assembly_file_id": asmRow.ID,
		"component_id":     "screw-a",
		"config_id":        "M5",
	})
	if _, isErr := setOut["code"]; isErr {
		s.Fail("set_active_config", "expected success, got code="+asString(setOut["code"])+
			" error="+asString(setOut["error"]))
	} else {
		s.Equal("set_active_config echoed config_id", setOut["config_id"], "M5")
		s.Equal("set_active_config not cleared", setOut["cleared"], false)
	}

	// BOM after repin: expect ONE row (M5, count=2).
	var bomAfter bomResp
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/bom", nil,
		owner.AccessToken, &bomAfter)
	if s.Status("get bom after repin", status, 200, raw) {
		s.Equal("bom row count after repin = 1", len(bomAfter.Rows), 1)
		if len(bomAfter.Rows) == 1 {
			s.Equal("merged row config_id = M5", bomAfter.Rows[0].ConfigID, "M5")
			s.Equal("merged row count = 2", bomAfter.Rows[0].Count, 2)
		}
	}

	// --- 8. set_active_config with empty config_id clears the pin. ---
	clearOut := runTool(s, ctx, pc, "set_active_config", map[string]any{
		"assembly_file_id": asmRow.ID,
		"component_id":     "screw-a",
		"config_id":        "",
	})
	s.Equal("set_active_config cleared", clearOut["cleared"], true)

	// After clearing, screw-a falls back to default_config (M3); screw-b is
	// still pinned to M5. So we should now see 2 rows: M3 (count=1) and
	// M5 (count=1).
	var bomCleared bomResp
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/bom", nil,
		owner.AccessToken, &bomCleared)
	if s.Status("get bom after clear", status, 200, raw) {
		s.Equal("bom row count after clear = 2", len(bomCleared.Rows), 2)
		seen := map[string]int{}
		for _, r := range bomCleared.Rows {
			seen[r.ConfigID] = r.Count
		}
		s.Equal("M3 row count after clear (default fallback)", seen["M3"], 1)
		s.Equal("M5 row count after clear", seen["M5"], 1)
	}

	// --- 9. add_configuration on a non-supporting kind fails cleanly. ---
	// Create a folder and try to attach a config to it.
	var folderRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "stuff",
			"kind":      "folder",
			"parent_id": nil,
		}, owner.AccessToken, &folderRow)
	s.Status("create folder", status, 201, raw)
	badAdd := runTool(s, ctx, pc, "add_configuration", map[string]any{
		"file_id": folderRow.ID,
		"id":      "X",
		"params":  map[string]any{},
	})
	s.Equal("add_configuration on folder fails with BAD_KIND", badAdd["code"], "BAD_KIND")
}
