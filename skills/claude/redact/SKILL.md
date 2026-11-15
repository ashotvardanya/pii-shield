---
name: redact
description: Work on files containing personal or sensitive data (names, addresses, emails, phones, bank/card/ID numbers, medical records, contracts, payslips, passwords/keys) without exposing the real values. Use when the user says redact, sensitive, private, confidential, PII, "hide my info", or points at a file in ~/Sensitive, or when a read is blocked by pii-shield.
---

# Redact: work on sensitive files using placeholders

Redaction runs on this Mac with Perplexity's open-source PII-Tracer model plus extra rules.
You only ever see placeholders such as `[PERSON_1]`, `[EMAIL_2]` or `[ACCOUNT_1]`. The real
values stay in `~/.pii-shield/vault.json`, which you must never read. The same value always gets
the same placeholder, across files and sessions.

A pii-shield hook enforces this. It blocks reads of originals, restored files, files in
protected folders (default `~/Sensitive`) and the vault, and it points you at the redacted copy.
When a read is blocked, do not try to get around it. Follow the pointer.

## Steps

0. **Find the files.** The user usually types `/redact <path> [<path>...] <what to do>`, with plain
   paths (no @). Paths may use `~` or be relative to the working directory. If no path is given,
   ask which file. If a path has spaces, quote it in the command.

1. **Redact.** Run `pii redact "<file>" ["<file2>" ...]`. It writes `<name>.redacted.<ext>` next
   to each file, and PDF and DOCX files become `.redacted.md`. It prints only counts, never values.
   The first run takes about 20 seconds while the model loads, and later runs are fast.
2. **Read only the `.redacted.` copy** with the Read tool. When grepping, pass `glob: "*.redacted.*"`.
3. **Do the task.** Use placeholders exactly as written, brackets included, in everything you
   write. Never guess, invent or ask the user for the real values behind them. If the task truly
   needs a hidden value (for example, to look up a real company), ask the user whether to `pii allow` it.
4. **Restore if there's an output file.** Write the output with placeholders (.md, .txt, .docx and
   so on), then run `pii restore "<output>"`. This creates `<name>.restored.<ext>` with the real
   values back. Do not open the restored file; it is blocked. Give the user its path.
5. **Tell the user how to check.** Mention that `pii review "<file>"` opens a local page that shows
   exactly what was hidden. If they find a miss or a false alarm:
   - `pii deny "missed text"`: always hide this
   - `pii allow "Company Name"`: never hide this
   Then run `pii redact` again on the file.

## Other commands

- `pii protect <dir>`: make a whole folder redacted-only
- `pii status`: settings and counts
- `echo "..." | pii text`: redact a snippet

Never run `cat`, `head`, `python` and similar on originals or restored files, and never print
`vault.json`. When a chat answer contains placeholders, just tell the user they can run
`pii restore` on a saved copy, or read the placeholders against `pii review`.
