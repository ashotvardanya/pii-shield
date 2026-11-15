"""Starts the LM Studio tool server and calls its tools (no model needed; temp home folder).
Run:  ~/.pii-shield/.venv/bin/python tests/test_mcp.py
"""
import asyncio, json, os, shutil, sys, tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
home = Path(tempfile.mkdtemp())
shutil.copytree(ROOT / "skills" / "lmstudio", home / ".lmstudio" / "skills")
(home / ".pii-shield").mkdir()
(home / ".pii-shield" / "vault.json").write_text(json.dumps(
    {"by_value": {"Jane Doe": "[PERSON_1]"}, "by_ph": {"[PERSON_1]": "Jane Doe"}}))


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "pii_shield" / "mcp_server.py")],
                                   env={**os.environ, "HOME": str(home)})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            assert tools == ["get_skill", "list_skills", "redact_file", "redact_text",
                             "restore_file", "restore_text"], tools
            print("ok   6 tools listed")
            out = (await s.call_tool("restore_text", {"text": "Hi [PERSON_1]"})).content[0].text
            assert out == "Hi Jane Doe", out
            print("ok   restore_text")
            out = (await s.call_tool("list_skills", {})).content[0].text
            assert out.count("\n- ") == 7, out
            print("ok   8 skills listed")
            out = (await s.call_tool("get_skill", {"name": "write-email"})).content[0].text
            assert out.startswith("# Write email"), out
            print("ok   get_skill")
    print("\nall MCP checks passed")

asyncio.run(main())
