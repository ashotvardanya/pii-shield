#!/bin/bash
# PII Shield installer for macOS. Safe to run again (it updates in place).
#   bash install.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
D="$HOME/.pii-shield"          # private data + Python env (never copied anywhere)
APP="$D/app"                   # installed code
BIN="$HOME/.local/bin"
REV="d25c16f2e57e321f6d2527715c01df9112f956f5"
export PATH="$BIN:/opt/homebrew/bin:/usr/local/bin:$PATH"

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
note() { printf "    %s\n" "$*"; }

[ "$(uname -s)" = Darwin ] || { echo "This installer is for macOS."; exit 1; }
RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
[ "$(uname -m)" = arm64 ] || note "Note: this Mac is not Apple Silicon; redaction will be slower."

step "1/7  Python tools"
if ! command -v uv >/dev/null 2>&1; then
  note "Installing uv (Python manager, from astral.sh)..."
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null
fi
UV="$(command -v uv)"
note "uv: $UV"

step "2/7  Python environment (first time: a few minutes)"
mkdir -p "$D"; chmod 700 "$D"
[ -x "$D/.venv/bin/python" ] || "$UV" venv -q --python 3.12 "$D/.venv"
"$UV" pip install -q -p "$D/.venv/bin/python" -r "$SRC/requirements.txt"
PY="$D/.venv/bin/python"

step "3/7  App files"
rm -rf "$APP"; mkdir -p "$APP"
cp "$SRC"/pii_shield/*.py "$SRC/README.md" "$APP/"
rm -f "$D"/pii.py "$D"/pii_server.py "$D"/chat_app.py "$D"/mcp_server.py "$D"/guard.py   # older layout
mkdir -p "$BIN"; cp "$SRC/bin/pii" "$BIN/pii"; chmod +x "$BIN/pii"
if ! grep -qs '.local/bin' "$HOME/.zshrc"; then
  printf '\n# PII Shield\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.zshrc"
  note "Added ~/.local/bin to PATH in ~/.zshrc"
fi
mkdir -p "$HOME/Sensitive"
note "Installed to $APP; private folder: ~/Sensitive"

step "4/7  PII model (Perplexity PII-Tracer, ~1.2 GB, downloaded once)"
"$PY" - "$REV" <<'EOF' 2>&1 | grep -vE "Warning|warn|Redirects" || true
import sys
from transformers import AutoModel
m = AutoModel.from_pretrained("perplexity-ai/PII-Tracer", trust_remote_code=True, revision=sys.argv[1])
m.tokenizer  # cache tokenizer.json too; the server runs offline and can't fetch it later
print("    model ready")
EOF

step "5/7  Claude"
if [ -d "$HOME/.claude" ] || command -v claude >/dev/null 2>&1; then
  mkdir -p "$HOME/.claude/skills/redact"
  cp "$SRC/skills/claude/redact/SKILL.md" "$HOME/.claude/skills/redact/"
  "$PY" "$SRC/scripts/setup_claude.py"
else
  note "Claude Code not found, skipped. Run this installer again after installing Claude."
fi

step "6/7  LM Studio"
if [ -d "$HOME/.lmstudio" ]; then
  mkdir -p "$HOME/.lmstudio/skills" "$HOME/.lmstudio/config-presets"
  cp -R "$SRC"/skills/lmstudio/* "$HOME/.lmstudio/skills/"
  [ -f "$HOME/.lmstudio/config-presets/Daily Assistant.preset.json" ] || \
    cp "$SRC/lmstudio/Daily Assistant.preset.json" "$HOME/.lmstudio/config-presets/"
  "$PY" "$SRC/scripts/setup_lmstudio.py"
else
  note "LM Studio not found, skipped. Install it from lmstudio.ai, open it once, then run this again."
fi

step "7/7  Self-test"
"$BIN/pii" text "Hi, I'm Jane Doe, email jane.doe@example.com, card 4111 1111 1111 1111" | sed 's/^/    /'
"$BIN/pii" stop >/dev/null || true

if   [ "$RAM_GB" -ge 32 ]; then MODEL="qwen/qwen3.8-27b@4bit  (about 15 GB, best quality)"
elif [ "$RAM_GB" -ge 16 ]; then MODEL="qwen/qwen3.5-9b  (about 6 GB)"
else                            MODEL="a 3-4B model, e.g. search 'qwen 4b' in LM Studio"; fi

cat <<EOF

$(printf '\033[1;32mDone.\033[0m') Open a NEW Terminal window, then:

  pii guide          how to use everything
  pii text "..."     redact a sentence
  pii chat           Private Chat page

In Claude:      /redact ~/Downloads/file.pdf summarize it
In LM Studio:   pick the "Daily Assistant" preset.
This Mac has ${RAM_GB} GB RAM. Suggested LM Studio model:
  $MODEL
EOF
