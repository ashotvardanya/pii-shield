"""Remove pii-shield entries from Claude settings and LM Studio mcp.json, leaving everything else."""
import json
from pathlib import Path

H = Path.home()

s = H / ".claude" / "settings.json"
if s.exists():
    data = json.loads(s.read_text())
    hooks = data.get("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [e for e in hooks[ev]
                     if not any("pii-shield" in h.get("command", "") for h in e.get("hooks", []))]
        if not hooks[ev]:
            del hooks[ev]
    if not hooks:
        data.pop("hooks", None)
    s.write_text(json.dumps(data, indent=2) + "\n")

m = H / ".lmstudio" / "mcp.json"
if m.exists():
    data = json.loads(m.read_text())
    ours = ("pii-shield", "mcp-server-fetch", "mcp-server-time",
            "@modelcontextprotocol/server-filesystem", "@modelcontextprotocol/server-memory")
    data["mcpServers"] = {k: v for k, v in data.get("mcpServers", {}).items()
                          if not any(o in json.dumps(v) for o in ours)}
    m.write_text(json.dumps(data, indent=2) + "\n")
