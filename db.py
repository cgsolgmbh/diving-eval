import logging
import os
import time
import importlib
import site
import sys
import pymssql

try:
    import pyodbc
except Exception:
    pyodbc = None

try:
    import pytds
except Exception:
    pytds = None


_DB_DRIVER = None
_LAST_CANDIDATES = None
_LOGGER = logging.getLogger(__name__)


def _normalize_sql_param(value):
    """Convert non-SQL-safe Python values (like NaN) to DB-safe values."""
    if value is None:
        return None

    # Unwrap NumPy scalar-like values when available.
    try:
        if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
            value = value.item()
    except Exception:
        pass

    # NaN is not comparable to itself.
    try:
        if value != value:
            return None
    except Exception:
        pass

    return value


def _normalize_sql_params(params):
    if not params:
        return ()
    return tuple(_normalize_sql_param(p) for p in params)


def _iter_extra_site_paths():
    paths = set()

    try:
        user_site = site.getusersitepackages()
        if user_site:
            paths.add(user_site)
    except Exception:
        pass

    try:
        for site_path in site.getsitepackages():
            if site_path:
                paths.add(site_path)
    except Exception:
        pass

    try:
        paths.add(
            os.path.join(
                sys.prefix,
                "Lib",
                "site-packages",
            )
        )
        paths.add(
            os.path.join(
                sys.prefix,
                "lib",
                f"python{sys.version_info.major}.{sys.version_info.minor}",
                "site-packages",
            )
        )
        paths.add(
            os.path.join(
                os.path.expanduser("~"),
                ".local",
                "lib",
                f"python{sys.version_info.major}.{sys.version_info.minor}",
                "site-packages",
            )
        )
        paths.add(os.path.join("/home/site/wwwroot", ".python_packages", "lib", "site-packages"))
    except Exception:
        pass

    for path in sorted(paths):
        if path and os.path.isdir(path):
            yield path


def _log(message):
    try:
        print(message, flush=True)
        _LOGGER.info(message)
    except Exception:
        pass


def _get_connection_string():
    cs = os.environ.get("SQL_CONNECTION_STRING")
    if not cs:
        # Azure App Service exposes Connection Strings as SQLCONNSTR_<name>
        cs = os.environ.get("SQLCONNSTR_SQL_CONNECTION_STRING")
    if cs:
        return cs.strip()

    try:
        import streamlit as st
        return str(st.secrets["SQL_CONNECTION_STRING"]).strip()
    except Exception:
        raise RuntimeError("SQL_CONNECTION_STRING not set")


def _split_connection_string(cs):
    tokens = []
    current = []
    brace_depth = 0

    for ch in str(cs).strip().rstrip(";"):
        if ch == ";" and brace_depth == 0:
            token = "".join(current).strip()
            if token:
                tokens.append(token)
            current = []
            continue

        if ch == "{":
            brace_depth += 1
        elif ch == "}" and brace_depth > 0:
            brace_depth -= 1

        current.append(ch)

    token = "".join(current).strip()
    if token:
        tokens.append(token)

    return tokens


def _unbrace(value):
    value = str(value).strip()
    if len(value) >= 2 and value.startswith("{") and value.endswith("}"):
        return value[1:-1]
    return value


def _parse_connection_string(cs):
    parts = {}
    current_key = None
    current_value = []

    for token in _split_connection_string(cs):
        if "=" in token:
            if current_key is not None:
                parts[current_key] = _unbrace(";".join(current_value).strip())

            key, value = token.split("=", 1)
            current_key = key.strip()
            current_value = [value.strip()]
            continue

        # If a password contains semicolons without braces, keep the fragments.
        if current_key and current_key.strip().lower() in {"pwd", "password"}:
            current_value.append(token)

    if current_key is not None:
        parts[current_key] = _unbrace(";".join(current_value).strip())

    normalized = {}
    for key, value in parts.items():
        normalized[key.strip().lower()] = value.strip()

    return normalized


def _odbc_escape_value(value):
    value = "" if value is None else str(value)
    if not value:
        return value
    if any(ch in value for ch in ";{}") or value != value.strip():
        return "{" + value.replace("}", "}}") + "}"
    return value


def _get_connection_parts():
    return _parse_connection_string(_get_connection_string())


def _get_params():
    parts = _get_connection_parts()
    server_raw = (parts.get("server") or parts.get("data source") or "").replace("tcp:", "")
    if "," in server_raw:
        server, port = server_raw.rsplit(",", 1)
        port = int(port.strip())
    else:
        server, port = server_raw, 1433
    return {
        "server": server,
        "port": port,
        "user": parts.get("uid", "") or parts.get("user id", "") or parts.get("user", ""),
        "password": parts.get("pwd", "") or parts.get("password", ""),
        "database": parts.get("database", "") or parts.get("initial catalog", ""),
    }


def _normalize_odbc_connection_string(cs):
    parts = _parse_connection_string(cs)
    items = []

    driver = parts.pop("driver", None) or "ODBC Driver 18 for SQL Server"
    items.append(("Driver", driver))

    server = parts.pop("server", None) or parts.pop("data source", None)
    if server:
        items.append(("Server", server))

    database = parts.pop("database", None) or parts.pop("initial catalog", None)
    if database:
        items.append(("Database", database))

    user = parts.pop("uid", None) or parts.pop("user id", None) or parts.pop("user", None)
    if user:
        items.append(("Uid", user))

    password = parts.pop("pwd", None) or parts.pop("password", None)
    if password is not None:
        items.append(("Pwd", password))

    if "encrypt" in parts:
        items.append(("Encrypt", parts.pop("encrypt")))
    else:
        items.append(("Encrypt", "yes"))

    if "trustservercertificate" in parts:
        items.append(("TrustServerCertificate", parts.pop("trustservercertificate")))
    else:
        items.append(("TrustServerCertificate", "no"))

    if "connection timeout" in parts:
        items.append(("Connection Timeout", parts.pop("connection timeout")))
    elif "connect timeout" in parts:
        items.append(("Connection Timeout", parts.pop("connect timeout")))
    else:
        items.append(("Connection Timeout", "30"))

    for key, value in parts.items():
        canonical_key = key.strip()
        if canonical_key in {"driver", "server", "data source", "database", "initial catalog", "uid", "user id", "user", "pwd", "password", "encrypt", "trustservercertificate", "connection timeout", "connect timeout"}:
            continue
        items.append((canonical_key, value))

    normalized = ";".join(f"{key}={_odbc_escape_value(value)}" for key, value in items)
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
        encryption="require",
        tds_version="7.4",
        login_timeout=10,
        timeout=30,
    )


def _open_conn_pytds():
    if pytds is None:
        raise RuntimeError("pytds not available")

    p = _get_params()
    cafile = os.environ.get("SQL_CAFILE", "/etc/ssl/certs/ca-certificates.crt")
    if not os.path.exists(cafile):
        cafile = None
    return pytds.connect(
        dsn=p["server"],
        port=p["port"],
        database=p["database"],
        user=p["user"],
        password=p["password"],
        login_timeout=10,
        timeout=30,
        cafile=cafile,
        validate_host=True,
        enc_login_only=False,
        autocommit=False,
    )


def _refresh_optional_drivers():
    """Try loading optional drivers again in case they became available at runtime."""
    global pyodbc, pytds
    try:
        for path in _iter_extra_site_paths():
            if path not in sys.path:
                sys.path.append(path)
    except Exception:
        pass

    if pyodbc is None:
        try:
            pyodbc = importlib.import_module("pyodbc")
        except Exception:
            pass
    if pytds is None:
        try:
            pytds = importlib.import_module("pytds")
        except Exception:
            try:
                pytds = importlib.import_module("tds")
            except Exception:
                pass


def _open_conn():
    """Open DB connection with retries for Azure SQL cold starts/network jitter."""
    global _DB_DRIVER, _LAST_CANDIDATES
    last_exc = None
    max_attempts = 12

    for attempt in range(1, max_attempts + 1):
        _refresh_optional_drivers()
        startup_candidates = []
        if pyodbc is not None:
            startup_candidates.append("pyodbc")
        if pytds is not None:
            startup_candidates.append("pytds")
        startup_candidates.append("pymssql")

        if _DB_DRIVER is None:
            candidates = list(startup_candidates)
        else:
            # Prefer last known-good driver, but keep full fallback chain.
            candidates = [_DB_DRIVER] + [d for d in startup_candidates if d != _DB_DRIVER]

        _LAST_CANDIDATES = list(candidates)

        _log(f"DB connect attempt {attempt}/{max_attempts} candidates={candidates} last_driver={_DB_DRIVER}")

        for driver in candidates:
            try:
                started = time.time()
                if driver == "pyodbc":
                    conn = _open_conn_pyodbc()
                elif driver == "pytds":
                    conn = _open_conn_pytds()
                else:
                    conn = _open_conn_pymssql()
                _DB_DRIVER = driver
                _log(f"DB connect success driver={driver} attempt={attempt} elapsed={time.time() - started:.2f}s")
                return conn
            except Exception as exc:
                last_exc = exc
                _log(f"DB connect failed driver={driver} attempt={attempt} error={type(exc).__name__}: {exc}")

        if attempt < max_attempts:
            try:
                import streamlit as st
                st.toast(f"Datenbank wacht auf... (Versuch {attempt}/{max_attempts})", icon="\u23f3")
            except Exception:
                pass
            # Longer bounded backoff handles serverless/paused DB wakeup reliably.
            time.sleep(min(3 * attempt, 20))

    driver_hint = "unknown" if _DB_DRIVER is None else _DB_DRIVER
    raise RuntimeError(f"DB connection failed after {max_attempts} attempts (driver={driver_hint}): {last_exc}")


def _as_dict_rows(cursor):
    if _DB_DRIVER == "pyodbc":
        cols = [c[0] for c in cursor.description] if cursor.description else []
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    if _DB_DRIVER == "pytds":
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
        elif _DB_DRIVER == "pytds":
            cursor = conn.cursor()
            sql_exec = sql
        else:
            cursor = conn.cursor(as_dict=True)
            sql_exec = sql
        started = time.time()
        params_exec = _normalize_sql_params(params)
        _log(f"DB query start driver={_DB_DRIVER} sql={sql_exec!r} params={params!r}")
        cursor.execute(sql_exec, params_exec)
        rows = _as_dict_rows(cursor)
        _log(f"DB query success driver={_DB_DRIVER} rows={len(rows)} elapsed={time.time() - started:.2f}s sql={sql_exec!r}")
        return rows
    except Exception as exc:
        sql_exec = locals().get("sql_exec", sql)
        _log(f"DB query failed driver={_DB_DRIVER} error={type(exc).__name__}: {exc} sql={sql_exec!r} params={params!r}")
        raise
    finally:
        conn.close()


def execute(sql, params=None):
    """Execute INSERT/UPDATE/DELETE."""
    conn = _open_conn()
    try:
        cursor = conn.cursor()
        sql_exec = sql.replace("%s", "?") if _DB_DRIVER == "pyodbc" else sql
        params_exec = _normalize_sql_params(params)
        _log(f"DB execute start driver={_DB_DRIVER} sql={sql_exec!r} params={params!r}")
        cursor.execute(sql_exec, params_exec)
        conn.commit()
        _log(f"DB execute success driver={_DB_DRIVER} sql={sql_exec!r}")
    except Exception as exc:
        sql_exec = locals().get("sql_exec", sql)
        _log(f"DB execute failed driver={_DB_DRIVER} error={type(exc).__name__}: {exc} sql={sql_exec!r} params={params!r}")
        raise
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
