--- kerf.equations — read / set equation variables.
--
-- Methods:
--   k.equations:read(project_id, file_id)                      -> eqs[], err
--   k.equations:set(project_id, file_id, name, expression)     -> result, err

local Equations = {}
Equations.__index = Equations

function Equations.new(client)
  return setmetatable({ _c = client }, Equations)
end

function Equations:read(project_id, file_id)
  return self._c:call("equations.read", {
    project_id = project_id,
    file_id    = file_id,
  })
end

function Equations:set(project_id, file_id, name, expression)
  return self._c:call("equations.set", {
    project_id = project_id,
    file_id    = file_id,
    name       = name,
    expression = expression,
  })
end

return Equations
