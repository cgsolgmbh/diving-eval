#!/bin/bash
# Run data import once in the background if the flag file doesn't exist yet
IMPORT_FLAG=/home/site/.import_done
IMPORT_LOG=/home/site/import.log

if [ ! -f "$IMPORT_FLAG" ]; then
    (
        echo "=== IMPORT STARTED $(date) ===" > "$IMPORT_LOG"
        python -u /home/site/wwwroot/sqltables/import_data.py >> "$IMPORT_LOG" 2>&1
        EXIT_CODE=$?
        echo "--- PYTHON DONE, exit=$EXIT_CODE ---" >> "$IMPORT_LOG"
        if [ $EXIT_CODE -eq 0 ]; then
            touch "$IMPORT_FLAG"
        fi
    ) &
fi

# Find app.py in the Oryx-extracted archive directory (e.g. /tmp/XXXXX/app.py)
APP_PY=$(find /tmp -maxdepth 2 -name 'app.py' 2>/dev/null | head -1)
if [ -z "$APP_PY" ]; then
    APP_PY=/home/site/wwwroot/app.py
fi

# Prepend wwwroot to PYTHONPATH so db.py from wwwroot overrides the archived version
export PYTHONPATH="/home/site/wwwroot:${PYTHONPATH}"

# Also cp as belt-and-suspenders
APP_DIR=$(dirname "$APP_PY")
cp /home/site/wwwroot/db.py "$APP_DIR/db.py" 2>/dev/null || true

echo "=== STARTUP $(date): APP_PY=$APP_PY ===" >> /home/site/startup_debug.log
echo "DB_PY_USER=$(head -20 $APP_DIR/db.py | grep -c 'User ID')" >> /home/site/startup_debug.log

exec python -m streamlit run "$APP_PY" \
    --server.port 8000 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false
