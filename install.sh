#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/wani3000/telegram-bot-for-my-mac-.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/github/claude-telegram-bot}"
PLIST_PATH="$HOME/Library/LaunchAgents/com.cwpark.claudebot.plist"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[1/7] Preparing install directory: $INSTALL_DIR"
mkdir -p "$(dirname "$INSTALL_DIR")"

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "[2/7] Updating existing repo"
  git -C "$INSTALL_DIR" pull --ff-only origin main
else
  echo "[2/7] Cloning repo"
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

echo "[3/7] Creating virtual environment"
"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate

echo "[4/7] Installing Python packages"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "[5/7] Preparing config"
CONFIG_READY="yes"
if [ ! -f config.json ]; then
  cp config.example.json config.json
  CLAUDE_PATH="$(command -v claude || true)"
  if [ -n "$CLAUDE_PATH" ]; then
    perl -0pi -e "s|\"CLAUDE_BIN\": \"claude\"|\"CLAUDE_BIN\": \"$CLAUDE_PATH\"|g" config.json
  fi
  echo "config.json created from template. Fill in BOT_TOKEN and ALLOWED_CHAT_IDS before starting."
  CONFIG_READY="no"
fi

if grep -q 'replace-with-your-telegram-token' config.json; then
  CONFIG_READY="no"
fi

mkdir -p "$HOME/Library/LaunchAgents"

echo "[6/7] Writing launchd plist"
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.cwpark.claudebot</string>
  <key>ProgramArguments</key>
  <array>
    <string>$INSTALL_DIR/.venv/bin/python</string>
    <string>$INSTALL_DIR/bot.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$INSTALL_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$INSTALL_DIR/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$INSTALL_DIR/stderr.log</string>
</dict>
</plist>
PLIST

echo "[7/7] Loading service"
if [ "$CONFIG_READY" = "yes" ]; then
  launchctl bootout "gui/$(id -u)/com.cwpark.claudebot" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  launchctl enable "gui/$(id -u)/com.cwpark.claudebot"
  launchctl kickstart -k "gui/$(id -u)/com.cwpark.claudebot" || true
else
  echo "Skipping launchd start because config.json still has placeholder values."
fi

echo
echo "Install complete."
echo "Repo: $INSTALL_DIR"
echo "LaunchAgent: $PLIST_PATH"
echo "Logs:"
echo "  tail -f $INSTALL_DIR/bot.log"
echo "  tail -f $INSTALL_DIR/stderr.log"
echo
if [ "$CONFIG_READY" = "yes" ]; then
  echo "Service loaded. Restart manually any time with:"
  echo "  launchctl kickstart -k gui/$(id -u)/com.cwpark.claudebot"
else
  echo "Next step:"
  echo "  1. Edit $INSTALL_DIR/config.json"
  echo "  2. Start the service with:"
  echo "     launchctl bootstrap gui/$(id -u) $PLIST_PATH"
  echo "     launchctl enable gui/$(id -u)/com.cwpark.claudebot"
  echo "     launchctl kickstart -k gui/$(id -u)/com.cwpark.claudebot"
fi
