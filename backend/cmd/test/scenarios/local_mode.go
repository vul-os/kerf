package scenarios

// local_mode covers the auth-optional-removal flow: when local_mode is
// on (the OSS default), POST /auth/bootstrap-local mints a singleton
// user + workspace and returns a session, idempotent on subsequent
// calls. The bootstrap-local endpoint is gated to local_mode=true; in
// the cloud-style boot (local_mode=false) it 404s so the multi-user
// signup flow can't be bypassed.

import (
	"context"
	"os"

	"github.com/imranp/kerf/backend/cmd/test/runner"
)

// boolPtr is a tiny helper for the BootOptions.LocalMode tri-state.
func boolPtr(v bool) *bool { return &v }

// LocalMode drives the local-mode-only auto-account flow.
func LocalMode(s *runner.Suite, _ *runner.Env) {
	ctx := context.Background()

	// Stand up an env with KERF_LOCAL_MODE=true so the env-var path is
	// also exercised. Defer the unset so we don't leak into other
	// scenarios run in the same process.
	prev, hadPrev := os.LookupEnv("KERF_LOCAL_MODE")
	if err := os.Setenv("KERF_LOCAL_MODE", "true"); err != nil {
		s.Fail("setenv KERF_LOCAL_MODE", err.Error())
		return
	}
	defer func() {
		if hadPrev {
			_ = os.Setenv("KERF_LOCAL_MODE", prev)
		} else {
			_ = os.Unsetenv("KERF_LOCAL_MODE")
		}
	}()

	env, err := runner.Boot(ctx, runner.BootOptions{
		LocalMode: boolPtr(true),
	})
	if !s.NoError("boot local-mode env", err) {
		return
	}
	defer env.Cleanup(ctx, true)
	c := env.Client

	// /api/config exposes local_mode=true.
	var cfgResp struct {
		CloudEnabled bool `json:"cloud_enabled"`
		LocalMode    bool `json:"local_mode"`
	}
	status, raw, _ := c.DoJSON("GET", "/api/config", nil, "", &cfgResp)
	if s.Status("GET /api/config", status, 200, raw) {
		s.True("config.local_mode true", cfgResp.LocalMode)
		s.False("config.cloud_enabled false", cfgResp.CloudEnabled)
	}

	// First call to /auth/bootstrap-local: creates the user + workspace,
	// returns a full auth bundle.
	var first authBundle
	status, raw, _ = c.DoJSON("POST", "/auth/bootstrap-local", map[string]any{}, "", &first)
	if !s.Status("POST /auth/bootstrap-local first", status, 200, raw) {
		return
	}
	s.NotEmpty("first.access_token", first.AccessToken)
	s.NotEmpty("first.refresh_token", first.RefreshToken)
	s.NotEmpty("first.user.id", first.User.ID)
	if !s.True("first.default_workspace populated", first.DefaultWorkspace != nil,
		"expected default_workspace in bootstrap response") {
		return
	}
	s.NotEmpty("first.default_workspace.id", first.DefaultWorkspace.ID)
	wsID := first.DefaultWorkspace.ID

	// /api/me with the issued access token returns the auto-created user.
	var me struct {
		ID    string `json:"id"`
		Email string `json:"email"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/me", nil, first.AccessToken, &me)
	if s.Status("GET /api/me", status, 200, raw) {
		s.Equal("me.id matches bootstrap user", me.ID, first.User.ID)
		s.NotEmpty("me.email", me.Email)
	}

	// /api/workspaces lists the auto-created default workspace.
	var workspaces []struct {
		ID   string `json:"id"`
		Slug string `json:"slug"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/workspaces", nil, first.AccessToken, &workspaces)
	if s.Status("GET /api/workspaces", status, 200, raw) {
		if s.True("workspaces non-empty", len(workspaces) >= 1, "expected at least one workspace") {
			found := false
			for _, w := range workspaces {
				if w.ID == wsID {
					found = true
					break
				}
			}
			s.True("default workspace listed", found, "default workspace not in /api/workspaces")
		}
	}

	// Project create against the default workspace succeeds.
	var proj struct {
		ID          string `json:"id"`
		WorkspaceID string `json:"workspace_id"`
		Name        string `json:"name"`
	}
	status, raw, _ = c.DoJSON("POST", "/api/projects", map[string]any{
		"name":         "local-mode test",
		"workspace_id": wsID,
	}, first.AccessToken, &proj)
	if s.Status("POST /api/projects", status, 201, raw) {
		s.Equal("proj.workspace_id", proj.WorkspaceID, wsID)
		s.NotEmpty("proj.id", proj.ID)
	}

	// Idempotency: a second bootstrap-local call returns the SAME user
	// (matched by id) but freshly-minted tokens.
	var second authBundle
	status, raw, _ = c.DoJSON("POST", "/auth/bootstrap-local", map[string]any{}, "", &second)
	if s.Status("POST /auth/bootstrap-local second", status, 200, raw) {
		s.Equal("idempotent: same user id", second.User.ID, first.User.ID)
		s.NotEmpty("second.access_token", second.AccessToken)
		s.True("tokens rotated",
			second.AccessToken != "" && second.AccessToken != first.AccessToken ||
				second.RefreshToken != first.RefreshToken,
			"expected fresh tokens on second bootstrap")
	}

	// --- Local mode disabled → /auth/bootstrap-local must 404 -----------
	// resolveLocalMode treats KERF_LOCAL_MODE as the highest-precedence
	// override, so flip it to "false" for this leg before booting; the
	// outer defer restores whatever was there (if anything).
	if err := os.Setenv("KERF_LOCAL_MODE", "false"); err != nil {
		s.Fail("setenv KERF_LOCAL_MODE=false", err.Error())
		return
	}
	envDisabled, err := runner.Boot(ctx, runner.BootOptions{
		LocalMode: boolPtr(false),
	})
	if !s.NoError("boot local-mode-off env", err) {
		return
	}
	defer envDisabled.Cleanup(ctx, true)
	cd := envDisabled.Client

	// /api/config reports the flag as off.
	var cfgOff struct {
		LocalMode bool `json:"local_mode"`
	}
	status, raw, _ = cd.DoJSON("GET", "/api/config", nil, "", &cfgOff)
	if s.Status("GET /api/config (local_mode off)", status, 200, raw) {
		s.False("config.local_mode false", cfgOff.LocalMode)
	}

	status, raw, _ = cd.Do("POST", "/auth/bootstrap-local", map[string]any{}, "")
	s.Status("POST /auth/bootstrap-local off → 404", status, 404, raw)
}
