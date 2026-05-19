# GitHub / GitLab sync — operator setup

This document covers what a Kerf Cloud operator must configure for GitHub
and GitLab sync to work end-to-end.

---

## Environment variables

### GitHub (GitHub App flow)

| Variable | Description |
|---|---|
| `CLOUD_GITHUB_APP_ID` | Numeric App ID shown on the GitHub App settings page |
| `CLOUD_GITHUB_APP_SLUG` | The URL slug of your App (e.g. `my-kerf-app`) |
| `CLOUD_GITHUB_PRIVATE_KEY_B64` | Base-64-encoded PEM private key for the App |

If any of these are absent the GitHub provider is silently disabled —
`GET /api/git/providers` will not list it and the UI will not offer
a GitHub mirror option.

### GitLab (OAuth App flow)

| Variable | Description |
|---|---|
| `CLOUD_GITLAB_APP_ID` | OAuth App client ID from GitLab |
| `CLOUD_GITLAB_APP_SECRET` | OAuth App client secret from GitLab |
| `CLOUD_GITLAB_HOST` | GitLab host URL — defaults to `https://gitlab.com` when unset |

Same rule: both must be present or GitLab is hidden from the UI.

---

## Registering the GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Set the **Callback URL** to:
   ```
   https://<your-kerf-domain>/auth/github/callback
   ```
3. Enable **Request user authorization (OAuth) during installation**.
4. Under **Permissions**, grant:
   - Repository: `Contents` — Read & write
   - Repository: `Metadata` — Read-only
5. Generate a private key and base-64 encode it:
   ```
   base64 -i private-key.pem | tr -d '\n'
   ```
   Set that value as `CLOUD_GITHUB_PRIVATE_KEY_B64`.

---

## Registering the GitLab OAuth App

1. Go to **GitLab → User Settings → Applications → New application**.
2. Set the **Redirect URI** to:
   ```
   https://<your-kerf-domain>/auth/gitlab/callback
   ```
3. Select scopes: `read_user`, `read_repository`, `write_repository`.
4. Save and copy the **Application ID** and **Secret** to
   `CLOUD_GITLAB_APP_ID` / `CLOUD_GITLAB_APP_SECRET`.

---

## End-to-end flow (GitHub)

1. **Link GitHub account** — user clicks *Link GitHub* in the Git panel.
   Browser navigates to `GET /auth/github/start` which redirects to the
   GitHub App installation page. After installing, GitHub redirects to
   `GET /auth/github/callback?installation_id=<id>&state=<…>`. Kerf stores
   the `installation_id` in `cloud_github_tokens`.

2. **Connect project** — user opens Git Settings, selects GitHub, pastes a
   remote URL such as `https://github.com/owner/repo.git`. The frontend
   posts `POST /api/projects/:pid/git/provider/connect` with
   `{provider: "github", remote_url: "…"}`. The backend parses the URL into
   `github_owner`/`github_repo` and writes them to `cloud_git_repos`.

3. **Commit** — user clicks Commit in the Git panel.

4. **Push** — user clicks the Push button. The frontend posts
   `POST /api/projects/:pid/git/provider/push` (not yet wired; see *Known
   gap* below). Until then, push to the Kerf SoR via
   `POST /api/projects/:pid/git/push` (requires `local_dir` — server-side
   operation only).

5. **Pull** — symmetric to push.

---

## Known gap — mirror push/pull not yet exposed to the browser

`GitHubProvider.push()` / `GitLabProvider.push()` return an
`authenticated_remote_url` that the *caller* must use to run `git push`.
There is currently no HTTP endpoint that accepts a browser request and
executes that git push server-side.

The existing `POST /api/projects/:pid/git/push` endpoint is the Kerf
internal S3-storer path; it requires a server-side `local_dir` and is not
useful from the browser.

**What this means for users:** the Push/Pull buttons in the Git panel
currently operate on the Kerf hosted SoR git (S3 backend), not on the
GitHub/GitLab mirror. Mirror push from the browser is planned as a
follow-up task.

---

## Common failures

| Symptom | Likely cause |
|---|---|
| GitHub provider absent from Git Settings | `CLOUD_GITHUB_APP_ID` or `CLOUD_GITHUB_PRIVATE_KEY_B64` not set |
| GitLab provider absent | `CLOUD_GITLAB_APP_ID` or `CLOUD_GITLAB_APP_SECRET` not set |
| GitHub link returns `error=install_failed` | App not installed on the GitHub org / token mint failed |
| Connect returns 400 "provider is required" | Frontend sent `provider_id` instead of `provider` — fixed in audit commit |
| Connect returns 400 "github_owner and github_repo are required" | `remote_url` could not be parsed — check URL format |
| Disconnect returns 400 | Frontend sent empty body — fixed in audit commit |
| Push button returns 400 "local_dir is required" | Button hit the S3-storer path, not the mirror path — mirror push not wired |
