#!/bin/bash
# BUKA deploy script — runs on buka.dk server via SSH
# Sets up Python venv, installs deps, starts/restarts app

APP_DIR="/var/www/buka"
VENV="$APP_DIR/venv"

echo "=== BUKA Deploy ==="
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# Install deps
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install flask flask-cors gunicorn --quiet

# Initialize DB if needed
"$VENV/bin/python" -c "from app import init_db; init_db()" 2>&1

# Start crawler in background if DB is small
COUNT=$("$VENV/bin/python" -c "
import sqlite3
try:
    db = sqlite3.connect('buka.db')
    print(db.execute('SELECT COUNT(*) FROM companies').fetchone()[0])
    db.close()
except:
    print(0)
" 2>/dev/null || echo 0)

echo "Current company count: $COUNT"
if [ "$COUNT" -lt 100 ]; then
  echo "Starting initial crawler run (background)..."
  nohup "$VENV/bin/python" crawler.py --limit 2000 --no-scrape > crawler.log 2>&1 &
  echo "Crawler PID: $!"
fi

# Kill existing gunicorn
pkill -f "gunicorn.*app:app" 2>/dev/null || true
sleep 1

# Start gunicorn
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "buka-secret-key-change-me")
nohup "$VENV/bin/gunicorn" \
  --bind 0.0.0.0:5000 \
  --workers 2 \
  --timeout 30 \
  --access-logfile access.log \
  --error-logfile error.log \
  "app:app" \
  --env "SECRET_KEY=$SECRET_KEY" \
  &

echo "App started. PID: $!"
echo "Checking health..."
sleep 3
curl -s http://localhost:5000/ | grep -o '<title>.*</title>' | head -1
echo "=== Deploy complete ==="
