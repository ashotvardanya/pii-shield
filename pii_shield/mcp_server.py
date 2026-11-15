"""pii-shield as an MCP tool server, for LM Studio (or any MCP app).

Tools: redact_text, restore_text, redact_file, restore_file, list_skills, get_skill.
Uses the same vault as the `pii` command, so placeholders match everywhere.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pii  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402

app = MCPServer("pii-shield", instructions=(
    "Local privacy tools. Use redact_text before the user pastes text into a cloud AI or "
    "website, and restore_text on the answer they bring back."))


@app.tool(description="Hide personal data (names, emails, phones, addresses, account numbers, "
                      "keys) in text, replacing it with placeholders like [PERSON_1]. Runs locally.")
def redact_text(text: str) -> str:
    cfg, v = pii.config(), pii.vault()
    red, used = pii.redact_text(text, cfg, v)
    pii.save(pii.VAULT, v)
    return red


@app.tool(description="Put the real values back into text containing placeholders like [PERSON_1].")
def restore_text(text: str) -> str:
    return pii.restore_text(text, pii.vault())


@app.tool(description="Make a redacted copy of a file (txt, md, csv, pdf, docx...) next to it. "
                      "Returns the new file's path and its redacted contents.")
def redact_file(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return f"No such file: {p}"
    cfg, v = pii.config(), pii.vault()
    text, ext = pii.read_any(p)
    red, used = pii.redact_text(text, cfg, v)
    out = pii.out_path(p, "redacted", ext)
    out.write_text(red)
    v["originals"][str(p)] = str(out)
    pii.save(pii.VAULT, v)
    pii.write_review(p, text, used, out)
    return f"Saved redacted copy: {out}\n{len(used)} items hidden.\n\n{red[:20000]}"


@app.tool(description="Put real values back into a file that contains placeholders. "
                      "Saves <name>.restored.<ext> next to it and returns its path.")
def restore_file(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return f"No such file: {p}"
    v = pii.vault()
    out = pii.out_path(p.with_name(p.name.replace(".redacted.", ".")), "restored", p.suffix)
    out.write_text(pii.restore_text(p.read_text(errors="replace"), v))
    v["restored"][str(out)] = str(p)
    pii.save(pii.VAULT, v)
    return f"Saved: {out}"


SKILLS = Path.home() / ".lmstudio" / "skills"


def _skills():
    out = {}
    for f in sorted(SKILLS.glob("*/SKILL.md")):
        text = f.read_text()
        desc = next((l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("description:")), "")
        out[f.parent.name] = (desc, text.split("---", 2)[-1].strip())
    return out


@app.tool(description="List the available skills (step-by-step playbooks for common tasks like "
                      "write-email, summarize, web-research, translate, redact) with when to use each.")
def list_skills() -> str:
    return "\n".join(f"- {n}: {d}" for n, (d, _) in _skills().items()) or "No skills installed."


@app.tool(description="Load a skill's instructions by name before doing that kind of task, "
                      "then follow them. Call list_skills if unsure of the name.")
def get_skill(name: str) -> str:
    s = _skills().get(name.strip().lower())
    return s[1] if s else f"No skill named {name!r}. Available: {', '.join(_skills())}"


if __name__ == "__main__":
    app.run("stdio")
