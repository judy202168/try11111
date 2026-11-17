#!/bin/sh
set -eu
if [ "${APP_MODE:-web}" = "worker" ]; then
    exec python scheduler.py
fi
exec gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers 2 --threads 4 --timeout 180 --access-logfile - app:app
