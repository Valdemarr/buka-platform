#!/bin/bash
if ! pgrep -f "gunicorn.*app" > /dev/null; then
  export PATH="$HOME/.local/bin:$PATH"
  cd ~/buka
  set -a && source .env && set +a
  nohup gunicorn --bind 127.0.0.1:5000 --workers 2 --daemon \
    --access-logfile ~/buka/access.log --error-logfile ~/buka/error.log app:app 2>&1
  echo "[$(date)] WATCHDOG: gunicorn was down, restarted" >> ~/buka/watchdog.log
fi
