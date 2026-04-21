#!/bin/bash

# BIST Scanner Launcher
# Double-click this file to start the app and open it in your browser.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Check Python
if ! command -v python3 &>/dev/null; then
  osascript -e 'display alert "Python3 bulunamadı." message "Lütfen python3 yükleyin: https://www.python.org"'
  exit 1
fi

# Install dependencies if needed
python3 -c "import flask, yfinance, pandas" 2>/dev/null
if [ $? -ne 0 ]; then
  osascript -e 'display notification "Gerekli paketler yükleniyor..." with title "BIST Tarayıcı"'
  pip3 install -r requirements.txt --break-system-packages -q
fi

# Kill any previous instance on port 5050
lsof -ti:5050 | xargs kill -9 2>/dev/null

# Start Flask in background
python3 app.py &
APP_PID=$!

# Wait for server to be ready
echo "Sunucu başlatılıyor..."
for i in {1..15}; do
  sleep 1
  if curl -s http://127.0.0.1:5050 > /dev/null; then
    break
  fi
done

# Open in default browser
open http://127.0.0.1:5050

# Keep terminal open so app stays alive
echo ""
echo "✅ BIST Tarayıcı çalışıyor → http://127.0.0.1:5050"
echo "Durdurmak için bu pencereyi kapatın."
wait $APP_PID
