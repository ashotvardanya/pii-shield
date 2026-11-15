#!/bin/bash
# Create a GitHub repo from this folder and push it. Run on a Mac signed in to GitHub CLI.
#   bash publish.sh
# Commits are re-signed with your private GitHub "noreply" email, so no personal email is published.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI not found. Install it with:  brew install gh   then run:  gh auth login"; exit 1
fi
gh auth status >/dev/null 2>&1 || { echo "Not signed in. Run:  gh auth login"; exit 1; }
git remote get-url origin >/dev/null 2>&1 && { echo "Already has a remote: $(git remote get-url origin)"; exit 1; }

LOGIN=$(gh api user -q .login)
ID=$(gh api user -q .id)
NAME=$(gh api user -q '.name // .login')
EMAIL="$ID+$LOGIN@users.noreply.github.com"
echo "Signed in as $LOGIN. Commits will show: $NAME <$EMAIL>"

read -r -p "Repository name [pii-shield]: " REPO; REPO=${REPO:-pii-shield}
read -r -p "Public or private? [public]: " VIS; VIS=$(echo "${VIS:-public}" | tr 'A-Z' 'a-z')
[[ "$VIS" == public || "$VIS" == private ]] || { echo "Please answer public or private."; exit 1; }

git config user.name "$NAME"
git config user.email "$EMAIL"
git rebase -q --root --exec 'git commit -q --amend --no-edit --reset-author'   # re-sign history

gh repo create "$REPO" "--$VIS" --source=. --remote=origin --push \
  --description "Local PII redaction for Claude, LM Studio and any AI, using Perplexity's open PII-Tracer model. A free, private take on Hybrid Compute."
gh repo edit "$LOGIN/$REPO" --add-topic privacy,pii,redaction,claude-code,lm-studio,mcp,macos >/dev/null || true
echo
echo "Published: https://github.com/$LOGIN/$REPO"
