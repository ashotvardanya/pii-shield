"""Keeps PII-Tracer loaded on 127.0.0.1:8765 so redaction is instant. Exits after 10 idle minutes."""
import json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # use the cached model; never phone home
import torch
from transformers import AutoModel

MODEL = "perplexity-ai/PII-Tracer"
REV = "d25c16f2e57e321f6d2527715c01df9112f956f5"  # pinned: the version that was reviewed
model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, revision=REV)
if torch.backends.mps.is_available():
    try:
        model = model.to("mps")
    except Exception:
        pass
model.eval()
lock, last = threading.Lock(), [time.time()]
CHUNK = 6000  # characters, comfortably under the 4096-token window


def chunks(text):
    i = 0
    while i < len(text):
        j = min(len(text), i + CHUNK)
        if j < len(text):  # cut at a paragraph or line break when possible
            k = max(text.rfind("\n\n", i, j), text.rfind("\n", i, j))
            if k > i + CHUNK // 2:
                j = k + 1
        yield i, text[i:j]
        i = j


def detect(text):
    out = []
    with lock, torch.inference_mode():
        for off, c in chunks(text):
            spans, _ = model.predict(c)
            out += [[off + s.start, off + s.end, s.label] for s in spans]
    return out


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        last[0] = time.time()
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        data = json.dumps({"spans": detect(body["text"])}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def reaper(srv):
    while time.time() - last[0] < 600:  # quit after 10 idle minutes to free ~1.5 GB
        time.sleep(30)
    srv.shutdown()


srv = ThreadingHTTPServer(("127.0.0.1", 8765), H)
threading.Thread(target=reaper, args=(srv,), daemon=True).start()
print("PII-Tracer ready on 127.0.0.1:8765", flush=True)
srv.serve_forever()
