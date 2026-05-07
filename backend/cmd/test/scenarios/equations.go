package scenarios

// Equations scenario — exercises the `.equations` file kind end-to-end:
//   - kind='equations' is accepted by POST /files (added in
//     1746577600000_kind_equations migration + the handlers.CreateFile
//     validator).
//   - GET round-trips the JSON content verbatim.
//   - PATCH appends a 4th param referencing an earlier one; GET reflects.
//   - A bad expression doesn't cause persistence to fail — the file's
//     content is stored as-is; the frontend evaluator surfaces the error.
//   - The LLM read_equations tool finds the file and returns the params.
//   - The LLM set_equation tool upserts a row.
//
// Mirrors the user-facing flow: equation files live in the standard files
// table just like any other kind, with no special server-side validation
// of the JSON shape (the contract is "the editor + evaluator reads it").

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/google/uuid"

	"github.com/imranp/kerf/backend/cmd/test/runner"
	"github.com/imranp/kerf/backend/internal/tools"
)

// Equations drives the .equations file kind. Registered in main.go's
// allScenarios.
func Equations(s *runner.Suite, env *runner.Env) {
	c := env.Client
	ctx := context.Background()

	owner, status, raw := registerWS(c, "equations-owner@example.com", "eqpass99hunter", "Equations Owner")
	if !s.Status("register equations owner", status, 201, raw) {
		return
	}
	if !s.True("equations owner default_workspace present", owner.DefaultWorkspace != nil,
		"expected default_workspace on register response") {
		return
	}

	// Create a project under the default workspace using tags + starter
	// (the project_type → tags refactor; see project_tags.go for context).
	var proj struct {
		ID   string   `json:"id"`
		Tags []string `json:"tags"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects", map[string]any{
		"workspace_id": owner.DefaultWorkspace.ID,
		"name":         "Parametric chair",
		"tags":         []string{"furniture"},
		"starter":      "jscad",
	}, owner.AccessToken, &proj)
	if !s.Status("create equations project", status, 201, raw) {
		return
	}
	pid := proj.ID
	pc := tools.ProjectCtx{
		Pool:      env.Pool,
		ProjectID: uuid.MustParse(pid),
		UserID:    uuid.MustParse(owner.User.ID),
		Role:      "owner",
	}

	// --- 1. Create kind='equations' via the API. The first three params
	// form a small chain: wall feeds h feeds outer_radius. ---
	initialJSON := `{
  "version": 1,
  "params": [
    { "name": "wall_thickness", "expr": "2", "unit": "mm", "comment": "Default wall" },
    { "name": "h", "expr": "wall_thickness * 5", "unit": "mm" },
    { "name": "outer_radius", "expr": "h / 2 + 3" }
  ]
}`
	var eqRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
		Name string `json:"name"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "params.equations",
			"kind":      "equations",
			"parent_id": nil,
			"content":   initialJSON,
		}, owner.AccessToken, &eqRow)
	if !s.Status("create equations file", status, 201, raw) {
		return
	}
	s.Equal("equations.kind", eqRow.Kind, "equations")
	s.Equal("equations.name", eqRow.Name, "params.equations")
	s.NotEmpty("equations.id", eqRow.ID)

	// --- 2. GET round-trips the content verbatim. ---
	var eqGet struct {
		Kind    string `json:"kind"`
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+eqRow.ID, nil,
		owner.AccessToken, &eqGet)
	if s.Status("get equations file", status, 200, raw) {
		s.Equal("equations.kind round-trip", eqGet.Kind, "equations")
		s.Equal("equations.content round-trip", eqGet.Content, initialJSON)
	}

	// --- 3. PATCH appends a 4th param that references an earlier one. ---
	patchedJSON := `{
  "version": 1,
  "params": [
    { "name": "wall_thickness", "expr": "2", "unit": "mm", "comment": "Default wall" },
    { "name": "h", "expr": "wall_thickness * 5", "unit": "mm" },
    { "name": "outer_radius", "expr": "h / 2 + 3" },
    { "name": "inner_radius", "expr": "outer_radius - wall_thickness" }
  ]
}`
	var eqPatched struct {
		Kind    string  `json:"kind"`
		Content *string `json:"content"`
	}
	status, raw, _ = c.DoJSON("PATCH", "/api/projects/"+pid+"/files/"+eqRow.ID,
		map[string]any{"content": patchedJSON}, owner.AccessToken, &eqPatched)
	if s.Status("patch equations file", status, 200, raw) {
		s.Equal("equations.kind after patch", eqPatched.Kind, "equations")
		if s.True("equations.content present after patch",
			eqPatched.Content != nil && *eqPatched.Content == patchedJSON,
			"expected patched content, got %v", eqPatched.Content) {
			// Patched content matches.
		}
	}

	// Re-GET to confirm persistence (catches the "PATCH echoed but didn't
	// save" class of bug).
	var eqAfterPatch struct {
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+eqRow.ID, nil,
		owner.AccessToken, &eqAfterPatch)
	if s.Status("get equations after patch", status, 200, raw) {
		s.Contains("equations.content has new param after patch",
			eqAfterPatch.Content, "inner_radius")
	}

	// --- 4. A bad expression doesn't reject persistence. The frontend
	// evaluator is responsible for surfacing the error; the server stores
	// the JSON as-is. ---
	badJSON := `{
  "version": 1,
  "params": [
    { "name": "x", "expr": "1 / 0" }
  ]
}`
	var badRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "bad.equations",
			"kind":      "equations",
			"parent_id": nil,
			"content":   badJSON,
		}, owner.AccessToken, &badRow)
	if s.Status("create bad equations file", status, 201, raw) {
		s.Equal("bad equations kind", badRow.Kind, "equations")
	}
	var badGet struct {
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+badRow.ID, nil,
		owner.AccessToken, &badGet)
	if s.Status("get bad equations file", status, 200, raw) {
		s.Equal("bad equations content round-trip", badGet.Content, badJSON)
	}

	// --- 5. read_equations LLM tool — finds an `.equations` file and
	// returns the parsed JSON. Picks the lexicographically-first one when
	// multiple exist (deterministic). ---
	readOut := runTool(s, ctx, pc, "read_equations", map[string]any{})
	s.Equal("read_equations exists=true", readOut["exists"], true)
	// version is encoded as float64 by encoding/json.
	s.Equal("read_equations version", readOut["version"], float64(1))
	if params, ok := readOut["params"].([]any); s.True("read_equations params is array",
		ok, "expected []any, got %T", readOut["params"]) {
		// bad.equations sorts before params.equations, so it should win.
		s.True("read_equations returned at least 1 param", len(params) > 0,
			"expected ≥1 param, got %d", len(params))
	}

	// --- 6. set_equation LLM tool — upsert a fresh param. We point at
	// the (lexicographically-first) bad.equations file since that's the
	// one read_equations resolves to. ---
	setOut := runTool(s, ctx, pc, "set_equation", map[string]any{
		"name":    "fresh_param",
		"expr":    "42",
		"unit":    "mm",
		"comment": "added by test",
	})
	if _, isErr := setOut["code"]; isErr {
		s.Fail("set_equation upsert", "expected success, got code="+asString(setOut["code"])+
			" error="+asString(setOut["error"]))
	} else {
		s.NotEmpty("set_equation path", asString(setOut["path"]))
		s.NotEmpty("set_equation id", asString(setOut["id"]))
		s.Equal("set_equation echoed name", setOut["name"], "fresh_param")
	}

	// --- 7. Verify the upsert landed by reading the file content back
	// and decoding the JSON. ---
	var afterSet struct {
		Content string `json:"content"`
	}
	upsertedID := asString(setOut["id"])
	if upsertedID != "" {
		status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+upsertedID, nil,
			owner.AccessToken, &afterSet)
		if s.Status("get file after set_equation", status, 200, raw) {
			s.Contains("set_equation persisted name", afterSet.Content, "fresh_param")
			s.Contains("set_equation persisted expr", afterSet.Content, "42")
			// JSON is valid (decodes cleanly).
			var doc map[string]any
			err := json.Unmarshal([]byte(afterSet.Content), &doc)
			s.NoError("file is valid JSON after set_equation", err)
			if params, ok := doc["params"].([]any); ok {
				// Each row carries `name` + `expr` minimally.
				ok2 := true
				for _, p := range params {
					m, _ := p.(map[string]any)
					if _, has := m["name"]; !has {
						ok2 = false
						break
					}
				}
				s.True("every persisted row has name", ok2, "")
			}
		}
	}

	// --- 8. Update an existing param via set_equation (idempotency). ---
	setOut2 := runTool(s, ctx, pc, "set_equation", map[string]any{
		"name": "fresh_param",
		"expr": "100",
	})
	s.Equal("set_equation update echoed name", setOut2["name"], "fresh_param")
	if upsertedID != "" {
		var afterUpdate struct {
			Content string `json:"content"`
		}
		_, _, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+upsertedID, nil,
			owner.AccessToken, &afterUpdate)
		s.Contains("set_equation update persisted expr=100", afterUpdate.Content, "100")
		// The "42" should be gone (it was the previous value of the same param).
		s.True("set_equation update replaced previous expr",
			!strings.Contains(afterUpdate.Content, `"expr": "42"`),
			"expected old expr replaced; content=%s", afterUpdate.Content)
	}
}
