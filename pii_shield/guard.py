#!/usr/bin/env python3
"""Claude Code hook: keeps Claude on redacted copies. Stdlib only, so it starts fast.

PreToolUse        -> blocks Read/Edit/Grep/Bash on originals, restored files, protected
                     folders and the vault; auto-creates the redacted copy and points Claude at it.
UserPromptSubmit  -> blocks a prompt that @-mentions a protected file, or pastes a card number,
                     IBAN, SSN or API key. Put "pii-ok" in the message to send it anyway.
"""
import json, os, re, subprocess, sys
from pathlib import Path

HOME = (Path.home() / ".pii-shield").resolve()
APP = Path(__file__).resolve().parent
PII = [str(HOME / ".venv" / "bin" / "python"), str(APP / "pii.py")]


def load(p, d):
    try:
        return json.loads(p.read_text())
    except Exception:
        return d


cfg = load(HOME / "config.json", {})
vault = load(HOME / "vault.json", {})
PROTECTED = [Path(d).expanduser().resolve() for d in
             cfg.get("protected_dirs", [str(Path.home() / "Sensitive")])]
ORIGINALS = vault.get("originals", {})          # original -> redacted copy
RESTORED = set(vault.get("restored", {}))       # files with real values put back
SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml",
             ".html", ".htm", ".log", ".eml", ".rtf", ".ini", ".toml", ".env", ".py", ".js",
             ".ts", ".sql", ".sh", ""}


def resolve(p, cwd):
    p = Path(os.path.expanduser(p))
    return (p if p.is_absolute() else Path(cwd) / p).resolve()


def in_protected(p):
    return any(p == d or d in p.parents for d in PROTECTED)


def is_source(p):
    """pii-shield's own code (no personal data) may be read and edited."""
    return p == APP or APP in p.parents


def verdict(p):
    """None if fine, else (reason, redacted_copy_or_None)."""
    s = str(p)
    if (p == HOME or HOME in p.parents) and not is_source(p):
        return ("this is the private PII vault", None)
    if s in RESTORED or ".restored." in p.name:
        return ("this file has the real personal data restored into it; the user can open it themselves", None)
    if ".redacted." in p.name:
        return None
    if s in ORIGINALS or (in_protected(p) and p.is_file()):
        red = ORIGINALS.get(s)
        stale = red and (not Path(red).exists() or p.stat().st_mtime > Path(red).stat().st_mtime)
        if (not red or stale) and p.suffix.lower() in SUPPORTED:
            r = subprocess.run(PII + ["redact", s], capture_output=True, text=True, timeout=600)
            m = re.search(r"-> (.+)", r.stdout)
            red = m.group(1).strip() if m else red
        return ("this is an original file with personal data", red)
    return None


def deny_tool(reason, red):
    msg = f"Blocked by pii-shield: {reason}."
    if red:
        msg += (f" A redacted copy is ready, read this instead: {red} . Keep placeholders like "
                f"[PERSON_1] exactly as written; after writing output, run `pii restore <file>`.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": msg}}))
    sys.exit(0)


def pre_tool(ev):
    tool, ti, cwd = ev.get("tool_name", ""), ev.get("tool_input", {}), ev.get("cwd", os.getcwd())
    if tool in ("Read", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead"):
        fp = ti.get("file_path") or ti.get("notebook_path")
        if fp and (v := verdict(resolve(fp, cwd))):
            deny_tool(*v)
    elif tool == "Grep":
        p = resolve(ti.get("path") or cwd, cwd)
        if ".redacted." in (ti.get("glob") or "") or is_source(p):
            return
        covers = lambda d: p == d or p in d.parents  # the search would walk into d
        if str(p) in ORIGINALS or str(p) in RESTORED or in_protected(p) or covers(HOME) \
                or HOME in p.parents or any(covers(d) for d in PROTECTED):
            deny_tool("searching here could expose original files; pass glob \"*.redacted.*\"", None)
    elif tool == "Bash":
        cmd = ti.get("command", "")
        if re.match(r"^\s*pii\s", cmd) and not re.search(r"[;&|`]|\$\(|>", cmd):
            if not re.search(r"^\s*pii\s+(forget)\b", cmd):
                return  # pii never prints real values
        if re.match(r"^\s*ls\b", cmd) and not re.search(r"[;&|`]|\$\(", cmd):
            return
        # running pii-shield's own Python or code is fine; only its data is protected
        for safe in (str(HOME / ".venv" / "bin" / "python"), str(APP), "~/.pii-shield/.venv/bin/python",
                     "~/.pii-shield/app", "$HOME/.pii-shield/.venv/bin/python", "$HOME/.pii-shield/app"):
            cmd = cmd.replace(safe, "")
        targets = [str(HOME), "~/.pii-shield", "$HOME/.pii-shield", "${HOME}/.pii-shield", "vault.json"]
        for d in PROTECTED:
            targets += [str(d), "~/" + str(d.relative_to(Path.home())) if Path.home() in d.parents else str(d)]
        for f in list(ORIGINALS) + list(RESTORED):
            targets += [f, Path(f).name]
        hit = next((t for t in targets if t and t in cmd), None)
        if hit or ".restored." in cmd:
            red = ORIGINALS.get(next((f for f in ORIGINALS if Path(f).name in cmd or f in cmd), ""), None)
            deny_tool("this shell command touches a protected file or folder; use the Read tool on the "
                      "*.redacted.* copy, or `pii redact <file>` to make one", red)


def prompt(ev):
    text = ev.get("prompt", "")
    if "pii-ok" in text:
        return
    problems = []
    redact_cmd = text.lstrip().startswith("/redact")
    for m in re.finditer(r"@(\"[^\"]+\"|\S+)", text):
        p = resolve(m.group(1).strip('"'), ev.get("cwd", os.getcwd()))
        if not p.is_file() or ".redacted." in p.name:
            continue
        if redact_cmd and str(p) not in ORIGINALS and not in_protected(p):
            # /redact @file would paste the original into the chat. Redact it here first.
            r = subprocess.run(PII + ["redact", str(p)], capture_output=True, text=True, timeout=600)
            out = re.search(r"-> (.+)", r.stdout)
            problems.append(f"@{m.group(1)} would have been sent unredacted"
                            + (f"; a redacted copy is ready: @{out.group(1).strip()}" if out else ""))
        elif v := verdict(p):
            problems.append(f"@{m.group(1)} is protected" + (f", use @{v[1]} instead" if v[1] else ""))
    if problems and redact_cmd:
        print(json.dumps({"decision": "block", "reason":
              "pii-shield stopped this message so the original file was not sent. "
              + "; ".join(problems) + ". Resend with the file path typed without the @ "
              "(e.g. /redact ~/Downloads/file.pdf), or @-mention the redacted copy."}))
        sys.exit(0)
    digits = lambda s: [int(c) for c in re.sub(r"\D", "", s)][::-1]
    for m in re.finditer(r"\b(?:\d[ -]?){13,19}\b", text):
        d = digits(m.group(0))
        if sum(x if i % 2 == 0 else (x * 2 - 9 if x > 4 else x * 2) for i, x in enumerate(d)) % 10 == 0:
            problems.append("looks like a card number")
    if re.search(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}", text):
        problems.append("looks like an IBAN")
    if re.search(r"\b\d{3}-\d{2}-\d{4}\b", text):
        problems.append("looks like a Social Security number")
    if re.search(r"\b(?:sk|pk|rk)_(?:live|test)_\w{10,}|\b(?:sk-|ghp_|github_pat_|xox[abp]-|AKIA)\w{12,}", text):
        problems.append("looks like an API key")
    if problems:
        print(json.dumps({"decision": "block", "reason":
              "pii-shield stopped this message before it was sent: " + "; ".join(sorted(set(problems))) +
              ". Put the data in a file in ~/Sensitive (Claude only ever sees a redacted copy), "
              "or add 'pii-ok' anywhere in your message to send it as is."}))
    sys.exit(0)


if __name__ == "__main__":
    ev = json.load(sys.stdin)
    (prompt if ev.get("hook_event_name") == "UserPromptSubmit" else pre_tool)(ev)
