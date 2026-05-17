--- kerf — Lua SDK for Kerf (https://kerf.sh).
--
-- Quickstart:
--   local kerf = require "kerf"
--   local k = kerf.from_env()
--   local files, err = k.files:list("proj_123")
--
-- Auth: set KERF_API_TOKEN (and optionally KERF_API_URL) in your environment,
-- or pass values explicitly to kerf.connect().

local Client         = require "kerf.client"
local kerr           = require "kerf.error"
local Files          = require "kerf.files"
local Equations      = require "kerf.equations"
local Configurations = require "kerf.configurations"
local Revisions      = require "kerf.revisions"
local Docs           = require "kerf.docs"

local DEFAULT_URL = "https://kerf.sh"

local M = {}

--- _build(api_url, api_token) -> Kerf handle
-- Internal: wires namespaces around a Client.
local function _build(api_url, api_token)
  local c = Client.new(api_url, api_token)
  return {
    files          = Files.new(c),
    equations      = Equations.new(c),
    configurations = Configurations.new(c),
    revisions      = Revisions.new(c),
    docs           = Docs.new(c),
  }
end

--- from_env() -> handle, err
-- Creates a Kerf client from KERF_API_TOKEN + KERF_API_URL environment vars.
-- Returns nil, KerfError when KERF_API_TOKEN is absent.
function M.from_env()
  local token = os.getenv("KERF_API_TOKEN") or ""
  token = token:match("^%s*(.-)%s*$")  -- trim whitespace
  if token == "" then
    return nil, kerr.new(
      kerr.MISSING_ENV,
      "KERF_API_TOKEN is not set. Generate one from workspace settings and export it."
    )
  end
  local url = os.getenv("KERF_API_URL") or DEFAULT_URL
  url = url:match("^%s*(.-)%s*$"):gsub("/+$", "")
  return _build(url, token), nil
end

--- connect(opts) -> handle
-- Creates a Kerf client with explicit credentials.
-- opts = { api_url = "...", api_token = "kerf_sk_..." }
-- api_url defaults to "https://kerf.sh".
function M.connect(opts)
  assert(type(opts) == "table", "kerf.connect: expected opts table")
  local url   = (opts.api_url or DEFAULT_URL):gsub("/+$", "")
  local token = opts.api_token
  assert(token and token ~= "", "kerf.connect: api_token is required")
  return _build(url, token)
end

-- Re-export error constants so callers only need to require "kerf".
M.error = kerr

return M
