-- Neovim with editors/nvim, driving `vela lsp` as a person would: open a
-- file with an error, see it, point at names, fix the error, rename,
-- complete, format.
--
--   nvim --headless --clean --cmd "set rtp^=editors/nvim" \
--        --cmd "let g:vela_command = ['build/vela', 'lsp']" -l tests/nvim_test.lua
--
-- run_tests.py runs it when nvim is installed. It prints "ok" and exits 0,
-- or says what went wrong and exits 1.

local function fail(what)
  io.stderr:write("nvim: " .. what .. "\n")
  os.exit(1)
end

local function expect(what, actual, expected)
  if not vim.deep_equal(actual, expected) then
    fail(what .. ":\n  expected " .. vim.inspect(expected) .. "\n  got      " .. vim.inspect(actual))
  end
end

local function wait(what, condition)
  if not vim.wait(15000, condition, 20) then
    fail("timed out waiting for " .. what)
  end
end

local dir = vim.fn.tempname()
vim.fn.mkdir(dir, "p")
local function write(name, text)
  local f = io.open(dir .. "/" .. name, "w")
  f:write(text)
  f:close()
end

write("shapes.vl", [[
// Shapes and their areas.
pub type Shape = enum {
    Circle(Float)
    Rect(Float, Float)
}

// The area of `s`.
pub fn area(s: Shape) -> Float {
    return match s {
        Shape.Circle(r) => 3.0 * r * r
        Shape.Rect(w, h) => w * h
    }
}
]])
write("main.vl", [[
import shapes

fn main() {
    let mut total = 0.0
    total = "x"
    for s in [shapes.Shape.Circle(1.0), shapes.Shape.Rect(2.0, 3.0)] {
        total = total + shapes.area(s)
    }
    print(total)
}
]])
write("odd.vl", "fn main(){\nprint(1+2)\n}\n")

-- Opening the file starts the server, which reports the error on line 5.
vim.cmd.edit(dir .. "/main.vl")
expect("filetype", vim.bo.filetype, "vela")
wait("the error", function() return #vim.diagnostic.get(0) > 0 end)
local d = vim.diagnostic.get(0)
expect("diagnostics", { #d, d[1].lnum, d[1].col, d[1].severity, d[1].message },
  { 1, 4, 12, vim.diagnostic.severity.ERROR, "cannot assign Str to 'total', which is Float" })

local function request(method, line, character)
  local params = { textDocument = vim.lsp.util.make_text_document_params(), position = { line = line, character = character } }
  local replies = vim.lsp.buf_request_sync(0, method, params, 5000)
  for _, r in pairs(replies or {}) do
    if r.error then
      fail(method .. ": " .. vim.inspect(r.error))
    end
    return r.result
  end
  fail("no reply to " .. method)
end

-- Hover, as K shows it.
expect("hover on total", request("textDocument/hover", 3, 13).contents.value, "```vela\nlet mut total: Float\n```")
expect("hover on area", request("textDocument/hover", 6, 32).contents.value,
  "```vela\npub fn area(s: Shape) -> Float\n```\n\nThe area of `s`.")

-- Go to definition, as gd does it: into shapes.vl.
local loc = request("textDocument/definition", 6, 32)
expect("definition", { vim.fs.basename(vim.uri_to_fname(loc.uri)), loc.range.start.line }, { "shapes.vl", 7 })

-- Deleting the bad line: Neovim sends the change, the error goes.
vim.api.nvim_buf_set_lines(0, 4, 5, false, {})
wait("the error to clear", function() return #vim.diagnostic.get(0) == 0 end)

-- Typing a new mistake brings a new error, before any save.
vim.api.nvim_buf_set_lines(0, 4, 4, false, { "    print(nope)" })
wait("the new error", function() return #vim.diagnostic.get(0) > 0 end)
expect("new diagnostic", vim.diagnostic.get(0)[1].message, "undefined name 'nope'")

-- Rename, as :lua vim.lsp.buf.rename("sum") does it, on `total`.
vim.api.nvim_win_set_cursor(0, { 4, 12 })
vim.lsp.buf.rename("sum")
wait("the rename", function() return vim.api.nvim_buf_get_lines(0, 3, 4, false)[1] == "    let mut sum = 0.0" end)
expect("renamed", vim.api.nvim_buf_get_lines(0, 5, 8, false),
  { "    for s in [shapes.Shape.Circle(1.0), shapes.Shape.Rect(2.0, 3.0)] {", "        sum = sum + shapes.area(s)", "    }" })

-- Completion after `shapes.`, typed in place of the mistake.
vim.api.nvim_buf_set_lines(0, 4, 5, false, { "    shapes." })
local items = request("textDocument/completion", 4, 11).items
table.sort(items, function(a, b) return a.sortText < b.sortText end)
expect("completion", vim.tbl_map(function(i) return i.label end, items), { "area", "Shape" })

-- Formatting another file, as :lua vim.lsp.buf.format() does.
vim.cmd.edit(dir .. "/odd.vl")
wait("the server on odd.vl", function() return #vim.lsp.get_active_clients({ bufnr = 0 }) > 0 end)
vim.lsp.buf.format({ timeout_ms = 5000 })
expect("formatted", vim.api.nvim_buf_get_lines(0, 0, -1, false), { "fn main() {", "    print(1 + 2)", "}" })

-- One server for all of them.
expect("clients", #vim.lsp.get_active_clients({ name = "vela" }), 1)
io.stdout:write("ok\n")
vim.cmd("qa!")
