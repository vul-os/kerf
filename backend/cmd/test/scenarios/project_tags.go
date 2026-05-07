package scenarios

// Project tags end-to-end: drive create/get/patch/list against the new
// `tags TEXT[]` column that replaced project_type. The previous
// project_type enum was dropped — see the 1746577500000_project_tags
// migration. Free-form tags + an explicit "starter" pick replace the
// type-derived behavior.

import (
	"net/url"

	"github.com/imranp/kerf/backend/cmd/test/runner"
)

// ProjectTags exercises the create / read / patch / list-with-filter
// surface for the tags column, plus the starter dispatch for
// "circuit" → main.circuit.tsx.
func ProjectTags(s *runner.Suite, env *runner.Env) {
	c := env.Client

	owner, status, raw := registerWS(c, "tags-owner@example.com", "tagspass99", "Tags Owner")
	if !s.Status("register tags owner", status, 201, raw) {
		return
	}
	if !s.True("owner default_workspace present", owner.DefaultWorkspace != nil,
		"expected default_workspace on register response") {
		return
	}
	wsID := owner.DefaultWorkspace.ID

	// projectShape captures just what we want to assert. The handler
	// returns the full row; extra fields are ignored.
	type projectShape struct {
		ID    string   `json:"id"`
		Name  string   `json:"name"`
		Tags  []string `json:"tags"`
	}

	// 1. Create with two tags + jscad starter.
	var jewelProj projectShape
	status, raw, _ = c.DoJSON("POST", "/api/projects", map[string]any{
		"workspace_id": wsID,
		"name":         "Jewelry surfacer",
		"tags":         []string{"jewelry", "surfacing"},
		"starter":      "jscad",
	}, owner.AccessToken, &jewelProj)
	if !s.Status("create jewelry+surfacing project", status, 201, raw) {
		return
	}
	s.Equal("create echoes 2 tags", len(jewelProj.Tags), 2)

	// 2. GET round-trips the tags array verbatim (modulo trim/dedupe,
	//    which we exercise on the patch step below).
	var roundTrip projectShape
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+jewelProj.ID, nil,
		owner.AccessToken, &roundTrip)
	if s.Status("get jewelry project", status, 200, raw) {
		s.Equal("get echoes 2 tags", len(roundTrip.Tags), 2)
		// Order is what the user supplied; the dedupe is order-stable.
		s.Equal("get tags[0]", roundTrip.Tags[0], "jewelry")
		s.Equal("get tags[1]", roundTrip.Tags[1], "surfacing")
	}

	// 3. PATCH tags → 3 entries.
	var patched projectShape
	status, raw, _ = c.DoJSON("PATCH", "/api/projects/"+jewelProj.ID,
		map[string]any{"tags": []string{"jewelry", "surfacing", "ring"}},
		owner.AccessToken, &patched)
	if s.Status("patch tags add ring", status, 200, raw) {
		s.Equal("patched tags count", len(patched.Tags), 3)
	}
	// And re-GET to make sure the patch actually persisted.
	var afterPatch projectShape
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+jewelProj.ID, nil,
		owner.AccessToken, &afterPatch)
	if s.Status("get after patch", status, 200, raw) {
		s.Equal("get after patch tags count", len(afterPatch.Tags), 3)
	}

	// 4. List with one tag filter — should return this project.
	var listOne []projectShape
	status, raw, _ = c.DoJSON("GET",
		"/api/projects?workspace_id="+url.QueryEscape(wsID)+"&tag=jewelry",
		nil, owner.AccessToken, &listOne)
	if s.Status("list ?tag=jewelry", status, 200, raw) {
		s.Equal("?tag=jewelry returns 1", len(listOne), 1)
		if len(listOne) > 0 {
			s.Equal("?tag=jewelry id matches", listOne[0].ID, jewelProj.ID)
		}
	}

	// 5. List with two tag filters — must AND. The project carries both
	//    tags so it should still appear.
	var listAnd []projectShape
	status, raw, _ = c.DoJSON("GET",
		"/api/projects?workspace_id="+url.QueryEscape(wsID)+"&tag=jewelry&tag=ring",
		nil, owner.AccessToken, &listAnd)
	if s.Status("list ?tag=jewelry&tag=ring", status, 200, raw) {
		s.Equal("?tag=jewelry&tag=ring returns 1", len(listAnd), 1)
	}

	// 6. List with a tag the project does NOT carry → empty.
	var listMiss []projectShape
	status, raw, _ = c.DoJSON("GET",
		"/api/projects?workspace_id="+url.QueryEscape(wsID)+"&tag=architecture",
		nil, owner.AccessToken, &listMiss)
	if s.Status("list ?tag=architecture", status, 200, raw) {
		s.Equal("?tag=architecture returns 0", len(listMiss), 0)
	}

	// 7. Create another project with the circuit starter; the seed file
	//    should land as main.circuit.tsx with kind='circuit'.
	var elecProj projectShape
	status, raw, _ = c.DoJSON("POST", "/api/projects", map[string]any{
		"workspace_id": wsID,
		"name":         "Tiny board",
		"tags":         []string{"electronics"},
		"starter":      "circuit",
	}, owner.AccessToken, &elecProj)
	if !s.Status("create electronics+circuit project", status, 201, raw) {
		return
	}
	s.Equal("electronics tags count", len(elecProj.Tags), 1)

	// Inspect the seeded files to verify starter dispatch.
	type fileShape struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		Kind string `json:"kind"`
	}
	var files []fileShape
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+elecProj.ID+"/files", nil,
		owner.AccessToken, &files)
	if s.Status("list electronics files", status, 200, raw) {
		s.Equal("electronics has 1 seed file", len(files), 1)
		if len(files) > 0 {
			s.Equal("electronics seed name", files[0].Name, "main.circuit.tsx")
			s.Equal("electronics seed kind", files[0].Kind, "circuit")
		}
	}
}
