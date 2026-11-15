---
name: redact
description: Hide personal data (names, emails, phones, addresses, account and card numbers, keys) before the user shares text or files with a cloud AI, a website or another person. Use when the user says redact, anonymize, hide my info, make this safe to share, or wants to paste something into ChatGPT/Claude/Gemini.
---
# Redact

Use the `redact` tools. They run on this Mac with Perplexity's PII-Tracer model.

- Text: call `redact_text`, then give the user the result in one code block so they can copy it.
- File: call `redact_file` with the full path. Tell the user where the redacted copy was saved.
- Answer brought back from a cloud AI: call `restore_text` (or `restore_file` for a file) to put the real values back.

Placeholders like [PERSON_1] stay the same across texts, files and sessions. If something
personal was missed, tell the user to run `pii deny "the text"` in Terminal; for a false alarm,
`pii allow "the text"`. Never repeat the original personal data in your own words.
