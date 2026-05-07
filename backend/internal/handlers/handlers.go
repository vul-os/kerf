package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/imranp/kerf/backend/internal/auth"
	"github.com/imranp/kerf/backend/internal/config"
	"github.com/imranp/kerf/backend/internal/distributors"
	"github.com/imranp/kerf/backend/internal/filesystem"
	"github.com/imranp/kerf/backend/internal/llm"
	"github.com/imranp/kerf/backend/internal/storage"
)

// DistributorsRegistry is the slice of *distributors.Registry the admin handlers
// need. Kept as an interface so cloud_enabled can swap a concrete *Registry
// in via the type assertion in distributor_admin's RefreshPart path.
type DistributorsRegistry interface {
	Meta() []distributors.ServiceMeta
	Upsert(ctx context.Context, name string, enabled bool, rateLimitPerMinute int, creds distributors.Credentials) (distributors.ServiceMeta, error)
	Reload(ctx context.Context) error
	Delete(ctx context.Context, name string) error
}

// Deps bundles everything handlers need.
type Deps struct {
	Cfg          *config.Config
	Pool         *pgxpool.Pool
	Auth         *auth.Service
	LLM          *llm.Registry
	Storage      storage.Storage
	Distributors DistributorsRegistry
	Mirror       *filesystem.Mirror
}

func writeJSON(w http.ResponseWriter, status int, body interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if body == nil {
		return
	}
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func decodeJSON(r *http.Request, dst interface{}) error {
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return err
	}
	return nil
}

// projectRole returns the caller's role on the project (or "" if none) and a
// boolean indicating whether the project exists. With workspaces, the role is
// the caller's role on the project's workspace, mapped:
//   - workspace owner → "owner"
//   - workspace admin → "editor"
//   - workspace member → "editor"
//
// (We collapse all members to edit access in v1; share_links still grant viewer.)
func projectRole(ctx context.Context, pool *pgxpool.Pool, projectID, userID string) (role string, exists bool, err error) {
	var workspaceID string
	err = pool.QueryRow(ctx, `select workspace_id from projects where id = $1`, projectID).Scan(&workspaceID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return "", false, nil
		}
		return "", false, err
	}
	exists = true
	var wsRole string
	err = pool.QueryRow(ctx,
		`select role from workspace_members where workspace_id = $1 and user_id = $2`,
		workspaceID, userID).Scan(&wsRole)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return "", true, nil
		}
		return "", true, err
	}
	switch wsRole {
	case "owner":
		return "owner", true, nil
	case "admin", "member":
		return "editor", true, nil
	}
	return "", true, nil
}

// requireMember returns the caller's role; writes 404 and returns "" if not authorized.
//
// Both "project missing" and "caller has no role on the project's workspace"
// return the same 404 — leaking project existence to outsiders is a small but
// real privacy issue (project names are often product code-names). 403 was the
// older response shape; we tightened it.
func requireMember(w http.ResponseWriter, r *http.Request, pool *pgxpool.Pool, projectID, userID string) string {
	role, exists, err := projectRole(r.Context(), pool, projectID, userID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return ""
	}
	if !exists || role == "" {
		writeError(w, http.StatusNotFound, "project not found")
		return ""
	}
	return role
}

// requireOwner ensures the caller is the project owner.
func requireOwner(w http.ResponseWriter, r *http.Request, pool *pgxpool.Pool, projectID, userID string) bool {
	role := requireMember(w, r, pool, projectID, userID)
	if role == "" {
		return false
	}
	if role != "owner" {
		writeError(w, http.StatusForbidden, "owner only")
		return false
	}
	return true
}

func notFound(err error) bool {
	return errors.Is(err, pgx.ErrNoRows)
}

// genericServerError sends a 500 with a sanitized message.
func genericServerError(w http.ResponseWriter, err error) {
	writeError(w, http.StatusInternalServerError, fmt.Sprintf("server error: %v", err))
}
