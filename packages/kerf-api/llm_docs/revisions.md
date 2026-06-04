# revisions

*Module: `kerf_api.tools.revisions` · Domain: api*

This module registers **2** LLM tool(s):

- [`list_revisions`](#list-revisions)
- [`restore_revision`](#restore-revision)

---

## `list_revisions`

List the most-recent edits to a file as a chronological history (newest first). Returns id, source ('user'|'tool'|'llm'|'restore'), created_at, and a 200-char content_preview per row.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string"
    },
    "limit": {
      "type": "integer"
    }
  },
  "required": [
    "file_path"
  ]
}
```

---

## `restore_revision`

Restore a file to one of its previous revisions. Use list_revisions first to find the desired revision id. The restore is itself recorded as a new revision so it can be undone.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_path": {
      "type": "string"
    },
    "revision_id": {
      "type": "string"
    }
  },
  "required": [
    "file_path",
    "revision_id"
  ]
}
```

---

## See also

- Package: `kerf_api`
