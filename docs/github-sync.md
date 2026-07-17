# Git sync (GitHub, GitLab, Gitea, any remote)

Every Kerf project is a real, local git repository — nothing more. Kerf
ships a git UI over that repo plus a **remotes** config field; there is no
hosted git product, no kerf-operated OAuth app, and no server holding your
credentials. Collaboration is `git push` / `git pull` to whatever remote
you configure, exactly like using the `git` CLI directly.

This page replaces the old hosted-GitHub-sync model. See `decisions.md`'s
*"Addendum: local git only; no OAuth; accounts shrink to the box"*
(2026-07-17) for the decision record.

---

## What changed

**Was:** Kerf operated a hosted git layer — a server-side bare repo per
project, a `POST /api/projects/:pid/git/init` endpoint, `cloud_git_commits`
/ `cloud_git_branches` tables, and a GitHub OAuth app that stored an
encrypted access token per user so Kerf could push/pull on your behalf.

**Now:** a Kerf project *is* a plain local git repo on disk (or on whatever
node you're running Kerf on). GitHub — and GitLab, Gitea, a teammate's node,
a homelab box — is just an ordinary git remote, added and authenticated the
same way you'd add one from the command line: an SSH key or a Personal
Access Token that you supply and that Kerf never sees a copy of beyond what
it needs to invoke `git` on your behalf, locally. There is no kerf-operated
OAuth app and no server-held token.

`file_revisions` (the always-on, per-file undo layer — see
[file-revisions.md](./file-revisions.md)) is unchanged and remains the
default safety net beneath deliberate git commits. The two layers still
coexist: `file_revisions` fires on every save, git commits are deliberate
checkpoints.

---

## Adding a remote

Kerf's Git panel is a UI over your project's local repo plus a **remotes**
list. To connect a remote:

1. Open the **Git panel** in the editor.
2. Add a remote URL and, if the remote requires it, your own credential:
   - **GitHub / GitLab / Gitea (HTTPS):** a Personal Access Token you
     generate on that host, scoped to the repo(s) you want to push/pull.
   - **Any host (SSH):** an SSH key pair — point Kerf at your existing key,
     or generate one and add the public half to the remote host yourself.
3. Push and pull from the Git panel exactly as you would with `git push` /
   `git pull` on the command line — Kerf is invoking the same operations
   against the remote you configured.

Kerf never brokers the credential exchange: you generate the token or key
on the remote host's own site (GitHub Settings → Developer settings →
Personal access tokens; GitLab → Access Tokens; Gitea → Applications), and
you paste or point Kerf at it directly. Nothing is proxied through a
kerf-operated server.

A node MAY also *serve* its own repos over standard git HTTP/SSH — that's
self-hosting a git remote for others to pull from, using the same
one-node-type capability every Kerf install has (see
[node-architecture.md](./node-architecture.md)). It's a capability of your
node, not a service Kerf runs for you.

---

## Multiple remotes

Nothing limits a project to one remote. Add GitHub as one remote and a
teammate's node or a Gitea instance as another; push to either
independently. Kerf doesn't privilege any particular host — GitHub, GitLab,
Gitea, and a self-hosted remote are configured and used identically.

---

## Related pages

- [file-revisions.md](./file-revisions.md) — the always-on per-file undo layer
- [node-architecture.md](./node-architecture.md) — node model; serving your own repos
- [projects.md](./projects.md) — project model
