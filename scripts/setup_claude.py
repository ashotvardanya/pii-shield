"""Add (or update) the pii-shield guard hooks in ~/.claude/settings.json. Keeps a backup."""
import json, shutil, time
from pathlib import Path

H = Path.home()
settings = H / ".claude" / "settings.json"
data = json.loads(settings.read_text()) if settings.exists() else {}
if settings.exists():
    (H / ".claude" / "backups").mkdir(parents=True, exist_ok=True)
    shutil.copy(settings, H / ".claude" / "backups" / f"settings.before-pii-shield.{int(time.time())}.json")

cmd = f'"{H}/.pii-shield/.venv/bin/python" "{H}/.pii-shield/app/guard.py"'
hooks = data.setdefault("hooks", {})


def without_ours(entries):
    return [e for e in entries
            if not any("pii-shield" in h.get("command", "") for h in e.get("hooks", []))]


for event, matcher in (("PreToolUse", "Read|Edit|MultiEdit|NotebookEdit|Grep|Bash"),
                       ("UserPromptSubmit", None)):
    entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 600}]}
    if matcher:
        entry = {"matcher": matcher, **entry}
    hooks[event] = without_ours(hooks.get(event, [])) + [entry]

settings.parent.mkdir(parents=True, exist_ok=True)
settings.write_text(json.dumps(data, indent=2) + "\n")
print("    Claude: /redact skill + file guard installed (restart Claude to load them)")
