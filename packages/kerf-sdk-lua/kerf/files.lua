--- kerf.files — operations on project files.
--
-- Methods:
--   k.files:list(project_id)                          -> files[], err
--   k.files:read(project_id, file_id)                 -> file, err
--   k.files:write(project_id, file_id, content)       -> result, err
--   k.files:create(project_id, name[, opts])          -> file, err
--   k.files:delete(project_id, file_id)               -> result, err
--
-- opts for create: { kind="file"|"folder", content="", parent_id="..." }

local Files = {}
Files.__index = Files

function Files.new(client)
  return setmetatable({ _c = client }, Files)
end

function Files:list(project_id)
  return self._c:call("files.list", { project_id = project_id })
end

function Files:read(project_id, file_id)
  return self._c:call("files.read", {
    project_id = project_id,
    file_id    = file_id,
  })
end

function Files:write(project_id, file_id, content)
  return self._c:call("files.write", {
    project_id = project_id,
    file_id    = file_id,
    content    = content,
  })
end

function Files:create(project_id, name, opts)
  opts = opts or {}
  local params = {
    project_id = project_id,
    name       = name,
    kind       = opts.kind    or "file",
    content    = opts.content or "",
  }
  if opts.parent_id then
    params.parent_id = opts.parent_id
  end
  return self._c:call("files.create", params)
end

function Files:delete(project_id, file_id)
  return self._c:call("files.delete", {
    project_id = project_id,
    file_id    = file_id,
  })
end

return Files
