package scenarios

// ScriptKind scenario — exercises the `.script.ts` file kind end-to-end:
//   - kind='script' is accepted by POST /files (added in
//     1746578200000_kind_script migration + the handlers.CreateFile
//     validator).
//   - kind='not_a_real_kind' is rejected at the handler validator with a 400.
//   - GET round-trips kind + TypeScript content byte-identical.
//
// The script file is a plain TypeScript source today. The eventual engine
// (esbuild-wasm bundler in a Web Worker, typed `kerf.*` API, fixed-RPC
// backend ops) is deferred — Phase 1 ships only the file-kind shape so
// the engine has a stable target to write to/read from.
//
// Mirrors simulation_kind.go for register/setup conventions.

import (
	"github.com/imranp/kerf/backend/cmd/test/runner"
)

// ScriptKind drives the .script.ts file kind. Registered in main.go's
// allScenarios.
func ScriptKind(s *runner.Suite, env *runner.Env) {
	c := env.Client

	owner, status, raw := registerWS(c, "script-owner@example.com", "scrpass99hunter", "Script Owner")
	if !s.Status("register script owner", status, 201, raw) {
		return
	}
	if !s.True("script owner default_workspace present", owner.DefaultWorkspace != nil,
		"expected default_workspace on register response") {
		return
	}

	// Holding project.
	var proj struct {
		ID string `json:"id"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects", map[string]any{
		"workspace_id": owner.DefaultWorkspace.ID,
		"name":         "Script project",
		"tags":         []string{"automation"},
	}, owner.AccessToken, &proj)
	if !s.Status("create script project", status, 201, raw) {
		return
	}
	pid := proj.ID

	// --- 1. kind validator: 'script' is accepted -------------------------
	// Sample TypeScript source the (still deferred) engine will eventually
	// bundle and execute. Today the kind is just a shape gate so scripts
	// are queryable, restorable via file_revisions, and shareable on
	// Workshop. Intentionally exercises a top-level await + import shape so
	// the future esbuild-wasm bundler has a non-trivial reference.
	scriptSrc := `// hello.script.ts — Phase 1 stub
import { kerf } from "kerf"

export default async function main() {
  const proj = await kerf.project.current()
  console.log("Hello from " + proj.name)
}
`
	var scriptRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
		Name string `json:"name"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "hello.script.ts",
			"kind":      "script",
			"parent_id": nil,
			"content":   scriptSrc,
		}, owner.AccessToken, &scriptRow)
	if !s.Status("create script file", status, 201, raw) {
		return
	}
	s.Equal("script.kind echoed", scriptRow.Kind, "script")
	s.Equal("script.name echoed", scriptRow.Name, "hello.script.ts")
	s.NotEmpty("script.id", scriptRow.ID)

	// --- 2. GET round-trips kind + content byte-identical ----------------
	var scriptGet struct {
		Kind    string `json:"kind"`
		Content string `json:"content"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/projects/"+pid+"/files/"+scriptRow.ID, nil,
		owner.AccessToken, &scriptGet)
	if s.Status("get script file", status, 200, raw) {
		s.Equal("script.kind round-trip", scriptGet.Kind, "script")
		s.Equal("script.content round-trip byte-identical", scriptGet.Content, scriptSrc)
	}

	// --- 3. kind validator rejects an unknown kind ----------------------
	// The handler's createFileReq validator lists allowed kinds and
	// surfaces the rejection as 400 (NOT a DB integrity-violation 500).
	// If a future refactor moves the gate to the DB the constraint check
	// would also reject — but the contract stays "do NOT silently
	// succeed".
	var badRow struct {
		ID   string `json:"id"`
		Kind string `json:"kind"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects/"+pid+"/files",
		map[string]any{
			"name":      "wat.junk",
			"kind":      "not_a_real_kind",
			"parent_id": nil,
			"content":   "",
		}, owner.AccessToken, &badRow)
	s.Equal("invalid kind rejected with 400", status, 400)
	s.True("invalid kind did NOT silently succeed (no id assigned)",
		badRow.ID == "", "got id=%q", badRow.ID)
}
