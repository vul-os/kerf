package tools

// Equations tools — let the LLM read and upsert project-level parameters in
// a `.equations` JSON file. The file shape is:
//
//   { "version": 1, "params": [
//       { "name": "wall", "expr": "2",       "unit": "mm", "comment": "Default wall" },
//       { "name": "h",    "expr": "wall * 5", "unit": "mm" }
//   ]}
//
// Frontend evaluator (src/lib/equations.js) walks params in declaration order
// and feeds the resolved scope into the JSCAD runner, the .feature evaluator
// (via `${name}` placeholders), and the sketch solver (same `${name}` syntax
// inside dimensional constraint values).
//
// LLM tools intentionally don't evaluate expressions — the source of truth is
// always the JSON file; the browser-side evaluator is canonical.

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/imranp/kerf/backend/internal/llm"
)

// equationsParam mirrors the JSON shape on the wire. Tolerant of extra keys.
type equationsParam struct {
	Name    string `json:"name"`
	Expr    string `json:"expr"`
	Unit    string `json:"unit,omitempty"`
	Comment string `json:"comment,omitempty"`
}

type equationsDoc struct {
	Version int              `json:"version"`
	Params  []equationsParam `json:"params"`
}

// findEquationsFile returns the first `.equations` file in the project.
// If multiple exist, it returns the lexicographically-first by path so the
// LLM has stable behavior across calls. (The runtime evaluator merges all
// `.equations` files in the project, last-loaded wins per duplicate name.)
func findEquationsFile(ctx context.Context, pc ProjectCtx) (uuid.UUID, string, error) {
	rows, err := pc.Pool.Query(ctx,
		`select id, name from files
		 where project_id = $1 and kind = 'equations' and deleted_at is null`,
		pc.ProjectID)
	if err != nil {
		return uuid.Nil, "", err
	}
	defer rows.Close()
	type cand struct {
		id   uuid.UUID
		name string
	}
	var found []cand
	for rows.Next() {
		var c cand
		if err := rows.Scan(&c.id, &c.name); err != nil {
			return uuid.Nil, "", err
		}
		found = append(found, c)
	}
	if len(found) == 0 {
		return uuid.Nil, "", nil
	}
	pick := found[0]
	for _, c := range found[1:] {
		if c.name < pick.name {
			pick = c
		}
	}
	return pick.id, pick.name, nil
}

// ----------------------------- read_equations --------------------------------

var readEquationsSpec = llm.ToolSpec{
	Name: "read_equations",
	Description: "Read the project-level .equations parameter file. Returns the parsed JSON shape {version, params:[{name, expr, unit, comment}, ...]}. If no .equations file exists, returns an empty params array. Equations are mathjs expressions evaluated in declaration order and exposed as named parameters to JSCAD (`{ params: { ... } }`), .feature nodes (`${name}` placeholders), and sketch dimensional constraints (`${name}` placeholders).",
	InputSchema: map[string]any{
		"type":       "object",
		"properties": map[string]any{},
	},
}

func runReadEquations(ctx context.Context, pc ProjectCtx, _ json.RawMessage) (string, error) {
	id, name, err := findEquationsFile(ctx, pc)
	if err != nil {
		return "", err
	}
	if id == uuid.Nil {
		return okPayload(map[string]any{
			"exists":  false,
			"version": 1,
			"params":  []equationsParam{},
		}), nil
	}
	var content string
	if err := pc.Pool.QueryRow(ctx,
		`select content from files where id = $1 and project_id = $2`,
		id, pc.ProjectID).Scan(&content); err != nil {
		return "", err
	}
	var doc equationsDoc
	if strings.TrimSpace(content) != "" {
		_ = json.Unmarshal([]byte(content), &doc)
	}
	if doc.Version == 0 {
		doc.Version = 1
	}
	if doc.Params == nil {
		doc.Params = []equationsParam{}
	}
	return okPayload(map[string]any{
		"exists":  true,
		"path":    "/" + name,
		"id":      id.String(),
		"version": doc.Version,
		"params":  doc.Params,
	}), nil
}

// ------------------------------ set_equation ---------------------------------

var setEquationSpec = llm.ToolSpec{
	Name: "set_equation",
	Description: "Upsert a single named parameter in the project-level .equations file. Creates the file at /params.equations if none exists. The `expr` is a mathjs expression that may reference earlier params by name (e.g. \"wall * 5\"). Use `unit` and `comment` for documentation only — they don't affect evaluation. To delete a param, omit the tool and use edit_file directly on the JSON.",
	InputSchema: map[string]any{
		"type": "object",
		"properties": map[string]any{
			"name": map[string]any{
				"type":        "string",
				"description": "Parameter name (a valid JS identifier: starts with letter/underscore, then letters/digits/underscore).",
			},
			"expr": map[string]any{
				"type":        "string",
				"description": "mathjs expression. May reference earlier params by name.",
			},
			"unit": map[string]any{
				"type":        "string",
				"description": "Optional display unit (e.g. \"mm\", \"deg\"). Display only — not used in evaluation.",
			},
			"comment": map[string]any{
				"type":        "string",
				"description": "Optional inline comment.",
			},
		},
		"required": []string{"name", "expr"},
	},
}

type setEquationArgs struct {
	Name    string `json:"name"`
	Expr    string `json:"expr"`
	Unit    string `json:"unit"`
	Comment string `json:"comment"`
}

// validIdent is a tiny tokenizer for the `name` field. mathjs is more lenient
// but JSCAD destructuring (`{ params: { wall_thickness, h } }`) requires a
// JS identifier.
func validIdent(s string) bool {
	if s == "" {
		return false
	}
	for i, r := range s {
		isLetter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || r == '_'
		isDigit := r >= '0' && r <= '9'
		if i == 0 && !isLetter {
			return false
		}
		if i > 0 && !isLetter && !isDigit {
			return false
		}
	}
	return true
}

func runSetEquation(ctx context.Context, pc ProjectCtx, args json.RawMessage) (string, error) {
	var a setEquationArgs
	if err := json.Unmarshal(args, &a); err != nil {
		return errPayload("invalid args: "+err.Error(), "BAD_ARGS"), nil
	}
	a.Name = strings.TrimSpace(a.Name)
	a.Expr = strings.TrimSpace(a.Expr)
	if !validIdent(a.Name) {
		return errPayload("name must be a valid identifier (letters/digits/underscore, no leading digit)", "BAD_ARGS"), nil
	}
	if a.Expr == "" {
		return errPayload("expr is required", "BAD_ARGS"), nil
	}

	id, name, err := findEquationsFile(ctx, pc)
	if err != nil {
		return "", err
	}

	var doc equationsDoc
	doc.Version = 1
	doc.Params = []equationsParam{}

	if id != uuid.Nil {
		var content string
		if err := pc.Pool.QueryRow(ctx,
			`select content from files where id = $1 and project_id = $2`,
			id, pc.ProjectID).Scan(&content); err != nil {
			return "", err
		}
		if strings.TrimSpace(content) != "" {
			_ = json.Unmarshal([]byte(content), &doc)
		}
		if doc.Version == 0 {
			doc.Version = 1
		}
		if doc.Params == nil {
			doc.Params = []equationsParam{}
		}
	}

	// Upsert: if a param with this name exists, replace; else append.
	updated := false
	for i := range doc.Params {
		if doc.Params[i].Name == a.Name {
			doc.Params[i].Expr = a.Expr
			doc.Params[i].Unit = a.Unit
			doc.Params[i].Comment = a.Comment
			updated = true
			break
		}
	}
	if !updated {
		doc.Params = append(doc.Params, equationsParam{
			Name:    a.Name,
			Expr:    a.Expr,
			Unit:    a.Unit,
			Comment: a.Comment,
		})
	}

	body, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return errPayload(fmt.Sprintf("encode equations: %v", err), "ERROR"), nil
	}

	if id == uuid.Nil {
		// Create at root as /params.equations.
		var newID uuid.UUID
		err = pc.Pool.QueryRow(ctx,
			`insert into files(project_id, parent_id, name, kind, content)
			 values ($1, null, 'params.equations', 'equations', $2)
			 returning id`,
			pc.ProjectID, string(body)).Scan(&newID)
		if err != nil {
			return "", err
		}
		_ = recordRevisionForFile(ctx, pc, newID, string(body), "tool")
		return okPayload(map[string]any{
			"path":    "/params.equations",
			"id":      newID.String(),
			"created": true,
			"name":    a.Name,
		}), nil
	}

	if _, err := pc.Pool.Exec(ctx,
		`update files set content = $1, updated_at = now() where id = $2 and project_id = $3`,
		string(body), id, pc.ProjectID); err != nil {
		return "", err
	}
	_ = recordRevisionForFile(ctx, pc, id, string(body), "tool")
	return okPayload(map[string]any{
		"path":    "/" + name,
		"id":      id.String(),
		"created": false,
		"name":    a.Name,
		"updated": updated,
	}), nil
}
