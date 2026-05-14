import os
import time
import pymssql


def _get_params():
    cs = os.environ.get("SQL_CONNECTION_STRING")
    if not cs:
        try:
            import streamlit as st
            cs = st.secrets["SQL_CONNECTION_STRING"]
        except Exception:
            raise RuntimeError("SQL_CONNECTION_STRING not set")
    parts = {}
    for part in cs.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k.strip()] = v.strip()
    server_raw = parts.get("Server", parts.get("server", "")).replace("tcp:", "")
    if "," in server_raw:
        server, port = server_raw.rsplit(",", 1)
        port = int(port.strip())
    else:
        server, port = server_raw, 1433
    result = {
        "server": server,
        "port": port,
        "user": parts.get("Uid", "") or parts.get("User ID", ""),
        "password": parts.get("Pwd", "") or parts.get("Password", ""),
        "database": parts.get("Database", ""),
    }
    # DEBUG: Log connection params (mask password)
    import sys
    pwd_masked = (result["password"][:3] + "***" + result["password"][-2:]) if result["password"] else "NONE"
    print(f"[DB_DEBUG] Connecting to {result['server']}:{result['port']} user={result['user']} db={result['database']} pwd_masked={pwd_masked}", file=sys.stderr)
    return result


def _open_conn():
    """Open a pymssql connection with retry for Azure SQL auto-pause wakeup."""
    p = _get_params()
    last_exc = None
    max_attempts = 6
    import sys
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[DB_DEBUG] Connection attempt {attempt}/{max_attempts}...", file=sys.stderr)
            return pymssql.connect(
                server=p["server"],
                port=p["port"],
                user=p["user"],
                password=p["password"],
                database=p["database"],
                tds_version="7.4",
                login_timeout=60,
            )
        except (pymssql.OperationalError, pymssql.InterfaceError) as exc:
            last_exc = exc
            print(f"[DB_DEBUG] Attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt < max_attempts:
                try:
                    import streamlit as st
                    st.toast(f"Datenbank wacht auf\u2026 (Versuch {attempt}/{max_attempts})", icon="\u23f3")
                except Exception:
                    pass
                time.sleep(20)
    print(f"[DB_DEBUG] All {max_attempts} attempts failed. Final error: {last_exc}", file=sys.stderr)
    raise last_exc


def query(sql, params=None):
    """Execute SELECT, return list of dicts."""
    conn = _open_conn()
    try:
        cursor = conn.cursor(as_dict=True)
        cursor.execute(sql, params or ())
        return cursor.fetchall()
    finally:
        conn.close()


def execute(sql, params=None):
    """Execute INSERT/UPDATE/DELETE."""
    conn = _open_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()
    finally:
        conn.close()


def table_select(table, select="*", **filters):
    """Simple SELECT with optional equality filters."""
    where = ""
    params = []
    if filters:
        clauses = [f"[{k}] = %s" for k in filters]
        where = " WHERE " + " AND ".join(clauses)
        params = list(filters.values())
    return query(f"SELECT {select} FROM [{table}]{where}", params or None)


def table_insert(table, data: dict):
    """INSERT a single row. Auto-assigns integer id if not provided (skipped for UNIQUEIDENTIFIER tables)."""
    if "id" not in data:
        try:
            rows = query(f"SELECT ISNULL(MAX(id), 0) AS max_id FROM [{table}]")
            data = {"id": (rows[0]["max_id"] if rows else 0) + 1, **data}
        except Exception:
            pass  # id is UNIQUEIDENTIFIER or has DEFAULT — let DB handle it
    cols = ", ".join(f"[{k}]" for k in data)
    placeholders = ", ".join("%s" for _ in data)
    execute(f"INSERT INTO [{table}] ({cols}) VALUES ({placeholders})", list(data.values()))


def table_update(table, data: dict, **filters):
    """UPDATE rows matching filters."""
    set_clause = ", ".join(f"[{k}] = %s" for k in data)
    where_clause = " AND ".join(f"[{k}] = %s" for k in filters)
    params = list(data.values()) + list(filters.values())
    execute(f"UPDATE [{table}] SET {set_clause} WHERE {where_clause}", params)


def table_delete(table, **filters):
    """DELETE rows matching filters."""
    where_clause = " AND ".join(f"[{k}] = %s" for k in filters)
    execute(f"DELETE FROM [{table}] WHERE {where_clause}", list(filters.values()))
