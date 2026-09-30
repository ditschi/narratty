-- narratty: show the path relative to where yazi started (like an editor's explorer),
-- instead of the full working directory.
local root = os.getenv("PWD") or ""
local name = root:match("([^/]+)/*$") or root

function Header:cwd()
	local cwd = tostring(cx.active.current.cwd)
	local rel = cwd
	if cwd == root then
		rel = name
	elseif cwd:sub(1, #root + 1) == root .. "/" then
		rel = name .. cwd:sub(#root + 1)
	end
	return ui.Span(rel):style(th.mgr.cwd)
end
