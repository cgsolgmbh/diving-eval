import os
import time
import pymssql
from contextlib import contextmanager


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
    return {
        "server": server,
        "port": port,
        "user": parts.get("Uid", "") or parts.get("User ID", ""),
        "password": parts.get("Pwd", "") or parts.get("Password", ""),
        "database": parts.get("Database", ""),
    }


@contextmanager
def get_conn():
    """Open a pymssql connection with retry for Azure SQL auto-pause wakeup."""
    p = _get_params()
    last_exc = None
    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        try:
            conn = pymssql.connect(
                server=p["server"],
                port=p["port"],
                user=p["user"],
                password=p["password"],
                database=p["database"],
                tds_version="7.4",
                login_timeout=60,
            )
            try:
                yield conn
            finally:
                conn.close()
            return
        except (pymssql.OperationalError, pymssql.InterfaceError) as exc:
            last_exc = exc
            if attempt < max_attempts:
                try:
                    import streamlit as st
                    st.toast(f"Datenbank wacht auf\u2026 (Versuch {attempt}/{max_attempts})", icon="\u23f3")
                except Exception:
                    pass
                time.sleep(20)
    raise last_exc


def query(sql, params=None):
    """Execute SELECT, return list of dicts."""
    with get_conn() as conn:
        cursor = conn.cursor(as_dict=True)
        cursor.execute(sql, params or ())
        return cursor.fetchall()


def execute(sql, params=None):
    """Execute INSERT/UPDATE/DELETE."""
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()


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
    """INSERT a single row. Auto-assigns id if not provided."""
    if "id" not in data:
        rows = query(f"SELECT ISNULL(MAX(id), 0) AS max_id FROM [{table}]")
        data = {"id": (rows[0]["max_id"] if rows else 0) + 1, **data}
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
