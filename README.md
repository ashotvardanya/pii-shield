# PII Shield

A free, private alternative to Perplexity's "Hybrid Compute" for macOS. Your personal data
(names, emails, phones, addresses, card and bank numbers, keys) is found **on your Mac** by
Perplexity's open-source PII-Tracer model and swapped for placeholders like `[PERSON_1]` before
anything goes to an AI. Your real details are put back into the answer afterwards.

Works with **Claude** (`/redact`), **LM Studio** (tools, skills and a ready-made assistant preset)
and a small **Private Chat** web page.

---

## Install (also on another Mac)

1. Copy this folder, or `dist/PII-Shield.zip`, to the Mac (AirDrop works) and unzip it.
2. Open **Terminal**, type `bash ` (with a space), drag `install.sh` into the window, and press Enter.
3. Wait a few minutes. It downloads Python and the PII model (about 2 GB in total) once.
4. Open a **new** Terminal window. `pii guide` opens this page.

Requirements: a Mac with Apple Silicon (M1 or newer) and about 3 GB of free disk space.
Claude and LM Studio are optional. Install either one, then run `install.sh` again to connect it.

To remove: `bash uninstall.sh` (it asks before deleting your vault).

---

## 1. Claude: private files with `/redact`

```
/redact ~/Downloads/contract.pdf summarize the payment terms
```

- Type the file path **without @**, and don't use the paperclip. Or drop files into `~/Sensitive`
  and just say `/redact contract.pdf`.
- Claude only sees `Dear [PERSON_1] ...`. If it writes you a document, you get a `.restored`
  copy with your real details back in.
- To check what was hidden: `pii review ~/Downloads/contract.pdf`

Files in `~/Sensitive` are always hidden from Claude. If you paste a card number, IBAN or API key
into Claude, the message is stopped before it is sent. Add `pii-ok` to send it anyway.

## 2. LM Studio: everyday private assistant

1. Load a model with the picker at the top. `install.sh` suggests one that fits your Mac's memory.
2. In the right panel, under **Preset**, choose **Daily Assistant**.
3. Use the wrench icon to turn the tools on. LM Studio asks before each tool runs; tick
   "Always allow" for the ones you trust.

| Tool | What it does |
|---|---|
| web | searches the internet and reads pages |
| files | reads and writes in Documents, Downloads, Desktop (asks first) |
| time | today's date and time |
| memory | "remember that my landlord is Steve" |
| redact | hides personal data before you paste text somewhere else, and loads skills |

Skills the assistant uses: write-email, summarize, web-research, rewrite, translate,
explain-simply, meeting-notes, redact. Everything runs on your Mac except web lookups.

## 3. Private Chat: redact, then use any AI

Run `pii chat` and a page opens in your browser.

- **Chat**: talk to LM Studio (turn on its server in the Developer tab) or a cloud model.
  The **Redact** switch hides personal data first.
- **Redact / Restore**: paste text, press Redact, copy it into claude.ai or ChatGPT, paste the
  answer back, press Restore.

## Commands

```
pii text "I'm Jane, call me at 555 0100"   # redact a sentence
pbpaste | pii text                          # redact what you copied
pii redact FILE / pii restore FILE          # files (PDF, Word, text, CSV...)
pii review FILE                             # see what was hidden
pii deny "nickname" / pii allow "Company"   # fix misses and false alarms
pii chat / pii guide / pii stop / pii status
```

## Resources

- **PII model** (shows as "python", about 1.5 GB): starts only when you redact something and quits
  after 10 idle minutes. Run `pii stop` to free it right away.
- **Private Chat**: runs only while `pii chat` is open (Ctrl+C stops it).
- **LM Studio models**: use RAM while loaded and unload after 60 idle minutes.
- Nothing starts when the Mac boots.

## Limitations (please read)

PII Shield is a best-effort safety net, not a guarantee.

- **Detection can miss things.** No model catches all personal data: unusual names, data in
  images or scanned PDFs (not read at all), and context clues ("my boss at the only bakery in
  town") can slip through. Check important files with `pii review` before sharing.
- **The Claude guard is a heuristic.** It blocks the common ways Claude could read an original
  file, but files attached with the paperclip or drag-and-drop, and creative shell commands, may
  bypass it. Type paths instead, and keep sensitive files in `~/Sensitive`.
- **Placeholders hide values, not meaning.** The AI still sees the structure of your text.
- **macOS on Apple Silicon only** for now. PII-Tracer is strongest in English.
- **Web tools in LM Studio** send search queries to the internet.

Built on [PII-Tracer](https://huggingface.co/perplexity-ai/PII-Tracer) by Perplexity (MIT).

## Where things live

| Path | What |
|---|---|
| `~/.pii-shield/vault.json` | real values for each placeholder (private, never shared) |
| `~/.pii-shield/app/` | installed code |
| `~/Sensitive/` | drop private files here |
| `~/.claude/skills/redact/`, `~/.claude/settings.json` hooks | Claude skill and guard |
| `~/.lmstudio/mcp.json`, `~/.lmstudio/skills/` | LM Studio tools and skills |

## Project layout (for developers)

```
install.sh / uninstall.sh / make_zip.sh
pii_shield/   pii.py (CLI + engine), pii_server.py (model), chat_app.py (Private Chat),
              mcp_server.py (LM Studio tools), guard.py (Claude hook)
skills/       claude/ and lmstudio/ SKILL.md files
lmstudio/     Daily Assistant preset
scripts/      config merging for Claude and LM Studio
tests/        test_core.py (no model needed, uses a temp home folder)
```

Run the tests with `~/.pii-shield/.venv/bin/python tests/test_core.py` and `tests/test_mcp.py`.
Build a zip to share with `bash make_zip.sh`. The zip contains code only, never your vault.
