# Workshop

The Workshop is the public project gallery on Kerf Cloud. It lets anyone browse, fork, and like published designs.

The Workshop is cloud-only by nature: it presupposes a hosted, multi-tenant server with anonymous visitors. A self-hosted instance can still publish its own projects (visibility `public`) and the `/api/workshop/` endpoints function, but there is no shared multi-user catalog without a hosted operator.

---

## Browsing the Workshop

```
GET /api/workshop/?page=1&sort=newest&tag=electronics
```

Parameters:
- `page` — page number (default 1, 20 results per page)
- `sort` — `newest` (default) or other sort modes
- `tag` — filter by tag (repeatable: `?tag=mech&tag=assembly`)

Each result includes the project name, description, thumbnail, like count, and owner information.

No authentication is required to browse.

### Project detail

```
GET /api/workshop/:slug
```

Where `:slug` is the project UUID. Returns the full project record including the README, tags, like count, and whether the authenticated viewer has liked it.

---

## Publishing a project

Publishing sets a project's visibility to `public` and lists it in the Workshop gallery.

```
POST /api/workshop/publish
```

Body:

```json
{
  "project_id": "...",
  "title": "My bracket",
  "description": "An aluminium bracket for...",
  "readme": null,
  "generate_readme": true
}
```

| Field | Description |
|---|---|
| `project_id` | UUID of your project |
| `title` | Optional — updates the project name |
| `description` | Optional — updates the project description |
| `readme` | Optional — explicit README text (Markdown). Overrides AI generation. |
| `generate_readme` | `true` (default) — AI-generates a README from project files and BOM if no explicit readme is provided |

On publish:
1. Project visibility is set to `public`.
2. If `generate_readme = true` and no explicit readme is supplied, a README is generated from the project context and BOM.
3. A hero cover image is auto-generated if a render service is configured; otherwise the existing thumbnail is used.

Publishing is **idempotent** — calling it again on an already-public project updates the title, description, and/or readme if new values are provided.

Publishing is free on all tiers, including the free tier. There are no marketplace fees.

### Regenerating the README

```
POST /api/workshop/regenerate-readme
```

Body: `{project_id}` — Re-generates the AI README for a project that is already public. The caller must be the project owner or admin.

---

## Unpublishing

```
DELETE /api/workshop/:slug
```

Sets visibility back to `private`. The project is removed from the gallery. Previously forked copies remain in their owners' workspaces.

---

## Gallery images

Published projects can have a curated gallery of up to 8 images shown in the Workshop listing.

```
POST   /api/projects/:pid/workshop-images               — upload an image
GET    /api/projects/:pid/workshop-images               — list images
PATCH  /api/projects/:pid/workshop-images/:id           — update caption / sort order
DELETE /api/projects/:pid/workshop-images/:id           — remove an image
POST   /api/projects/:pid/workshop-images/:id/set-primary — pin as the primary thumbnail
```

Images are served directly from storage and are publicly accessible for public projects:

```
GET /api/projects/:pid/workshop-images/:id/file
```

---

## Liking and forking

### Like

```
POST /api/workshop/:slug/like
```

Toggles like. Returns `{liked_by_me, likes_count}`. Requires authentication. Only public projects can be liked.

### Fork

```
POST /api/workshop/:slug/fork
```

Body: `{project_name?}`

Clones the public project and all its current files into your workspace as a new private project. The fork starts with a clean slate — it does not inherit the source's git history. The fork name defaults to `"<original name> (fork)"`.

---

## Parts library in the Workshop

The Workshop also exposes a parts library browse endpoint (for compatibility with older client versions):

```
GET /api/workshop/parts?search=&category=&verified_only=
```

This is a deprecated alias for the library parts list. Use `GET /api/library/parts` directly.

---

## Related pages

- [projects.md](./projects.md) — project model, visibility levels, sharing
- [sharing.md](./sharing.md) — share links for pre-publish review
- [cloud-features.md](./cloud-features.md) — why Workshop is cloud-only by nature
- [billing-and-credits.md](./billing-and-credits.md) — Workshop is free on all tiers
