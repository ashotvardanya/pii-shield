"""Quick checks that need no model and touch no real data (HOME is a temp folder).
Run:  ~/.pii-shield/.venv/bin/python tests/test_core.py
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["HOME"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT / "pii_shield"))
import pii  # noqa: E402

pii.model_spans = lambda text: []  # rules only; the real model is tested by install.sh
ok = 0


def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print("ok  ", name)


cfg, v = pii.config(), pii.vault()
text = "Mail jane.doe@example.org, card 4111 1111 1111 1111, IBAN DE89 3704 0044 0532 0130 00, key sk-abc123def456ghi789jkl"
red, used = pii.redact_text(text, cfg, v)
check("email hidden", "jane.doe@example.org" not in red)
check("card hidden", "4111" not in red)
check("IBAN hidden, label kept", "DE89" not in red and "IBAN [ACCOUNT_" in red)
check("API key hidden", "sk-abc" not in red)
check("restore round-trip", pii.restore_text(red, v) == text)
check("brackets dropped still restore", "jane.doe@example.org" in pii.restore_text("write to EMAIL_1", v))
red2, _ = pii.redact_text("again jane.doe@example.org", cfg, v)
check("same value, same placeholder", red2 == "again [EMAIL_1]")
check("random digits not a card", "1234 5678 9012 3456" in pii.redact_text("ref 1234 5678 9012 3456", cfg, v)[0])
cfg["allow"] = ["acme@corp.com"]
check("allow list respected", "acme@corp.com" in pii.redact_text("ask acme@corp.com", cfg, v)[0])


def guard(event):
    r = subprocess.run([sys.executable, str(ROOT / "pii_shield" / "guard.py")],
                       input=json.dumps(event), capture_output=True, text=True, env=os.environ)
    return r.stdout


home = Path(os.environ["HOME"])
(home / "Sensitive").mkdir()
check("guard blocks vault", "deny" in guard({"hook_event_name": "PreToolUse", "tool_name": "Read",
      "tool_input": {"file_path": str(home / ".pii-shield" / "vault.json")}, "cwd": "/"}))
check("guard allows normal files", guard({"hook_event_name": "PreToolUse", "tool_name": "Read",
      "tool_input": {"file_path": str(ROOT / "README.md")}, "cwd": "/"}) == "")
check("guard stops pasted card", "block" in guard({"hook_event_name": "UserPromptSubmit",
      "prompt": "my card 4000 0566 5566 5556", "cwd": "/"}))
check("pii-ok override", guard({"hook_event_name": "UserPromptSubmit",
      "prompt": "pii-ok my card 4000 0566 5566 5556", "cwd": "/"}) == "")
bash = lambda c: guard({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                        "tool_input": {"command": c}, "cwd": "/"})
check("guard allows running its own python", bash("~/.pii-shield/.venv/bin/python tests/test_core.py") == "")
check("guard blocks reading the vault by shell", "deny" in bash("cat ~/.pii-shield/vault.json"))
check("guard blocks vault via $HOME", "deny" in bash("cat $HOME/.pii-shield/vault.json"))
check("guard blocks path tricks", "deny" in bash("cat ~/.pii-shield/app/../vault.json"))
print(f"\nall {ok} checks passed")
