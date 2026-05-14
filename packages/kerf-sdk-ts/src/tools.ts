/**
 * Namespaced wrappers around the JSON-RPC methods exposed by /v1/rpc.
 *
 * Method names match METHOD_TO_TOOL in packages/kerf-v1/src/kerf_v1/routes.py:
 *   files.list, files.read, files.write, files.edit, files.create,
 *   files.delete, files.search, import_step, equations.read, equations.set,
 *   configurations.add, configurations.set_active, revisions.list,
 *   revisions.restore, docs.search
 *
 * Heavy-op bindings (kerf.fem, kerf.cam, kerf.topo) are reserved — their
 * /v1/rpc methods don't exist yet. Add them here when the backend lands them.
 */

import type { Kerf } from "./client.js";

// ---------------------------------------------------------------------------
// Shared return-shape types (minimal; widened to unknown where the server
// schema is complex or variable).
// ---------------------------------------------------------------------------

export interface FileEntry {
  id: string;
  name: string;
  kind: string;
  parent_id: string | null;
}

export interface RevisionEntry {
  id: string;
  created_at: string;
  message?: string;
}

export interface DocResult {
  title: string;
  url: string;
  excerpt: string;
}

export interface SearchResult {
  file_id: string;
  file_name: string;
  line: number;
  snippet: string;
}

// ---------------------------------------------------------------------------
// files.*
// ---------------------------------------------------------------------------

export class FilesNamespace {
  constructor(private readonly _c: Kerf) {}

  list(projectId: string): Promise<FileEntry[]> {
    return this._c.invoke("files.list", { project_id: projectId });
  }

  read(projectId: string, fileId: string): Promise<string> {
    return this._c.invoke("files.read", {
      project_id: projectId,
      file_id: fileId,
    });
  }

  write(projectId: string, fileId: string, content: string): Promise<unknown> {
    return this._c.invoke("files.write", {
      project_id: projectId,
      file_id: fileId,
      content,
    });
  }

  edit(
    projectId: string,
    fileId: string,
    oldString: string,
    newString: string,
  ): Promise<unknown> {
    return this._c.invoke("files.edit", {
      project_id: projectId,
      file_id: fileId,
      old_string: oldString,
      new_string: newString,
    });
  }

  create(
    projectId: string,
    name: string,
    kind = "file",
    content = "",
    parentId?: string,
  ): Promise<FileEntry> {
    const params: Record<string, unknown> = {
      project_id: projectId,
      name,
      kind,
      content,
    };
    if (parentId !== undefined) params["parent_id"] = parentId;
    return this._c.invoke("files.create", params);
  }

  delete(projectId: string, fileId: string): Promise<unknown> {
    return this._c.invoke("files.delete", {
      project_id: projectId,
      file_id: fileId,
    });
  }

  search(projectId: string, query: string): Promise<SearchResult[]> {
    return this._c.invoke("files.search", {
      project_id: projectId,
      query,
    });
  }
}

// ---------------------------------------------------------------------------
// equations.*
// ---------------------------------------------------------------------------

export class EquationsNamespace {
  constructor(private readonly _c: Kerf) {}

  read(projectId: string, fileId: string): Promise<Record<string, unknown>> {
    return this._c.invoke("equations.read", {
      project_id: projectId,
      file_id: fileId,
    });
  }

  set(
    projectId: string,
    fileId: string,
    name: string,
    expression: string,
  ): Promise<unknown> {
    return this._c.invoke("equations.set", {
      project_id: projectId,
      file_id: fileId,
      name,
      expression,
    });
  }
}

// ---------------------------------------------------------------------------
// configurations.*
// ---------------------------------------------------------------------------

export class ConfigurationsNamespace {
  constructor(private readonly _c: Kerf) {}

  add(
    projectId: string,
    fileId: string,
    label: string,
    params: Record<string, unknown>,
  ): Promise<unknown> {
    return this._c.invoke("configurations.add", {
      project_id: projectId,
      file_id: fileId,
      label,
      params,
    });
  }

  setActive(
    projectId: string,
    fileId: string,
    configId: string,
  ): Promise<unknown> {
    return this._c.invoke("configurations.set_active", {
      project_id: projectId,
      file_id: fileId,
      config_id: configId,
    });
  }
}

// ---------------------------------------------------------------------------
// revisions.*
// ---------------------------------------------------------------------------

export class RevisionsNamespace {
  constructor(private readonly _c: Kerf) {}

  list(projectId: string, fileId: string): Promise<RevisionEntry[]> {
    return this._c.invoke("revisions.list", {
      project_id: projectId,
      file_id: fileId,
    });
  }

  restore(
    projectId: string,
    fileId: string,
    revisionId: string,
  ): Promise<unknown> {
    return this._c.invoke("revisions.restore", {
      project_id: projectId,
      file_id: fileId,
      revision_id: revisionId,
    });
  }
}

// ---------------------------------------------------------------------------
// docs.*
// ---------------------------------------------------------------------------

export class DocsNamespace {
  constructor(private readonly _c: Kerf) {}

  search(query: string): Promise<DocResult[]> {
    return this._c.invoke("docs.search", { query });
  }
}
