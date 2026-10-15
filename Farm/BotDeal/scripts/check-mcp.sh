#!/bin/zsh
# Verify every Cursor MCP server binary referenced by ~/.cursor/mcp.json exists.
# All 8 servers point into ~/.gemini/mcp/ — a broken symlink there silently
# kills the whole Cursor MCP surface. Run after any ~/.gemini reorganization.
set -uo pipefail
cfg="$HOME/.cursor/mcp.json"
fail=0
for bin in $(python3 -c "
import json, sys
d = json.load(open('$cfg'))
for s in d.get('mcpServers', {}).values():
    cmd = s.get('command', '')
    print(cmd)
" 2>/dev/null); do
  if [[ ! -x "$bin" ]]; then
    print "MISSING: $bin"
    fail=1
  fi
done
(( fail == 0 )) && print "all MCP server binaries present" && exit 0
exit 1
