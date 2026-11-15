#!/bin/bash
# Removes PII Shield. Asks before deleting the vault (your placeholder <-> real value list).
#   bash uninstall.sh
set -uo pipefail
D="$HOME/.pii-shield"
PY="$D/.venv/bin/python"
SRC="$(cd "$(dirname "$0")" && pwd)"

pkill -f pii_server.py 2>/dev/null; pkill -f chat_app.py 2>/dev/null
[ -x "$PY" ] && "$PY" "$SRC/scripts/uninstall.py"
rm -rf "$HOME/.claude/skills/redact"
for s in redact web-research summarize write-email rewrite translate explain-simply meeting-notes; do
  rm -rf "$HOME/.lmstudio/skills/$s"
done
rm -f "$HOME/.lmstudio/config-presets/Daily Assistant.preset.json" "$HOME/.local/bin/pii"
rm -rf "$D/app" "$D/.venv"
echo "Removed the app, Claude skill + guard, LM Studio tools/skills/preset."

read -r -p "Also delete the vault (redacted files can no longer be restored)? [y/N] " a
if [[ "$a" =~ ^[Yy]$ ]]; then rm -rf "$D"; echo "Vault deleted."; else echo "Vault kept in $D"; fi
echo "Your ~/Sensitive folder and the PII model cache (~/.cache/huggingface) were left alone."
