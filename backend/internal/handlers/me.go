package handlers

import (
	"errors"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/imranp/kerf/backend/internal/middleware"
	"github.com/imranp/kerf/backend/internal/models"
)

type meResponse struct {
	models.User
	DefaultWorkspace *models.Workspace `json:"default_workspace,omitempty"`
}

// Me returns the currently authenticated user, plus their default workspace
// (oldest workspace they're a member of) so the client can route home.
func (d *Deps) Me(w http.ResponseWriter, r *http.Request) {
	uid := middleware.UserID(r.Context())
	var u models.User
	err := d.Pool.QueryRow(r.Context(),
		`select id, email, name, avatar_url, account_role, is_system, created_at from users where id = $1`,
		uid).Scan(&u.ID, &u.Email, &u.Name, &u.AvatarURL, &u.AccountRole, &u.IsSystem, &u.CreatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeError(w, http.StatusNotFound, "user not found")
			return
		}
		genericServerError(w, err)
		return
	}
	resp := meResponse{User: u}
	if ws, ok, err := d.defaultWorkspaceForUser(r.Context(), uid); err == nil && ok {
		resp.DefaultWorkspace = &ws
	}
	writeJSON(w, http.StatusOK, resp)
}

type updateMeReq struct {
	Name *string `json:"name,omitempty"`
}

// UpdateMe accepts a partial profile patch. Only `name` is mutable from this
// endpoint today; email is bound to the sign-in identity, avatar has its own
// upload route, and account_role / is_system are admin-only.
func (d *Deps) UpdateMe(w http.ResponseWriter, r *http.Request) {
	uid := middleware.UserID(r.Context())
	var body updateMeReq
	if err := decodeJSON(r, &body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid body")
		return
	}
	var u models.User
	if body.Name == nil {
		// Nothing to update — re-read and return.
		err := d.Pool.QueryRow(r.Context(),
			`select id, email, name, avatar_url, account_role, is_system, created_at from users where id = $1`,
			uid).Scan(&u.ID, &u.Email, &u.Name, &u.AvatarURL, &u.AccountRole, &u.IsSystem, &u.CreatedAt)
		if err != nil {
			genericServerError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, u)
		return
	}
	name := strings.TrimSpace(*body.Name)
	err := d.Pool.QueryRow(r.Context(), `
		update users set name = $2 where id = $1
		returning id, email, name, avatar_url, account_role, is_system, created_at
	`, uid, name).Scan(&u.ID, &u.Email, &u.Name, &u.AvatarURL, &u.AccountRole, &u.IsSystem, &u.CreatedAt)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeError(w, http.StatusNotFound, "user not found")
			return
		}
		genericServerError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, u)
}
