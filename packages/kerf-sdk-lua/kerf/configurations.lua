--- kerf.configurations — list and activate named parameter configurations.
--
-- Methods:
--   k.configurations:list(project_id, file_id)              -> configs[], err
--   k.configurations:activate(project_id, file_id, config_id) -> result, err

local Configurations = {}
Configurations.__index = Configurations

function Configurations.new(client)
  return setmetatable({ _c = client }, Configurations)
end

function Configurations:list(project_id, file_id)
  return self._c:call("configurations.list", {
    project_id = project_id,
    file_id    = file_id,
  })
end

function Configurations:activate(project_id, file_id, config_id)
  return self._c:call("configurations.set_active", {
    project_id = project_id,
    file_id    = file_id,
    config_id  = config_id,
  })
end

return Configurations
