package scenarios

// Workspaces scenario: exercises the full multi-member workspace surface —
// register flow's default_workspace, member invite/role-change/remove, the
// "cannot remove the only owner" guard, project-creation under a workspace,
// re-homing a project to a second workspace, and the workspace-avatar
// upload + delete round-trip.

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"io"
	"mime/multipart"
	"net/http"
	"net/textproto"

	"github.com/imranp/kerf/backend/cmd/test/runner"
)

// wsAuthBundle widens the local authBundle to capture default_workspace.
type wsAuthBundle struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	User         struct {
		ID    string `json:"id"`
		Email string `json:"email"`
		Name  string `json:"name"`
	} `json:"user"`
	DefaultWorkspace *struct {
		ID     string `json:"id"`
		Slug   string `json:"slug"`
		Name   string `json:"name"`
		MyRole string `json:"my_role"`
	} `json:"default_workspace,omitempty"`
}

func registerWS(c *runner.Client, email, password, name string) (wsAuthBundle, int, []byte) {
	var out wsAuthBundle
	status, raw, _ := c.DoJSON("POST", "/auth/register", map[string]string{
		"email": email, "password": password, "name": name,
	}, "", &out)
	return out, status, raw
}

// wsSummary mirrors models.Workspace as it appears in the listing.
type wsSummary struct {
	ID          string `json:"id"`
	Slug        string `json:"slug"`
	Name        string `json:"name"`
	MyRole      string `json:"my_role"`
	MemberCount int    `json:"member_count"`
	AvatarURL   string `json:"avatar_url,omitempty"`
}

// Workspaces is the entry point registered in main.go's allScenarios.
func Workspaces(s *runner.Suite, env *runner.Env) {
	c := env.Client
	ctx := context.Background()

	// 1. Register alice + bob.
	alice, status, raw := registerWS(c, "alice-ws@example.com", "alicepass99", "Alice")
	if !s.Status("register alice", status, 201, raw) {
		return
	}
	bob, status, raw := registerWS(c, "bob-ws@example.com", "bobpass99", "Bob")
	if !s.Status("register bob", status, 201, raw) {
		return
	}

	// 2. Alice's register response carries default_workspace.
	if !s.True("alice.default_workspace present", alice.DefaultWorkspace != nil,
		"expected default_workspace on register response") {
		return
	}
	s.NotEmpty("alice.default_workspace.slug", alice.DefaultWorkspace.Slug)
	s.Equal("alice.default_workspace.my_role", alice.DefaultWorkspace.MyRole, "owner")
	aliceSlug := alice.DefaultWorkspace.Slug

	// 3. GET /api/workspaces → one row, role=owner.
	var aliceList []wsSummary
	status, raw, _ = c.DoJSON("GET", "/api/workspaces", nil, alice.AccessToken, &aliceList)
	if !s.Status("alice list workspaces", status, 200, raw) {
		return
	}
	if !s.Equal("alice has 1 workspace", len(aliceList), 1) {
		return
	}
	s.Equal("alice ws role=owner", aliceList[0].MyRole, "owner")
	s.Equal("alice ws slug matches", aliceList[0].Slug, aliceSlug)

	// 4. Alice invites bob as admin.
	type invitedResp struct {
		Added *struct {
			UserID string `json:"user_id"`
			Role   string `json:"role"`
		} `json:"added"`
		Invite *struct {
			Token string `json:"token"`
		} `json:"invite"`
	}
	var invited invitedResp
	status, raw, _ = c.DoJSON("POST",
		fmt.Sprintf("/api/workspaces/%s/members", aliceSlug),
		map[string]string{"email": "bob-ws@example.com", "role": "admin"},
		alice.AccessToken, &invited)
	if !s.Status("alice invites bob", status, 201, raw) {
		return
	}
	if !s.True("invite returned added (existing user)", invited.Added != nil, "expected `added`, got body=%s", string(raw)) {
		return
	}
	s.Equal("bob added as admin", invited.Added.Role, "admin")
	s.Equal("bob added userId matches", invited.Added.UserID, bob.User.ID)

	// 5. Bob lists workspaces — he sees alice's, role=admin.
	var bobList []wsSummary
	status, raw, _ = c.DoJSON("GET", "/api/workspaces", nil, bob.AccessToken, &bobList)
	if !s.Status("bob list workspaces", status, 200, raw) {
		return
	}
	// Bob may have his own default + alice's; confirm alice's is in there.
	foundAlice := false
	var bobRoleOnAlice string
	for _, w := range bobList {
		if w.Slug == aliceSlug {
			foundAlice = true
			bobRoleOnAlice = w.MyRole
			break
		}
	}
	s.True("bob sees alice's workspace", foundAlice, "expected alice's workspace in bob's list, got %v", bobList)
	s.Equal("bob role on alice's ws = admin", bobRoleOnAlice, "admin")

	// 6. Bob tries to remove alice (the only owner) → 4xx.
	status, raw, _ = c.Do("DELETE",
		fmt.Sprintf("/api/workspaces/%s/members/%s", aliceSlug, alice.User.ID),
		nil, bob.AccessToken)
	s.True("bob can't remove only owner", status >= 400 && status < 500,
		"expected 4xx, got %d body=%s", status, string(raw))

	// 7. Alice changes bob's role to member.
	status, raw, _ = c.Do("PATCH",
		fmt.Sprintf("/api/workspaces/%s/members/%s", aliceSlug, bob.User.ID),
		map[string]string{"role": "member"}, alice.AccessToken)
	s.Status("alice demotes bob to member", status, 200, raw)

	// 8. Alice removes bob.
	status, raw, _ = c.Do("DELETE",
		fmt.Sprintf("/api/workspaces/%s/members/%s", aliceSlug, bob.User.ID),
		nil, alice.AccessToken)
	s.Status("alice removes bob", status, 204, raw)

	// 9. Bob lists again — alice's workspace is gone. Lazy-bootstrap may
	//    add bob's own personal workspace; we just assert alice's slug
	//    isn't in there.
	bobList = nil
	status, raw, _ = c.DoJSON("GET", "/api/workspaces", nil, bob.AccessToken, &bobList)
	if s.Status("bob list workspaces after removal", status, 200, raw) {
		stillThere := false
		for _, w := range bobList {
			if w.Slug == aliceSlug {
				stillThere = true
				break
			}
		}
		s.False("bob no longer sees alice's ws", stillThere,
			"expected alice's ws gone from bob's list")
	}

	// 10. Alice creates a project under her workspace.
	type proj struct {
		ID          string `json:"id"`
		WorkspaceID string `json:"workspace_id"`
		Name        string `json:"name"`
		MyRole      string `json:"my_role"`
	}
	var aliceProj proj
	status, raw, _ = c.DoJSON("POST", "/api/projects", map[string]string{
		"workspace_slug": aliceSlug,
		"name":           "Alice's project",
	}, alice.AccessToken, &aliceProj)
	if !s.Status("alice create project", status, 201, raw) {
		return
	}
	s.Equal("project workspace matches", aliceProj.WorkspaceID, alice.DefaultWorkspace.ID)
	s.Equal("alice owns project", aliceProj.MyRole, "owner")

	// 11. Alice creates a second workspace, then re-homes the project to it.
	var ws2 wsSummary
	status, raw, _ = c.DoJSON("POST", "/api/workspaces", map[string]string{
		"name": "Alice Side Lab",
		"slug": "alice-side-lab",
	}, alice.AccessToken, &ws2)
	if !s.Status("alice create second workspace", status, 201, raw) {
		return
	}
	s.Equal("ws2 my_role=owner", ws2.MyRole, "owner")

	var moved proj
	status, raw, _ = c.DoJSON("PATCH", "/api/projects/"+aliceProj.ID,
		map[string]string{"workspace_id": ws2.ID},
		alice.AccessToken, &moved)
	if s.Status("alice moves project to ws2", status, 200, raw) {
		s.Equal("project workspace_id moved", moved.WorkspaceID, ws2.ID)
	}

	// 12. Avatar upload — POST a small PNG to /api/workspaces/<slug>/avatar.
	body, ct := buildWorkspaceAvatarMultipart("ws-avatar.png", 48, 48)
	req, _ := http.NewRequest("POST", c.BaseURL+"/api/workspaces/"+aliceSlug+"/avatar", body)
	req.Header.Set("Content-Type", ct)
	req.Header.Set("Authorization", "Bearer "+alice.AccessToken)
	resp, err := c.HTTP.Do(req)
	if !s.NoError("POST workspace avatar", err) {
		return
	}
	rawBody, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if !s.Status("POST workspace avatar status", resp.StatusCode, 200, rawBody) {
		return
	}
	var withAvatar struct {
		Slug      string `json:"slug"`
		AvatarURL string `json:"avatar_url"`
	}
	_ = json.Unmarshal(rawBody, &withAvatar)
	s.NotEmpty("workspace avatar_url after upload", withAvatar.AvatarURL)

	// Storage key persisted.
	var storageKey string
	if err := env.Pool.QueryRow(ctx,
		`select coalesce(avatar_storage_key, '') from workspaces where slug = $1`,
		aliceSlug).Scan(&storageKey); s.NoError("workspace avatar key db read", err) {
		s.NotEmpty("workspace avatar_storage_key set", storageKey)
	}

	// 13. DELETE avatar → 204, db key cleared.
	status, raw, _ = c.Do("DELETE", "/api/workspaces/"+aliceSlug+"/avatar", nil, alice.AccessToken)
	s.Status("DELETE workspace avatar", status, 204, raw)
	var keyAfter string
	if err := env.Pool.QueryRow(ctx,
		`select coalesce(avatar_storage_key, '') from workspaces where slug = $1`,
		aliceSlug).Scan(&keyAfter); s.NoError("workspace avatar key after delete", err) {
		s.Equal("workspace avatar_storage_key cleared", keyAfter, "")
	}

	// Sanity: the workspace detail call returns avatar_url empty after delete.
	var detail struct {
		AvatarURL string `json:"avatar_url"`
	}
	status, raw, _ = c.DoJSON("GET", "/api/workspaces/"+aliceSlug, nil, alice.AccessToken, &detail)
	if s.Status("GET workspace after avatar delete", status, 200, raw) {
		s.Equal("avatar_url empty after delete", detail.AvatarURL, "")
	}
}

// buildWorkspaceAvatarMultipart returns a multipart body with a w*h PNG.
// Mirrors avatars.go's helper; kept local to avoid spreading dependencies.
func buildWorkspaceAvatarMultipart(filename string, w, h int) (*bytes.Buffer, string) {
	var pngBuf bytes.Buffer
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	for y := 0; y < h; y++ {
		for x := 0; x < w; x++ {
			img.Set(x, y, color.RGBA{R: byte((x * 6) % 255), G: 80, B: byte((y * 4) % 255), A: 255})
		}
	}
	_ = png.Encode(&pngBuf, img)

	body := &bytes.Buffer{}
	mw := multipart.NewWriter(body)
	hdr := textproto.MIMEHeader{}
	hdr.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename=%q`, filename))
	hdr.Set("Content-Type", "image/png")
	pw, _ := mw.CreatePart(hdr)
	_, _ = pw.Write(pngBuf.Bytes())
	mw.Close()
	return body, mw.FormDataContentType()
}
