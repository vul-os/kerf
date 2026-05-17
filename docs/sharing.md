# Sharing

How to share a project with collaborators or customers.

There are two sharing mechanisms in Kerf: **share links** (per-project invitations) and **Workshop publish** (public catalog listing). They are independent.

---

## Share links

A share link is a signed token that grants a recipient access to one specific project. It does not require them to have a Kerf account before they follow the link.

### Creating a share link

Any workspace member can create a share link for a project they have access to:

```
POST /api/projects/:pid/share/links
```

The link carries the creator's role capped at `editor`: owners and admins generate `editor` links; members with a lower role generate their own role. Recipients cannot exceed the link's role.

### Resolving a share link

Anyone with the token can look up the link:

```
GET /api/share/:token
```

Returns the project name, project ID, and the role the link grants. No authentication is required for this lookup — the token is the credential.

### Accepting a share link

An authenticated user accepts the link to join the project's workspace:

```
POST /api/share/:token/accept
```

Returns `{role}` confirming the access level granted.

### Link properties

| Property | Description |
|---|---|
| `token` | URL-safe random token (32 bytes, base64url) |
| `role` | `editor` (for owner/admin creators) or the creator's role |
| `expires_at` | Optional ISO timestamp; `null` means no expiry |
| `max_uses` | Optional integer; `null` means unlimited uses |
| `revoked_at` | Set when revoked; the link returns 404 after revocation |

### Revoking a share link

```
DELETE /api/projects/:pid/share/links/:lid
```

This sets `revoked_at = now()`. The token becomes invalid immediately. Any user who previously accepted the link retains their workspace membership — revoking the link does not remove them.

### Listing active share links

```
GET /api/projects/:pid/share/links
```

Returns all links for the project (including revoked ones, ordered by `created_at DESC`). Filter client-side on `revoked_at IS NULL` to see only active links.

---

## Customer share links (jewelry / design-review flow)

For project-revision-level sharing with a customer (e.g. share a specific revision for approval), a separate lightweight share mechanism exists in `kerf_cloud.share_link`:

- `create_share(project_id, revision_id, ttl_days=30)` — returns a short HMAC-signed token
- `resolve_share(token)` — validates + resolves to `{project_id, revision_id, metadata}`
- `add_comment(token, name, body)` — customer leaves a comment
- `record_approval(token, name, signature)` — customer approves the design
- `revoke_share(token)` — owner revokes

Tokens have a default TTL of 30 days. They are stored as JSON files under `data/cloud/share/` (no DB dependency; works in local-install mode). The token embeds an HMAC check digit so it cannot be guessed or forged.

---

## Project visibility vs share links

| Mechanism | Who can access | Auth required |
|---|---|---|
| Share link | Anyone with the token | Recipient needs a Kerf account to *accept* |
| `unlisted` visibility | Anyone with the project URL | No — URL is the credential |
| `public` visibility | Everyone — listed in Workshop | No |

These are independent controls. A `private` project can still have active share links. An `unlisted` project is browseable without a link if you know the URL.

---

## Related pages

- [projects.md](./projects.md) — project model and workspace membership
- [workshop.md](./workshop.md) — publishing to the public Workshop gallery
- [account-and-auth.md](./account-and-auth.md) — workspace roles
