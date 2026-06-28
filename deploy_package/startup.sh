#!/bin/bash

# Use the active runtime interpreter for both installs and app execution.
PYTHON_BIN=$(command -v python3)

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

# Ensure native ODBC driver exists; pyodbc alone is not enough for Azure SQL.
if command -v odbcinst >/dev/null 2>&1; then
    if ! odbcinst -q -d 2>/dev/null | grep -qi "ODBC Driver 18 for SQL Server"; then
        echo "ODBC Driver 18 missing; installing native dependencies..." >> /home/site/startup_debug.log
        export DEBIAN_FRONTEND=noninteractive
        apt-get update >> /home/site/startup_debug.log 2>&1 || true
        apt-get install -y --no-install-recommends curl gnupg apt-transport-https ca-certificates unixodbc unixodbc-dev >> /home/site/startup_debug.log 2>&1 || true
        if [ ! -f /etc/apt/sources.list.d/mssql-release.list ]; then
            curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft-prod.gpg 2>> /home/site/startup_debug.log || true
            echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list
            apt-get update >> /home/site/startup_debug.log 2>&1 || true
        fi
        ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 >> /home/site/startup_debug.log 2>&1 || true
        if odbcinst -q -d 2>/dev/null | grep -qi "ODBC Driver 18 for SQL Server"; then
            echo "ODBC Driver 18 install verified" >> /home/site/startup_debug.log
        else
            echo "ODBC Driver 18 still unavailable after install attempt" >> /home/site/startup_debug.log
        fi
    else
        echo "ODBC Driver 18 already present" >> /home/site/startup_debug.log
    fi
else
    echo "odbcinst not found; installing unixODBC + msodbcsql18..." >> /home/site/startup_debug.log
    export DEBIAN_FRONTEND=noninteractive
    apt-get update >> /home/site/startup_debug.log 2>&1 || true
    apt-get install -y --no-install-recommends curl gnupg apt-transport-https ca-certificates unixodbc unixodbc-dev >> /home/site/startup_debug.log 2>&1 || true
    if [ ! -f /etc/apt/sources.list.d/mssql-release.list ]; then
        curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft-prod.gpg 2>> /home/site/startup_debug.log || true
        echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list
        apt-get update >> /home/site/startup_debug.log 2>&1 || true
    fi
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 >> /home/site/startup_debug.log 2>&1 || true
fi

# Ensure the pure-Python SQL fallback driver is available even if Oryx build misses it.
if ! "$PYTHON_BIN" -c "import tds" >/dev/null 2>&1 && ! "$PYTHON_BIN" -c "import pytds" >/dev/null 2>&1; then
    echo "python-tds missing; installing to runtime env..." >> /home/site/startup_debug.log
    "$PYTHON_BIN" -m pip install --no-cache-dir python-tds >> /home/site/startup_debug.log 2>&1
    echo "python-tds install done, exit=$?" >> /home/site/startup_debug.log
fi

# Ensure pyodbc is present too; it is the preferred path when the native driver is available.
if ! "$PYTHON_BIN" -c "import pyodbc" >/dev/null 2>&1; then
    echo "pyodbc missing; installing to runtime env..." >> /home/site/startup_debug.log
    "$PYTHON_BIN" -m pip install --no-cache-dir pyodbc >> /home/site/startup_debug.log 2>&1
    echo "pyodbc install done, exit=$?" >> /home/site/startup_debug.log
fi

# Old targeted installs can leave incompatible wheels (e.g. cp310 vs runtime).
# Remove stale app-local package target so user-site packages are used consistently.
if [ -d /home/site/wwwroot/.python_packages ]; then
    rm -rf /home/site/wwwroot/.python_packages
    echo "Removed stale /home/site/wwwroot/.python_packages" >> /home/site/startup_debug.log
fi

# Self-healing: install dependencies to user site if runtime-critical modules are missing
if ! "$PYTHON_BIN" -c "import streamlit, pandas, pymssql, pyodbc" >/dev/null 2>&1 && ! "$PYTHON_BIN" -c "import streamlit, pandas, pymssql, tds" >/dev/null 2>&1 && ! "$PYTHON_BIN" -c "import streamlit, pandas, pymssql, pytds" >/dev/null 2>&1; then
    echo "Dependencies missing/broken; installing requirements to runtime env..." >> /home/site/startup_debug.log
    "$PYTHON_BIN" -m pip install --no-cache-dir --upgrade --force-reinstall -r /home/site/wwwroot/requirements.txt >> /home/site/startup_debug.log 2>&1
    echo "Install done, exit=$?" >> /home/site/startup_debug.log
else
    echo "Dependencies healthy in runtime env; skipping install" >> /home/site/startup_debug.log
fi

exec "$PYTHON_BIN" -m streamlit run "$APP_PY" \
    --server.port 8000 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.maxWebsocketConnections 1000 \
    --server.disconnectedSessionTTL 30 \
    --server.enableCORS false \
    --server.enableXsrfProtection false
