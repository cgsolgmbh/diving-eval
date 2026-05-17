#!/bin/bash

# Use the same interpreter for install and runtime to avoid binary-wheel mismatches.
if [ -x /opt/python/3.10.19/bin/python3 ]; then
    PYTHON_BIN=/opt/python/3.10.19/bin/python3
else
    PYTHON_BIN=$(command -v python3)
fi

# Run data import once in the background if the flag file doesn't exist yet
IMPORT_FLAG=/home/site/.import_done
IMPORT_LOG=/home/site/import.log

if [ ! -f "$IMPORT_FLAG" ]; then
    (
        echo "=== IMPORT STARTED $(date) ===" > "$IMPORT_LOG"
        "$PYTHON_BIN" -u /home/site/wwwroot/sqltables/import_data.py >> "$IMPORT_LOG" 2>&1
        EXIT_CODE=$?
        echo "--- PYTHON DONE, exit=$EXIT_CODE ---" >> "$IMPORT_LOG"
        if [ $EXIT_CODE -eq 0 ]; then
            touch "$IMPORT_FLAG"
        fi
    ) &
fi

# Always run the deployed app from wwwroot to avoid stale /tmp artifacts.
APP_PY=/home/site/wwwroot/app.py

# Keep import path deterministic and do not inherit stale .python_packages entries.
export PYTHONPATH="/home/site/wwwroot"

# Also cp as belt-and-suspenders
APP_DIR=$(dirname "$APP_PY")
cp /home/site/wwwroot/db.py "$APP_DIR/db.py" 2>/dev/null || true
cp /home/site/wwwroot/app.py "$APP_DIR/app.py" 2>/dev/null || true

echo "=== STARTUP $(date): APP_PY=$APP_PY ===" >> /home/site/startup_debug.log
echo "ENV_SQL_CS=$([ -n "$SQL_CONNECTION_STRING" ] && echo 'SET' || echo 'MISSING')" >> /home/site/startup_debug.log
echo "PYTHON_BIN=$PYTHON_BIN" >> /home/site/startup_debug.log

# Old targeted installs can leave incompatible wheels (e.g. cp310 vs runtime).
# Remove stale app-local package target so user-site packages are used consistently.
if [ -d /home/site/wwwroot/.python_packages ]; then
    rm -rf /home/site/wwwroot/.python_packages
    echo "Removed stale /home/site/wwwroot/.python_packages" >> /home/site/startup_debug.log
fi

# Self-healing: install dependencies to user site if streamlit is missing
if ! "$PYTHON_BIN" -c "import streamlit, pandas, pymssql" >/dev/null 2>&1; then
    echo "Dependencies missing/broken; installing requirements to user dir..." >> /home/site/startup_debug.log
    "$PYTHON_BIN" -m pip install --user --no-cache-dir --upgrade --force-reinstall -r /home/site/wwwroot/requirements.txt >> /home/site/startup_debug.log 2>&1
    echo "Install done, exit=$?" >> /home/site/startup_debug.log
else
    echo "Dependencies healthy in user site; skipping install" >> /home/site/startup_debug.log
fi

exec "$PYTHON_BIN" -m streamlit run "$APP_PY" \
    --server.port 8000 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false
