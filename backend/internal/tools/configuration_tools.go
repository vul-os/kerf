package tools

// Configurations / variants — LLM tools for authoring per-file parameter
// overrides. See backend/internal/llm/docs/configurations.md for the JSON
// shape and a worked example.
//
// Surface area:
//   - `add_configuration(file_id, id, label?, params)` — append a
//     configuration row to a file's JSON content (Part / Feature /
//     Sketch / JSCAD-as-JSON-comment-block). Idempotent: an existing id
//     gets its label + params updated in place.
//   - `set_active_config(assembly_file_id, component_id, config_id)` —
//     pin a specific configuration on an assembly's component. Empty
//     `config_id` clears the pin (component falls back to the file's
//     default_config).
//
// Both tools record a revision so Cmd-Z works.

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/imranp/kerf/backend/internal/llm"
)

// ----------------------------- add_configuration ---------------------------

var addConfigurationSpec = llm.ToolSpec{
	Name: "add_configuration",
	Description: "Append (or update) a configuration on a file that supports per-file parameter overrides — Part (.part), Feature (.feature), or Sketch (.sketch). Configurations let one file declare multiple variants (M3/M4/M5 sizes of one fastener, engraved vs blank lid). Each variant has a stable `id`, a human-readable `label`, and a `params` object whose keys override the equations scope at evaluation time. If a configuration with the same `id` already exists, its label and params are replaced (use this to update). The first configuration added becomes the file's `default_config` automatically.",
	InputSchema: map[string]any{
		"type": "object",
		"properties": map[string]any{
			"file_id": map[string]any{
				"type":        "string",
				"description": "Target file id (must be kind='part', 'feature', or 'sketch').",
			},
			"id": map[string]any{
				"type":        "string",
				"description": "Stable configuration id. Used by assembly components to pin a specific variant. Use a short, alphanumeric token (M3, M4, blank, engraved). Re-using an existing id updates that row in place.",
			},
			"label": map[string]any{
				"type":        "string",
				"description": "Human-readable label for the dropdown. Defaults to `id` when omitted.",
			},
			"params": map[string]any{
				"type":        "object",
				"description": "Object of param-name → value overrides. Merged OVER the equations scope at evaluation time, so collisions resolve to the configuration's value.",
			},
		},
		"required": []string{"file_id", "id"},
	},
}

type addConfigurationArgs struct {
	FileID string         `json:"file_id"`
	ID     string         `json:"id"`
	Label  string         `json:"label"`
	Params map[string]any `json:"params"`
}

func runAddConfiguration(ctx context.Context, pc ProjectCtx, args json.RawMessage) (string, error) {
	var a addConfigurationArgs
	if err := json.Unmarshal(args, &a); err != nil {
		return errPayload("invalid args: "+err.Error(), "BAD_ARGS"), nil
	}
	a.FileID = strings.TrimSpace(a.FileID)
	a.ID = strings.TrimSpace(a.ID)
	if a.FileID == "" {
		return errPayload("file_id is required", "BAD_ARGS"), nil
	}
	if a.ID == "" {
		return errPayload("id is required", "BAD_ARGS"), nil
	}
	if a.Params == nil {
		a.Params = map[string]any{}
	}

	fid, err := uuid.Parse(a.FileID)
	if err != nil {
		return errPayload("file_id must be a uuid: "+err.Error(), "BAD_ARGS"), nil
	}

	var name, kind, content string
	err = pc.Pool.QueryRow(ctx,
		`select name, kind, content from files
		 where id = $1 and project_id = $2 and deleted_at is null`,
		fid, pc.ProjectID).Scan(&name, &kind, &content)
	if err != nil {
		return errPayload("file not found: "+err.Error(), "NOT_FOUND"), nil
	}
	if kind != "part" && kind != "feature" && kind != "sketch" {
		return errPayload(
			fmt.Sprintf("file kind %q does not support configurations (want part / feature / sketch)", kind),
			"BAD_KIND"), nil
	}

	// Parse the JSON, splice in the new configuration, re-emit. We keep
	// the rest of the file's keys untouched — it's a pure additive edit.
	var doc map[string]any
	if strings.TrimSpace(content) != "" {
		if err := json.Unmarshal([]byte(content), &doc); err != nil {
			return errPayload("file is not valid JSON: "+err.Error(), "BAD_FILE"), nil
		}
	}
	if doc == nil {
		doc = map[string]any{}
	}

	// Pull existing configurations array, defaulting to an empty list.
	var existing []map[string]any
	if raw, ok := doc["configurations"]; ok {
		if arr, ok := raw.([]any); ok {
			for _, item := range arr {
				if m, ok := item.(map[string]any); ok {
					existing = append(existing, m)
				}
			}
		}
	}

	// Upsert by id.
	label := a.Label
	if label == "" {
		label = a.ID
	}
	updated := false
	for i := range existing {
		if asString(existing[i]["id"]) == a.ID {
			existing[i] = map[string]any{
				"id":     a.ID,
				"label":  label,
				"params": a.Params,
			}
			updated = true
			break
		}
	}
	if !updated {
		existing = append(existing, map[string]any{
			"id":     a.ID,
			"label":  label,
			"params": a.Params,
		})
	}

	// Re-coerce back to []any so json.Marshal preserves the array shape.
	out := make([]any, len(existing))
	for i, m := range existing {
		out[i] = m
	}
	doc["configurations"] = out

	// First-config defaulting: if there's no default_config yet, point it at
	// the new (or just-edited) row. This matches the editor's behavior.
	if _, has := doc["default_config"]; !has {
		doc["default_config"] = a.ID
	} else if asString(doc["default_config"]) == "" {
		doc["default_config"] = a.ID
	}

	body, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return errPayload("encode failed: "+err.Error(), "ERROR"), nil
	}

	if _, err := pc.Pool.Exec(ctx,
		`update files set content = $1, updated_at = now()
		 where id = $2 and project_id = $3`,
		string(body), fid, pc.ProjectID); err != nil {
		return "", err
	}
	_ = recordRevisionForFile(ctx, pc, fid, string(body), "tool")
	return okPayload(map[string]any{
		"file_id": a.FileID,
		"name":    name,
		"id":      a.ID,
		"label":   label,
		"updated": updated,
	}), nil
}

// asString safely coerces an interface{} (typically from json decoding) to a
// string. Non-string / nil values come back as "".
func asString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

// ----------------------------- set_active_config ---------------------------

var setActiveConfigSpec = llm.ToolSpec{
	Name: "set_active_config",
	Description: "Pin a configuration on an assembly's component. The component (by id, inside an assembly file) gets a `config_id` field that the renderer + BOM aggregator both consult: the M4 instance of a screw and the M5 instance of the same screw show as separate BOM rows. Pass an empty `config_id` to CLEAR the pin — the component then falls back to the file's `default_config`. The component_id is the entry's `id` inside the assembly's `components` array.",
	InputSchema: map[string]any{
		"type": "object",
		"properties": map[string]any{
			"assembly_file_id": map[string]any{
				"type":        "string",
				"description": "The assembly file (kind='assembly') whose component should be repinned.",
			},
			"component_id": map[string]any{
				"type":        "string",
				"description": "The id of the component inside the assembly's `components` array.",
			},
			"config_id": map[string]any{
				"type":        "string",
				"description": "Configuration id to pin (matches a row in the referenced file's `configurations`). Pass an empty string to clear the pin.",
			},
		},
		"required": []string{"assembly_file_id", "component_id"},
	},
}

type setActiveConfigArgs struct {
	AssemblyFileID string `json:"assembly_file_id"`
	ComponentID    string `json:"component_id"`
	ConfigID       string `json:"config_id"`
}

func runSetActiveConfig(ctx context.Context, pc ProjectCtx, args json.RawMessage) (string, error) {
	var a setActiveConfigArgs
	if err := json.Unmarshal(args, &a); err != nil {
		return errPayload("invalid args: "+err.Error(), "BAD_ARGS"), nil
	}
	a.AssemblyFileID = strings.TrimSpace(a.AssemblyFileID)
	a.ComponentID = strings.TrimSpace(a.ComponentID)
	a.ConfigID = strings.TrimSpace(a.ConfigID)
	if a.AssemblyFileID == "" || a.ComponentID == "" {
		return errPayload("assembly_file_id and component_id are required", "BAD_ARGS"), nil
	}

	fid, err := uuid.Parse(a.AssemblyFileID)
	if err != nil {
		return errPayload("assembly_file_id must be a uuid: "+err.Error(), "BAD_ARGS"), nil
	}

	var kind, content string
	err = pc.Pool.QueryRow(ctx,
		`select kind, content from files
		 where id = $1 and project_id = $2 and deleted_at is null`,
		fid, pc.ProjectID).Scan(&kind, &content)
	if err != nil {
		return errPayload("file not found: "+err.Error(), "NOT_FOUND"), nil
	}
	if kind != "assembly" {
		return errPayload(
			fmt.Sprintf("file kind %q is not an assembly", kind),
			"BAD_KIND"), nil
	}

	var doc map[string]any
	if strings.TrimSpace(content) != "" {
		if err := json.Unmarshal([]byte(content), &doc); err != nil {
			return errPayload("file is not valid JSON: "+err.Error(), "BAD_FILE"), nil
		}
	}
	if doc == nil {
		doc = map[string]any{}
	}

	// Locate components[] (legacy `children` is read but normalized to
	// `components` on write — the parseAssembly helper does the same on
	// the frontend).
	rawComponents, _ := doc["components"].([]any)
	if rawComponents == nil {
		if legacy, ok := doc["children"].([]any); ok {
			rawComponents = legacy
		}
	}
	found := false
	for i := range rawComponents {
		entry, ok := rawComponents[i].(map[string]any)
		if !ok {
			continue
		}
		if asString(entry["id"]) != a.ComponentID {
			continue
		}
		if a.ConfigID == "" {
			delete(entry, "config_id")
		} else {
			entry["config_id"] = a.ConfigID
		}
		rawComponents[i] = entry
		found = true
		break
	}
	if !found {
		return errPayload(
			fmt.Sprintf("component %q not found in assembly", a.ComponentID),
			"NOT_FOUND"), nil
	}

	doc["components"] = rawComponents
	delete(doc, "children") // collapse legacy on save.

	body, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return errPayload("encode failed: "+err.Error(), "ERROR"), nil
	}

	if _, err := pc.Pool.Exec(ctx,
		`update files set content = $1, updated_at = now()
		 where id = $2 and project_id = $3`,
		string(body), fid, pc.ProjectID); err != nil {
		return "", err
	}
	_ = recordRevisionForFile(ctx, pc, fid, string(body), "tool")
	return okPayload(map[string]any{
		"assembly_file_id": a.AssemblyFileID,
		"component_id":     a.ComponentID,
		"config_id":        a.ConfigID,
		"cleared":          a.ConfigID == "",
	}), nil
}
