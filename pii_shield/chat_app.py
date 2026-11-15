"""pii chat: a local chat page with a redaction toggle. http://127.0.0.1:8766

Brains: LM Studio (local), any OpenAI-compatible cloud API, or none (redact and copy, then
paste into claude.ai and paste the answer back to restore it).
"""
import json, re, sys, threading, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pii  # noqa: E402

PORT = 8766
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
LOCK = threading.Lock()


def cloud_cfg():
    c = pii.config().get("cloud", {})
    return {"base_url": c.get("base_url", "https://openrouter.ai/api/v1"),
            "model": c.get("model", ""), "api_key": c.get("api_key", "")}


def lmstudio_models():
    """Every downloaded chat model, one entry per version (e.g. qwen/qwen3.8-27b@4bit), smallest bit-width first."""
    import subprocess
    lms = Path.home() / ".lmstudio" / "bin" / "lms"
    try:
        out = subprocess.run([str(lms), "ls", "--json"], capture_output=True, text=True, timeout=15).stdout
        names = []
        for m in json.loads(out):
            if m.get("type") == "embedding" or "embed" in m.get("modelKey", ""):
                continue
            names += m.get("variants") or [m["modelKey"]]
        bits = lambda n: int(re.search(r"@(\d+)bit", n).group(1)) if re.search(r"@(\d+)bit", n) else 99
        return sorted(names, key=lambda n: (n.split("@")[0], bits(n)))
    except Exception:
        return []


def lmstudio_url():
    return pii.config().get("lmstudio_url", "http://localhost:1234/v1")


EFFORTS = {"none": 1500, "low": 4000, "medium": 8000}  # thinking level -> max tokens (stops runaway thinking)


def call(base, key, model, messages, effort=None):
    body = {"messages": messages, "temperature": 0.7}
    if model:
        body["model"] = model
    if effort in EFFORTS:
        body["reasoning_effort"] = effort
        body["max_tokens"] = EFFORTS[effort]

    def post(b):
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=json.dumps(b).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {key or 'lm-studio'}"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)["choices"][0]["message"]["content"] or ""
    try:
        text = post(body)
    except urllib.error.HTTPError as e:
        if "@" not in (model or "") or e.code not in (400, 404):
            raise
        body["model"] = model.split("@")[0]  # server didn't accept a version name; use the base model
        text = post(body)
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S).strip()
    return text or ("(The model used up its thinking time without answering. "
                    "Try again, or set Thinking to a lower level.)")


def restore_parts(text, v):
    """Split a reply into [text, placeholder_or_None] pieces so the page can mark restored values."""
    parts, pos = [], 0
    for m in re.finditer(r"\[([A-Z]+_\d+)\]|(?<![\w\[])([A-Z]+_\d+)(?![\w\]])", text):
        ph = f"[{m.group(1) or m.group(2)}]"
        if ph in v["by_ph"]:
            parts += [[text[pos:m.start()], None], [v["by_ph"][ph], ph]]
            pos = m.end()
    return parts + [[text[pos:], None]]


SYSTEM = ("You are a helpful assistant. A local privacy tool on the user's computer swaps personal "
          "details in their messages for placeholders such as [PERSON_1], [EMAIL_2] or [DETAIL_3] "
          "before you see them, and swaps them back in your reply. The user shared these details on "
          "purpose, so treat each placeholder as the real value and simply help: do not warn about "
          "privacy, do not mention or explain the placeholders, and do not ask what they stand for. "
          "When you refer to one, write it exactly as given, brackets included, e.g. "
          "\"Hi [PERSON_1],\".")


class H(BaseHTTPRequestHandler):
    def _ok_origin(self):
        # Block other websites and DNS rebinding from talking to this local server.
        if self.headers.get("Host") not in HOSTS:
            return False
        o = self.headers.get("Origin")
        return o is None or o.split("//")[-1] in HOSTS

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._ok_origin():
            return self._send(403, {"error": "forbidden"})
        if self.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if self.path == "/api/settings":
            c = cloud_cfg()
            models = lmstudio_models()
            if not models:
                try:
                    with urllib.request.urlopen(lmstudio_url() + "/models", timeout=2) as r:
                        models = [m["id"] for m in json.load(r)["data"] if "embed" not in m["id"]]
                except Exception:
                    pass
            return self._send(200, {"cloud_url": c["base_url"], "cloud_model": c["model"],
                                    "cloud_key_set": bool(c["api_key"]), "lmstudio_models": models})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._ok_origin() or "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(403, {"error": "forbidden"})
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        try:
            if self.path == "/api/redact":
                with LOCK:
                    cfg, v = pii.config(), pii.vault()
                    red, used = pii.redact_text(b["text"], cfg, v)
                    pii.save(pii.VAULT, v)
                return self._send(200, {"redacted": red,
                                        "spans": [[a, z, ph] for a, z, ph in used]})
            if self.path == "/api/restore":
                return self._send(200, {"text": pii.restore_text(b["text"], pii.vault())})
            if self.path == "/api/chat":
                msgs = [{"role": "system", "content": SYSTEM}] + b["messages"]
                if b["brain"] == "cloud":
                    c = cloud_cfg()
                    if not c["api_key"]:
                        return self._send(400, {"error": "Add a cloud API key in Settings first."})
                    reply = call(c["base_url"], c["api_key"], c["model"], msgs)
                else:
                    reply = call(lmstudio_url(), "", b.get("model", ""), msgs, b.get("effort", "low"))
                v = pii.vault()
                return self._send(200, {"raw": reply, "text": pii.restore_text(reply, v),
                                        "parts": restore_parts(reply, v)})
            if self.path == "/api/settings":
                cfg = pii.config()
                c = cfg.setdefault("cloud", {})
                for k in ("base_url", "model", "api_key"):
                    if b.get(k):
                        c[k] = b[k].strip()
                pii.save(pii.CONFIG, cfg)
                return self._send(200, {"ok": True})
        except urllib.error.URLError as e:
            where = "LM Studio (start its server in the Developer tab)" if b.get("brain") != "cloud" else "the cloud API"
            return self._send(502, {"error": f"Couldn't reach {where}: {getattr(e, 'reason', e)}"})
        except Exception as e:
            return self._send(500, {"error": f"{e.__class__.__name__}: {e}"})
        self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Private Chat</title>
<style>
:root{--bg:#fafaf9;--panel:#fff;--fg:#1c1917;--muted:#78716c;--line:#e7e5e4;--accent:#0f766e;--accent-fg:#fff;
--me:#f0fdfa;--mark:#fde68a;--mark-fg:#713f12;--err:#b91c1c;--back:#ccfbf1}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--panel:#1c1c1c;--fg:#f5f5f4;--muted:#a8a29e;--line:#2e2e2e;
--accent:#2dd4bf;--accent-fg:#042f2e;--me:#13302c;--mark:#78350f;--mark-fg:#fde68a;--err:#f87171;--back:#134e4a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,system-ui,sans-serif;
height:100vh;display:flex;flex-direction:column}
header{display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:15px;margin:0 8px 0 0}
select,input,button,textarea{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px 10px}
button{cursor:pointer}button.primary{background:var(--accent);color:var(--accent-fg);border-color:var(--accent);font-weight:600}
.toggle{display:flex;align-items:center;gap:6px;font-size:14px;cursor:pointer;user-select:none}
.toggle input{width:16px;height:16px;accent-color:var(--accent)}
.spacer{flex:1}
nav{display:flex;gap:4px}nav button{border:none;background:none;color:var(--muted)}nav button.on{color:var(--fg);font-weight:600;background:var(--bg)}
main{flex:1;overflow:auto;padding:16px}
.wrap{max-width:820px;margin:0 auto}
.msg{margin:0 0 14px;padding:12px 14px;border-radius:12px;background:var(--panel);border:1px solid var(--line);white-space:pre-wrap;word-break:break-word}
.msg.me{background:var(--me)}
.meta{font-size:12px;color:var(--muted);margin-top:8px}
.meta details summary{cursor:pointer}
.sent{margin-top:6px;padding:8px 10px;border-radius:8px;background:var(--bg);font:13px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap}
mark{background:var(--mark);color:var(--mark-fg);border-radius:3px;padding:0 2px}
mark.back{background:var(--back);color:inherit;border-bottom:1.5px dotted var(--accent);cursor:help}
.err{color:var(--err)}
footer{border-top:1px solid var(--line);background:var(--panel);padding:12px 16px}
footer .wrap{display:flex;gap:8px;align-items:flex-end}
textarea{flex:1;resize:none;min-height:44px;max-height:200px}
.empty{color:var(--muted);text-align:center;margin-top:12vh}
.pane{display:none}.pane.on{display:block}
.tool textarea{width:100%;min-height:160px;margin:8px 0}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
label.f{display:block;font-size:13px;color:var(--muted);margin:12px 0 4px}label.f input{width:100%}
.hint{font-size:13px;color:var(--muted)}
</style></head><body>
<header>
 <h1>Private Chat</h1>
 <nav><button data-p="chat" class="on">Chat</button><button data-p="tool">Redact / Restore</button><button data-p="settings">Settings</button></nav>
 <span class="spacer"></span>
 <select id="brain" title="Which model answers"><option value="local">LM Studio (on this Mac)</option><option value="cloud">Cloud API</option></select>
 <select id="model" title="LM Studio model"></select>
 <select id="effort" title="How long the model thinks before answering">
  <option value="none">Thinking: Off (fastest)</option><option value="low">Thinking: Low</option><option value="medium">Thinking: Medium</option>
 </select>
 <label class="toggle" title="Hide personal data before it is sent"><input type="checkbox" id="redact" checked>Redact</label>
</header>

<main>
<div class="wrap">
 <section class="pane on" id="p-chat"><div id="log"><p class="empty">Type a message. With <b>Redact</b> on, names, emails, phones, addresses,<br>account numbers and keys are swapped for placeholders before anything is sent.</p></div></section>

 <section class="pane tool" id="p-tool">
  <h3>Use with Claude (or any website)</h3>
  <p class="hint">1. Paste your text and press Redact. 2. Copy the result into Claude. 3. Paste Claude's answer below and press Restore to get your real details back.</p>
  <textarea id="tin" placeholder="Paste text with personal data..."></textarea>
  <div class="row"><button class="primary" id="tred">Redact</button><button id="tcopy">Copy result</button></div>
  <div class="sent" id="tout"></div>
  <textarea id="rin" placeholder="Paste Claude's answer with [PERSON_1]-style placeholders..."></textarea>
  <div class="row"><button class="primary" id="tres">Restore</button><button id="rcopy">Copy result</button></div>
  <div class="sent" id="rout"></div>
 </section>

 <section class="pane" id="p-settings">
  <h3>Cloud API (optional)</h3>
  <p class="hint">Any OpenAI-compatible API. Free options: OpenRouter's free models, Google Gemini's free tier.
  Your key is saved only in ~/.pii-shield/config.json on this Mac.</p>
  <label class="f">Base URL<input id="curl"></label>
  <label class="f">Model<input id="cmodel" placeholder="e.g. a model id from openrouter.ai/models"></label>
  <label class="f">API key<input id="ckey" type="password" placeholder="leave empty to keep the current key"></label>
  <div class="row"><button class="primary" id="csave">Save</button><span id="cmsg" class="hint"></span></div>
 </section>
</div>
</main>

<footer id="composer"><div class="wrap">
 <textarea id="inp" rows="1" placeholder="Message (Enter to send, Shift+Enter for a new line)"></textarea>
 <button class="primary" id="send">Send</button>
</div></footer>

<script>
const $ = id => document.getElementById(id);
const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const api = (path, body) => fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {})
  .then(async r => { const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); return j; });
const history = []; // what the model has seen (placeholders when redaction was on)
let busy = false;

const store = {get(k){try{return localStorage.getItem(k)}catch(e){return null}}, set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
$('redact').checked = store.get('redact') !== '0';
$('redact').onchange = () => store.set('redact', $('redact').checked ? '1' : '0');
$('brain').value = store.get('brain') || 'local';
$('brain').onchange = () => { store.set('brain', $('brain').value); const local = $('brain').value === 'local';
  $('model').style.display = local ? '' : 'none'; $('effort').style.display = local ? '' : 'none'; };
$('effort').value = ['none', 'low', 'medium'].includes(store.get('effort')) ? store.get('effort') : 'low';
$('effort').onchange = () => store.set('effort', $('effort').value);

document.querySelectorAll('nav button').forEach(b => b.onclick = () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'p-' + b.dataset.p));
  $('composer').style.display = b.dataset.p === 'chat' ? '' : 'none';
});

function add(cls, html) {
  const empty = document.querySelector('#log .empty'); if (empty) empty.remove();
  const d = document.createElement('div'); d.className = 'msg ' + cls; d.innerHTML = html;
  $('log').appendChild(d); d.scrollIntoView({behavior:'smooth', block:'end'}); return d;
}

async function send() {
  const text = $('inp').value.trim(); if (!text || busy) return;
  busy = true; $('send').disabled = true; $('inp').value = '';
  const me = add('me', esc(text));
  let outgoing = text;
  try {
    if ($('redact').checked) {
      const r = await api('/api/redact', {text});
      outgoing = r.redacted;
      me.innerHTML += `<div class="meta">${r.spans.length ? `🔒 ${r.spans.length} item(s) hidden. Sent as:` : '🔒 Nothing personal found. Sent as typed.'}`
        + (r.spans.length ? `<div class="sent">${highlightSent(r.redacted)}</div>` : '') + '</div>';
    } else {
      me.innerHTML += `<div class="meta">⚠️ Sent without redaction</div>`;
    }
    history.push({role:'user', content: outgoing});
    const wait = add('', '<span class="hint">Thinking…</span>');
    const r = await api('/api/chat', {brain: $('brain').value, model: $('model').value, effort: $('effort').value, messages: history});
    history.push({role:'assistant', content: r.raw});
    const shown = r.parts.map(([t, ph]) => ph ? `<mark class="back" title="Put back on your Mac (the model only saw ${esc(ph)})">${esc(t)}</mark>` : esc(t)).join('');
    const n = r.parts.filter(p => p[1]).length;
    wait.innerHTML = shown + (n ? `<div class="meta"><details><summary>🔓 ${n} highlighted item(s) were put back on your Mac. Show what the model actually wrote</summary><div class="sent">${highlightSent(r.raw)}</div></details></div>` : '');
  } catch (e) {
    document.querySelectorAll('#log .msg').forEach(m => { if (m.textContent === 'Thinking…') m.remove(); });
    if (history.length && history[history.length-1].role === 'user') history.pop();
    add('', `<span class="err">${esc(e.message)}</span>`);
  }
  busy = false; $('send').disabled = false; $('inp').focus();
}
const highlightSent = s => esc(s).replace(/\[[A-Z]+_\d+\]/g, m => `<mark>${m}</mark>`);

$('send').onclick = send;
$('inp').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
$('inp').addEventListener('input', e => { e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px'; });

$('tred').onclick = async () => { const r = await api('/api/redact', {text: $('tin').value}); $('tout').innerHTML = highlightSent(r.redacted); $('tout').dataset.v = r.redacted; };
$('tres').onclick = async () => { const r = await api('/api/restore', {text: $('rin').value}); $('rout').textContent = r.text; };
$('tcopy').onclick = () => navigator.clipboard.writeText($('tout').dataset.v || '');
$('rcopy').onclick = () => navigator.clipboard.writeText($('rout').textContent);

async function loadSettings() {
  try {
    const s = await api('/api/settings');
    $('curl').value = s.cloud_url; $('cmodel').value = s.cloud_model;
    $('ckey').placeholder = s.cloud_key_set ? 'saved (leave empty to keep)' : 'paste your key';
    $('model').innerHTML = s.lmstudio_models.length ? s.lmstudio_models.map(m => `<option>${esc(m)}</option>`).join('')
      : '<option value="">LM Studio not running</option>';
    const saved = store.get('model'); if (saved && s.lmstudio_models.includes(saved)) $('model').value = saved;
  } catch (e) {}
  $('brain').onchange();
}
$('model').onchange = () => store.set('model', $('model').value);
$('csave').onclick = async () => {
  await api('/api/settings', {base_url: $('curl').value, model: $('cmodel').value, api_key: $('ckey').value});
  $('ckey').value = ''; $('cmsg').textContent = 'Saved'; loadSettings();
};
loadSettings();
</script></body></html>"""


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Private Chat running at {url}  (Ctrl+C to stop)", flush=True)
    if "--no-open" not in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    threading.Thread(target=pii.ensure_server, daemon=True).start()  # warm up the model
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
