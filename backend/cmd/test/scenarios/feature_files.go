package scenarios

// File-kind plumbing scenarios for the consolidated `.feature` and
// `.circuit.tsx` kinds.
//
//   - create_feature scaffolds a kind='feature' file (.feature suffix).
//   - create_circuit scaffolds a kind='circuit' file (.circuit.tsx).
//   - The kind row plumbing accepts both kinds via the API as well.
//
// The dedicated per-operation tools (feature_pad / pocket / fillet, plus
// add_component / connect / set_component_prop) were consolidated away.
// The model now mutates these files via write_file / edit_file directly
// after consulting docs/llm/feature.md and docs/llm/circuit.md.

import (
	"context"
	"strings"

	"github.com/google/uuid"

	"github.com/imranp/kerf/backend/cmd/test/runner"
	"github.com/imranp/kerf/backend/internal/tools"
)

// FeatureFiles drives the feature + circuit kind plumbing.
func FeatureFiles(s *runner.Suite, env *runner.Env) {
	c := env.Client
	ctx := context.Background()

	owner, status, raw := registerWS(c, "feat-owner@example.com", "featpass1", "Feat Owner")
	if !s.Status("register feat owner", status, 201, raw) {
		return
	}
	if !s.True("feat owner default_workspace present", owner.DefaultWorkspace != nil,
		"expected default_workspace on register response") {
		return
	}
	var proj struct {
		ID string `json:"id"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects",
		map[string]string{
			"name":         "Feature project",
			"workspace_id": owner.DefaultWorkspace.ID,
		}, owner.AccessToken, &proj)
	if !s.Status("create feat project", status, 201, raw) {
		return
	}
	pid := proj.ID
	pc := tools.ProjectCtx{
		Pool:      env.Pool,
		ProjectID: uuid.MustParse(pid),
		UserID:    uuid.MustParse(owner.User.ID),
		Role:      "owner",
	}

	// --- create_feature: appends .feature, kind='feature'. ---
	out := runTool(s, ctx, pc, "create_feature", map[string]any{
		"path": "/parts/widget.feature",
		"name": "Widget body",
	})
	featID, _ := out["id"].(string)
	if !s.NotEmpty("create_feature id", featID) {
		return
	}
	var kind string
	if err := env.Pool.QueryRow(ctx,
		`select kind from files where id = $1`, featID).Scan(&kind); s.NoError("kind lookup feature", err) {
		s.Equal("feature row kind=feature", kind, "feature")
	}

	// .feature suffix auto-appended.
	out2 := runTool(s, ctx, pc, "create_feature", map[string]any{
		"path": "/parts/auto-suffix",
	})
	pathOut, _ := out2["path"].(string)
	s.True("create_feature auto-suffix .feature",
		strings.HasSuffix(pathOut, ".feature"),
		"path=%q", pathOut)

	// Reserved-extension paths are rejected (.sketch / .assembly / .drawing / .part).
	for _, ext := range []string{".sketch", ".assembly", ".drawing", ".part"} {
		o := runTool(s, ctx, pc, "create_feature", map[string]any{
			"path": "/parts/reserved" + ext,
		})
		s.Equal("create_feature rejects "+ext, o["code"], "BAD_KIND")
	}

	// --- READONLY guards: write_file refuses to CREATE a .feature file
	// (steers to create_feature). create_file with kind='feature' or a
	// .feature suffix is similarly rejected. Editing an EXISTING .feature
	// via write_file IS allowed once the file has been scaffolded. ---
	wfFeat := runTool(s, ctx, pc, "write_file", map[string]any{
		"path":    "/parts/missing.feature",
		"content": "garbage",
	})
	s.Equal("write_file on missing .feature → READONLY_FEATURE",
		wfFeat["code"], "READONLY_FEATURE")
	cfFeat := runTool(s, ctx, pc, "create_file", map[string]any{
		"path": "/parts/foo.feature",
		"kind": "feature",
	})
	s.Equal("create_file kind=feature → READONLY_FEATURE", cfFeat["code"], "READONLY_FEATURE")
	cfFeatSuffix := runTool(s, ctx, pc, "create_file", map[string]any{
		"path": "/parts/bar.feature",
	})
	s.Equal("create_file .feature suffix → READONLY_FEATURE", cfFeatSuffix["code"], "READONLY_FEATURE")

	// --- create_circuit: appends .circuit.tsx, kind='circuit'. ---
	co := runTool(s, ctx, pc, "create_circuit", map[string]any{
		"path":      "/electronics/board",
		"width_mm":  25,
		"height_mm": 25,
	})
	circuitID, _ := co["id"].(string)
	circuitPath, _ := co["path"].(string)
	if !s.NotEmpty("create_circuit id", circuitID) {
		return
	}
	s.True("create_circuit appended .circuit.tsx",
		strings.HasSuffix(circuitPath, ".circuit.tsx"),
		"path=%q", circuitPath)
	if err := env.Pool.QueryRow(ctx,
		`select kind from files where id = $1`, circuitID).Scan(&kind); s.NoError("kind lookup circuit", err) {
		s.Equal("circuit row kind=circuit", kind, "circuit")
	}

	// --- write_file ON .circuit.tsx works (text is canonical TSX, not JSON). ---
	wfCircuit := runTool(s, ctx, pc, "write_file", map[string]any{
		"path":    circuitPath,
		"content": "// hand-edited circuit file\nexport default null\n",
	})
	if _, isErr := wfCircuit["code"]; isErr {
		s.Fail("write_file on .circuit.tsx",
			"expected success, got code="+asString(wfCircuit["code"])+
				" error="+asString(wfCircuit["error"]))
	} else {
		s.True("write_file on .circuit.tsx ok", wfCircuit["bytes"] != nil)
	}
	var content string
	if err := env.Pool.QueryRow(ctx,
		`select content from files where id = $1`, circuitID).Scan(&content); s.NoError("read circuit", err) {
		s.Contains("circuit content has hand-edited marker", content, "hand-edited circuit file")
	}

	// --- The API also accepts these kinds via POST /files (the create_file
	// LLM tool's enum is more restrictive: file|folder|assembly only). ---
	for _, k := range []string{"sketch", "feature", "drawing", "part", "circuit"} {
		var f struct {
			Kind string `json:"kind"`
		}
		status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
			map[string]any{"name": "via-api-" + k, "kind": k},
			owner.AccessToken, &f)
		if s.Status("POST /files kind="+k+" via API", status, 201, raw) {
			s.Equal("API row kind="+k, f.Kind, k)
		}
	}

	// --- "Use in feature" UI workflow: the SketchView toolbar creates a
	// .feature file seeded with a single pad referencing the originating
	// sketch's path. Mirror the createFeatureFromSketch store action with
	// raw API calls and assert the sketch + feature plumbing round-trips. ---
	var sketchRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":    "profile.sketch",
			"kind":    "sketch",
			"content": `{"entities":[]}`,
		}, owner.AccessToken, &sketchRow)
	if s.Status("create sketch via API", status, 201, raw) {
		s.Equal("sketch.kind", sketchRow.Kind, "sketch")
		s.NotEmpty("sketch.id", sketchRow.ID)
	}

	featureSeed := `{"features":[{"id":"f1","op":"pad","sketch_path":"/profile.sketch","height":5,"direction":"up"}]}`
	var featRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "profile.feature",
			"kind":      "feature",
			"parent_id": nil,
			"content":   featureSeed,
		}, owner.AccessToken, &featRow)
	if s.Status("create feature-from-sketch via API", status, 201, raw) {
		s.Equal("feature.kind", featRow.Kind, "feature")
		s.NotEmpty("feature.id", featRow.ID)
	}

	// Round-trip the seeded content via GET /files/:id.
	var featGet struct {
		Kind    string `json:"kind"`
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+featRow.ID, nil,
		owner.AccessToken, &featGet)
	if s.Status("get feature-from-sketch", status, 200, raw) {
		s.Equal("feature.kind round-trip", featGet.Kind, "feature")
		s.Equal("feature.content round-trip", featGet.Content, featureSeed)
	}
}

// asString safely converts an interface{} to string ("" on miss).
func asString(v any) string {
	s, _ := v.(string)
	return s
}
