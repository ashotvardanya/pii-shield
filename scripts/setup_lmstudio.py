"""Add the pii-shield tools to LM Studio's ~/.lmstudio/mcp.json (keeps any other servers)."""
import json, os, shutil
from pathlib import Path

H = Path.home()
path = H / ".lmstudio" / "mcp.json"
data = json.loads(path.read_text()) if path.exists() else {}
servers = data.setdefault("mcpServers", {})

extra_path = f"{H}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
find = lambda name: shutil.which(name, path=extra_path)
try:
    tz = os.path.realpath("/etc/localtime").split("zoneinfo/")[1]
except Exception:
    tz = "UTC"

servers["redact"] = {"command": f"{H}/.pii-shield/.venv/bin/python",
                     "args": [f"{H}/.pii-shield/app/mcp_server.py"]}
added, skipped = ["redact"], []

if uvx := find("uvx"):
    servers["web"] = {"command": uvx, "args": ["mcp-server-fetch"]}
    servers["time"] = {"command": uvx, "args": ["mcp-server-time", "--local-timezone", tz]}
    added += ["web", "time"]
else:
    skipped += ["web", "time (need uv)"]

if npx := find("npx"):
    env = {"PATH": extra_path}
    folders = [str(H / d) for d in ("Documents", "Downloads", "Desktop") if (H / d).is_dir()]
    servers["files"] = {"command": npx, "args": ["-y", "@modelcontextprotocol/server-filesystem", *folders],
                        "env": env}
    servers["memory"] = {"command": npx, "args": ["-y", "@modelcontextprotocol/server-memory"],
                         "env": {**env, "MEMORY_FILE_PATH": str(H / ".lmstudio" / "memory.jsonl")}}
    added += ["files", "memory"]
else:
    skipped += ["files", "memory (need Node.js: brew install node, or nodejs.org)"]

path.write_text(json.dumps(data, indent=2) + "\n")
print(f"    LM Studio tools: {', '.join(added)}  (timezone {tz})")
if skipped:
    print(f"    Skipped: {', '.join(skipped)}")
print("    Skills and the 'Daily Assistant' preset are installed. Restart LM Studio, then turn the")
print("    tools on with the wrench icon in the chat's right panel.")
