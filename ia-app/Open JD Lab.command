#!/bin/zsh
set -e

APP_DIR="${0:A:h}"
APP_URL="http://127.0.0.1:5050/"

if ! /usr/bin/curl -fsS "$APP_URL" >/dev/null 2>&1; then
  cd "$APP_DIR"
  PORT=5050 /usr/bin/nohup "$APP_DIR/.venv/bin/python" "$APP_DIR/app.py" >>"$APP_DIR/jd-lab.log" 2>&1 &
  for attempt in {1..20}; do
    if /usr/bin/curl -fsS "$APP_URL" >/dev/null 2>&1; then
      break
    fi
    /bin/sleep 0.25
  done
fi

if /usr/bin/curl -fsS "$APP_URL" >/dev/null 2>&1; then
  /usr/bin/open "$APP_URL"
else
  /usr/bin/osascript -e 'display alert "JD Lab could not start" message "Open jd-lab.log in the IA App folder for details." as critical'
  exit 1
fi
