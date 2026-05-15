--- kerf.docs — full-text / semantic search across the Kerf documentation.
--
-- Methods:
--   k.docs:search(query[, opts])  -> hits[], err
--
-- opts: { k = <max results> }

local Docs = {}
Docs.__index = Docs

function Docs.new(client)
  return setmetatable({ _c = client }, Docs)
end

function Docs:search(query, opts)
  local params = { query = query }
  if opts and opts.k and opts.k > 0 then
    params.k = opts.k
  end
  return self._c:call("docs.search", params)
end

return Docs
