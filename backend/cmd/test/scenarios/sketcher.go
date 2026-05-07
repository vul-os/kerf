package scenarios

// Sketcher scenarios — sketch authoring + cross-cutting Part →
// assembly model resolution.
//
// Sketches (`kind='sketch'`) are scaffolded via create_sketch. The LLM
// surface for editing them via dedicated tools has been consolidated
// away; the model now writes JSON directly via write_file / edit_file
// after consulting docs/llm/sketch.md.

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/imranp/kerf/backend/cmd/test/runner"
	"github.com/imranp/kerf/backend/internal/tools"
)

// Sketcher tests create_sketch + the cross-cutting Part-model wiring.
func Sketcher(s *runner.Suite, env *runner.Env) {
	c := env.Client
	ctx := context.Background()

	owner, status, raw := register(c, "sketch-owner@example.com", "sketchpass1", "Sketch Owner")
	if !s.Status("register sketch owner", status, 201, raw) {
		return
	}
	var proj struct {
		ID string `json:"id"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects",
		map[string]string{"name": "Sketcher project", "workspace_id": owner.DefaultWorkspace.ID}, owner.AccessToken, &proj)
	if !s.Status("create sketch project", status, 201, raw) {
		return
	}
	pid := proj.ID
	pc := tools.ProjectCtx{
		Pool:      env.Pool,
		ProjectID: uuid.MustParse(pid),
		UserID:    uuid.MustParse(owner.User.ID),
		Role:      "owner",
	}

	// --- create_sketch ---
	out := runTool(s, ctx, pc, "create_sketch", map[string]any{
		"path":  "/sketches/profile.sketch",
		"plane": "XZ",
		"name":  "Top profile",
	})
	sketchID, _ := out["id"].(string)
	if !s.NotEmpty("create_sketch id", sketchID) {
		return
	}
	s.Equal("create_sketch plane", out["plane"], "XZ")

	// File row exists with kind='sketch'.
	var kind string
	if err := env.Pool.QueryRow(ctx,
		`select kind from files where id = $1`, sketchID).Scan(&kind); s.NoError("kind lookup", err) {
		s.Equal("sketch row kind=sketch", kind, "sketch")
	}

	// .sketch suffix is auto-appended when missing.
	out2 := runTool(s, ctx, pc, "create_sketch", map[string]any{
		"path": "/sketches/no-suffix",
	})
	pathOut, _ := out2["path"].(string)
	s.True("create_sketch auto-appends .sketch",
		strings.HasSuffix(pathOut, ".sketch"),
		"path=%q does not end in .sketch", pathOut)

	// Re-create same path → EXISTS.
	dup := runTool(s, ctx, pc, "create_sketch", map[string]any{
		"path": "/sketches/profile.sketch",
	})
	s.Equal("create_sketch duplicate path → EXISTS", dup["code"], "EXISTS")

	// --- READONLY guards: write_file / create_file refuse to CREATE a
	// .sketch (they steer to create_sketch). Editing an EXISTING .sketch
	// via write_file IS allowed — that's the contract for in-place
	// authoring. ---
	wfNew := runTool(s, ctx, pc, "write_file", map[string]any{
		"path":    "/sketches/missing.sketch",
		"content": "garbage",
	})
	s.Equal("write_file on missing .sketch → READONLY_SKETCH",
		wfNew["code"], "READONLY_SKETCH")
	cfKind := runTool(s, ctx, pc, "create_file", map[string]any{
		"path": "/sketches/foo.sketch",
		"kind": "sketch",
	})
	s.Equal("create_file kind=sketch → READONLY_SKETCH", cfKind["code"], "READONLY_SKETCH")
	cfSuffix := runTool(s, ctx, pc, "create_file", map[string]any{
		"path": "/sketches/bar.sketch",
	})
	s.Equal("create_file .sketch suffix → READONLY_SKETCH", cfSuffix["code"], "READONLY_SKETCH")

	// Sketch content has the canonical seed (version=1, origin point).
	var content string
	if err := env.Pool.QueryRow(ctx,
		`select content from files where id = $1`, sketchID).Scan(&content); s.NoError("read sketch content", err) {
		s.True("sketch content non-empty", len(content) > 0)
		var doc map[string]any
		if err := json.Unmarshal([]byte(content), &doc); s.NoError("decode sketch json", err) {
			s.Equal("sketch.version=1", doc["version"], float64(1))
			plane, _ := doc["plane"].(map[string]any)
			s.Equal("sketch.plane.name=XZ", plane["name"], "XZ")
		}
	}

	// --- End-to-end sketch → feature handoff ---
	//
	// Mirrors the user-facing flow that "Pad a closed-rectangle sketch"
	// drives: write a hand-crafted sketch JSON containing 4 points + 4 lines
	// forming a closed rectangle, then create a `.feature` file with
	// op:'pad' / 'pocket' / 'hole' referencing that sketch by path. We
	// verify the round-trip is faithful — the sketcher UI relies on the
	// sketch_path being preserved verbatim so the OCCT worker can resolve
	// the profile when evaluating the feature tree. (The actual mesh
	// evaluation happens client-side in the worker; the backend's job is
	// just to persist + serve.)
	rectSketchJSON := `{
  "version": 1,
  "plane": {"type": "base", "name": "XY"},
  "entities": [
    {"id": "origin", "type": "point", "x": 0, "y": 0},
    {"id": "p_tl", "type": "point", "x": 0, "y": 10},
    {"id": "p_tr", "type": "point", "x": 20, "y": 10},
    {"id": "p_br", "type": "point", "x": 20, "y": 0},
    {"id": "ln_top",    "type": "line", "p1": "p_tl", "p2": "p_tr"},
    {"id": "ln_right",  "type": "line", "p1": "p_tr", "p2": "p_br"},
    {"id": "ln_bottom", "type": "line", "p1": "p_br", "p2": "origin"},
    {"id": "ln_left",   "type": "line", "p1": "origin", "p2": "p_tl"}
  ],
  "constraints": [
    {"id": "cn_h1", "type": "horizontal", "line": "ln_top"},
    {"id": "cn_h2", "type": "horizontal", "line": "ln_bottom"},
    {"id": "cn_v1", "type": "vertical",   "line": "ln_left"},
    {"id": "cn_v2", "type": "vertical",   "line": "ln_right"}
  ],
  "visible_3d": [],
  "solved": {},
  "metadata": {}
}`
	out3 := runTool(s, ctx, pc, "create_sketch", map[string]any{
		"path":  "/sketches/rect.sketch",
		"plane": "XY",
		"name":  "Rect profile",
	})
	rectSketchID, _ := out3["id"].(string)
	if !s.NotEmpty("create_sketch rect id", rectSketchID) {
		return
	}
	rectSketchPath, _ := out3["path"].(string)
	s.NotEmpty("create_sketch rect path", rectSketchPath)
	// Overwrite the seeded content with the rectangle profile. write_file
	// on an existing .sketch is allowed (the READONLY guard only blocks
	// CREATE); the SketchView calls the same persistence route under the
	// hood when its solver fires.
	wfRect := runTool(s, ctx, pc, "write_file", map[string]any{
		"path":    rectSketchPath,
		"content": rectSketchJSON,
	})
	if _, isErr := wfRect["code"]; isErr {
		s.Fail("write_file rect sketch",
			"expected success, got code="+asString(wfRect["code"])+
				" error="+asString(wfRect["error"]))
		return
	}
	var rectGet struct {
		Kind    string `json:"kind"`
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+rectSketchID, nil,
		owner.AccessToken, &rectGet)
	if s.Status("get rect sketch", status, 200, raw) {
		s.Equal("rect sketch kind", rectGet.Kind, "sketch")
		s.Contains("rect sketch content has 4 lines", rectGet.Content, "ln_bottom")
	}

	// Pad feature referencing the rectangle sketch by path. The seed shape
	// matches what the SketchView's "New feature from sketch" toolbar emits
	// (see workspace.js#createFeatureFromSketch).
	padFeatureSeed := fmt.Sprintf(
		`{"version":1,"name":"Padded rect","features":[{"id":"f_pad","op":"pad","sketch_path":%q,"height":5,"direction":"up"}]}`,
		rectSketchPath,
	)
	var padFeat struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "rect-pad.feature",
			"kind":      "feature",
			"parent_id": nil,
			"content":   padFeatureSeed,
		}, owner.AccessToken, &padFeat)
	if !s.Status("create pad feature", status, 201, raw) {
		return
	}
	s.Equal("pad feature kind", padFeat.Kind, "feature")
	s.NotEmpty("pad feature id", padFeat.ID)

	// Round-trip the pad feature: the sketch_path must be byte-identical
	// after the file goes through persistence (the OCCT worker resolves
	// profiles by exact-string path match against the loaded sketches map).
	var padGet struct {
		Kind    string `json:"kind"`
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+padFeat.ID, nil,
		owner.AccessToken, &padGet)
	if s.Status("get pad feature", status, 200, raw) {
		s.Equal("pad feature kind round-trip", padGet.Kind, "feature")
		s.Equal("pad feature content round-trip", padGet.Content, padFeatureSeed)
		s.Contains("pad feature content has sketch_path",
			padGet.Content, rectSketchPath)
		s.Contains("pad feature content has op:pad", padGet.Content, `"op":"pad"`)
	}

	// Pocket feature referencing the same sketch. Pocket sits AFTER the
	// pad in the same tree — the OCCT evaluator threads `current` through
	// the ops and the pocket subtracts from the pad result.
	pocketFeatureSeed := fmt.Sprintf(
		`{"version":1,"name":"Padded + pocketed","features":[{"id":"f_pad","op":"pad","sketch_path":%q,"height":10,"direction":"up"},{"id":"f_pocket","op":"pocket","sketch_path":%q,"depth":3}]}`,
		rectSketchPath, rectSketchPath,
	)
	var pocketFeat struct {
		ID string `json:"id"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "rect-pocket.feature",
			"kind":      "feature",
			"parent_id": nil,
			"content":   pocketFeatureSeed,
		}, owner.AccessToken, &pocketFeat)
	if !s.Status("create pocket feature", status, 201, raw) {
		return
	}
	s.NotEmpty("pocket feature id", pocketFeat.ID)
	var pocketGet struct {
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+pocketFeat.ID, nil,
		owner.AccessToken, &pocketGet)
	if s.Status("get pocket feature", status, 200, raw) {
		s.Contains("pocket feature has op:pocket", pocketGet.Content, `"op":"pocket"`)
		s.Contains("pocket feature carries sketch_path", pocketGet.Content, rectSketchPath)
	}

	// Hole feature: needs a center sketch with a single point (or a circle
	// whose center is the hole position). Use the same rectangle sketch's
	// existing point — the hole op picks the first non-origin point as
	// the hole center.
	holeFeatureSeed := fmt.Sprintf(
		`{"version":1,"name":"Padded + drilled","features":[{"id":"f_pad","op":"pad","sketch_path":%q,"height":10,"direction":"up"},{"id":"f_hole","op":"hole","sketch_path":%q,"diameter":3,"depth":15}]}`,
		rectSketchPath, rectSketchPath,
	)
	var holeFeat struct {
		ID string `json:"id"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "rect-hole.feature",
			"kind":      "feature",
			"parent_id": nil,
			"content":   holeFeatureSeed,
		}, owner.AccessToken, &holeFeat)
	if !s.Status("create hole feature", status, 201, raw) {
		return
	}
	s.NotEmpty("hole feature id", holeFeat.ID)
	var holeGet struct {
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+holeFeat.ID, nil,
		owner.AccessToken, &holeGet)
	if s.Status("get hole feature", status, 200, raw) {
		s.Contains("hole feature has op:hole", holeGet.Content, `"op":"hole"`)
		s.Contains("hole feature has diameter", holeGet.Content, `"diameter":3`)
	}

	// --- Part with model_storage_key referenced by an assembly: BOM
	// rollup must surface model_storage_key on the part row. ---
	storageKey := "projects/" + pid + "/assets/test-model.step"
	createPartOut := runTool(s, ctx, pc, "create_part", map[string]any{
		"path": "/library/widget.part",
		"metadata": map[string]any{
			"name":              "Widget",
			"mpn":               "W-001",
			"model_storage_key": storageKey,
			"model_mime_type":   "model/step",
		},
	})
	partID, _ := createPartOut["id"].(string)
	if !s.NotEmpty("create part with model_storage_key", partID) {
		return
	}

	assyContent := fmt.Sprintf(`{"version":1,"components":[{"file_id":%q,"object_id":""}]}`, partID)
	var assy struct {
		ID string `json:"id"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{"name": "main.assembly", "kind": "assembly", "content": assyContent},
		owner.AccessToken, &assy)
	if !s.Status("create assembly with widget part", status, 201, raw) {
		return
	}

	// BOM rollup carries through model_storage_key on the row's Part.
	var bom struct {
		Rows []struct {
			Part struct {
				ModelStorageKey string `json:"model_storage_key"`
				Name            string `json:"name"`
			} `json:"part"`
			Count int `json:"count"`
		} `json:"rows"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/bom",
		nil, owner.AccessToken, &bom)
	if s.Status("GET /bom widget", status, 200, raw) {
		if s.Equal("bom rows for widget", len(bom.Rows), 1) && len(bom.Rows) == 1 {
			s.Equal("bom row.Part.model_storage_key passed through",
				bom.Rows[0].Part.ModelStorageKey, storageKey)
			s.Equal("bom row.Part.Name", bom.Rows[0].Part.Name, "Widget")
		}
	}
}
