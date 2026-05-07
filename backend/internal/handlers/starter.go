package handlers

// Starter-file registry: which seed file the CreateProject handler emits
// for a fresh project. Picked by an explicit "starter" field on the create
// request (not derived from project tags) so the user can opt into a circuit
// starter on a "mechanical" tag combo or a JSCAD starter on an "electronics"
// project. Mirrored on the frontend in src/lib/projectTags.js.
//
// History: this file used to be projecttype.go and held the now-defunct
// project_type enum + per-type kinds map. We dropped that surface in favor
// of free-form tags + an explicit starter pick — see ROADMAP.md "Drop
// project types → free-form tags" and CONTRACT.md "Project tags".

// ProjectTypeStarter describes the seed file the CreateProject handler emits
// for a fresh project. The starter goes through the same files table +
// filesystem mirror path as any other create.
type ProjectTypeStarter struct {
	Name string // e.g. "main.jscad", "main.circuit.tsx"
	Kind string // e.g. "file", "circuit"
	// Body is the file's initial content; empty string for "create empty".
	Body string
}

// DefaultStarter is the starter id used when the create request omits the
// "starter" field. JSCAD has been Kerf's default since day one.
const DefaultStarter = "jscad"

// IsValidStarter reports whether the given starter id is recognized by
// StarterFor. The set is small and locked — adding a new starter means
// updating both the StarterFor switch and this validator.
func IsValidStarter(s string) bool {
	switch s {
	case "jscad", "circuit", "blank":
		return true
	}
	return false
}

// StarterFor returns the seed file for a given starter kind. The kinds are:
//   - "jscad"   → main.jscad with the canonical JSCAD hello-world body.
//   - "circuit" → main.circuit.tsx with a minimal tscircuit board.
//   - "blank"   → no starter file (Name=="" tells the handler to skip insert).
func StarterFor(kind string) ProjectTypeStarter {
	switch kind {
	case "circuit":
		return ProjectTypeStarter{
			Name: "main.circuit.tsx",
			Kind: "circuit",
			Body: defaultCircuitTSX,
		}
	case "blank":
		return ProjectTypeStarter{}
	case "jscad":
		fallthrough
	default:
		return ProjectTypeStarter{
			Name: "main.jscad",
			Kind: "file",
			Body: defaultJSCAD,
		}
	}
}

// defaultCircuitTSX is the starter for an electronics-flavored project.
// Mirrors the minimal tscircuit "hello-world" so the user can see something
// render before the dedicated electronics editor lands.
const defaultCircuitTSX = `// Kerf: tscircuit starter. Default export is a <board /> component.
// See /docs/llm/circuit.md once the docs corpus ships an electronics page.
export default () => (
  <board width="20mm" height="20mm">
    <resistor name="R1" resistance="1k" footprint="0402" />
    <capacitor name="C1" capacitance="100nF" footprint="0402" />
    <trace from=".R1 .pin1" to=".C1 .pin1" />
  </board>
)
`
