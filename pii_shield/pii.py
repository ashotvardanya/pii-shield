#!/usr/bin/env python3
"""
pii - local redaction for working with Claude on sensitive files.

  pii redact FILE...     write FILE.redacted.<ext> next to each file (PDF/DOCX -> .redacted.md)
  pii text "TEXT"        redact a sentence and print it (or pipe text in: pbpaste | pii text)
  pii review FILE        open a side-by-side check page in your browser (local only)
  pii restore FILE...    put real values back -> FILE.restored.<ext>
  pii allow "TEXT"       never redact TEXT (e.g. your company name)
  pii deny  "TEXT"       always redact TEXT (e.g. a nickname the model missed)
  pii protect DIR        Claude may only read redacted copies inside DIR
  pii status             show settings and counts (never prints real values)
  pii stop               unload the PII model now (it also quits by itself after 10 idle minutes)
  pii chat               open the Private Chat page in your browser
  pii guide              open the how-to guide
  pii forget             wipe the vault (placeholders can no longer be restored)

Real values live only in ~/.pii-shield/vault.json (chmod 600). Nothing here
ever prints a real value to the terminal, so it is safe for Claude to run it.
"""
import html, json, os, re, socket, subprocess, sys, time, urllib.request
from pathlib import Path

HOME = Path.home() / ".pii-shield"          # private data: vault, config, reviews, venv
APP = Path(__file__).resolve().parent       # this code
VAULT = HOME / "vault.json"
CONFIG = HOME / "config.json"
REVIEWS = HOME / "reviews"
PORT = 8765
PY = HOME / ".venv" / "bin" / "python"

LABELS = {"private_person": "PERSON", "account_number": "ACCOUNT", "private_url": "URL",
          "private_date": "DATE", "private_address": "ADDRESS", "private_email": "EMAIL",
          "private_phone": "PHONE", "other_pii": "DETAIL", "secret": "SECRET"}

REGEX = [  # high-precision safety net on top of the model
    ("EMAIL", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("SECRET", r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{10,}\b"),
    ("SECRET", r"\b(?:sk-|ghp_|gho_|github_pat_|xox[abp]-|AIza)[A-Za-z0-9_\-]{16,}\b"),
    ("SECRET", r"\bAKIA[0-9A-Z]{16}\b"),
    ("SECRET", r"(?<=://)[^:/\s@]+:[^@\s/]+(?=@)"),                       # user:pass@host
    ("ACCOUNT", r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b"),  # IBAN
    ("ACCOUNT", r"\b(?:\d[ -]?){13,19}\b"),                                 # cards (Luhn)
    ("ID", r"\b\d{3}-\d{2}-\d{4}\b"),                                      # US SSN
]

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
            ".log", ".eml", ".rtf", ".ini", ".toml", ".env", ".py", ".js", ".ts", ".sql", ".sh"}


# ------------------------------------------------------------------ storage
def load(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save(path, data):
    HOME.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def config():
    c = load(CONFIG, {})
    c.setdefault("protected_dirs", [str(Path.home() / "Sensitive")])
    c.setdefault("allow", [])
    c.setdefault("deny", [])
    return c


def vault():
    v = load(VAULT, {})
    for k in ("by_value", "by_ph", "count", "originals", "restored"):
        v.setdefault(k, {})
    for val, ph in list(v["by_value"].items()):  # migrate vague [PII_n] to [DETAIL_n]
        if ph.startswith("[PII_"):
            v["count"]["DETAIL"] = v["count"].get("DETAIL", 0) + 1
            new = f"[DETAIL_{v['count']['DETAIL']}]"
            v["by_value"][val], v["by_ph"][new] = new, val  # old [PII_n] still restores
    return v


# ------------------------------------------------------------------ detection
def luhn(s):
    d = [int(c) for c in re.sub(r"\D", "", s)][::-1]
    return 13 <= len(d) <= 19 and sum(x if i % 2 == 0 else (x * 2 - 9 if x > 4 else x * 2)
                                      for i, x in enumerate(d)) % 10 == 0


def server_up():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
        return True
    except OSError:
        return False


def ensure_server():
    if server_up():
        return True
    HOME.mkdir(exist_ok=True)
    log = open(HOME / "server.log", "a")
    subprocess.Popen([str(PY), str(APP / "pii_server.py")], stdout=log, stderr=log,
                     start_new_session=True)
    for _ in range(240):  # model load ~5-20s
        time.sleep(0.5)
        if server_up():
            return True
    return False


def model_spans(text):
    if not ensure_server():
        print("warning: PII model unavailable, using rules only (see ~/.pii-shield/server.log)",
              file=sys.stderr)
        return []
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/detect",
                                 data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return [(a, b, LABELS.get(l, "ID")) for a, b, l in json.load(r)["spans"]]
    except Exception as e:  # don't fall back silently: rules alone miss names and addresses
        sys.exit(f"error: PII model failed ({type(e).__name__}); nothing was redacted. "
                 "See ~/.pii-shield/server.log, or run `pii stop` and try again.")


def detect(text, cfg, v):
    spans = list(model_spans(text))
    for kind, pat in REGEX:
        for m in re.finditer(pat, text):
            if kind == "ACCOUNT" and not m.group(0)[:2].isalpha() and not luhn(m.group(0)):
                continue
            spans.append((m.start(), m.end(), kind))
    # anything already in the vault or deny list, everywhere it appears (whole words)
    known = [(val, v["by_value"][val].strip("[]").rsplit("_", 1)[0]) for val in v["by_value"]]
    known += [(d, "DETAIL") for d in cfg["deny"]]
    for val, kind in known:
        kind = "DETAIL" if kind == "PII" else kind  # older vault entries
        if len(val) < 3:
            continue
        for m in re.finditer(r"(?<!\w)" + re.escape(val) + r"(?!\w)", text):
            spans.append((m.start(), m.end(), kind))
    # trim whitespace/punctuation, drop allow-listed, merge overlaps (longest wins)
    allow = {a.lower() for a in cfg["allow"]}
    clean = []
    for a, b, k in spans:
        while a < b and text[a] in " \t\n,;:.\"'": a += 1
        while b > a and text[b - 1] in " \t\n,;:\"'": b -= 1
        # drop field labels the model sometimes includes ("IBAN DE89..." -> "DE89...")
        lbl = re.match(r"(?i)(?:iban|swift|bic|card|ssn|dob|phone|tel|email|e-mail|account|acct)\b[\s:#.-]*",
                       text[a:b])
        if lbl:
            a += lbl.end()
        if a < b and text[a] == "(" and ")" not in text[a:b]: a += 1
        if a < b and text[b - 1] == ")" and "(" not in text[a:b]: b -= 1
        if b - a >= 2 and text[a:b].lower() not in allow:
            clean.append((a, b, k))
    clean.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged = []
    for s in clean:
        if merged and s[0] < merged[-1][1]:
            if s[1] > merged[-1][1]:
                merged[-1] = (merged[-1][0], s[1], merged[-1][2])
            continue
        merged.append(s)
    return merged


def redact_text(text, cfg, v):
    spans = detect(text, cfg, v)
    out, pos, used = [], 0, []
    for a, b, kind in spans:
        val = text[a:b]
        if val not in v["by_value"]:
            v["count"][kind] = v["count"].get(kind, 0) + 1
            ph = f"[{kind}_{v['count'][kind]}]"
            v["by_value"][val], v["by_ph"][ph] = ph, val
        ph = v["by_value"][val]
        out += [text[pos:a], ph]
        used.append((a, b, ph))
        pos = b
    out.append(text[pos:])
    return "".join(out), used


def restore_text(text, v):
    def sub(m):
        return v["by_ph"].get(f"[{m.group(1)}]", m.group(0))
    text = re.sub(r"\[([A-Z]+_\d+)\]", sub, text)
    return re.sub(r"(?<![\w\[])([A-Z]+_\d+)(?![\w\]])", sub, text)  # model dropped brackets


# ------------------------------------------------------------------ files
def read_any(p):
    ext = p.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages), ".md"
    if ext == ".docx":
        import docx
        d = docx.Document(str(p))
        parts = [para.text for para in d.paragraphs]
        for t in d.tables:
            parts += [" | ".join(c.text for c in row.cells) for row in t.rows]
        return "\n".join(parts), ".md"
    return p.read_text(errors="replace"), (p.suffix or ".txt")


def out_path(p, tag, ext):
    name = p.name[: -len(p.suffix)] if p.suffix else p.name
    return p.with_name(f"{name}.{tag}{ext}")


def write_review(src, text, used, redacted):
    REVIEWS.mkdir(parents=True, exist_ok=True)
    parts, pos = [], 0
    for a, b, ph in used:
        parts += [html.escape(text[pos:a]),
                  f'<mark title="{html.escape(ph)}">{html.escape(text[a:b])}'
                  f'<sub>{html.escape(ph)}</sub></mark>']
        pos = b
    parts.append(html.escape(text[pos:]))
    rows = "".join(f"<tr><td>{html.escape(ph)}</td><td>{html.escape(text[a:b])}</td></tr>"
                   for ph, (a, b) in {ph: (a, b) for a, b, ph in used}.items())
    page = f"""<!doctype html><meta charset=utf-8><title>Review: {html.escape(src.name)}</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--card:#f5f5f7;--mark:#ffe08a;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1c1e;--fg:#f2f2f7;--muted:#98989d;--card:#2c2c2e;--mark:#7a5c00;--line:#3a3a3c}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;padding:24px}}
h1{{font-size:18px;margin:0 0 4px}} p{{color:var(--muted);margin:0 0 16px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media (max-width:800px){{.grid{{grid-template-columns:1fr}}}}
pre{{background:var(--card);padding:16px;border-radius:10px;white-space:pre-wrap;word-break:break-word;margin:0;font:13px/1.55 ui-monospace,Menlo,monospace}}
mark{{background:var(--mark);color:inherit;border-radius:3px;padding:0 2px}} sub{{font-size:10px;opacity:.7;margin-left:2px}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
table{{border-collapse:collapse;margin-bottom:20px}} td{{border-bottom:1px solid var(--line);padding:4px 12px 4px 0}}
</style>
<h1>{html.escape(src.name)}</h1>
<p>{len(used)} redactions. Highlighted text is what was hidden. Anything personal that is NOT highlighted on the left was missed:
fix it with <code>pii deny "text"</code> (or <code>pii allow "text"</code> for false alarms) and run <code>pii redact</code> again.
Redacted copy: {html.escape(str(redacted))}</p>
<h2>Replacements</h2><table>{rows}</table>
<div class=grid><div><h2>Original (stays on your Mac)</h2><pre>{''.join(parts)}</pre></div>
<div><h2>What Claude sees</h2><pre>{html.escape(open(redacted).read())}</pre></div></div>"""
    rp = REVIEWS / (re.sub(r"\W", "_", str(src)) + ".html")
    rp.write_text(page)
    os.chmod(rp, 0o600)
    return rp


# ------------------------------------------------------------------ commands
def cmd_redact(files, open_review=False):
    cfg, v = config(), vault()
    for f in files:
        p = Path(f).expanduser().resolve()
        if ".redacted." in p.name:
            print(f"skip {p.name}: already a redacted copy"); continue
        text, ext = read_any(p)
        red, used = redact_text(text, cfg, v)
        op = out_path(p, "redacted", ext)
        op.write_text(red)
        v["originals"][str(p)] = str(op)
        save(VAULT, v)
        rp = write_review(p, text, used, op)
        kinds = {}
        for _, _, ph in used:
            k = ph.strip("[]").rsplit("_", 1)[0]
            kinds[k] = kinds.get(k, 0) + 1
        summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "nothing found"
        print(f"{p.name} -> {op}\n  redacted: {summary}\n  review:   pii review \"{p}\"")
        if open_review:
            subprocess.run(["open", str(rp)])


def cmd_text(args):
    if args:
        text = " ".join(args)
    else:
        if sys.stdin.isatty():
            print("Type or paste your text, then press Enter and Ctrl+D (Ctrl+C cancels):",
                  file=sys.stderr)
        try:
            text = sys.stdin.read()
        except KeyboardInterrupt:
            print("\ncancelled", file=sys.stderr)
            return
    cfg, v = config(), vault()
    red, _ = redact_text(text, cfg, v)
    save(VAULT, v)
    sys.stdout.write(red if red.endswith("\n") else red + "\n")


def cmd_review(f):
    p = Path(f).expanduser().resolve()
    if ".redacted." in p.name:  # accept either the original or the copy
        v = vault()
        p = Path(next((o for o, r in v["originals"].items() if r == str(p)), str(p)))
    rp = REVIEWS / (re.sub(r"\W", "_", str(p)) + ".html")
    if not rp.exists():
        sys.exit(f"no review yet for {p.name}; run: pii redact \"{p}\"")
    subprocess.run(["open", str(rp)])
    print(f"opened review for {p.name} in your browser")


def cmd_restore(files):
    v = vault()
    for f in files:
        p = Path(f).expanduser().resolve()
        tag = "restored"
        if p.suffix.lower() == ".docx":
            import docx
            d = docx.Document(str(p))
            paras = list(d.paragraphs) + [c for t in d.tables for row in t.rows
                                          for cell in row.cells for c in cell.paragraphs]
            for para in paras:
                if re.search(r"[A-Z]+_\d+", para.text):
                    new = restore_text(para.text, v)
                    if new != para.text:
                        for r in para.runs[1:]:
                            r.text = ""
                        para.runs[0].text = new
            op = out_path(p, tag, ".docx")
            d.save(str(op))
        else:
            text = p.read_text(errors="replace")
            name = p.name.replace(".redacted.", ".")
            op = out_path(p.with_name(name), tag, p.suffix)
            op.write_text(restore_text(text, v))
        v["restored"][str(op)] = str(p)
        save(VAULT, v)
        print(f"{p.name} -> {op}  (contains real data; Claude is blocked from reading it)")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__); return
    c, rest = a[0], a[1:]
    if c == "redact":
        o = "--open" in rest
        files = [x for x in rest if x != "--open"]
        if not files:
            sys.exit('Usage: pii redact FILE...   (for a sentence, use: pii text "your text")')
        missing = [f for f in files if not Path(f).expanduser().exists()]
        if missing:
            sys.exit(f"No such file: {missing[0]}\n"
                     f'pii redact works on files. To redact a sentence, use: pii text "your text"')
        cmd_redact(files, o)
    elif c == "text":
        cmd_text(rest)
    elif c == "review":
        cmd_review(rest[0])
    elif c == "restore":
        cmd_restore(rest)
    elif c in ("allow", "deny"):
        cfg = config(); cfg[c] = sorted(set(cfg[c]) | {" ".join(rest)}); save(CONFIG, cfg)
        print(f"added to {c} list ({len(cfg[c])} entries)")
    elif c == "protect":
        cfg = config(); d = str(Path(rest[0]).expanduser().resolve())
        cfg["protected_dirs"] = sorted(set(cfg["protected_dirs"]) | {d}); save(CONFIG, cfg)
        Path(d).mkdir(parents=True, exist_ok=True)
        print(f"protected: {d}")
    elif c == "status":
        cfg, v = config(), vault()
        print(json.dumps({"protected_dirs": cfg["protected_dirs"], "allow_entries": len(cfg["allow"]),
                          "deny_entries": len(cfg["deny"]), "placeholders": len(v["by_ph"]),
                          "redacted_files": len(v["originals"]), "model_server": server_up()}, indent=1))
    elif c == "stop":
        r = subprocess.run(["pkill", "-f", "pii_server.py"])
        print("PII model stopped, memory freed" if r.returncode == 0 else "PII model wasn't running")
    elif c == "forget":
        VAULT.unlink(missing_ok=True); print("vault wiped")
    else:
        sys.exit(f"Unknown command: {c}\n"
                 f'To redact a sentence, use: pii text "your text"\nRun "pii help" to see all commands.')


if __name__ == "__main__":
    main()
