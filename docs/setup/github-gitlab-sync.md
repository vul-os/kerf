# GitHub / GitLab sync — operator setup (retired)

This page described operator setup for kerf-run GitHub App / GitLab OAuth
App installations (`CLOUD_GITHUB_APP_ID`, `CLOUD_GITLAB_APP_SECRET`, and the
`/auth/github/callback` / `/auth/gitlab/callback` install flows) backing a
kerf-hosted git "system of record" with mirror push/pull to GitHub/GitLab.

That model is retired. Per the "Addendum: local git only; no OAuth" ADR in
`decisions.md` (2026-07-17): a kerf project is a plain local git repo, and
collaboration is `git push`/`pull` to any remote the user configures —
GitHub, GitLab, a teammate's node, or a homelab box. GitHub and GitLab are
used as ordinary git remotes authenticated with the user's own SSH key or
personal access token, exactly as with the git CLI. There is no
kerf-operated OAuth app or GitHub App for any provider, no
`CLOUD_GITHUB_APP_ID` / `CLOUD_GITLAB_APP_SECRET` to configure, and no
operator setup step at all — there is nothing to register.

See [github-sync.md](../github-sync.md) for the current model and
[commit-and-branches.md](../commit-and-branches.md) for the user-facing
connect flow.
