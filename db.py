import os
import time
import pymssql

try:
    import pyodbc
except Exception:
    pyodbc = None


_DB_DRIVER = None


def _get_connection_string():
    cs = os.environ.get("SQL_CONNECTION_STRING")
    if cs:
        return cs.strip()

    try:
        import streamlit as st
        return str(st.secrets["SQL_CONNECTION_STRING"]).strip()
    except Exception:
        raise RuntimeError("SQL_CONNECTION_STRING not set")


def _get_params():
    cs = _get_connection_string()
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


def _normalize_odbc_connection_string(cs):
    normalized = cs.strip().rstrip(";")
    lower = normalized.lower()

    if "driver=" not in lower:
        normalized = "Driver={ODBC Driver 18 for SQL Server};" + normalized

    if "encrypt=" not in lower:
        normalized += ";Encrypt=yes"

    if "trustservercertificate=" not in lower:
        normalized += ";TrustServerCertificate=no"

    if "connection timeout=" not in lower and "connect timeout=" not in lower:
        normalized += ";Connection Timeout=30"

    return normalized + ";"


def _open_conn_pyodbc():
    if pyodbc is None:
        raise RuntimeError("pyodbc not available")

    cs = _normalize_odbc_connection_string(_get_connection_string())
    return pyodbc.connect(cs, autocommit=False)


def _open_conn_pymssql():
    p = _get_params()
    return pymssql.connect(
        server=p["server"],
        port=p["port"],
        user=p["user"],
        password=p["password"],
        database=p["database"],
        tds_version="7.4",
        login_timeout=10,
        timeout=30,
    )


def _open_conn():
    """Open DB connection with retries for Azure SQL cold starts/network jitter."""
    global _DB_DRIVER
    last_exc = None
    max_attempts = 5

    for attempt in range(1, max_attempts + 1):
        if _DB_DRIVER is None:
            candidates = ["pyodbc", "pymssql"] if pyodbc is not None else ["pymssql"]
        else:
            candidates = [_DB_DRIVER]

        for driver in candidates:
            try:
                if driver == "pyodbc":
                    conn = _open_conn_pyodbc()
                else:
                    conn = _open_conn_pymssql()
                _DB_DRIVER = driver
                return conn
            except Exception as exc:
                last_exc = exc

        if attempt < max_attempts:
            try:
                import streamlit as st
                st.toast(f"Datenbank wacht auf... (Versuch {attempt}/{max_attempts})", icon="\u23f3")
            except Exception:
                pass
            # Short bounded backoff keeps UI responsive while still handling wakeup.
            time.sleep(min(2 * attempt, 8))

    driver_hint = "unknown" if _DB_DRIVER is None else _DB_DRIVER
    raise RuntimeError(f"DB connection failed after {max_attempts} attempts (driver={driver_hint}): {last_exc}")


def _as_dict_rows(cursor):
    if _DB_DRIVER == "pyodbc":
        cols = [c[0] for c in cursor.description] if cursor.description else []
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    return cursor.fetchall()


def query(sql, params=None):
    """Execute SELECT, return list of dicts."""
    conn = _open_conn()
    try:
        if _DB_DRIVER == "pyodbc":
            cursor = conn.cursor()
            sql_exec = sql.replace("%s", "?")
        else:
            cursor = conn.cursor(as_dict=True)
            sql_exec = sql
        cursor.execute(sql_exec, params or ())
        return _as_dict_rows(cursor)
    finally:
        conn.close()


def execute(sql, params=None):
    """Execute INSERT/UPDATE/DELETE."""
    conn = _open_conn()
    try:
        cursor = conn.cursor()
        sql_exec = sql.replace("%s", "?") if _DB_DRIVER == "pyodbc" else sql
        cursor.execute(sql_exec, params or ())
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
