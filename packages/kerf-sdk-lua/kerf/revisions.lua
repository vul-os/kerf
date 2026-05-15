--- kerf.revisions — file history browsing and restoration.
--
-- Methods:
--   k.revisions:list(project_id, file_id)                       -> revs[], err
--   k.revisions:read(project_id, file_id, revision_id)          -> rev, err
--   k.revisions:restore(project_id, file_id, revision_id)       -> result, err

local Revisions = {}
Revisions.__index = Revisions

function Revisions.new(client)
  return setmetatable({ _c = client }, Revisions)
end

function Revisions:list(project_id, file_id)
  return self._c:call("revisions.list", {
    project_id = project_id,
    file_id    = file_id,
  })
end

function Revisions:read(project_id, file_id, revision_id)
  return self._c:call("revisions.read", {
    project_id  = project_id,
    file_id     = file_id,
    revision_id = revision_id,
  })
end

function Revisions:restore(project_id, file_id, revision_id)
  return self._c:call("revisions.restore", {
    project_id  = project_id,
    file_id     = file_id,
    revision_id = revision_id,
  })
end

return Revisions
