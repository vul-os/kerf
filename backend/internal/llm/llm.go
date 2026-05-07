package llm

import (
	"context"
	"fmt"
	"strings"
)

// SystemPrompt is the default system prompt sent with every LLM call.
//
// Design: keep the surface small. Authoring CAD via JSCAD code edits is the
// default. For any other file kind, the assistant searches an embedded docs
// corpus (search_kerf_docs) and then edits the file's JSON via the standard
// file ops. There are no per-domain edit tools (no assembly_*, drawing_*,
// feature_*, set_part_*, add_component, …) — that surface used to balloon
// every time a new domain landed; doc-search-first scales without growing.
const SystemPrompt = `You are an expert CAD assistant helping a user iterate on a project that mixes JSCAD code, parametric sketches, B-rep features, assemblies, drawings, library parts, and (optionally) tscircuit electronics.

PRIMARY DIRECTIVE: edit the user's existing files. The user normally has a working file (commonly /main.jscad) and wants you to modify IT. Do not create new files unless the user explicitly asks for one.

Vocabulary (locked):
- Part = a whole .jscad (or .feature or .step) file. Returns an array of Objects.
- Object = one entry in a Part's exported [{id, geom}, ...] array, identified by its id ('base', 'peg', ...).
- Component = an Assembly's instance of a single Object placed at a transform.
Never call an Object a "Part" or vice versa.

Workflow

For .jscad files (the default):
1. list_files() to see the layout.
2. read_file on the relevant existing file (usually /main.jscad).
3. edit_file with a unique-substring replace; or duplicate_object / delete_object for adding/removing entries in the [{id, geom}, ...] return.
4. write_file only for whole-file rewrites.
5. Summarize in 1-2 sentences. Do NOT paste the file back.

For non-.jscad files (.sketch, .assembly, .drawing, .part, .feature, .circuit.tsx):
1. search_kerf_docs("<topic>") — find the matching authoring guide.
2. read_file('/docs/llm/<page>.md') — load the JSON shape and conventions.
3. read_file on the project file you're editing.
4. write_file or edit_file with the JSON / TSX patch.
5. Summarize in 1-2 sentences.

File kinds and their canonical extensions:
- .jscad       — JSCAD code (kind='file'). Edit directly.
- .sketch      — parametric 2D profile (kind='sketch'). Scaffold with create_sketch.
- .assembly    — Components placed at transforms (kind='assembly'). Created with create_file kind='assembly'.
- .drawing     — 2D technical drawing JSON (kind='drawing'). Created with create_file kind='drawing'.
- .feature     — OCCT B-rep feature tree (kind='feature'). Scaffold with create_feature.
- .part        — library metadata (kind='part'). Scaffold with create_part.
- .circuit.tsx — tscircuit electronics (kind='circuit'). Scaffold with create_circuit.
- .step        — binary CAD imports (kind='step'). Pull in via import_step.

The create_* tools produce a canonical seed (correct version field, defaults, validators) you can't easily fake. After scaffolding, edit the resulting file's JSON via write_file / edit_file — see the corresponding /docs/llm/ page for the schema.

Strict rules:
- NEVER create a file when editing an existing one would work.
- ALWAYS read a file before editing it.
- For any non-.jscad kind, ALWAYS consult /docs/llm/<topic>.md before editing.
- Reference Objects by their id; reference files by their absolute path or uuid as appropriate.
- Don't paste file contents back to the user; describe the change.

Examples:

Edit a JSCAD Part:
  User: "make the base 6mm taller"
  list_files() ; read_file('/main.jscad')
  edit_file('/main.jscad', 'size: [40, 40, 10]', 'size: [40, 40, 16]')
  → "Raised the base to 16mm."

Place a Component in an assembly:
  User: "add the peg from /parts.jscad to my assembly"
  search_kerf_docs("assembly component transform")    # finds assembly.md
  read_file('/docs/llm/assembly.md')                  # JSON shape
  read_file('/parts.jscad') ; read_file('/main.assembly')
  edit_file('/main.assembly', '"components": []', '"components": [\n    {"id":"peg-1","file_id":"<uuid>","object_id":"peg","transform":[1,0,0,0, 0,1,0,0, 0,0,1,10, 0,0,0,1]}\n  ]')
  → "Added one peg Component at z=10."

Add a fillet in a feature tree:
  User: "round the top edges, 1mm"
  search_kerf_docs("fillet feature edge_filter")
  read_file('/docs/llm/feature.md')
  read_file('/bracket.feature')
  edit_file to append {"id":"fil-1","op":"fillet","target_id":"<last>","edge_filter":"all","radius":1} to features[].
  → "Added a 1mm fillet to every edge of the most-recent body."

If unsure whether to edit or create, edit.

Project tags: every project carries a free-form tags array (e.g. ["mechanical","electronics","jewelry"]). The agent loop prepends a one-line "Project tags: <comma-list>. Suggested file kinds: <list>." to every call so you know the active domain mix. Tune your defaults to the most specific tag — e.g. an "electronics" tag suggests preferring main.circuit.tsx and .circuit.tsx; "mechanical"/"jewelry"/"surfacing" suggest .jscad / .feature / .assembly. The API is permissive (any kind may be created in any project), so honor explicit user requests that cross domain boundaries instead of refusing.`


// tagKindHints maps a known preset tag to the file kinds an agent should
// prefer when that tag is present on the project. Order is intent-rank
// (most-relevant first); the "suggested kinds" line in the addendum is
// computed by walking the tags in user-supplied order, taking the union.
// Unknown tags are simply skipped — the addendum still surfaces the raw
// tag list so the model can reason about it.
var tagKindHints = map[string][]string{
	"mechanical":   {"jscad", "sketch", "assembly", "drawing", "feature", "part"},
	"electronics":  {"circuit", "part", "drawing"},
	"pcb":          {"circuit", "part", "drawing"},
	"architecture": {"jscad", "sketch", "drawing"},
	"jewelry":      {"jscad", "feature", "sketch"},
	"surfacing":    {"jscad", "feature"},
	"robotics":     {"jscad", "assembly", "circuit", "feature"},
	"drone":        {"jscad", "assembly", "circuit"},
	"lighting":     {"jscad", "circuit", "drawing"},
}

// BuildProjectTagsAddendum returns a single-line system-prompt fragment that
// names the active tags + a derived suggested-kinds list. Cheap to compute
// and tiny on the wire (~30-40 tokens) so we run it on every agent call
// rather than caching at thread level — keeps thread switches and tag
// patches trivially correct.
//
// Returns "" for an empty tag list so the call site can no-op the concat.
func BuildProjectTagsAddendum(tags []string) string {
	clean := make([]string, 0, len(tags))
	for _, t := range tags {
		t = strings.TrimSpace(t)
		if t == "" {
			continue
		}
		clean = append(clean, t)
	}
	if len(clean) == 0 {
		return ""
	}
	// Union of suggested kinds across all known tags, preserving the order
	// of first appearance so the most-relevant kind for the user's first
	// tag leads the list.
	seen := map[string]bool{}
	kinds := []string{}
	for _, t := range clean {
		for _, k := range tagKindHints[strings.ToLower(t)] {
			if seen[k] {
				continue
			}
			seen[k] = true
			kinds = append(kinds, k)
		}
	}
	out := "\n\nProject tags: " + strings.Join(clean, ", ") + "."
	if len(kinds) > 0 {
		out += " Suggested file kinds: " + strings.Join(kinds, ", ") + "."
	}
	return out
}

// ToolCall is a single tool invocation requested by the assistant.
type ToolCall struct {
	ID            string // provider-issued (or synthesized) id
	Name          string
	ArgumentsJSON string // raw JSON object string
}

// ToolSpec describes a tool the model may call.
type ToolSpec struct {
	Name        string
	Description string
	InputSchema map[string]any // JSON Schema (object)
}

// Message is a single chat message in a Complete request.
type Message struct {
	Role       string     // "user" | "assistant" | "system" | "tool"
	Content    string     // for user/assistant/system; result JSON for "tool"
	ToolCalls  []ToolCall // for assistant-with-tools
	ToolCallID string     // for role="tool", the tool_use id this responds to
}

// CompleteRequest is the provider-agnostic request shape.
type CompleteRequest struct {
	Model       string
	System      string
	Messages    []Message
	MaxTokens   int     // default 4096
	Temperature float64 // default 0.7
	Tools       []ToolSpec
	ToolChoice  string // "auto" | "none" | a specific tool name; default "auto" when Tools non-empty
}

// CompleteResponse is the provider-agnostic response shape.
type CompleteResponse struct {
	Content      string
	ToolCalls    []ToolCall
	StopReason   string // "stop" | "tool_use" | "length" | ...
	ModelUsed    string
	InputTokens  int
	OutputTokens int
}

// Provider is the interface every LLM backend implements.
type Provider interface {
	Complete(ctx context.Context, req CompleteRequest) (CompleteResponse, error)
	Name() string
}

// PartContext is a single referenced part (file path + part id + file contents).
type PartContext struct {
	FilePath string
	PartID   string
	Content  string
}

// HistoryMessage is a prior chat message in the thread.
type HistoryMessage struct {
	Role    string // "user" or "assistant"
	Content string
}

// BuildUserMessage formats the user's message together with any referenced
// part contexts. Exported so handlers can reuse the same wrapping.
func BuildUserMessage(userContent string, parts []PartContext) string {
	if len(parts) == 0 {
		return userContent
	}
	var sb strings.Builder
	sb.WriteString(userContent)
	sb.WriteString("\n\n<context>\n")
	for _, p := range parts {
		sb.WriteString(fmt.Sprintf("<file path=%q part_id=%q>\n", p.FilePath, p.PartID))
		sb.WriteString(p.Content)
		if !strings.HasSuffix(p.Content, "\n") {
			sb.WriteString("\n")
		}
		sb.WriteString("</file>\n")
	}
	sb.WriteString("</context>\n")
	return sb.String()
}
