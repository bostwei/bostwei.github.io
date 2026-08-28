#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.shiyanwei.cv-site-sync"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$ROOT/scripts/${LABEL}.plist" "$DEST"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
launchctl enable "gui/$(id -u)/${LABEL}"
echo "Installed watcher: $DEST"
echo "It updates this GitHub site whenever Overleaf/Dropbox saves Shiyan_Wei_CV.tex"
echo "It does not commit or push. Run git commit/push when you want https://bostwei.github.io/ to change."
echo "Uninstall: launchctl bootout gui/$(id -u)/${LABEL} && rm -f $DEST"
