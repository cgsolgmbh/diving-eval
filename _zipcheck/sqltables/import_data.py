"""
Import PostgreSQL INSERT statements into Azure SQL Database.
Usage: python sqltables/import_data.py
"""

import os
import re
import sys

# pymssql bundles its own OpenSSL which has no CA bundle on Windows.
# SSL_CERT_FILE must be set before pymssql (and OpenSSL) is loaded.
try:
    import certifi as _certifi
    os.environ.setdefault("SSL_CERT_FILE", _certifi.where())
except ImportError:
    pass  # certifi not installed — connection may fail on Windows

# ── Connection ────────────────────────────────────────────────────────────────

def parse_connection_string(conn_str: str) -> dict:
    """Extract Server, Database, Uid, Pwd from an ODBC connection string."""
    params = {}
    for part in conn_str.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            params[key.strip()] = value.strip()

    # Strip "tcp:" prefix and split "hostname,port" into separate parts
    raw_server = params.get("Server", "").replace("tcp:", "")
    if "," in raw_server:
        server, port = raw_server.rsplit(",", 1)
    else:
        server, port = raw_server, "1433"

    return {
        "server": server,
        "port": port.strip(),
        "database": params.get("Database", ""),
        "user": params.get("Uid", "") or params.get("User ID", ""),
        "password": params.get("Pwd", ""),
    }


def load_connection() -> dict:
    # Try environment variable first (App Service sets this)
    conn_str = os.environ.get("SQL_CONNECTION_STRING", "")
    if conn_str:
        return parse_connection_string(conn_str)

    secrets_path = os.path.join(
        os.path.dirname(__file__), "..", ".streamlit", "secrets.toml"
    )
    with open(secrets_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SQL_CONNECTION_STRING"):
                _, _, raw = line.partition("=")
                conn_str = raw.strip().strip('"')
                return parse_connection_string(conn_str)
    raise RuntimeError("SQL_CONNECTION_STRING not found in env or secrets.toml")


# ── SQL parsing ───────────────────────────────────────────────────────────────

def tokenise_values(values_text: str) -> list[list]:
    """
    Parse the VALUES section of a PostgreSQL INSERT.
    Returns a list of rows, each row a list of Python-ready strings or None.

    Handles:
    - single-quoted strings (including '' escapes)
    - unquoted numbers / NULL / true / false
    - commas and parentheses inside quoted strings
    """
    rows = []
    i = 0
    n = len(values_text)

    while i < n:
        # skip whitespace / commas between rows
        while i < n and values_text[i] in " \t\r\n,":
            i += 1
        if i >= n:
            break
        if values_text[i] != "(":
            i += 1
            continue

        i += 1  # skip '('
        row = []
        current = []

        while i < n:
            ch = values_text[i]

            if ch == "'":
                # quoted string — collect until closing quote, respecting ''
                current.append(ch)
                i += 1
                while i < n:
                    c2 = values_text[i]
                    if c2 == "'":
                        current.append(c2)
                        i += 1
                        if i < n and values_text[i] == "'":
                            # escaped quote inside string
                            current.append(values_text[i])
                            i += 1
                        else:
                            break  # end of quoted string
                    else:
                        current.append(c2)
                        i += 1

            elif ch == "," :
                row.append(_convert_value("".join(current).strip()))
                current = []
                i += 1

            elif ch == ")":
                row.append(_convert_value("".join(current).strip()))
                rows.append(row)
                i += 1
                break

            else:
                current.append(ch)
                i += 1

    return rows


def _convert_value(token: str):
    """Convert a single parsed token to a Python value suitable for pymssql."""
    if token.upper() == "NULL":
        return None
    if token.lower() == "true":
        return 1
    if token.lower() == "false":
        return 0
    if token.startswith("'") and token.endswith("'"):
        # strip outer quotes; inner '' is already correct T-SQL escaping
        return token[1:-1].replace("''", "'")
    # numeric
    return token


def parse_insert(sql: str) -> tuple[str, list[str], list[list]]:
    """
    Parse a PostgreSQL INSERT statement.
    Returns (table_name, [col_names], [[row_values], ...])
    """
    # Extract table name: "public"."tablename"  or  "tablename"
    table_match = re.match(
        r'INSERT\s+INTO\s+"public"\."(\w+)"\s*\(', sql, re.IGNORECASE
    )
    if not table_match:
        table_match = re.match(
            r'INSERT\s+INTO\s+"(\w+)"\s*\(', sql, re.IGNORECASE
        )
    if not table_match:
        raise ValueError("Cannot parse table name from INSERT statement")
    table_name = table_match.group(1)

    # Extract column list
    cols_start = sql.index("(") + 1
    cols_end = sql.index(")")
    cols_raw = sql[cols_start:cols_end]
    columns = [c.strip().strip('"') for c in cols_raw.split(",")]

    # Extract VALUES section
    values_keyword = re.search(r"\)\s*VALUES\s*\(", sql, re.IGNORECASE)
    if not values_keyword:
        raise ValueError("Cannot find VALUES in INSERT statement")
    values_start = values_keyword.end() - 1  # point at the opening '('
    values_text = sql[values_start:]

    rows = tokenise_values(values_text)
    return table_name, columns, rows


# ── Import ────────────────────────────────────────────────────────────────────

TABLE_ORDER = [
    "agecategories",
    "agecategorieshd",
    "agedives",
    "pistedisciplines",
    "athletes",
    "competitions",
    "compresults",
    "compresultsbig",
    "pisteenvironment",
    "pistemirwald",
    "pisterefcomppoints",
    "pisterefcompresults",
    "pisterefminpoints",
    "pistereftrainingsince",
    "pistereftrainingtime",
    "pisteresults",
    "scoretables",
    "selectionpoints",
    "socadditionalvalues",
    "team",
    "trainingsperformance",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_sql_file(table: str):
    candidate = os.path.join(SCRIPT_DIR, f"{table}_rows.sql")
    return candidate if os.path.exists(candidate) else None


def import_table(conn, table: str, columns: list[str], rows: list[list]) -> tuple[int, int]:
    """Delete existing rows and bulk-insert new ones. Returns (inserted, errors)."""
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM [{table}]")

    col_list = ", ".join(f"[{c}]" for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})"

    inserted = 0
    errors = 0
    batch_size = 100

    for batch_start in range(0, len(rows), batch_size):
        batch = rows[batch_start : batch_start + batch_size]
        for row in batch:
            try:
                cursor.execute(insert_sql, row)
                inserted += 1
            except Exception as exc:
                print(f"    ✗ Row error in [{table}]: {exc}")
                print(f"      Row data: {row[:5]}{'...' if len(row) > 5 else ''}")
                errors += 1

        progress = min(batch_start + batch_size, len(rows))
        print(f"  … {progress}/{len(rows)} rows", end="\r")

    return inserted, errors


def main():
    try:
        import pymssql
    except ImportError:
        print("pymssql not installed. Run: pip install pymssql")
        sys.exit(1)

    print("Connecting to Azure SQL …")
    cfg = load_connection()
    try:
        conn = pymssql.connect(
            server=cfg["server"],
            port=cfg["port"],
            database=cfg["database"],
            user=cfg["user"],
            password=cfg["password"],
            tds_version="7.4",
            autocommit=True,
        )
    except Exception as exc:
        print(f"✗ Connection failed: {exc}")
        print()
        print("Troubleshooting tips:")
        print("  1. Add your public IP to the Azure SQL firewall in Azure portal")
        print("     (Networking → Firewall rules → Add client IP)")
        print("  2. Ensure pymssql and certifi are installed:")
        print("     pip install pymssql certifi")
        sys.exit(1)
    print(f"Connected to {cfg['server']}:{cfg['port']} / {cfg['database']}\n")

    total_tables = 0
    total_rows = 0
    total_errors = 0

    # Disable all FK constraints so tables can be deleted/re-inserted in any order
    cur = conn.cursor()
    cur.execute("""
        SELECT QUOTENAME(OBJECT_SCHEMA_NAME(fk.parent_object_id)) + '.' +
               QUOTENAME(OBJECT_NAME(fk.parent_object_id)) AS tbl,
               QUOTENAME(fk.name) AS fk_name
        FROM sys.foreign_keys fk
    """)
    fk_rows = cur.fetchall()
    for tbl, fk_name in fk_rows:
        cur.execute(f"ALTER TABLE {tbl} NOCHECK CONSTRAINT {fk_name}")
    print(f"Disabled {len(fk_rows)} FK constraint(s).\n")

    for table in TABLE_ORDER:
        sql_file = find_sql_file(table)
        if sql_file is None:
            print(f"[SKIP] {table} — no file found")
            continue

        print(f"[{table}]")
        with open(sql_file, encoding="utf-8", errors="replace") as f:
            sql = f.read().strip()

        if not sql:
            print(f"  (empty file, skipped)")
            continue

        try:
            tbl, columns, rows = parse_insert(sql)
        except Exception as exc:
            print(f"  ✗ Parse error: {exc}")
            total_errors += 1
            continue

        print(f"  Parsed {len(rows)} rows, {len(columns)} columns")

        try:
            inserted, errors = import_table(conn, tbl, columns, rows)
        except Exception as exc:
            print(f"  ✗ Import error: {exc}")
            total_errors += 1
            continue

        print(f"  ✓ {inserted} rows inserted, {errors} errors          ")
        total_tables += 1
        total_rows += inserted
        total_errors += errors

    # Re-enable FK constraints and validate
    cur2 = conn.cursor()
    for tbl, fk_name in fk_rows:
        cur2.execute(f"ALTER TABLE {tbl} WITH CHECK CHECK CONSTRAINT {fk_name}")
    print(f"Re-enabled {len(fk_rows)} FK constraint(s).\n")

    conn.close()

    print("\n" + "=" * 50)
    print(f"Summary: {total_tables} tables, {total_rows} rows inserted, {total_errors} errors")


if __name__ == "__main__":
    main()
