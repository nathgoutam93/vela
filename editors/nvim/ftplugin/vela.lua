-- Vela buffers: four-space indents, // comments, and `vela lsp` for errors
-- as you type, hover (K), go to definition, references, the outline and
-- formatting.
--
--   vim.g.vela_command        the server's command line (default {"vela", "lsp"})
--   vim.g.vela_format_on_save true to format with `vela fmt` rules on :w
if vim.b.did_ftplugin then
  return
end
vim.b.did_ftplugin = true

vim.bo.expandtab = true
vim.bo.shiftwidth = 4
vim.bo.softtabstop = 4
vim.bo.commentstring = "// %s"

local file = vim.api.nvim_buf_get_name(0)
if file == "" then
  return
end

vim.lsp.start({
  name = "vela",
  cmd = vim.g.vela_command or { "vela", "lsp" },
  -- One server serves every Vela file; it finds each file's program itself.
  root_dir = vim.fs.dirname(file),
  reuse_client = function(client, config)
    return client.name == config.name
  end,
})

if vim.g.vela_format_on_save then
  vim.api.nvim_create_autocmd("BufWritePre", {
    buffer = 0,
    callback = function()
      vim.lsp.buf.format({ name = "vela", timeout_ms = 2000 })
    end,
  })
end
