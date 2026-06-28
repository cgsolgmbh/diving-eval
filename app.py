import streamlit as st
import datetime
import pandas as pd
import db
import importlib
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import re
import os
import json
import base64
import math

st.set_page_config(page_title="Diving Evaluation", page_icon="🤿")


def get_app_version():
    """Return a human-readable runtime version for live verification."""
    env_version = os.getenv("APP_VERSION")
    if env_version:
        return str(env_version).strip()

    for version_name in ("app_version.txt", ".app_version"):
        version_file = os.path.join(os.path.dirname(__file__), version_name)
        if os.path.exists(version_file):
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    value = f.read().strip()
                    if value:
                        return value
            except Exception:
                pass

    try:
        mtime = datetime.datetime.utcfromtimestamp(os.path.getmtime(__file__))
        return f"local-{mtime.strftime('%Y%m%d-%H%M%S')}"
    except Exception:
        return "local-unknown"


# Auth handled by login_view()
# --- Caching für selten geänderte Tabellen ---
@st.cache_data

def get_official_category_local(age, year, agecat_df):
    try:
        age = int(age)
    except Exception:
        return None
    # Falls du ein Jahr-Feld hast, ergänze: & (agecat_df["year"] == int(year))
    row = agecat_df[(agecat_df["min_age"] <= age) & (agecat_df["max_age"] >= age)]
    if not row.empty:
        return row.iloc[0]["category"]
    return None

def is_excluded_discipline_local(discipline, age, year, agecat_df):
    category = get_official_category_local(age, year, agecat_df)
    return (
        str(discipline).strip().lower() in ["1m synchro", "3m synchro"]
        and category in ["Jugend C", "Jugend D"]
    )

def get_pistedisciplines():
    return db.table_select('pistedisciplines', 'id, name')

@st.cache_data
def get_athletes():
    return db.table_select('athletes', 'id, full_name, sex, vintage, category')

@st.cache_data
def get_agecategories():
    return db.table_select('agecategories')

@st.cache_data
def get_scoretables():
    return db.table_select('scoretables')

def fetch_all_rows(table, select="*", **filters):
    return db.table_select(table, select, **filters)

def cascade_competition_rename(old_name, new_name):
    """Propagate a competition name change to name-based references."""
    old_val = str(old_name or "").strip()
    new_val = str(new_name or "").strip()
    if not old_val or not new_val:
        return {"compresults": 0, "pisterefcompresults": 0}
    if old_val.lower() == new_val.lower():
        return {"compresults": 0, "pisterefcompresults": 0}

    updated_compresults = 0
    updated_ref = 0

    comp_rows = fetch_all_rows("compresults", select="id, Competition")
    for row in comp_rows:
        comp_name = str(row.get("Competition") or "").strip()
        if comp_name.lower() == old_val.lower():
            db.table_update("compresults", {"Competition": new_val}, id=int(row["id"]))
            updated_compresults += 1

    ref_rows = fetch_all_rows("pisterefcompresults", select="id, competition1, competition2, competition3")
    for row in ref_rows:
        payload = {}
        for col in ["competition1", "competition2", "competition3"]:
            val = str(row.get(col) or "").strip()
            if val.lower() == old_val.lower():
                payload[col] = new_val
        if payload:
            db.table_update("pisterefcompresults", payload, id=int(row["id"]))
            updated_ref += 1

    return {"compresults": updated_compresults, "pisterefcompresults": updated_ref}

def read_uploaded_csv_with_fallback(uploaded_file, **kwargs):
    """Read uploaded CSV with common encoding fallbacks used by Excel exports."""
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
    last_exc = None
    for enc in encodings:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        try:
            return pd.read_csv(uploaded_file, encoding=enc, **kwargs)
        except UnicodeDecodeError as exc:
            last_exc = exc
            continue

    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    if last_exc:
        raise last_exc
    return pd.read_csv(uploaded_file, **kwargs)

def get_lookup_dict(data, key, value):
    return {d[key]: d[value] for d in data}

def get_points(discipline_id, result, category, sex):
    try:
        if not discipline_id or not category or not sex:
            return 0
        if result in (None, "", " ", "nan"):
            return 0
        # NEU: Wenn raw_result 9999 ist, immer 0 Punkte zurückgeben
        if str(result).strip() == "9999":
            return 0
        score_rows = db.table_select('scoretables', discipline_id=discipline_id, category=category.strip(), sex=sex.capitalize())
        score_rows = sorted(score_rows, key=lambda x: float(x['result_min']) if x['result_min'] not in (None, "", "nan") else float('-inf'))
        for row in score_rows:
            try:
                if row['result_min'] in (None, "", "nan") or row['result_max'] in (None, "", "nan"):
                    continue
                rmin = float(row['result_min'])
                rmax = float(row['result_max'])
                val = float(result)
                if rmin <= val <= rmax:
                    return row['points']
            except Exception:
                continue
    except Exception:
        pass
    return 0

def get_points_with_next_higher(scoretable_rows, value):
    """Return scoretable points for value; if no exact range matches, use next higher threshold."""
    try:
        v = float(value)
    except Exception:
        return None

    next_higher = None
    next_higher_min = None

    for row in scoretable_rows or []:
        try:
            rmin = float(row['result_min'])
            rmax = float(row['result_max'])
            points = row.get('points')

            if rmin <= v <= rmax:
                return points

            if rmin >= v and (next_higher_min is None or rmin < next_higher_min):
                next_higher_min = rmin
                next_higher = points
        except Exception:
            continue

    return next_higher

# --- LOGIN-MODUL ---
if "user" not in st.session_state:
    st.session_state["user"] = None

def _get_secret_or_env(name, default=""):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except Exception:
        return os.getenv(name, default)

def _get_allowed_login_emails():
    configured = _get_secret_or_env("ALLOWED_LOGIN_EMAILS", "")
    if configured:
        return {e.strip().lower() for e in str(configured).split(",") if e and e.strip()}

    # No allowlist configured -> password-only fallback for recovery.
    return set()

def _get_admin_entra_group_ids():
    raw = _get_secret_or_env("ADMIN_ENTRA_GROUP_IDS", "")
    return {g.strip().lower() for g in str(raw).split(",") if g and g.strip()}

def _get_request_headers_lower():
    try:
        ctx = getattr(st, "context", None)
        headers = getattr(ctx, "headers", None)
        if headers:
            return {str(k).lower(): str(v) for k, v in dict(headers).items()}
    except Exception:
        pass
    return {}

def _parse_client_principal_from_headers():
    headers = _get_request_headers_lower()
    raw_principal = headers.get("x-ms-client-principal")
    if not raw_principal:
        return None

    try:
        padded = raw_principal + "=" * (-len(raw_principal) % 4)
        decoded = base64.b64decode(padded)
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return None

def _entra_user_from_principal(principal):
    claims = principal.get("claims", []) if isinstance(principal, dict) else []
    user_details = principal.get("userDetails") if isinstance(principal, dict) else None

    email = None
    group_ids = set()
    for c in claims:
        typ = str(c.get("typ", "")).lower()
        val = str(c.get("val", ""))

        if not email and typ in [
            "preferred_username",
            "email",
            "upn",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
        ]:
            email = val

        if (
            typ == "groups"
            or typ.endswith("/claims/groups")
            or typ.endswith("/groups")
            or "claims/groups" in typ
        ) and val:
            group_ids.add(val.lower())

    if not email and user_details:
        email = str(user_details)

    return {"email": (email or "").strip(), "group_ids": group_ids}

def try_login_with_entra_group():
    principal = _parse_client_principal_from_headers()
    if not principal:
        return False

    user_info = _entra_user_from_principal(principal)
    admin_group_ids = _get_admin_entra_group_ids()
    allowed_emails = _get_allowed_login_emails()

    email_l = user_info["email"].strip().lower()
    is_admin_by_group = bool(user_info["group_ids"] & admin_group_ids) if admin_group_ids else False
    is_admin_by_email = email_l in allowed_emails

    if not (is_admin_by_group or is_admin_by_email):
        st.error("Kein Zugriff: Entra-Login hat keine passende Admin-Gruppe/E-Mail.")
        return False

    st.session_state["user"] = {
        "email": user_info["email"] or "entra-user",
        "auth_source": "entra",
        "is_admin": True,
    }
    return True

def login_view():
    st.title("🔐 Login erforderlich")
    st.markdown("[Mit Entra anmelden](/.auth/login/aad?post_login_redirect_uri=/)")

    if try_login_with_entra_group():
        st.rerun()

    email = st.text_input("E-Mail")
    password = st.text_input("Passwort", type="password")

    erlaubte_emails = _get_allowed_login_emails()

    if st.button("Einloggen") and email and password:
        try:
            admin_pw = _get_secret_or_env("ADMIN_PASSWORD", "")
            if not admin_pw:
                st.error("Login-Konfiguration fehlt: ADMIN_PASSWORD ist nicht gesetzt.")
                return

            email_l = email.strip().lower()
            password_ok = (password == admin_pw)
            email_ok = (not erlaubte_emails) or (email_l in erlaubte_emails)

            if password_ok and email_ok:
                st.session_state["user"] = {"email": email}
                st.rerun()
            else:
                st.error("Login fehlgeschlagen – E-Mail oder Passwort falsch.")
        except Exception as e:
            st.error(f"Login fehlgeschlagen: {e}")

def logout_button():
    if st.button("🚪 Logout"):
        st.session_state["user"] = None
        st.rerun()

# --- HAUPTSTEUERUNG ---

def startseite():
    st.title("🏊‍♂️ Diving Analysis")
    st.markdown("Willkommen beim Auswertungstool von Swiss-Aquatics Diving")

    st.header("👤 Athletes")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("Athleten anzeigen"):
            st.session_state["page"] = "Athleten anzeigen"
            st.rerun()
        if st.button("Athleten eingeben"):
            st.session_state["page"] = "Athleten eingeben"
            st.rerun()
    with col2:
        if st.button("Athleten importieren"):
            st.session_state["page"] = "Athleten importieren"
            st.rerun()
    with col3:
        if st.button("Athleten bearbeiten"):
            st.session_state["page"] = "Athleten bearbeiten"
            st.rerun()
    with col4:
        if st.button("Athleten löschen"):
            st.session_state["page"] = "Athleten löschen"
            st.rerun()

    st.header("📊 Piste")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("Piste Resultate anzeigen"):
            st.session_state["page"] = "Piste Resultate anzeigen"
            st.rerun()
        if st.button("Piste Ergebnisse eingeben"):
            st.session_state["page"] = "Piste Ergebnisse eingeben"
            st.rerun()
        if st.button("Piste Ergebnisse bearbeiten"):
            st.session_state["page"] = "Piste Ergebnisse bearbeiten"
            st.rerun()
    with col2:
        if st.button("Piste Punkte neu berechnen"):
            st.session_state["page"] = "Piste Punkte neu berechnen"
            st.rerun()
        if st.button("Piste RefPoint Competition Analyse"):
            st.session_state["page"] = "Piste RefPoint Competition Analyse"
            st.rerun()
    with col3:
        if st.button("Tool Environment"):
            st.session_state["page"] = "Tool Environment"
            st.rerun()
        if st.button("Trainingsperformance - Resilienz"):
            st.session_state["page"] = "Trainingsperformance - Resilienz"
            st.rerun()
    with col4:
        if st.button("SOC Full Calculation"):
            st.session_state["page"] = "SOC Full Calculation"
            st.rerun()
        if st.button("Full PISTE Results SOC"):
            st.session_state["page"] = "Full PISTE Results SOC"
            st.rerun()

    st.header("🏆 Wettkampf")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("Wettkampfauswertungen"):
            st.session_state["page"] = "Wettkampfauswertungen"
            st.rerun()
    with col2:
        if st.button("Wettkampfresultate eingeben"):
            st.session_state["page"] = "Wettkampfresultate eingeben"
            st.rerun()
        if st.button("Wettkampfresultate korrigieren"):
            st.session_state["page"] = "Wettkampfresultate korrigieren"
            st.rerun()
    with col3:
        if st.button("Vergleich BIG Competitions"):
            st.session_state["page"] = "Vergleich BIG Competitions"
            st.rerun()
    with col4:
        if st.button("Selektionen Wettkämpfe"):
            st.session_state["page"] = "Selektionen Wettkämpfe"
            st.rerun()

    # --- Admin-Bereich ---
    st.header("⚙️ Admin")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Referenz- und Bewertungstabellen"):
            st.session_state["page"] = "Referenz- und Bewertungstabellen"
            st.rerun()

def fetch_all_rows(table, select="*", **filters):
    return db.table_select(table, select, **filters)

def get_category_from_agecategories(vintage, pisteyear, agecategories):
    try:
        if vintage is None or pisteyear is None:
            return None
        age = int(pisteyear) - int(vintage)
        for cat in agecategories:
            min_age = int(cat.get('min_age', 0))
            max_age = int(cat.get('max_age', 99))
            if min_age <= age <= max_age:
                return cat.get('category')
    except Exception as e:
        st.warning(f"Fehler bei Kategorie-Berechnung: {e}")
    return None

def get_birth_quarter(birthdate):
    try:
        if isinstance(birthdate, str):
            birthdate = pd.to_datetime(birthdate)
        month = birthdate.month
        if 1 <= month <= 3:
            return "q1"
        elif 4 <= month <= 6:
            return "q2"
        elif 7 <= month <= 9:
            return "q3"
        elif 10 <= month <= 12:
            return "q4"
    except Exception as e:
        return None
    return None

def _norm_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip().lower()

def _normalize_sex_value(val):
    s = _norm_str(val)
    if not s or s == "nan":
        return None
    mapping = {
        "m": "male",
        "male": "male",
        "man": "male",
        "w": "female",
        "f": "female",
        "female": "female",
        "woman": "female",
        "mixed": "mixed",
        "mix": "mixed",
    }
    return mapping.get(s, s)

def _name_tokens(first_name, last_name):
    first = _norm_str(first_name)
    last = _norm_str(last_name)
    first_tok = first.split()[0] if first else ""
    last_tok = last.split()[-1] if last else ""
    return first_tok, last_tok

# Thresholds for team flags
NATIONAL_TEAM_MIN_PERCENT = 90
REGIONAL_TEAM_MIN_PERCENT = 70

def _extract_year_from_text(text):
    try:
        s = str(text or "")
    except Exception:
        return None
    m = re.search(r"(20\d{2})", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _category_group_from_start(category_start):
    c = _norm_str(category_start)
    if c.startswith("jugend"):
        return "jugend"
    if c == "elite":
        return "elite"
    return "all"


def _safe_percent_value(val, fallback=None):
    try:
        if val in (None, "", "nan"):
            return fallback
        if isinstance(val, str):
            s = val.replace("%", "").replace(",", ".").strip()
            if s == "":
                return fallback
            return float(s)
        return float(val)
    except Exception:
        return fallback


def ensure_kaderthresholds_table():
    """Seed threshold rows in existing socadditionalvalues table (no CREATE TABLE rights required)."""
    existing = fetch_all_rows(
        "socadditionalvalues",
        select="id, first_name, last_name",
        toolenvironment="kaderthresholds",
    )
    existing_keys = {
        (_norm_str(r.get("first_name")), _norm_str(r.get("last_name")))
        for r in (existing or [])
    }

    defaults = [
        {"discipline": "default", "category_group": "all", "national_percent": "90", "regional_percent": "70", "notes": "Fallback für alle Disziplinen"},
        {"discipline": "high diving", "category_group": "all", "national_percent": "90", "regional_percent": "70", "notes": "High Diving gesamt"},
        {"discipline": "high diving", "category_group": "jugend", "national_percent": "90", "regional_percent": "70", "notes": "High Diving Jugend"},
        {"discipline": "high diving", "category_group": "elite", "national_percent": "90", "regional_percent": "70", "notes": "High Diving Elite"},
        {"discipline": "high diving 20m", "category_group": "all", "national_percent": "90", "regional_percent": "70", "notes": "High Diving 20m"},
        {"discipline": "high diving 27m", "category_group": "all", "national_percent": "90", "regional_percent": "70", "notes": "High Diving 27m"},
    ]

    for row in defaults:
        key = (_norm_str(row["discipline"]), _norm_str(row["category_group"]))
        if key not in existing_keys:
            db.table_insert(
                "socadditionalvalues",
                {
                    "toolenvironment": "kaderthresholds",
                    "PisteYear": "global",
                    "first_name": row["discipline"],
                    "last_name": row["category_group"],
                    "CompPointsNationalTeam": row["national_percent"],
                    "CompPointsRegionalTeam": row["regional_percent"],
                    "quality": row["notes"],
                },
            )


def load_kader_threshold_rules():
    try:
        ensure_kaderthresholds_table()
        rows = fetch_all_rows(
            "socadditionalvalues",
            select="first_name, last_name, CompPointsNationalTeam, CompPointsRegionalTeam",
            toolenvironment="kaderthresholds",
        )
    except Exception:
        return {}

    rules = {}
    for r in rows or []:
        key = (_norm_str(r.get("first_name")), _norm_str(r.get("last_name")) or "all")
        rules[key] = {
            "national": _safe_percent_value(r.get("CompPointsNationalTeam"), None),
            "regional": _safe_percent_value(r.get("CompPointsRegionalTeam"), None),
        }
    return rules


def resolve_kader_thresholds(discipline, category_start, rules=None):
    rules = rules if rules is not None else load_kader_threshold_rules()
    d = _norm_str(discipline)
    group = _category_group_from_start(category_start)

    for key in [(d, group), (d, "all"), ("default", group), ("default", "all")]:
        if key not in rules:
            continue
        r = rules[key]
        national = _safe_percent_value(r.get("national"), NATIONAL_TEAM_MIN_PERCENT)
        regional = _safe_percent_value(r.get("regional"), REGIONAL_TEAM_MIN_PERCENT)
        return national, regional

    return float(NATIONAL_TEAM_MIN_PERCENT), float(REGIONAL_TEAM_MIN_PERCENT)

def compute_compresult_team_flags(
    *,
    competition_name,
    sex,
    discipline,
    category_start,
    points,
    competitions_df: pd.DataFrame,
    selectionpoints_df: pd.DataFrame,
):
    """Compute NationalTeam/RegionalTeam for a compresult.

    IMPORTANT: selection thresholds are year-dependent; we use competitions.PisteYear
    (not the calendar year of the competition date).
    """

    def safe_float(x):
        try:
            if x in (None, "", "nan"):
                return None
            if isinstance(x, str):
                s = x.strip().replace("%", "").replace(",", ".")
                if s == "":
                    return None
                return float(s)
            return float(x)
        except Exception:
            return None

    points_val = safe_float(points)
    if points_val is None:
        return {"NationalTeam": "no", "RegionalTeam": "no"}

    national_threshold, regional_threshold = resolve_kader_thresholds(discipline, category_start)

    comp_row = {}
    piste_year = None
    fallback_year = None
    if competitions_df is not None and not competitions_df.empty and "Name" in competitions_df.columns:
        comp_match = competitions_df[
            competitions_df["Name"].astype(str).str.strip().str.lower() == _norm_str(competition_name)
        ]
        if not comp_match.empty:
            comp_row = comp_match.iloc[0].to_dict()
            piste_year = comp_row.get("PisteYear")
            if comp_row.get("Date"):
                fallback_year = _extract_year_from_text(comp_row.get("Date"))

    if fallback_year is None:
        fallback_year = _extract_year_from_text(competition_name)

    sel = selectionpoints_df
    if sel is None or sel.empty:
        return {"NationalTeam": "no", "RegionalTeam": "no"}

    # Base filter (sex/discipline/category)
    relevant_selection = sel[
        (sel.get("sex").astype(str).str.strip().str.lower() == _norm_str(sex))
        & (sel.get("Discipline").astype(str).str.strip().str.lower() == _norm_str(discipline))
        & (sel.get("category").astype(str).str.strip().str.lower() == _norm_str(category_start))
    ]

    # Year filter: prefer competitions.PisteYear; if no match, fall back to calendar year
    # (some selectionpoints datasets are maintained by calendar year).
    base_selection = relevant_selection
    if "year" in relevant_selection.columns:
        filtered_by_year = None
        if piste_year not in (None, "", "nan"):
            filtered_by_year = relevant_selection[
                relevant_selection["year"].astype(str).str.strip() == str(piste_year).strip()
            ]
        if filtered_by_year is not None and not filtered_by_year.empty:
            relevant_selection = filtered_by_year
        elif fallback_year is not None:
            filtered_by_fallback = base_selection[
                base_selection["year"].astype(str).str.strip() == str(fallback_year).strip()
            ]
            if not filtered_by_fallback.empty:
                relevant_selection = filtered_by_fallback

    def get_status(selection_row, qual_flag, pts):
        if selection_row is None or selection_row.empty:
            return "no", "", "no"
        limit = safe_float(selection_row.iloc[0].get("points"))
        if not limit:
            return "no", "", "no"
        percentage = round((float(pts) / float(limit)) * 100, 1)
        status = "yes" if bool(qual_flag) and float(pts) >= float(limit) else "no"
        national = "yes" if percentage >= float(national_threshold) else "no"
        return status, f"{percentage}%", national

    # NationalTeam is derived from the selection thresholds (JEM/EM/WM)
    comp_col = relevant_selection.get("Competition").astype(str).str.strip().str.lower()
    jem_row = relevant_selection[comp_col == "jem"]
    em_row = relevant_selection[comp_col == "em"]
    wm_row = relevant_selection[comp_col == "wm"]

    jem_qual = bool(comp_row.get("qual-JEM", False))
    em_qual = bool(comp_row.get("qual-EM", False))
    wm_qual = bool(comp_row.get("qual-WM", False))

    _, _, jem_nt = get_status(jem_row, jem_qual, points_val)
    _, _, em_nt = get_status(em_row, em_qual, points_val)
    _, _, wm_nt = get_status(wm_row, wm_qual, points_val)
    nationalteam = "yes" if "yes" in [jem_nt, em_nt, wm_nt] else "no"

    # RegionalTeam is derived from a reference value (usually "Regional"; if not present, fall back to JEM)
    regionalteam = "no"
    regional_qual = bool(comp_row.get("qual-Regional", False))
    # Be tolerant: some datasets use different labels (e.g. "Regional-Kader", "Regional Team", etc.)
    is_regional = comp_col.isin(["regional", "regionalteam", "regional team", "regio"]) | comp_col.str.contains("reg", na=False)
    regional_row = relevant_selection[is_regional]
    # Many datasets only contain JEM/EM/WM thresholds; use JEM as Regional fallback reference.
    regional_ref_row = regional_row if not regional_row.empty else jem_row
    regional_pct = None
    if not regional_ref_row.empty and "points" in regional_ref_row.columns:
        ref_val = safe_float(regional_ref_row.iloc[0].get("points"))
        if ref_val:
            try:
                regional_pct = round((float(points_val) / float(ref_val)) * 100, 1)
            except Exception:
                regional_pct = None

    excluded_synchro = (
        _norm_str(category_start) in ["jugend c", "jugend d"]
        and _norm_str(discipline) in [
            "1m synchro",
            "3m synchro",
            "platform synchro",
            "turm synchro",
        ]
    )

    if regional_qual and not excluded_synchro and regional_pct is not None and regional_pct >= float(regional_threshold):
        regionalteam = "yes"

    return {"NationalTeam": nationalteam, "RegionalTeam": regionalteam}

# Punkteberechnung
def get_points(discipline_id, result, category, sex):
    try:
        if not discipline_id or not category or not sex:
            return 0

        score_rows = db.table_select('scoretables', discipline_id=discipline_id, category=category.strip(), sex=sex.capitalize())

        score_rows = sorted(score_rows, key=lambda x: float(x['result_min']))

        for row in score_rows:
            try:
                rmin = float(row['result_min'])
                rmax = float(row['result_max'])
                if rmin <= float(result) <= rmax:
                    return row['points']
            except Exception as e:
                st.warning(f"Fehler beim Vergleich in get_points: {e}")
    except Exception as e:
        st.error(f"Fehler beim Abrufen der Scoretable: {e}")
    
    return 0

# Alterskategorie
def get_category_from_testyear(vintage, test_year):
    age = int(test_year) - int(vintage)
    categories = db.table_select('agecategories')
    for cat in categories:
        if cat['min_age'] <= age <= cat['max_age']:
            return cat['category']
    return "Unbekannt"

# Ergebnisseingabe
def get_athletes():
    return db.table_select('athletes')

def manage_results_entry():
    st.header("🎯 Ergebnisse für einen Athleten eingeben")

    athletes = get_athletes()

    pistedisciplines = get_pistedisciplines()

    athlete_names = {
        f"{a.get('first_name', '').strip()} {a.get('last_name', '').strip()}": a['id']
        for a in athletes if a.get('first_name') and a.get('last_name') and 'id' in a
    }
    if not athlete_names:
        st.warning("Keine Athleten mit Vor- und Nachnamen gefunden! Prüfe die Datenbank und die Feldnamen.")
        return

    selected_athlete_name = st.selectbox("Wähle einen Athleten", [""] + list(athlete_names.keys()), index=0)
    test_year = st.text_input("Testjahr (Format: yyyy)", value=str(datetime.date.today().year))

    if not test_year.isdigit() or len(test_year) != 4:
        st.error("Bitte ein gültiges Jahr im Format yyyy eingeben!")
        return

    if selected_athlete_name:
        athlete_id = athlete_names[selected_athlete_name]
        athlete_data = next(a for a in athletes if a['id'] == athlete_id)
        sex = athlete_data.get("sex")
        vintage = athlete_data.get("vintage")
        category = get_category_from_testyear(vintage, test_year)

        st.subheader(f"Ergebnisse für {selected_athlete_name} ({category}, {sex}) eingeben")

        input_data = []
        allowed_disciplines = [
            "BodySize", "UpperBodySize", "JumpHeight", "102c", "202c", "302c", "402c",
            "ABSWallbar", "ShoulderEvel", "ShoulderExt", "PikePosition", "Split",
            "Handstand", "PullUp", "GlobalCore"
        ]
        discipline_map = {d["name"]: d for d in pistedisciplines}
        for discipline_name in allowed_disciplines:
            discipline = discipline_map.get(discipline_name)
            if not discipline:
                continue
            discipline_id = discipline["id"]
            value = st.number_input(f"{discipline_name}", min_value=0.0, step=0.1, format="%.2f", key=f"{discipline_id}")
            input_data.append((discipline_id, value))

        if st.button("💾 Ergebnisse speichern"):
            excluded_ids = {
                "640260ec-a094-462d-a69e-d91bbe35d94c",  # BodyWeight
                "5906836a-24aa-40e1-a71f-614a7ea4a825",  # BodySize
                "7eb062f7-3329-4cde-8875-bd6fd362137b",  # UpperBodySize
            }

            # Einzelpunkte speichern
            for discipline_id, raw_result in input_data:
                if raw_result <= 0:
                    continue
                # 9999-Logik EINZEL-EINGABE
                if str(raw_result).strip() == "9999":
                    points = 0
                elif discipline_id in excluded_ids:
                    points = 0
                else:
                    points = get_points(discipline_id, raw_result, category, sex)

                existing = db.table_select('pisteresults', 'id', athlete_id=athlete_id, discipline_id=discipline_id, TestYear=int(test_year))

                if existing:
                    db.table_update('pisteresults', {
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex
                    }, id=existing[0]['id'])
                else:
                    db.table_insert('pisteresults', {
                        'athlete_id': athlete_id,
                        'discipline_id': discipline_id,
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(test_year)
                    })

            st.success("✅ Ergebnisse gespeichert und Punkte berechnet!")

    st.markdown("---")
    st.subheader("📤 Ergebnisse per Datei importieren")

    uploaded_file = st.file_uploader("CSV/XLSX-Datei mit Ergebnissen hochladen", type=["csv", "xlsx"])

    if uploaded_file:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        expected_base = ["Testjahr", "first_name", "last_name"]
        if not all(col in df.columns for col in expected_base):
            st.error(f"❌ Die Datei muss folgende Spalten enthalten:\n\n{', '.join(expected_base)}")
            return

        discipline_map = {d['name'].replace(" ", "").lower(): d['id'] for d in pistedisciplines}
        athlete_records = get_athletes()
        athlete_lookup = {
            (a['first_name'].strip().lower(), a['last_name'].strip().lower()): a
            for a in athlete_records if a.get('first_name') and a.get('last_name')
        }

        excluded_ids = {
            "640260ec-a094-462d-a69e-d91bbe35d94c",  # BodyWeight
            "5906836a-24aa-40e1-a71f-614a7ea4a825",  # BodySize
            "7eb062f7-3329-4cde-8875-bd6fd362137b",  # UpperBodySize
        }

        inserted_count = 0
        skipped_rows = []

        for _, row in df.iterrows():
            first = str(row['first_name']).strip().lower()
            last = str(row['last_name']).strip().lower()
            test_year = int(row['Testjahr'])

            athlete_data = athlete_lookup.get((first, last))
            if not athlete_data:
                skipped_rows.append({
                    "first_name": row["first_name"],
                    "last_name": row["last_name"],
                    "Testjahr": row["Testjahr"]
                })
                continue

            athlete_id = athlete_data['id']
            sex = athlete_data['sex']
            vintage = athlete_data['vintage']
            category = get_category_from_testyear(vintage, test_year)

            # Einzelpunkte speichern
            for discipline_name, raw_result in row.items():
                if discipline_name in expected_base or pd.isna(raw_result):
                    continue

                discipline_key = discipline_name.replace(" ", "").lower()
                if discipline_key not in discipline_map:
                    continue

                discipline_id = discipline_map[discipline_key]
                # 9999-Logik IMPORT
                if str(raw_result).strip() == "9999":
                    points = 0
                elif discipline_id in excluded_ids:
                    points = 0
                else:
                    points = get_points(discipline_id, raw_result, category, sex)

                existing = db.table_select('pisteresults', 'id', athlete_id=athlete_id, discipline_id=discipline_id, TestYear=test_year)

                if existing:
                    db.table_update('pisteresults', {
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex
                    }, id=existing[0]['id'])
                else:
                    db.table_insert('pisteresults', {
                        'athlete_id': athlete_id,
                        'discipline_id': discipline_id,
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex,
                        'TestYear': test_year
                    })
            inserted_count += 1

        st.success(f"✅ {inserted_count} Ergebnisse importiert.")
        if skipped_rows:
            st.warning(f"⚠️ {len(skipped_rows)} Zeile(n) konnten keinem Athleten zugeordnet werden:")
            st.dataframe(pd.DataFrame(skipped_rows))

# Athleten bearbeiten
def edit_athletes():
    st.header("✏️ Athleten bearbeiten")
    try:
        athletes = db.table_select('athletes')
    except Exception as e:
        st.error(f"Athleten konnten nicht geladen werden: {e}")
        return
    athlete_names = {f"{a['first_name']} {a['last_name']}": a['id'] for a in athletes}
    selected_name = st.selectbox("Athlet auswählen", [""] + list(athlete_names.keys()), index=0)

    if selected_name:
        athlete_id = athlete_names[selected_name]
        athlete = db.table_select('athletes', id=athlete_id)[0]

        first_name = st.text_input("Vorname", athlete['first_name'])
        last_name = st.text_input("Nachname", athlete['last_name'])
        bd = athlete['birthdate']
        if isinstance(bd, str):
            bd = datetime.datetime.strptime(bd, "%Y-%m-%d").date()
        birthdate = st.date_input("Geburtsdatum", bd)
        sex = st.selectbox("Geschlecht", ["male", "female"], index=0 if athlete['sex'] == "male" else 1)
        teams = db.table_select('team', 'ShortName')
        club_options = [t['ShortName'] for t in teams if t.get('ShortName')]
        default_index = club_options.index(athlete['club']) if athlete['club'] in club_options else 0
        club = st.selectbox("Verein", club_options, index=default_index)
        nationalteam = st.selectbox("Nationalteam", ["yes", "no"], index=0 if athlete['nationalteam'] == "yes" else 1)

        if st.button("Aktualisieren"):
            vintage = birthdate.year
            full_name = f"{first_name} {last_name}"
            category = get_category_from_testyear(vintage, datetime.date.today().year)
            db.table_update('athletes', {
                'first_name': first_name,
                'last_name': last_name,
                'birthdate': birthdate.strftime('%Y-%m-%d'),
                'sex': sex,
                'club': club,
                'nationalteam': nationalteam,
                'vintage': vintage,
                'full_name': full_name,
                'category': category
            }, id=athlete_id)
            st.success("Athletendaten aktualisiert.")

        st.markdown("---")
        st.subheader("🩹 Verletzungsstatus pro Jahr")
        injury_map = load_athleteyearstatus_map()
        available_year_rows = fetch_all_rows("socadditionalvalues", select="PisteYear")
        year_options = sorted(
            {
                str(row.get("PisteYear")).strip()
                for row in available_year_rows
                if row.get("PisteYear") not in (None, "", "nan")
            },
            key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)),
        )
        if not year_options:
            year_options = [str(year) for year in range(2024, 2031)]

        selected_year = st.selectbox("Jahr", year_options, key=f"injury_year_{athlete_id}")
        injury_key = (first_name.lower().strip(), last_name.lower().strip(), str(selected_year))
        injured_default = injury_map.get(injury_key, False)
        injured_now = st.checkbox("Verletzt", value=injured_default, key=f"injury_flag_{athlete_id}")
        if st.button("Verletzungsstatus speichern", key=f"save_injury_{athlete_id}"):
            save_athleteyearstatus(first_name, last_name, selected_year, injured_now)
            st.success(f"Verletzungsstatus für {selected_year} gespeichert.")

        athlete_status_rows = []
        for year in year_options:
            athlete_status_rows.append({
                "PisteYear": year,
                "injured": "yes" if injury_map.get((first_name.lower().strip(), last_name.lower().strip(), str(year)), False) else "no",
            })
        st.dataframe(pd.DataFrame(athlete_status_rows), use_container_width=True)
    else:
        st.info("Bitte zuerst einen Athleten auswählen.")

# Auswertung starten
def auswertung_starten():
    st.header("📈 Piste Resultate anzeigen")

    # Daten laden (jetzt mit Caching und Utilitys)
    try:
        results = fetch_all_rows("pisteresults", select="*")
        athletes = get_athletes()
        disciplines = get_pistedisciplines()
    except Exception as e:
        st.error(f"Piste Resultate konnten nicht geladen werden: {e}")
        return

    # Lookup-Tabellen
    athlete_lookup = get_lookup_dict(athletes, "id", "full_name")
    discipline_lookup = get_lookup_dict(disciplines, "id", "name")

    # Filteroptionen extrahieren
    all_years = sorted(set([r['TestYear'] for r in results if r['TestYear']]), reverse=True)
    all_categories = sorted(set([r['category'] for r in results if r['category']]))
    all_sexes = sorted(set([r['sex'] for r in results if r.get('sex')]))
    all_names = sorted(set([athlete_lookup.get(r['athlete_id'], "Unbekannt") for r in results]))

    # Dynamische Multiselect-Funktion
    def dynamic_multiselect(label, options, key):
        default = st.session_state.get(f"{key}_default", ["Alle"])
        selected = st.multiselect(label, ["Alle"] + options, default=default, key=key)
        if "Alle" in selected and len(selected) > 1:
            selected = [s for s in selected if s != "Alle"]
            st.session_state[f"{key}_default"] = selected
            st.rerun()
        if not selected:
            selected = ["Alle"]
            st.session_state[f"{key}_default"] = selected
            st.rerun()
        return selected

    # Filter mit automatischem "Alle"-Verhalten
    selected_years = dynamic_multiselect("📅 Testjahr wählen", all_years, "jahr")
    selected_categories = dynamic_multiselect("📂 Kategorie wählen", all_categories, "kategorie")
    selected_sexes = dynamic_multiselect("⚧ Geschlecht wählen", all_sexes, "geschlecht")
    selected_names = dynamic_multiselect("👤 Name wählen", all_names, "name")

    # Daten filtern
    filtered = results
    if "Alle" not in selected_years:
        filtered = [r for r in filtered if r['TestYear'] in selected_years]
    if "Alle" not in selected_categories:
        filtered = [r for r in filtered if r['category'] in selected_categories]
    if "Alle" not in selected_sexes:
        filtered = [r for r in filtered if r.get('sex') in selected_sexes]
    if "Alle" not in selected_names:
        filtered = [r for r in filtered if athlete_lookup.get(r['athlete_id'], "Unbekannt") in selected_names]

    # Ergebnisstruktur
    results_dict = {}
    for entry in filtered:
        athlete_id = entry['athlete_id']
        discipline_id = entry['discipline_id']
        year = entry['TestYear']
        category = entry['category']
        points = entry['points']
        sex = entry.get('sex')
        full_name = athlete_lookup.get(athlete_id, "Unbekannt")
        discipline_name = discipline_lookup.get(discipline_id, "Unbekannt")
        raw_value = entry.get('raw_result', None)

        key = (athlete_id, year)
        if key not in results_dict:
            results_dict[key] = {
                "Name": full_name,
                "Kategorie": category,
                "Geschlecht": sex,
                "Testjahr": year,
                "Totalpunkte": 0
            }

        results_dict[key][f"{discipline_name}_Wert"] = raw_value
        results_dict[key][f"{discipline_name}_Punkte"] = points
        results_dict[key]["Totalpunkte"] += points if points not in (None, "", "nan") else 0

    # DataFrame erzeugen
    df = pd.DataFrame.from_dict(results_dict, orient='index').reset_index(drop=True)
    st.dataframe(df)

    st.download_button("📥 CSV herunterladen", df.to_csv(index=False, encoding='utf-8-sig'), file_name="resultate.csv", mime='text/csv')

    try:
        import io
        excel_buffer = io.BytesIO()
        df.to_excel(excel_buffer, index=False, engine='openpyxl')
        excel_buffer.seek(0)
        st.download_button("📥 Excel herunterladen", excel_buffer, file_name="resultate.xlsx")
    except ImportError:
        st.info("📦 Modul 'openpyxl' ist nicht installiert – Excel-Export nicht verfügbar.")


def manage_pisteresults_correction():
    st.header("🛠️ Piste Ergebnisse bearbeiten")

    results = fetch_all_rows("pisteresults", select="*")
    if not results:
        st.info("Keine Piste-Ergebnisse vorhanden.")
        return

    athletes = get_athletes()
    disciplines = get_pistedisciplines()

    athlete_by_id = {a.get("id"): a for a in athletes if a.get("id")}
    discipline_name_by_id = {d.get("id"): d.get("name") for d in disciplines if d.get("id")}

    df = pd.DataFrame(results)
    required_cols = ["id", "athlete_id", "discipline_id", "raw_result", "points", "TestYear", "category", "sex"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    df["athlete_label"] = df["athlete_id"].map(
        lambda aid: (
            f"{str((athlete_by_id.get(aid) or {}).get('first_name', '')).strip()} {str((athlete_by_id.get(aid) or {}).get('last_name', '')).strip()}"
        ).strip()
    )
    df["discipline_name"] = df["discipline_id"].map(lambda did: discipline_name_by_id.get(did, "Unbekannt"))

    years = sorted(
        {
            int(y)
            for y in df["TestYear"].dropna().tolist()
            if str(y).strip().isdigit()
        },
        reverse=True,
    )
    selected_year = st.selectbox("Testjahr", [""] + [str(y) for y in years], index=0)
    if not selected_year:
        st.info("Bitte zuerst ein Testjahr auswählen.")
        return

    df_year = df[df["TestYear"].astype(str).str.strip() == selected_year].copy()
    if df_year.empty:
        st.info("Keine Einträge für das gewählte Jahr gefunden.")
        return

    athletes_in_year = sorted(
        {
            str(a).strip()
            for a in df_year["athlete_label"].dropna().tolist()
            if str(a).strip() and str(a).strip().lower() != "nan"
        }
    )


def ensure_athleteyearstatus_table():
    """Compatibility shim: injury flags are stored in socadditionalvalues special rows."""
    return None

def _injury_status_year_key(piste_year):
    return f"injuryflags:{str(piste_year).strip()}"

def _injury_status_year_from_key(piste_year):
    value = str(piste_year or "").strip()
    prefix = "injuryflags:"
    return value[len(prefix):] if value.lower().startswith(prefix) else value


def load_athleteyearstatus_map():
    try:
        rows = fetch_all_rows(
            "socadditionalvalues",
            select="first_name, last_name, PisteYear, quality",
            toolenvironment="injuryflags",
        )
    except Exception:
        return {}

    status_map = {}
    for row in rows or []:
        key = (
            _norm_str(row.get("first_name")),
            _norm_str(row.get("last_name")),
            _norm_str(_injury_status_year_from_key(row.get("PisteYear"))),
        )
        status_map[key] = _norm_str(row.get("quality")) in ("injured", "verletzt", "1", "true", "yes", "y")
    return status_map


def save_athleteyearstatus(first_name, last_name, piste_year, injured):
    year_key = _injury_status_year_key(piste_year)
    existing = db.table_select(
        "socadditionalvalues",
        "id",
        first_name=first_name,
        last_name=last_name,
        PisteYear=year_key,
        toolenvironment="injuryflags",
    )
    if injured:
        payload = {
            "toolenvironment": "injuryflags",
            "first_name": first_name,
            "last_name": last_name,
            "PisteYear": year_key,
            "quality": "injured",
        }
        if existing:
            db.table_update("socadditionalvalues", payload, id=existing[0]["id"])
        else:
            db.table_insert("socadditionalvalues", payload)
    else:
        if existing:
            db.table_delete("socadditionalvalues", id=existing[0]["id"])


def manage_scoretable():
    st.header("📋 Scoretabelle verwalten")

    disciplines = db.table_select('pistedisciplines', 'id, name')
    discipline_map = {d['name']: d['id'] for d in disciplines}
    selected_discipline = st.selectbox("Disziplin auswählen", list(discipline_map.keys()))

    categories = db.table_select('agecategories', 'category')
    category_options = sorted(list(set(c['category'] for c in categories)))

    if selected_discipline:
        discipline_id = discipline_map[selected_discipline]
        entries = db.query("SELECT * FROM [scoretables] WHERE [discipline_id] = ? ORDER BY result_min", [discipline_id])

        st.subheader(f"Aktuelle Punktebereiche für {selected_discipline}")
        if entries:
            for entry in entries:
                with st.expander(f"Bearbeiten: {entry['category']} / {entry['sex']} | {entry['result_min']} - {entry['result_max']} → {entry['points']} Punkte"):
                    new_min = st.number_input("Von (inkl.)", value=entry['result_min'], key=f"min_{entry['id']}", format="%.1f")
                    new_max = st.number_input("Bis (inkl.)", value=entry['result_max'], key=f"max_{entry['id']}", format="%.1f")
                    new_points = st.number_input("Punkte", value=entry['points'], key=f"points_{entry['id']}", step=1)
                    new_category = st.selectbox("Kategorie", category_options, index=category_options.index(entry.get('category', category_options[0])), key=f"cat_{entry['id']}")
                    new_sex = st.selectbox("Geschlecht", ["male", "female"], index=0 if entry.get('sex') == "male" else 1, key=f"sex_{entry['id']}")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("💾 Speichern", key=f"save_{entry['id']}"):
                            if new_max >= new_min:
                                db.table_update('scoretables', {
                                    'result_min': new_min,
                                    'result_max': new_max,
                                    'points': new_points,
                                    'category': new_category,
                                    'sex': new_sex
                                }, id=entry['id'])
                                st.success("Eintrag aktualisiert.")
                                st.rerun()
                            else:
                                st.error("❗ 'Bis' muss größer oder gleich 'Von' sein.")
                    with col2:
                        if st.button("🗑️ Löschen", key=f"delete_{entry['id']}"):
                            db.table_delete('scoretables', id=entry['id'])
                            st.warning("Eintrag gelöscht.")
                            st.rerun()
        else:
            st.info("Noch keine Punktebereiche vorhanden für diese Disziplin.")

        st.subheader("➕ Neuen Eintrag hinzufügen")
        result_min = st.number_input("Von (inkl.)", min_value=0.0, step=0.1, format="%.1f", key="add_min")
        result_max = st.number_input("Bis (inkl.)", min_value=0.0, step=0.1, format="%.1f", key="add_max")
        points = st.number_input("Punkte", min_value=0, step=1, key="add_points")
        new_category = st.selectbox("Kategorie", category_options, key="add_category")
        new_sex = st.selectbox("Geschlecht", ["male", "female"], key="add_sex")

        if st.button("➕ Eintrag speichern", key="add_save"):
            if result_max >= result_min:
                db.table_insert('scoretables', {
                    'discipline_id': discipline_id,
                    'result_min': result_min,
                    'result_max': result_max,
                    'points': points,
                    'category': new_category,
                    'sex': new_sex
                })
                st.success("Eintrag hinzugefügt!")
                st.rerun()
            else:
                st.error("❗ 'Bis' muss größer oder gleich 'Von' sein.")

def import_athletes():
    st.header("📥 Athleten importieren")

    # Button für Bioage-Update ALLER Athleten
    if st.button("🔄 Bioage für alle bestehenden Athleten berechnen und speichern"):
        athletes = db.table_select("athletes", "id, birthdate")
        updated = 0
        skipped = 0
        for a in athletes:
            birthdate = a.get("birthdate")
            athlete_id = a.get("id")
            if not birthdate or not athlete_id:
                skipped += 1
                continue
            bioage = get_birth_quarter(birthdate)
            if bioage:
                db.table_update("athletes", {"bioage": bioage}, id=athlete_id)
                updated += 1
            else:
                skipped += 1
        st.success(f"Bioage für {updated} Athleten aktualisiert. {skipped} Athleten übersprungen (fehlendes oder ungültiges Geburtsdatum).")

    uploaded_file = st.file_uploader("CSV-Datei mit Athletendaten hochladen", type="csv")

    # 📄 Beispiel-CSV zum Herunterladen anbieten
    sample_df = pd.DataFrame([{
        "first_name": "Max",
        "last_name": "Mustermann",
        "birthdate": "2005-03-15",
        "sex": "male",
        "club": "SC Beispiel",
        "nationalteam": "no"
    }])
    st.download_button(
        label="📄 Beispiel-CSV herunterladen",
        data=sample_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="athleten_beispiel.csv",
        mime="text/csv"
    )

    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        required_columns = {"first_name", "last_name", "birthdate", "sex", "club", "nationalteam"}

        if not required_columns.issubset(df.columns):
            st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_columns)}")
            return

        inserted = 0
        skipped_duplicates = []
        for _, row in df.iterrows():
            try:
                birthdate = pd.to_datetime(row['birthdate']).strftime('%Y-%m-%d')
                vintage = int(row['birthdate'][:4])
                full_name = f"{row['first_name']} {row['last_name']}"
                category = get_category_from_testyear(vintage, datetime.date.today().year)
                bioage = get_birth_quarter(birthdate)

                # Prüfen, ob Athlet bereits existiert
                existing = db.table_select('athletes', 'id', first_name=row['first_name'].strip(), last_name=row['last_name'].strip(), birthdate=birthdate)
                if existing:
                    skipped_duplicates.append({
                        "first_name": row['first_name'],
                        "last_name": row['last_name'],
                        "birthdate": birthdate
                    })
                    continue

                db.table_insert('athletes', {
                    'first_name': row['first_name'],
                    'last_name': row['last_name'],
                    'birthdate': birthdate,
                    'sex': row['sex'],
                    'club': row['club'],
                    'nationalteam': row['nationalteam'],
                    'vintage': vintage,
                    'full_name': full_name,
                    'category': category,
                    'bioage': bioage
                })
                inserted += 1
            except Exception as e:
                st.warning(f"Fehler beim Einfügen von {row['first_name']} {row['last_name']}: {e}")

        if skipped_duplicates:
            st.warning(f"{len(skipped_duplicates)} Athlet(en) wurden nicht importiert, da sie bereits existieren:")
            st.dataframe(pd.DataFrame(skipped_duplicates))

        st.success(f"✅ {inserted} Athleten erfolgreich importiert.")

def delete_athlete():
    st.header("🗑️ Athlet löschen")
    athletes = db.table_select('athletes', 'id, first_name, last_name, birthdate, club')

    if not athletes:
        st.info("Keine Athleten vorhanden.")
        return

    athlete_names = {
        f"{a['first_name']} {a['last_name']} | {a['birthdate']} | {a['club']}": a['id']
        for a in athletes
    }
    selected_name = st.selectbox("Wähle einen Athleten zum Löschen", list(athlete_names.keys()))

    if selected_name:
        athlete_id = athlete_names[selected_name]
        # Optional: Details nochmal anzeigen
        athlete = next((a for a in athletes if a['id'] == athlete_id), None)
        if athlete:
            st.info(f"**Vorname:** {athlete['first_name']}  \n"
                    f"**Nachname:** {athlete['last_name']}  \n"
                    f"**Geburtsdatum:** {athlete['birthdate']}  \n"
                    f"**Verein:** {athlete['club']}")

        if st.button("❗ Endgültig löschen"):
            try:
                # Ergebnisse löschen
                db.table_delete('pisteresults', athlete_id=athlete_id)
                db.table_delete('athletes', id=athlete_id)
                st.success(f"Athlet '{selected_name}' und alle zugehörigen Ergebnisse wurden gelöscht.")
                st.rerun()
            except Exception as e:
                st.error(f"Fehler beim Löschen: {e}")

def punkte_neuberechnen():
    st.header("🔄 Punkte neu berechnen für ein bestimmtes Testjahr")

    st.info("""
    **Hinweis:**  
    „Piste Punkte neu berechnen“ wird **nur benötigt**, wenn sich etwas an den Bewertungsgrundlagen ändert, z.B.:

    - Die Scoretabelle (`scoretables`) wird angepasst (z.B. neue Punkteverteilung, neue Kategorien, neue Altersgrenzen).
    - Die Alterskategorien ändern sich.
    - Es gibt sonstige Regeländerungen, die die Punkteberechnung beeinflussen.

    Im normalen Ablauf (Eingabe oder Import von Ergebnissen) werden die Punkte immer direkt nach aktueller Scoretabelle berechnet und gespeichert.
    **Nur wenn sich die Regeln nachträglich ändern, müssen die bestehenden Ergebnisse mit „Piste Punkte neu berechnen“ aktualisiert werden.**
    """)

    # Jahre aus pisteresults holen
    years_data = fetch_all_rows("pisteresults", select="TestYear")
    all_years = sorted(set(r["TestYear"] for r in years_data if r["TestYear"]), reverse=True)
    selected_year = st.selectbox("📅 Testjahr für Neuberechnung wählen", all_years)

    if st.button("🔄 Neuberechnung starten"):
        results = fetch_all_rows("pisteresults", select="*")
        if not results:
            st.warning(f"⚠️ Keine Resultate für das Jahr {selected_year} gefunden.")
            return

        pistedisciplines = get_pistedisciplines()
        athletes = get_athletes()
        athlete_lookup = {a['id']: a for a in athletes}

        # IDs für Spezialdisziplinen holen
        pistetotalpoints_id = next((d['id'] for d in pistedisciplines if d['name'] == "PisteTotalPoints"), None)
        pistepointsdurchschnitt_id = next((d['id'] for d in pistedisciplines if d['name'].strip().lower() == "pistepointsdurchschnitt"), None)
        pistetotalinpoints_id = next((d['id'] for d in pistedisciplines if d['name'] == "PisteTotalinPoints"), None)

        excluded_ids = {
            "640260ec-a094-462d-a69e-d91bbe35d94c",  # BodyWeight
            "5906836a-24aa-40e1-a71f-614a7ea4a825",  # BodySize
            "7eb062f7-3329-4cde-8875-bd6fd362137b",  # UpperBodySize
        }

        updated_count = 0
        # 1. Alle Einzelpunkte neu berechnen
        for entry in results:
            if entry["TestYear"] != selected_year:
                continue

            discipline_id = entry["discipline_id"]
            raw_result = entry["raw_result"]
            athlete_id = entry["athlete_id"]
            athlete = athlete_lookup.get(athlete_id)
            if not athlete:
                continue
            sex = athlete.get("sex")
            vintage = athlete.get("vintage")
            category = get_category_from_testyear(vintage, selected_year)

            new_points = 0 if discipline_id in excluded_ids else get_points(discipline_id, raw_result, category, sex)

            db.table_update("pisteresults", {
                "points": new_points,
                "category": category
            }, id=entry["id"])
            updated_count += 1

        # 2. Für jeden Athleten im Jahr: Spezialdisziplinen berechnen und speichern
        athlete_ids = set(r["athlete_id"] for r in results if r["TestYear"] == selected_year)
        for athlete_id in athlete_ids:
            athlete = athlete_lookup.get(athlete_id)
            if not athlete:
                continue
            sex = athlete.get("sex")
            vintage = athlete.get("vintage")
            category = get_category_from_testyear(vintage, selected_year)

            # Alle Einzelpunkte laden
            all_results = fetch_all_rows(
                "pisteresults",
                select="discipline_id, points",
                athlete_id=athlete_id,
                TestYear=selected_year
            )
            single_points = [
                r["points"] for r in all_results
                if r["discipline_id"] not in excluded_ids and r.get("points") not in (None, 0)
            ]
            total_points = round(sum(single_points), 2) if single_points else 0
            avg_points = round(total_points / len(single_points), 2) if single_points else 0

            # --- PisteTotalPoints speichern ---
            if pistetotalpoints_id:
                existing_total = fetch_all_rows(
                    'pisteresults',
                    select='id',
                    athlete_id=athlete_id,
                    discipline_id=pistetotalpoints_id,
                    TestYear=selected_year
                )
                if existing_total:
                    db.table_update('pisteresults', {
                        'raw_result': total_points,
                        'points': total_points,
                        'category': category,
                        'sex': sex
                    }, id=existing_total[0]['id'])
                else:
                    db.table_insert('pisteresults', {
                        'athlete_id': athlete_id,
                        'discipline_id': pistetotalpoints_id,
                        'raw_result': total_points,
                        'points': total_points,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(selected_year)
                    })

            # --- PistePointsDurchschnitt speichern und bewerten ---
            if pistepointsdurchschnitt_id:
                # Bewertung holen
                scoretable_rows = fetch_all_rows('scoretables', select='*', discipline_id=pistepointsdurchschnitt_id)
                bewertung = None
                for row in scoretable_rows:
                    try:
                        rmin = float(row['result_min'])
                        rmax = float(row['result_max'])
                        if rmin <= avg_points <= rmax:
                            bewertung = row['points']
                            break
                    except Exception:
                        continue

                existing_avg = fetch_all_rows(
                    'pisteresults',
                    select='id',
                    athlete_id=athlete_id,
                    discipline_id=pistepointsdurchschnitt_id,
                    TestYear=selected_year
                )
                if existing_avg:
                    db.table_update('pisteresults', {
                        'raw_result': avg_points,
                        'points': bewertung,
                        'category': category,
                        'sex': sex
                    }, id=existing_avg[0]['id'])
                else:
                    db.table_insert('pisteresults', {
                        'athlete_id': athlete_id,
                        'discipline_id': pistepointsdurchschnitt_id,
                        'raw_result': avg_points,
                        'points': bewertung,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(selected_year)
                    })

            # --- PisteTotalinPoints speichern (Bewertung des Durchschnitts) ---
            if pistetotalinpoints_id:
                scoretable_rows = fetch_all_rows('scoretables', select='*', discipline_id=pistetotalinpoints_id)
                pistetotalinpoints_value = get_points_with_next_higher(scoretable_rows, avg_points)

                existing_totalin = fetch_all_rows(
                    'pisteresults',
                    select='id',
                    athlete_id=athlete_id,
                    discipline_id=pistetotalinpoints_id,
                    TestYear=selected_year
                )
                if existing_totalin:
                    db.table_update('pisteresults', {
                        'raw_result': avg_points,
                        'points': pistetotalinpoints_value,
                        'category': category,
                        'sex': sex
                    }, id=existing_totalin[0]['id'])
                else:
                    db.table_insert('pisteresults', {
                        'athlete_id': athlete_id,
                        'discipline_id': pistetotalinpoints_id,
                        'raw_result': avg_points,
                        'points': pistetotalinpoints_value,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(selected_year)
                    })

        st.success(f"✅ {updated_count} Resultate für das Jahr {selected_year} wurden neu bewertet.")

def bewertung_wettkampf():
    st.header("🔄 Wettkampfbewertungen berechnen")

    selection_points = fetch_all_rows('selectionpoints')
    competitions = fetch_all_rows('competitions')
    agedives = fetch_all_rows('agedives')
    athletes = fetch_all_rows('athletes', select='id, first_name, last_name, full_name, sex')
    df_athletes = pd.DataFrame(athletes)
    df_agedives = pd.DataFrame(agedives)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    missing_selection_combos = []

    athlete_sex_by_id = {}
    athlete_sex_by_name = {}
    athlete_sex_by_tokens = {}
    try:
        if not df_athletes.empty:
            if 'id' in df_athletes.columns and 'sex' in df_athletes.columns:
                athlete_sex_by_id = {
                    str(r['id']): _normalize_sex_value(r.get('sex'))
                    for _, r in df_athletes.iterrows()
                    if r.get('id') is not None
                }
            if all(c in df_athletes.columns for c in ['first_name', 'last_name', 'sex']):
                for _, r in df_athletes.iterrows():
                    key = (_norm_str(r.get('first_name')), _norm_str(r.get('last_name')))
                    sex_val = _normalize_sex_value(r.get('sex'))
                    if key != ("", "") and sex_val and key not in athlete_sex_by_name:
                        athlete_sex_by_name[key] = sex_val

                    tok = _name_tokens(r.get('first_name'), r.get('last_name'))
                    if tok != ("", "") and sex_val and tok not in athlete_sex_by_tokens:
                        athlete_sex_by_tokens[tok] = sex_val

            # Also learn from full_name if present
            if 'full_name' in df_athletes.columns and 'sex' in df_athletes.columns:
                for _, r in df_athletes.iterrows():
                    full = _norm_str(r.get('full_name'))
                    if not full:
                        continue
                    parts = full.split()
                    if len(parts) < 2:
                        continue
                    tok = (parts[0], parts[-1])
                    sex_val = _normalize_sex_value(r.get('sex'))
                    if tok != ("", "") and sex_val and tok not in athlete_sex_by_tokens:
                        athlete_sex_by_tokens[tok] = sex_val
    except Exception:
        athlete_sex_by_id = {}
        athlete_sex_by_name = {}
        athlete_sex_by_tokens = {}

    def _needs_sex_update(raw_val):
        return _norm_str(raw_val) in ("", "nan", "none")

    def resolve_sex_for_compresult(result_row):
        current = _normalize_sex_value(result_row.get('sex'))
        if current:
            return current
        athlete_id = result_row.get('athlete_id')
        if athlete_id not in (None, "", "nan"):
            lookup = athlete_sex_by_id.get(str(athlete_id))
            if lookup:
                return lookup
        first = _norm_str(result_row.get('first_name'))
        last = _norm_str(result_row.get('last_name'))
        lookup = athlete_sex_by_name.get((first, last))
        if lookup:
            return lookup
        tok_lookup = athlete_sex_by_tokens.get(_name_tokens(first, last))
        return tok_lookup

    def safe_numeric(val):
        if val in ("", None):
            return None
        try:
            if isinstance(val, str):
                cleaned = val.replace("%", "").replace(",", ".").strip()
                if cleaned == "":
                    return None
                return float(cleaned)
            return float(val)
        except Exception:
            return None

    def get_status(selection_row, qual_flag, points, national_threshold):
        if selection_row.empty:
            return "no", "", "no"
        limit = safe_numeric(selection_row.iloc[0].get('points'))
        if not limit:
            return "no", "", "no"
        points_val = safe_numeric(points)
        if points_val is None:
            return "no", "", "no"
        percentage = round((points_val / limit) * 100, 1)
        if qual_flag:
            status = "yes" if points_val >= limit else "no"
        else:
            status = "no"
        national = "yes" if percentage >= float(national_threshold) else "no"
        return status, f"{percentage}%", national

    def _comp_label_col(df: pd.DataFrame) -> pd.Series:
        if df is None or df.empty or 'Competition' not in df.columns:
            return pd.Series([], dtype=str)
        return df['Competition'].astype(str).str.strip().str.lower()

    def _extract_comp_calendar_year(comp_row, competition_name):
        try:
            dt = comp_row.get("Date") if isinstance(comp_row, dict) else None
            y = _extract_year_from_text(dt)
            if y is not None:
                return y
        except Exception:
            pass
        return _extract_year_from_text(competition_name)

    # --- Nur ein PisteYear neu berechnen (z.B. 2026) ---
    # Wichtig: PisteYear kommt aus competitions.PisteYear und kann sich vom Kalenderjahr des Datums unterscheiden.
    try:
        pisteyears = sorted({str(c.get("PisteYear")) for c in competitions if c.get("PisteYear")}, reverse=True)
    except Exception:
        pisteyears = []
    if pisteyears:
        selected_pisteyear = st.selectbox("PisteYear gezielt neu berechnen", pisteyears, index=0)
    else:
        selected_pisteyear = None

    if st.button("🔄 Alle Wettkampfbewertungen berechnen"):
        comp_results = fetch_all_rows('compresults')
        df_results = pd.DataFrame(comp_results)
        df_selection = pd.DataFrame(selection_points)
        df_comp = pd.DataFrame(competitions)
        kader_rules = load_kader_threshold_rules()
        missing_selection_combos = []

        for _, row in df_results.iterrows():
            comp_id = row["id"]
            sex = resolve_sex_for_compresult(row)
            # If sex was missing, persist it immediately
            if sex and _needs_sex_update(row.get('sex')):
                try:
                    db.table_update('compresults', {"sex": sex}, id=comp_id)
                except Exception:
                    pass

            discipline = row["Discipline"]
            category = row["CategoryStart"]
            points = row["Points"]
            competition_name = row["Competition"]
            national_threshold, regional_threshold = resolve_kader_thresholds(discipline, category, rules=kader_rules)

            dives = None
            if all(col in df_agedives.columns for col in ['sex', 'category', 'Discipline', 'dives']):
                dives_row = df_agedives[
                    (df_agedives['sex'].astype(str).str.strip().str.lower() == str(sex).strip().lower()) &
                    (df_agedives['category'].astype(str).str.strip().str.lower() == str(category).strip().lower()) &
                    (df_agedives['Discipline'].astype(str).str.strip().str.lower() == str(discipline).strip().lower())
                ]
                dives = dives_row.iloc[0]['dives'] if not dives_row.empty else None

            if dives is None:
                st.warning(f"Keine dives für {sex}, {category}, {discipline}")
            if points in (None, "", "nan"):
                st.warning(f"Keine Punkte für {row}")

            average_points = None
            try:
                points_val = float(points)
                dives_val = float(dives)
                average_points = points_val / dives_val if dives_val else None
            except Exception:
                average_points = None

            comp_row = df_comp[df_comp["Name"] == competition_name]
            comp_row = comp_row.iloc[0] if not comp_row.empty else {}

            piste_year = comp_row.get("PisteYear")
            comp_calendar_year = _extract_comp_calendar_year(comp_row, competition_name)

            relevant_selection = df_selection[
                (df_selection['sex'].astype(str).str.strip().str.lower() == str(sex).strip().lower()) &
                (df_selection['Discipline'].astype(str).str.strip().str.lower() == str(discipline).strip().lower()) &
                (df_selection['category'].astype(str).str.strip().str.lower() == str(category).strip().lower())
            ]
            if relevant_selection.empty:
                missing_selection_combos.append({
                    "sex": str(sex),
                    "Discipline": str(discipline),
                    "CategoryStart": str(category),
                })

            jem_qual = bool(comp_row.get("qual-JEM", False))
            em_qual = bool(comp_row.get("qual-EM", False))
            wm_qual = bool(comp_row.get("qual-WM", False))
            regional_qual = bool(comp_row.get("qual-Regional", False))

            excluded_synchro = (
                str(category).strip().lower() in ["jugend c", "jugend d"] and
                str(discipline).strip().lower() in ["1m synchro", "3m synchro", "platform synchro", "turm synchro"]
            )

            base_selection = relevant_selection
            if "year" in relevant_selection.columns:
                by_piste = None
                if piste_year not in (None, "", "nan"):
                    by_piste = relevant_selection[
                        relevant_selection["year"].astype(str).str.strip() == str(piste_year).strip()
                    ]
                if by_piste is not None and not by_piste.empty:
                    relevant_selection = by_piste
                elif comp_calendar_year is not None:
                    by_cal = base_selection[
                        base_selection["year"].astype(str).str.strip() == str(comp_calendar_year).strip()
                    ]
                    if not by_cal.empty:
                        relevant_selection = by_cal

            comp_col = _comp_label_col(relevant_selection)
            jem_row = relevant_selection[comp_col == "jem"]
            em_row = relevant_selection[comp_col == "em"]
            wm_row = relevant_selection[comp_col == "wm"]
            is_regional = comp_col.isin(["regional", "regionalteam", "regional team", "regio"]) | comp_col.str.contains("reg", na=False)
            regional_row = relevant_selection[is_regional]

            jem_qual = bool(comp_row.get("qual-JEM", False))
            em_qual = bool(comp_row.get("qual-EM", False))
            wm_qual = bool(comp_row.get("qual-WM", False))
            regional_qual = bool(comp_row.get("qual-Regional", False))

            try:
                points_float = float(points)
            except Exception:
                points_float = None

            if points_float is None:
                continue

            jem, jem_pct, jem_nt = get_status(jem_row, jem_qual, points_float, national_threshold)
            em, em_pct, em_nt = get_status(em_row, em_qual, points_float, national_threshold)
            wm, wm_pct, wm_nt = get_status(wm_row, wm_qual, points_float, national_threshold)
            nationalteam = "yes" if "yes" in [jem_nt, em_nt, wm_nt] else "no"

            # RegionalTeam-Berechnung
            regional_pct = None
            regionalteam = "no"
            regional_ref_row = regional_row if not regional_row.empty else jem_row
            if not regional_ref_row.empty and 'points' in regional_ref_row.columns:
                try:
                    ref_val = safe_numeric(regional_ref_row.iloc[0].get('points'))
                    points_val_local = safe_numeric(points)
                    percent = round((float(points_val_local) / float(ref_val)) * 100, 1) if ref_val and points_val_local is not None else None
                    regional_pct = percent
                except Exception:
                    pass

            excluded_synchro = (
                str(category).strip().lower() in ["jugend c", "jugend d"] and
                str(discipline).strip().lower() in ["1m synchro", "3m synchro", "platform synchro", "turm synchro"]
            )

            if regional_qual and not excluded_synchro and regional_pct is not None and regional_pct >= float(regional_threshold):
                regionalteam = "yes"

            update_payload = {
                "JEM": jem,
                "JEM%": safe_numeric(jem_pct),
                "EM": em,
                "EM%": safe_numeric(em_pct),
                "WM": wm,
                "WM%": safe_numeric(wm_pct),
                "NationalTeam": nationalteam,
                "RegionalTeam": regionalteam,
                "AveragePoints": average_points,
                "timestamp": now_str
            }
            db.table_update('compresults', update_payload, id=comp_id)
        st.success("Alle Wettkampfbewertungen wurden neu berechnet!")

    if selected_pisteyear and st.button(f"🔄 Nur PisteYear {selected_pisteyear} neu berechnen"):
        comp_results = fetch_all_rows('compresults')
        df_results = pd.DataFrame(comp_results)
        df_selection = pd.DataFrame(selection_points)
        df_comp = pd.DataFrame(competitions)
        kader_rules = load_kader_threshold_rules()

        updated_count = 0
        total_in_year = 0
        missing_selection_combos = []  # combinations where no selectionpoints exist (after base filter)
        no_threshold_rows = 0  # rows where we have selectionpoints but none for JEM/EM/WM/Regional
        no_regional_ref_rows = 0
        seen_regional_labels = set()
        for _, row in df_results.iterrows():
            comp_id = row["id"]
            sex = resolve_sex_for_compresult(row)
            discipline = row["Discipline"]
            category = row["CategoryStart"]
            points = row["Points"]
            competition_name = row["Competition"]
            national_threshold, regional_threshold = resolve_kader_thresholds(discipline, category, rules=kader_rules)

            comp_row = df_comp[df_comp["Name"] == competition_name]
            comp_row = comp_row.iloc[0] if not comp_row.empty else {}
            piste_year = comp_row.get("PisteYear")
            comp_calendar_year = _extract_comp_calendar_year(comp_row, competition_name)
            if str(piste_year).strip() != str(selected_pisteyear).strip():
                continue

            total_in_year += 1

            # If sex was missing, persist it immediately (needed for selectionpoints matching)
            if sex and _needs_sex_update(row.get('sex')):
                try:
                    db.table_update('compresults', {"sex": sex}, id=comp_id)
                except Exception:
                    pass

            dives = None
            if all(col in df_agedives.columns for col in ['sex', 'category', 'Discipline', 'dives']):
                dives_row = df_agedives[
                    (df_agedives['sex'].astype(str).str.strip().str.lower() == str(sex).strip().lower()) &
                    (df_agedives['category'].astype(str).str.strip().str.lower() == str(category).strip().lower()) &
                    (df_agedives['Discipline'].astype(str).str.strip().str.lower() == str(discipline).strip().lower())
                ]
                dives = dives_row.iloc[0]['dives'] if not dives_row.empty else None

            average_points = None
            try:
                points_val = float(points)
                dives_val = float(dives)
                average_points = points_val / dives_val if dives_val else None
            except Exception:
                average_points = None

            relevant_selection = df_selection[
                (df_selection['sex'].astype(str).str.strip().str.lower() == str(sex).strip().lower()) &
                (df_selection['Discipline'].astype(str).str.strip().str.lower() == str(discipline).strip().lower()) &
                (df_selection['category'].astype(str).str.strip().str.lower() == str(category).strip().lower())
            ]
            if relevant_selection.empty:
                missing_selection_combos.append({
                    "sex": str(sex),
                    "Discipline": str(discipline),
                    "CategoryStart": str(category),
                })

            jem_qual = bool(comp_row.get("qual-JEM", False))
            em_qual = bool(comp_row.get("qual-EM", False))
            wm_qual = bool(comp_row.get("qual-WM", False))
            regional_qual = bool(comp_row.get("qual-Regional", False))

            excluded_synchro = (
                str(category).strip().lower() in ["jugend c", "jugend d"] and
                str(discipline).strip().lower() in ["1m synchro", "3m synchro", "platform synchro", "turm synchro"]
            )

            base_selection = relevant_selection
            if "year" in relevant_selection.columns:
                by_piste = None
                if piste_year not in (None, "", "nan"):
                    by_piste = relevant_selection[
                        relevant_selection["year"].astype(str).str.strip() == str(piste_year).strip()
                    ]
                if by_piste is not None and not by_piste.empty:
                    relevant_selection = by_piste
                elif comp_calendar_year is not None:
                    by_cal = base_selection[
                        base_selection["year"].astype(str).str.strip() == str(comp_calendar_year).strip()
                    ]
                    if not by_cal.empty:
                        relevant_selection = by_cal

            comp_col = _comp_label_col(relevant_selection)
            jem_row = relevant_selection[comp_col == "jem"]
            em_row = relevant_selection[comp_col == "em"]
            wm_row = relevant_selection[comp_col == "wm"]
            is_regional = comp_col.isin(["regional", "regionalteam", "regional team", "regio"]) | comp_col.str.contains("reg", na=False)
            regional_row = relevant_selection[is_regional]

            if not relevant_selection.empty:
                for lbl in comp_col[is_regional].dropna().unique().tolist():
                    seen_regional_labels.add(str(lbl))

            if relevant_selection.empty:
                # already counted by missing_selection_combos
                pass
            elif regional_qual and not excluded_synchro and regional_row.empty and jem_row.empty:
                no_regional_ref_rows += 1

            if (not relevant_selection.empty) and jem_row.empty and em_row.empty and wm_row.empty and regional_row.empty:
                no_threshold_rows += 1

            try:
                points_float = float(points)
            except Exception:
                points_float = None

            if points_float is None:
                continue

            jem, jem_pct, jem_nt = get_status(jem_row, jem_qual, points_float, national_threshold)
            em, em_pct, em_nt = get_status(em_row, em_qual, points_float, national_threshold)
            wm, wm_pct, wm_nt = get_status(wm_row, wm_qual, points_float, national_threshold)
            nationalteam = "yes" if "yes" in [jem_nt, em_nt, wm_nt] else "no"

            # RegionalTeam-Berechnung
            regional_pct = None
            regionalteam = "no"
            regional_ref_row = regional_row if not regional_row.empty else jem_row
            if not regional_ref_row.empty and 'points' in regional_ref_row.columns:
                try:
                    ref_val = safe_numeric(regional_ref_row.iloc[0].get('points'))
                    points_val_local = safe_numeric(points)
                    percent = round((float(points_val_local) / float(ref_val)) * 100, 1) if ref_val and points_val_local is not None else None
                    regional_pct = percent
                except Exception:
                    pass

            if regional_qual and not excluded_synchro and regional_pct is not None and regional_pct >= float(regional_threshold):
                regionalteam = "yes"

            update_payload = {
                "JEM": jem,
                "JEM%": safe_numeric(jem_pct),
                "EM": em,
                "EM%": safe_numeric(em_pct),
                "WM": wm,
                "WM%": safe_numeric(wm_pct),
                "NationalTeam": nationalteam,
                "RegionalTeam": regionalteam,
                "AveragePoints": average_points,
                "timestamp": now_str
            }
            db.table_update('compresults', update_payload, id=comp_id)
            updated_count += 1

        st.success(f"✅ {updated_count} Resultate für PisteYear {selected_pisteyear} wurden neu berechnet.")
        st.info(
            f"Diagnose: total in PisteYear={selected_pisteyear}: {total_in_year} | "
            f"ohne selectionpoints-Match: {len(missing_selection_combos)} | "
            f"selectionpoints vorhanden aber keine JEM/EM/WM/Regional-Zeile: {no_threshold_rows} | "
            f"Regional qualifiziert (nicht Synchro C/D), aber ohne Regional- und ohne JEM-Referenz: {no_regional_ref_rows}"
        )
        if seen_regional_labels:
            st.info("Gefundene selectionpoints-Competition Labels für Regional: " + ", ".join(sorted(seen_regional_labels)))
        if missing_selection_combos:
            df_missing = pd.DataFrame(missing_selection_combos)
            df_missing = df_missing.drop_duplicates().sort_values(["sex", "Discipline", "CategoryStart"])
            st.warning("Für diese (sex/Discipline/CategoryStart) Kombinationen gibt es keine passenden selectionpoints → NationalTeam/RegionalTeam bleibt immer 'no'.")
            st.dataframe(df_missing)

    if st.button("🔄 Nur neue Einträge berechnen"):
        comp_results = fetch_all_rows('compresults')
        df_results = pd.DataFrame([r for r in comp_results if not r.get("timestamp")])
        df_selection = pd.DataFrame(selection_points)
        df_comp = pd.DataFrame(competitions)
        kader_rules = load_kader_threshold_rules()

        for _, row in df_results.iterrows():
            comp_id = row["id"]
            sex = resolve_sex_for_compresult(row)
            if sex and _needs_sex_update(row.get('sex')):
                try:
                    db.table_update('compresults', {"sex": sex}, id=comp_id)
                except Exception:
                    pass

            discipline = row["Discipline"]
            category = row["CategoryStart"]
            points = row["Points"]
            competition_name = row["Competition"]
            national_threshold, regional_threshold = resolve_kader_thresholds(discipline, category, rules=kader_rules)

            dives = None
            if all(col in df_agedives.columns for col in ['sex', 'category', 'Discipline', 'dives']):
                dives_row = df_agedives[
                    (df_agedives['sex'].astype(str).str.strip().str.lower() == str(sex).strip().lower()) &
                    (df_agedives['category'].astype(str).str.strip().str.lower() == str(category).strip().lower()) &
                    (df_agedives['Discipline'].astype(str).str.strip().str.lower() == str(discipline).strip().lower())
                ]
                dives = dives_row.iloc[0]['dives'] if not dives_row.empty else None

            average_points = None
            try:
                points_val = float(points)
                dives_val = float(dives)
                average_points = points_val / dives_val if dives_val else None
            except Exception:
                average_points = None

            comp_row = df_comp[df_comp["Name"] == competition_name]
            comp_row = comp_row.iloc[0] if not comp_row.empty else {}

            piste_year = comp_row.get("PisteYear")
            comp_calendar_year = _extract_comp_calendar_year(comp_row, competition_name)

            relevant_selection = df_selection[
                (df_selection['sex'].astype(str).str.strip().str.lower() == str(sex).strip().lower()) &
                (df_selection['Discipline'].astype(str).str.strip().str.lower() == str(discipline).strip().lower()) &
                (df_selection['category'].astype(str).str.strip().str.lower() == str(category).strip().lower())
            ]
            base_selection = relevant_selection
            if "year" in relevant_selection.columns:
                by_piste = None
                if piste_year not in (None, "", "nan"):
                    by_piste = relevant_selection[
                        relevant_selection["year"].astype(str).str.strip() == str(piste_year).strip()
                    ]
                if by_piste is not None and not by_piste.empty:
                    relevant_selection = by_piste
                elif comp_calendar_year is not None:
                    by_cal = base_selection[
                        base_selection["year"].astype(str).str.strip() == str(comp_calendar_year).strip()
                    ]
                    if not by_cal.empty:
                        relevant_selection = by_cal

            comp_col = _comp_label_col(relevant_selection)
            jem_row = relevant_selection[comp_col == "jem"]
            em_row = relevant_selection[comp_col == "em"]
            wm_row = relevant_selection[comp_col == "wm"]
            is_regional = comp_col.isin(["regional", "regionalteam", "regional team", "regio"]) | comp_col.str.contains("reg", na=False)
            regional_row = relevant_selection[is_regional]

            jem_qual = bool(comp_row.get("qual-JEM", False))
            em_qual = bool(comp_row.get("qual-EM", False))
            wm_qual = bool(comp_row.get("qual-WM", False))
            regional_qual = bool(comp_row.get("qual-Regional", False))

            jem, jem_pct, jem_nt = get_status(jem_row, jem_qual, points, national_threshold)
            em, em_pct, em_nt = get_status(em_row, em_qual, points, national_threshold)
            wm, wm_pct, wm_nt = get_status(wm_row, wm_qual, points, national_threshold)

            nationalteam = "yes" if "yes" in [jem_nt, em_nt, wm_nt] else "no"

            # RegionalTeam-Berechnung
            regional_pct = None
            regionalteam = "no"
            regional_ref_row = regional_row if not regional_row.empty else jem_row
            if not regional_ref_row.empty and 'points' in regional_ref_row.columns:
                try:
                    ref_val = safe_numeric(regional_ref_row.iloc[0].get('points'))
                    points_val_local = safe_numeric(points)
                    percent = round((float(points_val_local) / float(ref_val)) * 100, 1) if ref_val and points_val_local is not None else None
                    regional_pct = percent
                except Exception:
                    pass

            excluded_synchro = (
                str(category).strip().lower() in ["jugend c", "jugend d"] and
                str(discipline).strip().lower() in ["1m synchro", "3m synchro", "platform synchro", "turm synchro"]
            )

            if regional_qual and not excluded_synchro and regional_pct is not None and regional_pct >= float(regional_threshold):
                regionalteam = "yes"

            update_payload = {
                "JEM": jem,
                "JEM%": safe_numeric(jem_pct),
                "EM": em,
                "EM%": safe_numeric(em_pct),
                "WM": wm,
                "WM%": safe_numeric(wm_pct),
                "NationalTeam": nationalteam,
                "RegionalTeam": regionalteam,
                "AveragePoints": average_points,
                "timestamp": now_str
            }
            db.table_update('compresults', update_payload, id=comp_id)
        st.success("Neue Einträge wurden berechnet!")

    # TESTTOOL: Timestamps zurücksetzen
    with st.expander("🧪 Test-Tools"):
        if st.button("❌ Alle Timestamps in compresults zurücksetzen"):
            try:
                comp_results = fetch_all_rows("compresults")
                for row in comp_results:
                    db.table_update('compresults', {"timestamp": None}, id=row["id"])
                st.success("Alle Timestamps wurden zurückgesetzt.")
            except Exception as e:
                st.error(f"Fehler beim Zurücksetzen: {e}")


def auswertung_wettkampf():
    st.header("🏅 Wettkampfauswertungen")

    # Button zur Bewertungsseite
    if st.button("🔄 Zu Wettkampf-Bewertung"):
        st.session_state["page"] = "Wettkampf-Bewertung"
        st.rerun()

    comp_results = fetch_all_rows("compresults")
    if not comp_results:
        st.info("Keine Wettkampfergebnisse vorhanden.")
        return
    df_output = pd.DataFrame(comp_results)

    # PisteYear aus competitions holen und mappen (Competition -> PisteYear)
    competitions = fetch_all_rows('competitions', select='Name, PisteYear')
    comp_year_map = {
        str(c.get('Name')).strip(): c.get('PisteYear')
        for c in competitions
        if c.get('Name')
    }
    if "Competition" in df_output.columns:
        df_output["PisteYear"] = df_output["Competition"].map(comp_year_map)
    elif "PisteYear" not in df_output.columns:
        df_output["PisteYear"] = None

    # Filter für die wichtigsten Felder
    with st.expander("🔎 Filter anzeigen"):
        first_name_filter = st.text_input("Vorname (Teilstring möglich)", "")
        last_name_filter = st.text_input("Nachname (Teilstring möglich)", "")
        competition_filter = st.multiselect("Wettkampf (Competition)", sorted(df_output["Competition"].dropna().unique()))
        pisteyear_filter = st.multiselect("PisteYear", sorted(df_output["PisteYear"].dropna().unique().tolist()))
        discipline_filter = st.multiselect("Disziplin", sorted(df_output["Discipline"].dropna().unique()))
        category_filter = st.multiselect("Kategorie", sorted(df_output["CategoryStart"].dropna().unique()))
        sex_filter = st.multiselect("Geschlecht", sorted(df_output["sex"].dropna().unique()))
        prefin_filter = st.multiselect("PreFin", sorted(df_output["PreFin"].dropna().unique()))
        jem_yes = st.checkbox("Nur JEM = yes", value=False)
        em_yes = st.checkbox("Nur EM = yes", value=False)
        wm_yes = st.checkbox("Nur WM = yes", value=False)
        nationalteam_yes = st.checkbox("Nur NationalTeam = yes", value=False)
        regionalteam_yes = st.checkbox("Nur RegionalTeam = yes", value=False)

    # Filter anwenden
    filtered = df_output.copy()
    if first_name_filter:
        filtered = filtered[filtered["first_name"].str.contains(first_name_filter, case=False, na=False)]
    if last_name_filter:
        filtered = filtered[filtered["last_name"].str.contains(last_name_filter, case=False, na=False)]
    if competition_filter:
        filtered = filtered[filtered["Competition"].isin(competition_filter)]
    if pisteyear_filter:
        filtered = filtered[filtered["PisteYear"].isin(pisteyear_filter)]
    if discipline_filter:
        filtered = filtered[filtered["Discipline"].isin(discipline_filter)]
    if category_filter:
        filtered = filtered[filtered["CategoryStart"].isin(category_filter)]
    if sex_filter:
        filtered = filtered[filtered["sex"].isin(sex_filter)]
    if prefin_filter:
        filtered = filtered[filtered["PreFin"].isin(prefin_filter)]
    if jem_yes:
        filtered = filtered[filtered["JEM"] == "yes"]
    if em_yes:
        filtered = filtered[filtered["EM"] == "yes"]
    if wm_yes:
        filtered = filtered[filtered["WM"] == "yes"]
    if nationalteam_yes:
        filtered = filtered[filtered["NationalTeam"] == "yes"]
    if regionalteam_yes:
        filtered = filtered[filtered["RegionalTeam"] == "yes"]

    st.dataframe(filtered)
    st.download_button("📥 Gefilterte Ergebnisse als CSV", filtered.to_csv(index=False, encoding='utf-8-sig'),
                    file_name="wettkampfauswertung_gefilt.csv", mime="text/csv")

    import io
    excel_buffer = io.BytesIO()
    filtered.to_excel(excel_buffer, index=False, engine='openpyxl')
    excel_buffer.seek(0)
    st.download_button(
        "📥 Gefilterte Ergebnisse als Excel",
        excel_buffer,
        file_name="wettkampfauswertung_gefilt.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def manage_compresults_entry():
    st.header("🏅 Wettkampfresultate eingeben")

    st.caption("Wettkämpfe können direkt hier oder unter 'Referenz- und Bewertungstabellen' bearbeitet werden.")
    st.caption("Synchro unterstützt Paar-Erfassung: weiblich, männlich und mixed (1x weiblich + 1x männlich).")
    col_jump, col_inline = st.columns([1, 2])
    with col_jump:
        if st.button("⚙️ Zu Wettkämpfe-Tabelle", key="goto_competitions_table"):
            st.session_state["page"] = "Referenz- und Bewertungstabellen"
            st.rerun()
    with col_inline:
        show_inline_comp_editor = st.checkbox("Wettkämpfe hier bearbeiten", value=False, key="show_inline_comp_editor")

    if show_inline_comp_editor:
        st.subheader("🏟️ Wettkämpfe bearbeiten")
        competitions_inline = fetch_all_rows("competitions", select="*")
        df_comp_inline = pd.DataFrame(competitions_inline)
        comp_cols = [
            "id",
            "Name",
            "Date",
            "PisteYear",
            "Type",
            "qual-Regional",
            "qual-National",
            "qual-JEM",
            "qual-EM",
            "qual-WM",
            "qual-Piste",
        ]
        for c in comp_cols:
            if c not in df_comp_inline.columns:
                df_comp_inline[c] = None
        if not df_comp_inline.empty:
            df_comp_inline = df_comp_inline.sort_values(["Date", "Name"], na_position="last")

        editable_comp = df_comp_inline[comp_cols].copy().reset_index(drop=True)
        edited_comp = st.data_editor(
            editable_comp,
            hide_index=True,
            num_rows="dynamic",
            disabled=["id"],
            key="inline_competitions_editor",
        )

        if st.button("💾 Wettkämpfe speichern", key="save_inline_competitions"):
            def _norm_comp_value(v):
                if pd.isna(v):
                    return None
                if isinstance(v, pd.Timestamp):
                    return v.date().isoformat()
                if isinstance(v, datetime.datetime):
                    return v.date().isoformat()
                if isinstance(v, datetime.date):
                    return v.isoformat()
                if isinstance(v, str):
                    s = v.strip()
                    return s if s else None
                return v

            orig = editable_comp.copy()
            new = edited_comp.copy()
            orig["id"] = orig["id"].apply(lambda x: None if pd.isna(x) else str(x))
            new["id"] = new["id"].apply(lambda x: None if pd.isna(x) else str(x))

            orig_name_by_id = {}
            if "Name" in orig.columns:
                for _, orig_row in orig.iterrows():
                    rid = orig_row.get("id")
                    if rid:
                        name_val = _norm_comp_value(orig_row.get("Name"))
                        orig_name_by_id[str(rid)] = str(name_val or "").strip()

            orig_ids = {v for v in orig["id"].tolist() if v}
            new_ids = {v for v in new["id"].tolist() if v}

            for del_id in sorted(orig_ids - new_ids):
                db.table_delete("competitions", id=int(del_id))

            int_existing = []
            for v in orig_ids:
                try:
                    int_existing.append(int(v))
                except Exception:
                    pass
            next_id = (max(int_existing) + 1) if int_existing else 1

            persist_cols = [c for c in comp_cols if c != "id"]
            cascade_compresults_total = 0
            cascade_ref_total = 0
            for _, row in new.iterrows():
                row_id = row.get("id")
                payload = {c: _norm_comp_value(row.get(c)) for c in persist_cols}
                payload = {k: v for k, v in payload.items() if v is not None}

                if not payload:
                    continue

                if not row_id:
                    while str(next_id) in orig_ids:
                        next_id += 1
                    payload["id"] = next_id
                    db.table_insert("competitions", payload)
                    orig_ids.add(str(next_id))
                    next_id += 1
                else:
                    db.table_update("competitions", payload, id=int(row_id))

                    old_name = orig_name_by_id.get(str(row_id), "")
                    new_name = str(_norm_comp_value(row.get("Name")) or "").strip()
                    if old_name and new_name and old_name.lower() != new_name.lower():
                        cascade_counts = cascade_competition_rename(old_name, new_name)
                        cascade_compresults_total += cascade_counts["compresults"]
                        cascade_ref_total += cascade_counts["pisterefcompresults"]

            st.success(
                f"Wettkämpfe gespeichert. Verknüpfungen aktualisiert: "
                f"compresults={cascade_compresults_total}, "
                f"pisterefcompresults={cascade_ref_total}."
            )
            st.rerun()

    # --- Neuer Wettkampf anlegen ---
    if "show_new_comp_form" not in st.session_state:
        st.session_state["show_new_comp_form"] = False

    if st.button("➕ Neuer Wettkampf aufnehmen", key="show_new_comp_form_btn"):
        st.session_state["show_new_comp_form"] = True

    if st.session_state.get("show_new_comp_form", False):
        st.subheader("Neuen Wettkampf anlegen")
        comp_name = st.text_input("Name", key="comp_name_field")
        comp_date = st.date_input("Datum", key="comp_date_field")
        try:
            default_year = comp_date.year
        except Exception:
            default_year = datetime.date.today().year
        qual_regional = st.checkbox("qual-Regional", key="qual_regional_field")
        qual_national = st.checkbox("qual-National", key="qual_national_field")
        qual_jem = st.checkbox("qual-JEM", key="qual_jem_field")
        qual_em = st.checkbox("qual-EM", key="qual_em_field")
        qual_wm = st.checkbox("qual-WM", key="qual_wm_field")
        qual_piste = st.checkbox("qual-Piste", key="qual_piste_field")
        comp_type = st.selectbox("Type", ["National", "Regional", "International"], key="comp_type_field")
        piste_year = st.number_input("PisteYear", min_value=2000, max_value=2100, value=default_year, key="piste_year_field")

        if st.button("💾 Wettkampf speichern", key="save_competition"):
            if not comp_name:
                st.error("Bitte einen Namen eingeben.")
            else:
                db.table_insert("competitions", {
                    "Name": comp_name,
                    "Date": comp_date.strftime("%Y-%m-%d"),
                    "qual-Regional": qual_regional,
                    "qual-National": qual_national,
                    "qual-JEM": qual_jem,
                    "qual-EM": qual_em,
                    "qual-WM": qual_wm,
                    "qual-Piste": qual_piste,
                    "Type": comp_type,
                    "PisteYear": int(piste_year)
                })
                st.success("Wettkampf gespeichert!")
                st.session_state["show_new_comp_form"] = False
        st.stop()

    # --- Athleten und Wettkämpfe laden ---
    athletes = fetch_all_rows('athletes', select='id, first_name, last_name, sex')

    competitions = fetch_all_rows('competitions', select='Name, Date, PisteYear, [qual-Regional], [qual-JEM], [qual-EM], [qual-WM]')
    competition_names = [c['Name'] for c in competitions]
    selected_competition = st.selectbox("Wettkampf", competition_names)

    selectionpoints = fetch_all_rows('selectionpoints')
    selectionpoints_df = pd.DataFrame(selectionpoints)
    competitions_df = pd.DataFrame(competitions)

    discipline = st.selectbox(
        "Disziplin",
        [
            "1m",
            "3m",
            "platform",
            "3m synchro",
            "platform synchro",
            "high diving",
            "high diving 20m",
            "high diving 27m",
        ],
    )
    is_synchro = discipline in ["3m synchro", "platform synchro"]

    # --- Synchro: Modus (gleich / mixed) ---
    if is_synchro:
        synchro_mode = st.radio(
            "Synchro Modus",
            ["weiblich (Pair)", "männlich (Pair)", "mixed (1 weiblich + 1 männlich)"],
            horizontal=True,
            key="synchro_mode_radio",
        )
        is_mixed = "mixed" in synchro_mode
        female_names = {f"{a['first_name']} {a['last_name']}": a for a in athletes if _normalize_sex_value(a.get('sex')) == 'female'}
        male_names = {f"{a['first_name']} {a['last_name']}": a for a in athletes if _normalize_sex_value(a.get('sex')) == 'male'}

        if is_mixed:
            st.info("Mixed Synchro: 1 weibliche + 1 männliche Athletin/Athlet. Beide Ergebnisse werden mit sex='mixed' gespeichert.")
            selected_female = st.selectbox("Athletin (weiblich)", list(female_names.keys()), key="synchro_female_sel")
            selected_male = st.selectbox("Athlet (männlich)", list(male_names.keys()), key="synchro_male_sel")
            synchro_athletes = [female_names.get(selected_female), male_names.get(selected_male)]
            sex_to_save = "mixed"
        elif "weiblich" in synchro_mode:
            selected_ath1 = st.selectbox("Athletin 1 (weiblich)", list(female_names.keys()), key="synchro_f1_sel")
            selected_ath2 = st.selectbox("Athletin 2 (weiblich)", list(female_names.keys()), key="synchro_f2_sel")
            synchro_athletes = [female_names.get(selected_ath1), female_names.get(selected_ath2)]
            sex_to_save = "female"
        else:
            selected_ath1 = st.selectbox("Athlet 1 (männlich)", list(male_names.keys()), key="synchro_m1_sel")
            selected_ath2 = st.selectbox("Athlet 2 (männlich)", list(male_names.keys()), key="synchro_m2_sel")
            synchro_athletes = [male_names.get(selected_ath1), male_names.get(selected_ath2)]
            sex_to_save = "male"
        athlete_data = None
    else:
        is_mixed = False
        synchro_athletes = []
        sex_to_save = None
        athlete_names = {f"{a['first_name']} {a['last_name']}": a for a in athletes}
        selected_athlete = st.selectbox("Athlet", list(athlete_names.keys()))
        athlete_data = athlete_names[selected_athlete] if selected_athlete else None
        if athlete_data:
            sex_to_save = athlete_data['sex']

    category_start = st.selectbox("Kategorie", ["Jugend A", "Jugend B", "Jugend C", "Jugend D", "Elite"])
    prefin = st.selectbox("PreFin", ["FinalOnly", "Preliminary", "Final"])
    points = st.number_input("Punkte", min_value=0.0, step=0.1, format="%.2f")
    difficulty = st.number_input("Difficulty", min_value=0.0, step=0.1, format="%.2f")

    if st.button("💾 Ergebnis speichern"):
        if is_synchro:
            valid_athletes = [a for a in synchro_athletes if a]
            if len(valid_athletes) < 2:
                st.error("Bitte beide Athleten auswählen.")
            else:
                team_flags = compute_compresult_team_flags(
                    competition_name=selected_competition,
                    sex=sex_to_save,
                    discipline=discipline,
                    category_start=category_start,
                    points=points,
                    competitions_df=competitions_df,
                    selectionpoints_df=selectionpoints_df,
                )
                for ath in valid_athletes:
                    db.table_insert('compresults', {
                        "first_name": ath['first_name'],
                        "last_name": ath['last_name'],
                        "sex": sex_to_save,
                        "Competition": selected_competition,
                        "Discipline": discipline,
                        "CategoryStart": category_start,
                        "PreFin": prefin,
                        "Points": points,
                        "Difficulty": difficulty,
                        **team_flags,
                    })
                label = "Mixed-Paar" if is_mixed else "Synchro-Paar"
                st.success(f"Wettkampfresultat für {label} gespeichert (2 Einträge)!")
        elif athlete_data:
            team_flags = compute_compresult_team_flags(
                competition_name=selected_competition,
                sex=athlete_data['sex'],
                discipline=discipline,
                category_start=category_start,
                points=points,
                competitions_df=competitions_df,
                selectionpoints_df=selectionpoints_df,
            )
            db.table_insert('compresults', {
                "first_name": athlete_data['first_name'],
                "last_name": athlete_data['last_name'],
                "sex": athlete_data['sex'],
                "Competition": selected_competition,
                "Discipline": discipline,
                "CategoryStart": category_start,
                "PreFin": prefin,
                "Points": points,
                "Difficulty": difficulty,
                **team_flags,
            })
            st.success("Wettkampfresultat gespeichert!")

    st.markdown("---")
    st.subheader("📤 Ergebnisse per Datei importieren")

    # Beispiel-Datei
    example_data = {
        "first_name": ["Max"],
        "last_name": ["Mustermann"],
        "Competition": [competition_names[0] if competition_names else ""],
        "Discipline": ["1m"],
        "CategoryStart": ["Jugend B"],
        "PreFin": ["FinalOnly"],
        "Points": [350.5],
        "Difficulty": [2.8]
    }
    example_df = pd.DataFrame(example_data)
    st.download_button("📄 Beispiel-Datei herunterladen", example_df.to_csv(index=False).encode("utf-8"), file_name="beispiel_wettkampfresultate.csv", mime="text/csv")

    uploaded_file = st.file_uploader("CSV-Datei mit Wettkampfresultaten hochladen", type=["csv"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        required_cols = ["first_name", "last_name", "Competition", "Discipline", "CategoryStart", "PreFin", "Points", "Difficulty"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_cols)}")
            return

        inserted = 0
        skipped = []
        for _, row in df.iterrows():
            first = str(row["first_name"]).strip()
            last = str(row["last_name"]).strip()
            athlete = next((a for a in athletes if a["first_name"] == first and a["last_name"] == last), None)
            if not athlete:
                skipped.append({"first_name": first, "last_name": last})
                continue
            try:
                team_flags = compute_compresult_team_flags(
                    competition_name=row["Competition"],
                    sex=athlete["sex"],
                    discipline=row["Discipline"],
                    category_start=row["CategoryStart"],
                    points=row["Points"],
                    competitions_df=competitions_df,
                    selectionpoints_df=selectionpoints_df,
                )
                db.table_insert('compresults', {
                    "first_name": first,
                    "last_name": last,
                    "sex": athlete["sex"],
                    "Competition": row["Competition"],
                    "Discipline": row["Discipline"],
                    "CategoryStart": row["CategoryStart"],
                    "PreFin": row["PreFin"],
                    "Points": row["Points"],
                    "Difficulty": row["Difficulty"],
                    **team_flags,
                })
                inserted += 1
            except Exception as e:
                st.warning(f"Fehler bei {first} {last}: {e}")
        st.success(f"✅ {inserted} Resultate importiert.")
        if skipped:
            st.warning("Folgende Athleten wurden nicht gefunden:")
            st.dataframe(pd.DataFrame(skipped))

    st.markdown("---")
    st.subheader("Import DiveLive")

    # Beispiel-Datei (DiveLive)
    sample_divelive = pd.DataFrame(
        {
            "Category": ["Jugend B"],
            "gender": ["female"],
            "event_height": ["3"],
            "total_award": ["350.50"],
            "firstname": ["Max"],
            "lastname": ["Mustermann"],
        }
    )
    st.download_button(
        "📄 Beispiel DiveLive CSV herunterladen",
        data=sample_divelive.to_csv(index=False).encode("utf-8-sig"),
        file_name="divelive_beispiel.csv",
        mime="text/csv",
        key="divelive_sample_download",
    )

    if not competition_names:
        st.warning("Keine Wettkämpfe in der Tabelle competitions vorhanden. Bitte zuerst einen Wettkampf anlegen.")
        return

    selected_competition_divelive = st.selectbox(
        "Wettkampf für DiveLive Import",
        competition_names,
        index=competition_names.index(selected_competition) if selected_competition in competition_names else 0,
        key="divelive_selected_competition",
    )

    divelive_file = st.file_uploader(
        "DiveLive CSV-Datei hochladen",
        type=["csv"],
        key="divelive_compresults_uploader",
    )

    def _normalize_divelive_discipline(value: str, category: str = "") -> str:
        s = str(value or "").strip().lower()
        cat = str(category or "").strip().lower()
        if s == "":
            return ""
        if "high" in s or "20m" in s or "27m" in s:
            if "27" in s:
                return "high diving 27m"
            if "20" in s:
                return "high diving 20m"
            if cat in ["jugend a", "jugend b"]:
                return "high diving"
            return "high diving"
        if "platform" in s or "tower" in s or "turm" in s:
            return "platform"
        if s.startswith("1"):
            return "1m"
        if s.startswith("3"):
            return "3m"
        return str(value).strip()

    def _safe_float_import(x):
        try:
            if x in (None, "", "nan"):
                return None
            if isinstance(x, str):
                s = x.strip().replace("%", "").replace(",", ".").strip()
                if s == "":
                    return None
                return float(s)
            return float(x)
        except Exception:
            return None

    if divelive_file is not None:
        if st.button("Import DiveLive", key="import_divelive_btn"):
            try:
                try:
                    divelive_file.seek(0)
                except Exception:
                    pass

                try:
                    df_dl = pd.read_csv(divelive_file, sep=None, engine="python", encoding="utf-8-sig")
                except TypeError:
                    df_dl = pd.read_csv(divelive_file, sep=None, engine="python")

                cols_by_lower = {str(c).strip().lower(): c for c in df_dl.columns}
                required_src = ["category", "gender", "event_height", "total_award", "firstname", "lastname"]
                missing = [c for c in required_src if c not in cols_by_lower]
                if missing:
                    st.error(f"❌ DiveLive CSV muss folgende Spalten enthalten: {', '.join(required_src)}")
                    st.info(f"Fehlend: {', '.join(missing)}")
                    return

                # lookup for optional sex fallback
                athlete_lookup = {
                    (str(a.get("first_name", "")).strip().lower(), str(a.get("last_name", "")).strip().lower()): a
                    for a in athletes
                }

                inserted_dl = 0
                skipped_dl = []

                for _, row in df_dl.iterrows():
                    try:
                        first = str(row[cols_by_lower["firstname"]]).strip()
                        last = str(row[cols_by_lower["lastname"]]).strip()
                        if first.lower() in ("", "nan") or last.lower() in ("", "nan"):
                            skipped_dl.append({"first_name": first, "last_name": last, "reason": "Vor-/Nachname fehlt"})
                            continue

                        athlete = athlete_lookup.get((first.lower(), last.lower()))
                        if not athlete:
                            skipped_dl.append({"first_name": first, "last_name": last, "reason": "Athlet nicht in athletes gefunden"})
                            continue

                        category = str(row[cols_by_lower["category"]]).strip()
                        if category.lower() in ("", "nan"):
                            skipped_dl.append({"first_name": first, "last_name": last, "reason": "Category fehlt"})
                            continue

                        discipline_val = _normalize_divelive_discipline(row[cols_by_lower["event_height"]], category=category)
                        if str(discipline_val).strip() == "":
                            skipped_dl.append({"first_name": first, "last_name": last, "reason": "event_height/Discipline fehlt"})
                            continue

                        points_val = _safe_float_import(row[cols_by_lower["total_award"]])
                        if points_val is None:
                            skipped_dl.append({"first_name": first, "last_name": last, "reason": "total_award/Points leer/ungültig"})
                            continue

                        sex_val = _normalize_sex_value(row[cols_by_lower["gender"]])
                        if not sex_val:
                            sex_val = _normalize_sex_value(athlete.get("sex"))

                        # Team-Flags berechnen (falls möglich) – Import soll nie komplett abstürzen
                        team_flags = {"NationalTeam": "no", "RegionalTeam": "no"}
                        try:
                            if sex_val:
                                team_flags = compute_compresult_team_flags(
                                    competition_name=selected_competition_divelive,
                                    sex=sex_val,
                                    discipline=discipline_val,
                                    category_start=category,
                                    points=points_val,
                                    competitions_df=competitions_df,
                                    selectionpoints_df=selectionpoints_df,
                                )
                        except Exception as e:
                            skipped_dl.append({"first_name": first, "last_name": last, "reason": f"Team-Flags Fehler: {e}"})

                        db.table_insert('compresults', {
                            "first_name": first,
                            "last_name": last,
                            "sex": sex_val,
                            "Competition": selected_competition_divelive,
                            "Discipline": discipline_val,
                            "CategoryStart": category,
                            "PreFin": "FinalOnly",
                            "Points": points_val,
                            "Difficulty": 0.0,
                            **team_flags,
                        })
                        inserted_dl += 1
                    except Exception as e:
                        skipped_dl.append({"first_name": first if 'first' in locals() else "", "last_name": last if 'last' in locals() else "", "reason": f"Import Fehler: {e}"})

                st.success(f"✅ {inserted_dl} DiveLive Resultate importiert (Wettkampf: {selected_competition_divelive}).")
                if skipped_dl:
                    st.warning("Einige Zeilen wurden übersprungen:")
                    st.dataframe(pd.DataFrame(skipped_dl))
            except Exception as e:
                st.error(f"❌ Import fehlgeschlagen: {e}")

def manage_compresults_correction():
    st.header("🛠️ Wettkampfresultate korrigieren")

    comp_results = fetch_all_rows("compresults", select="*")
    if not comp_results:
        st.info("Keine Wettkampfresultate vorhanden.")
        return

    df = pd.DataFrame(comp_results)
    required_cols = ["id", "first_name", "last_name", "sex", "Competition", "Discipline", "CategoryStart", "PreFin", "Points", "Difficulty"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    competitions = sorted(
        {
            str(c).strip()
            for c in df["Competition"].dropna().tolist()
            if str(c).strip() and str(c).strip().lower() != "nan"
        }
    )
    if not competitions:
        st.info("Keine Wettkämpfe in compresults gefunden.")
        return

    selected_competition = st.selectbox("Wettkampf", [""] + competitions, index=0)
    if not selected_competition:
        st.info("Bitte zuerst einen Wettkampf auswählen.")
        return

    df_comp = df[df["Competition"].astype(str).str.strip() == selected_competition].copy()
    if df_comp.empty:
        st.info("Keine Resultate für den gewählten Wettkampf gefunden.")
        return

    df_comp["athlete_label"] = (
        df_comp["first_name"].fillna("").astype(str).str.strip()
        + " "
        + df_comp["last_name"].fillna("").astype(str).str.strip()
    ).str.strip()

    athletes = sorted(
        {
            str(a).strip()
            for a in df_comp["athlete_label"].dropna().tolist()
            if str(a).strip() and str(a).strip().lower() != "nan"
        }
    )
    if not athletes:
        st.info("Keine Athleten für den gewählten Wettkampf gefunden.")
        return

    selected_athlete = st.selectbox("Athlet", [""] + athletes, index=0)
    if not selected_athlete:
        st.info("Bitte zuerst einen Athleten auswählen.")
        return

    df_ath = df_comp[df_comp["athlete_label"] == selected_athlete].copy()
    if df_ath.empty:
        st.info("Keine Resultate für den gewählten Athleten gefunden.")
        return

    disciplines = sorted(
        {
            str(d).strip()
            for d in df_ath["Discipline"].dropna().tolist()
            if str(d).strip() and str(d).strip().lower() != "nan"
        }
    )
    if not disciplines:
        st.info("Keine Disziplinen für den gewählten Athleten gefunden.")
        return

    selected_discipline = st.selectbox("Disziplin (aktueller Eintrag)", disciplines)
    df_target = df_ath[df_ath["Discipline"].astype(str).str.strip() == selected_discipline].copy()
    if df_target.empty:
        st.info("Kein passender Eintrag gefunden.")
        return

    if len(df_target) > 1:
        row_options = []
        for _, row in df_target.iterrows():
            row_options.append(
                f"id={row.get('id')} | PreFin={row.get('PreFin')} | Punkte={row.get('Points')} | Difficulty={row.get('Difficulty')}"
            )
        selected_row = st.selectbox("Eintrag", row_options)
        selected_id = int(str(selected_row).split("|")[0].replace("id=", "").strip())
        current = df_target[df_target["id"] == selected_id].iloc[0]
    else:
        current = df_target.iloc[0]

    def _safe_float(value, fallback=0.0):
        try:
            if value in (None, "", "nan"):
                return fallback
            return float(value)
        except Exception:
            return fallback

    current_discipline = str(current.get("Discipline") or "").strip()
    current_category = str(current.get("CategoryStart") or "").strip()
    current_prefin = str(current.get("PreFin") or "").strip()
    current_points = _safe_float(current.get("Points"), 0.0)
    current_difficulty = _safe_float(current.get("Difficulty"), 0.0)

    all_discipline_values = sorted(
        {
            str(d).strip()
            for d in df["Discipline"].dropna().tolist()
            if str(d).strip() and str(d).strip().lower() != "nan"
        }
    )
    discipline_options = sorted(
        set(
            [
                "1m",
                "3m",
                "platform",
                "3m synchro",
                "platform synchro",
                "high diving",
                "high diving 20m",
                "high diving 27m",
            ]
            + all_discipline_values
            + [current_discipline]
        )
    )
    category_options = ["Jugend A", "Jugend B", "Jugend C", "Jugend D", "Elite"]
    prefin_options = ["FinalOnly", "Preliminary", "Final"]

    new_discipline = st.selectbox(
        "Neue Disziplin",
        discipline_options,
        index=discipline_options.index(current_discipline) if current_discipline in discipline_options else 0,
    )
    new_category = st.selectbox(
        "Neue Kategorie",
        category_options,
        index=category_options.index(current_category) if current_category in category_options else 0,
    )
    new_prefin = st.selectbox(
        "Neuer PreFin",
        prefin_options,
        index=prefin_options.index(current_prefin) if current_prefin in prefin_options else 0,
    )
    new_points = st.number_input("Neue Punktzahl", min_value=0.0, step=0.1, format="%.2f", value=current_points)
    new_difficulty = st.number_input("Neue Difficulty", min_value=0.0, step=0.1, format="%.2f", value=current_difficulty)
    current_id = int(current["id"])

    st.markdown("---")
    st.caption(f"Aktueller Eintrag: id={current_id}")
    delete_confirmed = st.checkbox(
        "Ich möchte diesen Eintrag dauerhaft löschen",
        key=f"compresult_delete_confirm_{current_id}",
    )
    if st.button("🗑️ Eintrag löschen", key=f"compresult_delete_btn_{current_id}"):
        if not delete_confirmed:
            st.error("Bitte das Löschen zuerst bestätigen.")
        else:
            try:
                db.table_delete("compresults", id=current_id)
                st.success(f"Eintrag id={current_id} wurde gelöscht.")
                st.rerun()
            except Exception as e:
                st.error(f"Löschen fehlgeschlagen: {e}")

    st.markdown("---")

    if st.button("💾 Korrektur speichern"):
        competitions_data = fetch_all_rows('competitions', select='Name, Date, PisteYear, [qual-Regional], [qual-JEM], [qual-EM], [qual-WM]')
        selectionpoints_data = fetch_all_rows('selectionpoints')
        competitions_df = pd.DataFrame(competitions_data)
        selectionpoints_df = pd.DataFrame(selectionpoints_data)

        sex_value = current.get("sex")
        if sex_value in (None, "", "nan"):
            athletes_data = fetch_all_rows("athletes", select="first_name, last_name, sex")
            for athlete in athletes_data:
                if (
                    str(athlete.get("first_name", "")).strip().lower() == str(current.get("first_name", "")).strip().lower()
                    and str(athlete.get("last_name", "")).strip().lower() == str(current.get("last_name", "")).strip().lower()
                ):
                    sex_value = athlete.get("sex")
                    break

        team_flags = {"NationalTeam": "no", "RegionalTeam": "no"}
        if sex_value not in (None, "", "nan"):
            team_flags = compute_compresult_team_flags(
                competition_name=selected_competition,
                sex=sex_value,
                discipline=new_discipline,
                category_start=new_category,
                points=new_points,
                competitions_df=competitions_df,
                selectionpoints_df=selectionpoints_df,
            )

        update_payload = {
            "Discipline": new_discipline,
            "CategoryStart": new_category,
            "PreFin": new_prefin,
            "Points": new_points,
            "Difficulty": new_difficulty,
            "timestamp": None,
            **team_flags,
        }
        db.table_update("compresults", update_payload, id=current_id)
        st.success(f"Eintrag id={current_id} wurde korrigiert. timestamp wurde auf NULL gesetzt.")
        st.rerun()

def safe_numeric(val):
    if val in ("", None):
        return None
    try:
        return float(val.replace("%", "")) if isinstance(val, str) and "%" in val else float(val)
    except Exception:
        return None

def wettkampf_performance_per_athlete():
    """Zeige Wettkampfperformance für einen gefilterten Athleten mit Top-3 Wettkämpfen pro Jahr."""
    def format_optional_number(value, suffix=""):
        if value in ("", None):
            return "-"
        try:
            if isinstance(value, str):
                cleaned = value.replace("%", "").replace(",", ".").strip()
                if cleaned == "":
                    return "-"
                value = float(cleaned)
            else:
                value = float(value)
        except Exception:
            return "-"
        return f"{value:.2f}{suffix}"

    st.header("🏊 Wettkampf-Performance pro Athlet")
    
    # Lade Athleten
    athletes = db.table_select('athletes', 'first_name, last_name')
    athlete_names = {f"{a['first_name']} {a['last_name']}": (a['first_name'], a['last_name']) for a in athletes}
    
    selected_athlete = st.selectbox("Athlet auswählen", sorted(athlete_names.keys()))
    if not selected_athlete:
        st.info("Bitte wählen Sie einen Athleten aus.")
        return
    
    first_name, last_name = athlete_names[selected_athlete]
    
    # Lade pisterefcompresults für diesen Athleten
    results = db.query("""
        SELECT 
            PisteYear,
            competition1, discipline1, points1, reference1, pointsaverage1,
            competition2, discipline2, points2, reference2, pointsaverage2,
            competition3, discipline3, points3, reference3, pointsaverage3,
            refaverage, performance, quality
        FROM pisterefcompresults
        WHERE LTRIM(RTRIM(first_name))=%s AND LTRIM(RTRIM(last_name))=%s
        ORDER BY TRY_CONVERT(int, PisteYear)
    """, (first_name, last_name))
    
    if not results:
        st.warning(f"Keine Wettkampfresultate für {selected_athlete} gefunden.")
        return
    
    st.success(f"✅ {len(results)} Jahre mit Wettkampfresultaten gefunden.")
    
    # Tabelle der Top-3 Wettkämpfe pro Jahr
    st.subheader("📋 Top-3 Wettkämpfe pro Jahr")
    
    table_data = []
    for row in results:
        year = row['PisteYear']
        for slot in [1, 2, 3]:
            comp_key = f'competition{slot}'
            disc_key = f'discipline{slot}'
            pts_key = f'points{slot}'
            ref_key = f'reference{slot}'
            
            comp = row.get(comp_key, '-')
            disc = row.get(disc_key, '-')
            pts = row.get(pts_key, '-')
            ref = row.get(ref_key, '-')
            
            table_data.append({
                'Jahr': year,
                'Slot': slot,
                'Wettkampf': comp if comp else '-',
                'Disziplin': disc if disc else '-',
                'Punkte': pts if pts is not None else '-',
                'Reference': ref if ref is not None else '-'
            })
    
    df_table = pd.DataFrame(table_data)
    st.dataframe(df_table, use_container_width=True)
    
    # Zusammenfassung pro Jahr
    st.subheader("📊 Performance-Zusammenfassung pro Jahr")
    
    summary_data = []
    for row in results:
        year = row['PisteYear']
        refavg = row.get('refaverage')
        perf = row.get('performance')
        quality = row.get('quality')
        
        summary_data.append({
            'Jahr': year,
            'Ref-Durchschnitt': format_optional_number(refavg),
            'Performance (%)': format_optional_number(perf, "%"),
            'Qualität': quality if quality else '-'
        })
    
    df_summary = pd.DataFrame(summary_data)
    st.dataframe(df_summary, use_container_width=True)
    
    # Grafik: Refaverage vs Jahr (Trend)
    st.subheader("📈 Trend: Ref-Durchschnitt über Zeit")
    
    df_trend = pd.DataFrame(results)
    df_trend['PisteYear'] = df_trend['PisteYear'].astype(int)
    df_trend['refaverage'] = pd.to_numeric(df_trend['refaverage'], errors='coerce')
    df_trend = df_trend.dropna(subset=['refaverage'])
    
    if not df_trend.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df_trend['PisteYear'], df_trend['refaverage'], marker='o', linewidth=2, markersize=8, color='#1f77b4', label='Ref-Durchschnitt')
        ax.set_xlabel('Jahr', fontsize=12)
        ax.set_ylabel('Ref-Durchschnitt', fontsize=12)
        ax.set_title(f'Wettkampf-Trend für {selected_athlete}', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        # Xticks auf ganze Jahre setzen
        years_int = sorted(df_trend['PisteYear'].unique())
        ax.set_xticks(years_int)
        
        st.pyplot(fig)
        plt.close()
    else:
        st.warning("Keine Trend-Daten für Grafik verfügbar.")
    
    # Grafik: Points pro Slot pro Jahr
    st.subheader("📊 Top-3 Punkte pro Jahr")
    
    df_points = df_trend.copy()
    df_points['points1'] = pd.to_numeric(df_points['points1'], errors='coerce')
    df_points['points2'] = pd.to_numeric(df_points['points2'], errors='coerce')
    df_points['points3'] = pd.to_numeric(df_points['points3'], errors='coerce')
    
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Filtere Jahre mit mindestens einem Punkt-Wert
    df_points_plot = df_points[df_points[['points1', 'points2', 'points3']].notna().any(axis=1)]
    
    if not df_points_plot.empty:
        x = df_points_plot['PisteYear']
        width = 0.25
        x_pos = range(len(x))
        
        ax.bar([i - width for i in x_pos], df_points_plot['points1'].fillna(0), width, label='1. Wettkampf', color='#2ca02c', alpha=0.8)
        ax.bar([i for i in x_pos], df_points_plot['points2'].fillna(0), width, label='2. Wettkampf', color='#ff7f0e', alpha=0.8)
        ax.bar([i + width for i in x_pos], df_points_plot['points3'].fillna(0), width, label='3. Wettkampf', color='#d62728', alpha=0.8)
        
        ax.set_xlabel('Jahr', fontsize=12)
        ax.set_ylabel('Punkte', fontsize=12)
        ax.set_title(f'Top-3 Punkte-Verteilung für {selected_athlete}', fontsize=14, fontweight='bold')
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        st.pyplot(fig)
        plt.close()
    else:
        st.warning("Keine Punkte-Daten für Grafik verfügbar.")

def piste_refpoint_wettkampf_analyse():
    st.header("📊 Piste RefPoint Wettkampf Analyse")

    agecategories = db.table_select("agecategories", '*')
    agecat_df = pd.DataFrame(agecategories)
    selectionpoints = fetch_all_rows('selectionpoints')
    sel_df = pd.DataFrame(selectionpoints)

    st.info("""
    **Hinweis:**  
    Der Button **"Full Analyse"** berechnet für das angegebene Jahr:
    - die RefPoints (Prozent-Erreichung zum Referenzwert) für alle Wettkampfergebnisse,
    - die Top 3 Wettkämpfe pro Athlet,
    - und die Entwicklung (Vergleich zum Vorjahr), **sofern mindestens für das angegebene Jahr und das Jahr davor Daten vorhanden sind**.
    """)

    years = [str(y) for y in range(2024, 2031)]
    selected_year = st.selectbox("Jahr für Analyse wählen", years)

    if st.button("Full Analyse"):
        st.info("Starte: Berechnen ...")
        selected_year_int = int(selected_year)

        competitions = db.table_select('competitions', 'Name, Date, PisteYear, [qual-Regional], [qual-National]')
        compresults = fetch_all_rows('compresults', select='*')
        athletes = db.table_select('athletes', 'id, vintage, first_name, last_name')
        pisterefcomppoints = db.table_select('pisterefcomppoints', '*')

        comp_qual_lookup = {str(c['Name']).strip().lower(): c for c in competitions}
        athlete_vintage = {a['id']: a['vintage'] for a in athletes}
        athlete_name_lookup = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a['vintage'] for a in athletes}
        refpoints_df = pd.DataFrame(pisterefcomppoints)

        if refpoints_df.empty or "Discipline" not in refpoints_df.columns:
            st.error("❌ Tabelle 'pisterefcomppoints' ist leer oder hat falsche Spalten. Bitte Daten neu importieren (_fix_pisterefcomppoints.py ausführen).")
            return


        updated = 0
        updates = []

        for row in compresults:
            competition_name = str(row.get("Competition", "")).strip().lower()
            comp_row = comp_qual_lookup.get(competition_name, {})
            comp_pisteyear = comp_row.get("PisteYear")

            # Nur Wettkämpfe mit passendem PisteYear verarbeiten!
            if str(comp_pisteyear) != str(selected_year):
                continue

            colname = f"PisteRefPoints{selected_year}%"
            existing_percent = row.get(colname)

            discipline = row.get("Discipline")
            sex = row.get("sex")
            points = row.get("Points")
            comp_date = comp_row.get("Date")
            if comp_date:
                comp_year = int(str(comp_date)[:4])
            else:
                comp_year = comp_row.get("PisteYear") or selected_year_int

            athlete_id = row.get("athlete_id")
            vintage = None
            if athlete_id and athlete_id in athlete_vintage:
                vintage = athlete_vintage[athlete_id]
            else:
                first = row.get("first_name", "").strip().lower()
                last = row.get("last_name", "").strip().lower()
                vintage = athlete_name_lookup.get((first, last))
            if not vintage:
                continue

            try:
                age = int(comp_year) - int(vintage)
            except Exception:
                continue

            if not (8 <= age <= 19):
                continue

            category = str(row.get("CategoryStart", "")).strip().lower()
            if category == "elite":
                continue

            if not (discipline and sex and points):
                continue

            if is_excluded_discipline_local(discipline, age, selected_year, agecat_df):
                continue

            ref_row = refpoints_df[
                (refpoints_df["Discipline"].astype(str).str.strip().str.lower() == str(discipline).lower()) &
                (refpoints_df["sex"].astype(str).str.strip().str.lower() == str(sex).lower())
            ]
            if ref_row.empty or str(age) not in ref_row.columns:
                continue

            ref_value = ref_row.iloc[0][str(age)]
            try:
                ref_value = float(ref_value)
                points_val = float(points)
                percent = round((points_val / ref_value) * 100, 1) if ref_value else None
            except Exception:
                percent = None
                continue

            # Sammle Update für Batch — % bei Änderungen immer neu schreiben
            update_entry = {"id": row["id"]}
            if percent is not None:
                changed = False
                try:
                    old_percent = float(existing_percent) if existing_percent not in (None, "", "nan") else None
                    changed = old_percent is None or abs(old_percent - percent) >= 0.05
                except Exception:
                    changed = True
                if changed:
                    update_entry[colname] = percent
                    updated += 1
            updates.append(update_entry)

            # --- RegionalTeam ---
            discipline_lower = discipline.strip().lower()
            val = comp_row.get("qual-Regional", False)
            regional_qual = bool(val)
            excluded_synchro_regio = (
                category in ["jugend c", "jugend d"] and
                discipline_lower in ["1m synchro", "3m synchro", "platform synchro"]
            )
            if regional_qual and not excluded_synchro_regio and percent is not None and percent >= 70:
                regionalteam = "yes"
            else:
                regionalteam = "no"
            updates[-1]["RegionalTeam"] = regionalteam

            # --- NationalTeam ---
            val_nat = comp_row.get("qual-National", False)
            national_qual = bool(val_nat)
            excluded_synchro_nat = (
                category in ["jugend c", "jugend d"] and
                discipline_lower in ["3m synchro", "turm synchro"]
            )
            percent_nt = None

            if national_qual and not excluded_synchro_nat:
                if category in ["jugend c", "jugend d"]:
                    ref_row_nt = refpoints_df[
                        (refpoints_df["Discipline"].astype(str).str.strip().str.lower() == discipline_lower) &
                        (refpoints_df["sex"].astype(str).str.strip().str.lower() == sex.strip().lower())
                    ]
                    if not ref_row_nt.empty and str(age) in ref_row_nt.columns:
                        ref_value_nt = ref_row_nt.iloc[0][str(age)]
                        try:
                            ref_value_nt = float(ref_value_nt)
                            points_val_nt = float(points)
                            percent_nt = round((points_val_nt / ref_value_nt) * 100, 1) if ref_value_nt else None
                        except Exception:
                            percent_nt = None
                else:
                    sel_row_nt = sel_df[
                        (sel_df["Competition"].astype(str).str.strip().str.lower() == "jem") &
                        (sel_df["category"].astype(str).str.strip().str.lower() == category) &
                        (sel_df["Discipline"].astype(str).str.strip().str.lower() == discipline_lower) &
                        (sel_df["sex"].astype(str).str.strip().str.lower() == sex.strip().lower()) &
                        (sel_df["year"].astype(str) == str(comp_year))
                    ]
                    if not sel_row_nt.empty:
                        try:
                            ref_value_nt = float(sel_row_nt.iloc[0]["points"])
                            points_val_nt = float(points)
                            percent_nt = round((points_val_nt / ref_value_nt) * 100, 1) if ref_value_nt else None
                        except Exception:
                            percent_nt = None

                nationalteam = "yes" if percent_nt is not None and percent_nt >= 90 else "no"
            else:
                nationalteam = "no"
            updates[-1]["NationalTeam"] = nationalteam

        # --- Batch-Update ---
        batch_size = 500
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i+batch_size]
            for entry in batch:
                entry_id = entry["id"]
                update_data = {k: v for k, v in entry.items() if k != "id"}
                db.table_update('compresults', update_data, id=entry_id)

        st.success(f"Berechnen abgeschlossen. {updated} Einträge für {selected_year} aktualisiert.")


        # ... im Top3-Abschnitt:
        ref_col = f"PisteRefPoints{selected_year}%"
        compresults = fetch_all_rows('compresults', select='*')
        df = pd.DataFrame(compresults)
        if ref_col not in df.columns:
            st.error(f"Spalte {ref_col} nicht gefunden!")
        else:
            competitions = db.table_select('competitions', 'Name, PisteYear')
            comp_map = {c['Name']: (int(c.get('PisteYear')) if c.get('PisteYear') else None) for c in competitions}
            df["PisteYear"] = df["Competition"].map(comp_map)
            athletes = db.table_select('athletes', 'first_name, last_name, vintage')
            athlete_vintage = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a['vintage'] for a in athletes}
            pisterefcomppoints = db.table_select('pisterefcomppoints', '*')
            pisterefcomppoints_df = pd.DataFrame(pisterefcomppoints)

            # Altersberechnung
            df["age"] = df.apply(lambda r: int(selected_year) - int(r["vintage"]) if r.get("vintage") else None, axis=1)
            # Ausschluss Synchro etc.
            df = df[~df.apply(lambda r: is_excluded_discipline_local(r.get("Discipline"), r.get("age"), selected_year, agecat_df), axis=1)]

            # --- NEU: Elite ausschließen ---
            df = df[df["CategoryStart"].str.strip().str.lower() != "elite"]

            # --- NEU: Nur Wettkämpfe mit PisteYear == ausgewähltes Jahr ---
            df = df[df["PisteYear"] == int(selected_year)]

            grouped = df[df[ref_col].notnull() & (df[ref_col] != "")].groupby([
                df['first_name'].str.strip().str.lower(),
                df['last_name'].str.strip().str.lower()
            ])
            max_id_row = db.query("SELECT ISNULL(MAX(id), 0) AS max_id FROM [pisterefcompresults]")
            next_id = (max_id_row[0]['max_id'] if max_id_row else 0) + 1
            inserted = 0
            for (first, last), group in grouped:
                group = group.sort_values(ref_col, ascending=False)
                top3 = group.head(3)
                if top3.empty:
                    continue
                vintage = athlete_vintage.get((first, last))
                if not vintage:
                    continue
                age = int(selected_year) - int(vintage)
                data = {
                    "id": next_id,
                    "first_name": top3.iloc[0]['first_name'],
                    "last_name": top3.iloc[0]['last_name'],
                    "age": age,
                    "PisteYear": int(selected_year),
                }
                next_id += 1
                pointsaverage = []
                for i in range(1, 4):
                    if len(top3) >= i:
                        row = top3.iloc[i-1]
                        data[f"competition{i}"] = row.get("Competition")
                        data[f"discipline{i}"] = row.get("Discipline")
                        data[f"points{i}"] = row.get("Points")
                        data[f"reference{i}"] = row.get(ref_col)
                        avg_points = None
                        avg_row = df[
                            (df['first_name'].str.strip().str.lower() == first) &
                            (df['last_name'].str.strip().str.lower() == last) &
                            (df['Competition'] == row.get("Competition")) &
                            (df['Discipline'] == row.get("Discipline")) &
                            (df['PisteYear'] == int(selected_year))
                        ]
                        if not avg_row.empty:
                            avg_points = avg_row.iloc[0].get("AveragePoints")
                        data[f"pointsaverage{i}"] = avg_points
                        if avg_points not in (None, "", "nan"):
                            try:
                                pointsaverage.append(float(avg_points))
                            except Exception:
                                pass
                    else:
                        data[f"competition{i}"] = None
                        data[f"discipline{i}"] = None
                        data[f"points{i}"] = None
                        data[f"reference{i}"] = None
                        data[f"pointsaverage{i}"] = None
                data["pointsaverageaverage"] = round(sum(pointsaverage) / len(pointsaverage), 2) if pointsaverage else None
                refs = [data[f"reference{i}"] for i in range(1, 4) if data[f"reference{i}"] is not None]
                try:
                    refs = [float(r) for r in refs if r not in ("", None)]
                    data["refaverage"] = round(sum(refs) / len(refs), 1) if refs else None
                except Exception:
                    data["refaverage"] = None
                pointsaverageref = None
                try:
                    discipline = data.get("discipline1")
                    if not discipline:
                        discipline = top3.iloc[0].get("Discipline") if len(top3) > 0 else None
                    sex = None
                    cr_row = df[
                        (df['first_name'].str.strip().str.lower() == first) &
                        (df['last_name'].str.strip().str.lower() == last) &
                        (df['PisteYear'] == int(selected_year))
                    ]
                    if not cr_row.empty:
                        sex = cr_row.iloc[0].get("sex")
                    if not sex or sex == "":
                        athlete_row = [a for a in athletes if a['first_name'].strip().lower() == first and a['last_name'].strip().lower() == last]
                        if athlete_row:
                            sex = athlete_row[0].get("sex")
                    quality_col = f"quality{int(age)}"
                    ref_row = pisterefcomppoints_df[
                        (pisterefcomppoints_df["Discipline"].astype(str).str.strip().str.lower() == str(discipline).strip().lower()) &
                        (pisterefcomppoints_df["sex"].astype(str).str.strip().str.lower() == str(sex).strip().lower())
                    ]
                    if not ref_row.empty and quality_col in ref_row.columns:
                        ref_value = ref_row.iloc[0][quality_col]
                        avg_val = data.get("pointsaverageaverage")
                        if ref_value not in (None, "", "nan") and avg_val not in (None, "", "nan"):
                            try:
                                ref_value = float(ref_value)
                                avg_val = float(avg_val)
                                if ref_value != 0:
                                    pointsaverageref = round((avg_val / ref_value) * 100, 1)
                            except Exception:
                                pointsaverageref = None
                except Exception:
                    pointsaverageref = None
                data["pointsaverageref%"] = pointsaverageref
                db.table_delete('pisterefcompresults',
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    PisteYear=data["PisteYear"])
                db.table_insert("pisterefcompresults", data)
                inserted += 1
            st.success(f"Top3-Auswertung abgeschlossen. {inserted} Einträge für {selected_year} gespeichert.")

        # --- ENTWICKLUNG RECHNEN ---
        st.info("Starte: Entwicklung rechnen ...")
        year_list = [str(y) for y in range(2024, int(selected_year) + 1)]
        refcompresults = []
        for y in year_list:
            refcompresults.extend(fetch_all_rows("pisterefcompresults", select="*", PisteYear=y))
        if not refcompresults:
            st.warning("Keine Daten in pisterefcompresults für die gewählten Jahre gefunden.")
        else:
            df = pd.DataFrame(refcompresults)
            df["PisteYear"] = df["PisteYear"].astype(str)
            grouped = df.groupby([df['first_name'].str.strip().str.lower(), df['last_name'].str.strip().str.lower()])
            updated = 0
            for (first, last), group in grouped:
                group = group.sort_values("PisteYear")
                this_year_row = group[group["PisteYear"] == str(selected_year)]
                if this_year_row.empty:
                    continue
                this_year_value = this_year_row.iloc[0].get("refaverage")
                prev_years = group[group["PisteYear"] != str(selected_year)]
                prev_values = prev_years["refaverage"].dropna().tolist()
                if len(prev_values) < 1 or this_year_value is None:
                    continue
                try:
                    prev_avg = sum([float(v) for v in prev_values]) / len(prev_values)
                    this_val = float(this_year_value)
                    if prev_avg == 0:
                        performance = None
                    else:
                        performance = round(((this_val - prev_avg) / prev_avg) * 100, 1)
                except Exception:
                    performance = None
                db.table_update('pisterefcompresults', {"performance": performance},
                    first_name=this_year_row.iloc[0]["first_name"],
                    last_name=this_year_row.iloc[0]["last_name"],
                    PisteYear=str(selected_year))
                updated += 1

            # DiveQuality-Berechnung
            refcomppoints = db.table_select("pisterefcomppoints", '*')
            refcomppoints_df = pd.DataFrame(refcomppoints)
            compresults = fetch_all_rows('compresults', select='*')
            competitions = db.table_select("competitions", "Name, PisteYear")
            compresults_df = pd.DataFrame(compresults)
            comp_map = {c["Name"]: (int(c.get("PisteYear")) if c.get("PisteYear") else None) for c in competitions}
            compresults_df["PisteYear"] = compresults_df["Competition"].map(comp_map)
            for (first, last), group in grouped:
                group = group.sort_values("PisteYear")
                this_year_row = group[group["PisteYear"] == str(selected_year)]
                if this_year_row.empty:
                    continue
                age = this_year_row.iloc[0].get("age")
                sex = this_year_row.iloc[0].get("sex", None)
                try:
                    age_int = int(float(age)) if pd.notna(age) else None
                except Exception:
                    age_int = None
                if not age or not sex:
                    cr = compresults_df[
                        (compresults_df['first_name'].str.strip().str.lower() == first) &
                        (compresults_df['last_name'].str.strip().str.lower() == last) &
                        (compresults_df['PisteYear'] == int(selected_year))
                    ]
                    if not cr.empty:
                        sex = cr.iloc[0].get("sex")
                if age_int is None:
                    continue
                cr_rows = compresults_df[
                    (compresults_df['first_name'].str.strip().str.lower() == first) &
                    (compresults_df['last_name'].str.strip().str.lower() == last) &
                    (compresults_df['Competition'].notnull()) &
                    (compresults_df['Points'].notnull()) &
                    (compresults_df['PisteYear'] == int(selected_year))
                ]
                quality_vals = []
                for _, cr_row in cr_rows.iterrows():
                    discipline = cr_row.get("Discipline")
                    avg_points = cr_row.get("AveragePoints")
                    # --- AUSSCHLUSS HIER ---
                    if is_excluded_discipline_local(discipline, age, selected_year, agecat_df):
                        continue
                    if not (discipline and sex):
                        continue
                    if pd.isna(avg_points):
                        continue
                    ref_row = refcomppoints_df[
                        (refcomppoints_df["Discipline"].astype(str).str.strip().str.lower() == str(discipline).strip().lower()) &
                        (refcomppoints_df["sex"].astype(str).str.strip().str.lower() == str(sex).strip().lower())
                    ]
                    quality_col = f"quality{age_int}"
                    if ref_row.empty or quality_col not in ref_row.columns:
                        continue
                    ref_value = ref_row.iloc[0][quality_col]
                    try:
                        ref_value = float(ref_value)
                        avg_points_val = float(avg_points)
                        if not math.isfinite(ref_value) or not math.isfinite(avg_points_val):
                            continue
                        deviation = round(((avg_points_val - ref_value) / ref_value) * 100, 1) if ref_value else None
                        if deviation is not None and pd.notna(deviation) and math.isfinite(float(deviation)):
                            quality_vals.append(deviation)
                    except Exception:
                        continue
                quality = round(sum(quality_vals) / len(quality_vals), 1) if quality_vals else None
                if pd.isna(quality) or (quality is not None and not math.isfinite(float(quality))):
                    quality = None
                db.table_update('pisterefcompresults', {"quality": quality},
                    first_name=this_year_row.iloc[0]["first_name"],
                    last_name=this_year_row.iloc[0]["last_name"],
                    PisteYear=int(selected_year))
            st.success(f"Entwicklung für {updated} Personen berechnet und gespeichert.")

def show_top3_wettkaempfe():
    st.header("🏆 Top 3 Wettkämpfe pro Athlet und Jahr")

    df = pd.DataFrame(fetch_all_rows("pisterefcompresults", select="*"))
    if df.empty:
        st.info("Keine Top-3-Wettkämpfe für die Auswahl gefunden.")
        return

    jahre = sorted(df["PisteYear"].dropna().unique())
    jahr = st.multiselect("Jahr", jahre, default=jahre)
    alter = sorted(df["age"].dropna().unique())
    age = st.multiselect("Alter", alter, default=alter)

    # --- Namensfilter ---
    first_names = sorted(df["first_name"].dropna().unique())
    last_names = sorted(df["last_name"].dropna().unique())
    first_name_filter = st.text_input("Vorname (Teilstring möglich)", "")
    last_name_filter = st.text_input("Nachname (Teilstring möglich)", "")

    if st.button("Show Results"):
        filtered = df[df["PisteYear"].isin(jahr)]
        if age:
            filtered = filtered[filtered["age"].isin(age)]
        if first_name_filter:
            filtered = filtered[filtered["first_name"].str.contains(first_name_filter, case=False, na=False)]
        if last_name_filter:
            filtered = filtered[filtered["last_name"].str.contains(last_name_filter, case=False, na=False)]

        rows = []
        for _, row in filtered.iterrows():
            for i in range(1, 4):
                comp = row.get(f"competition{i}")
                pts = row.get(f"points{i}")
                discipline = row.get(f"discipline{i}")
                reference = row.get(f"reference{i}")
                pointsaverage = row.get(f"pointsaverage{i}")
                if comp not in (None, "", "nan") and pts not in (None, "", "nan"):
                    rows.append({
                        "Vorname": row.get("first_name"),
                        "Nachname": row.get("last_name"),
                        "Jahr": row.get("PisteYear"),
                        "Wettkampf": comp,
                        "Disziplin": discipline,
                        "Alter": row.get("age"),
                        "Reference": reference,
                        "RefAverage": row.get("refaverage"),
                        "Points": pts,
                        "PointsAverage": pointsaverage,
                        "PointsAverageAverage": row.get("pointsaverageaverage"),
                        "PointsAverageRef%": row.get("pointsaverageref%"),
                        "Quality": row.get("quality"),
                        "PisteYear": row.get("PisteYear")
                    })
        top3_df = pd.DataFrame(rows)

        if top3_df.empty:
            st.info("Keine Top-3-Wettkämpfe für die Auswahl gefunden.")
            return

        show_cols = [
            "Vorname", "Nachname", "Jahr", "Wettkampf", "Disziplin", "Alter",
            "Reference", "RefAverage", "Points", "PointsAverage", "PointsAverageAverage",
            "PointsAverageRef%", "Quality", "PisteYear"
        ]
        for col in show_cols:
            if col not in top3_df.columns:
                top3_df[col] = None
        top3_df = top3_df[show_cols]

        st.dataframe(top3_df)
        st.download_button(
            "📥 Top 3 Wettkämpfe als CSV",
            top3_df.to_csv(index=False, encoding='utf-8-sig'),
            file_name="top3_wettkaempfe.csv",
            mime="text/csv"
        )

        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            top3_df.to_excel(writer, index=False, sheet_name="Top 3 Wettkämpfe")
        output.seek(0)
        st.download_button(
            "📥 Top 3 Wettkämpfe als Excel",
            output.getvalue(),
            file_name="top3_wettkaempfe.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

def manage_tool_environment():
    st.header("🛠️ Tool Environment Werte eingeben oder importieren")

    # Athleten laden
    athletes = db.table_select('athletes', 'first_name, last_name, birthdate')
    athlete_names = [f"{a['first_name']} {a['last_name']}" for a in athletes]
    athlete_lookup = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a for a in athletes}

     # Manuelle Eingabe
    st.subheader("🔹 Einzelnen Wert eingeben")
    pisteyear = st.number_input("PisteYear", min_value=2020, max_value=2100, value=datetime.date.today().year, step=1)
    selected_athlete = st.selectbox("Athlet auswählen", [""] + athlete_names, index=0)
    toolenvvalue = st.number_input("Tool Environment Wert", min_value=0.0, max_value=100.0, value=0.0, step=0.1, format="%.2f")

    if st.button("💾 Wert speichern", key="tool_environment_save"):
        if not selected_athlete:
            st.warning("Bitte zuerst einen Athleten auswählen.")
        else:
            first_name, last_name = selected_athlete.split(" ", 1)
            data = {
                "first_name": first_name,
                "last_name": last_name,
                "PisteYear": int(pisteyear),
                "toolenvvalue": float(toolenvvalue),
            }
            existing = db.table_select(
                "pisteenvironment",
                "first_name",
                first_name=first_name,
                last_name=last_name,
                PisteYear=int(pisteyear),
            )
            if existing:
                db.table_update(
                    "pisteenvironment",
                    {"toolenvvalue": float(toolenvvalue)},
                    first_name=first_name,
                    last_name=last_name,
                    PisteYear=int(pisteyear),
                )
            else:
                db.table_insert("pisteenvironment", data)
            st.success(f"Eintrag für {selected_athlete} gespeichert.")

    st.markdown("---")
    st.subheader("🔹 CSV-Import")

    # Beispiel-CSV
    example = pd.DataFrame([{
        "first_name": "Max",
        "last_name": "Mustermann",
        "PisteYear": 2024,
        "toolenvvalue": 7.5
    }])
    st.download_button(
        label="📄 Beispiel-CSV herunterladen",
        data=example.to_csv(index=False).encode("utf-8"),
        file_name="tool_environment_beispiel.csv",
        mime="text/csv"
    )

    uploaded_file = st.file_uploader("CSV-Datei mit Tool Environment-Werten hochladen", type="csv")
    if uploaded_file:
        st.info("Datei geladen. Klicke auf '📤 Import starten', um den Import auszuführen.")
        if st.button("📤 Import starten", key="tool_environment_import_submit"):
            try:
                df = read_uploaded_csv_with_fallback(uploaded_file)
            except UnicodeDecodeError as e:
                st.error(f"❌ Datei konnte nicht gelesen werden (Encoding): {e}")
                return
            except Exception as e:
                st.error(f"❌ Datei konnte nicht gelesen werden: {e}")
                return

            required_columns = {"first_name", "last_name", "PisteYear", "toolenvvalue"}
            if not required_columns.issubset(df.columns):
                st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_columns)}")
                return

            missing_athletes = []
            inserted = 0
            for _, row in df.iterrows():
                key = (str(row['first_name']).strip().lower(), str(row['last_name']).strip().lower())
                if key not in athlete_lookup:
                    missing_athletes.append({"first_name": row['first_name'], "last_name": row['last_name']})
                    continue
                try:
                    first_name = str(row['first_name']).strip()
                    last_name = str(row['last_name']).strip()
                    year_val = int(row['PisteYear'])
                    env_val = float(row['toolenvvalue'])

                    existing = db.table_select(
                        "pisteenvironment",
                        "first_name",
                        first_name=first_name,
                        last_name=last_name,
                        PisteYear=year_val,
                    )
                    if existing:
                        db.table_update(
                            "pisteenvironment",
                            {"toolenvvalue": env_val},
                            first_name=first_name,
                            last_name=last_name,
                            PisteYear=year_val,
                        )
                    else:
                        db.table_insert("pisteenvironment", {
                            "first_name": first_name,
                            "last_name": last_name,
                            "PisteYear": year_val,
                            "toolenvvalue": env_val,
                        })
                    inserted += 1
                except Exception as e:
                    st.warning(f"Fehler beim Einfügen von {row['first_name']} {row['last_name']}: {e}")
            st.success(f"{inserted} Einträge erfolgreich importiert.")
            if missing_athletes:
                st.warning(f"{len(missing_athletes)} Athlet(en) nicht gefunden:")
                st.dataframe(pd.DataFrame(missing_athletes))

def bio_mirwald():
    st.header("🧬 Bio Mirwald Eingabe & Import")

    # --- Einzel-Eingabe ---
    athletes = db.table_select('athletes', 'first_name, last_name')
    athlete_names = [f"{a['first_name']} {a['last_name']}" for a in athletes]
    athlete_lookup = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a for a in athletes}

    st.subheader("Einzel-Eingabe")
    selected_name = st.selectbox("Athlet auswählen", [""] + athlete_names, index=0)
    pisteyear = st.number_input("PisteYear", min_value=2000, max_value=2100, value=datetime.date.today().year)
    bioentwstand = st.selectbox("bioentwstand", [1, 2, 3])

    if st.button("Speichern"):
        if not selected_name:
            st.warning("Bitte zuerst einen Athleten auswählen.")
            return
        first_name, last_name = selected_name.split(" ", 1)
        db.table_insert("pistemirwald", {
            "first_name": first_name,
            "last_name": last_name,
            "PisteYear": pisteyear,
            "bioentwstand": bioentwstand
        })
        st.success(f"Eintrag für {selected_name} gespeichert.")

    st.markdown("---")

    # --- CSV-Import ---
    st.subheader("CSV-Import")
    sample_df = pd.DataFrame([{
        "first_name": "Max",
        "last_name": "Mustermann",
        "PisteYear": 2024,
        "bioentwstand": 1
    }])
    st.download_button(
        "📄 Beispiel-CSV herunterladen",
        data=sample_df.to_csv(index=False).encode("utf-8"),
        file_name="bio_mirwald_beispiel.csv",
        mime="text/csv"
    )

    uploaded_file = st.file_uploader("CSV-Datei mit Mirwald-Daten hochladen", type="csv")
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        required_columns = {"first_name", "last_name", "PisteYear", "bioentwstand"}
        if not required_columns.issubset(df.columns):
            st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_columns)}")
            return

        missing_athletes = []
        inserted = 0
        for _, row in df.iterrows():
            key = (str(row['first_name']).strip().lower(), str(row['last_name']).strip().lower())
            if key not in athlete_lookup:
                missing_athletes.append({"first_name": row['first_name'], "last_name": row['last_name']})
                continue
            try:
                db.table_insert("pistemirwald", {
                    "first_name": row['first_name'],
                    "last_name": row['last_name'],
                    "PisteYear": int(row['PisteYear']),
                    "bioentwstand": int(row['bioentwstand'])
                })
                inserted += 1
            except Exception as e:
                st.warning(f"Fehler beim Einfügen von {row['first_name']} {row['last_name']}: {e}")

        st.success(f"{inserted} Einträge erfolgreich importiert.")
        if missing_athletes:
            st.warning(f"{len(missing_athletes)} Athlet(en) nicht gefunden:")
            st.dataframe(pd.DataFrame(missing_athletes))

def manage_trainingsperformance_resilienz():
    st.header("💪 Trainingsperformance - Resilienz")

    # Athleten laden
    athletes = db.table_select('athletes', 'first_name, last_name')
    athlete_names = [f"{a['first_name']} {a['last_name']}" for a in athletes]
    athlete_lookup = {(a['first_name'], a['last_name']): a for a in athletes}

    st.subheader("🔹 Einzelnen Wert eingeben")
    pisteyear = st.number_input("PisteYear", min_value=2020, max_value=2100, value=datetime.date.today().year, step=1)
    selected_athlete = st.selectbox("Athlet auswählen", [""] + athlete_names, index=0)
    if selected_athlete:
        first_name, last_name = selected_athlete.split(" ", 1)
        cols = st.columns(5)
        q1 = cols[0].number_input("q1", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q2 = cols[1].number_input("q2", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q3 = cols[2].number_input("q3", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q4 = cols[3].number_input("q4", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q5 = cols[4].number_input("q5", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        cols2 = st.columns(5)
        q6 = cols2[0].number_input("q6", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q7 = cols2[1].number_input("q7", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q8 = cols2[2].number_input("q8", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q9 = cols2[3].number_input("q9", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        q10 = cols2[4].number_input("q10", min_value=0.0, max_value=5.0, value=0.0, step=0.5)
        trainingtime = st.number_input("Trainingtime (Stunden)", min_value=0, max_value=40, value=0)
        trainingsince = st.text_input("Trainingsince (z.B. 2018)", value="2015")

        if st.button("💾 Wert speichern"):
            data = {
                "first_name": first_name,
                "last_name": last_name,
                "PisteYear": pisteyear,
                "q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5,
                "q6": q6, "q7": q7, "q8": q8, "q9": q9, "q10": q10,
                "trainingtime": trainingtime,
                "trainingsince": trainingsince
            }
            existing = db.table_select("trainingsperformance", "first_name", first_name=first_name, last_name=last_name, PisteYear=pisteyear)
            if existing:
                db.table_update("trainingsperformance", data, first_name=first_name, last_name=last_name, PisteYear=pisteyear)
            else:
                db.table_insert("trainingsperformance", data)
            # Summen berechnen und socadditionalvalues upsert
            trainingperf = sum([q2, q3, q4, q5, q7, q8, q9, q10])
            resilience = q1 + q6
            # Trainingsince- und Trainingstime-Wert berechnen
            trainingsince_value = get_trainingsince_value(pisteyear, trainingsince, first_name, last_name)
            trainingstime_value = get_trainingstime_value(pisteyear, trainingtime, first_name, last_name)
            athlete = athlete_lookup.get((first_name, last_name))
            vintage = int(str(athlete["birthdate"])[:4]) if athlete and athlete.get("birthdate") else None
            category = get_category_from_testyear(vintage, pisteyear) if vintage else None

            data2 = {
                "first_name": first_name,
                "last_name": last_name,
                "PisteYear": pisteyear,
                "trainingperf": trainingperf,
                "resilience": resilience,
                "trainingsince": trainingsince_value,
                "trainingtime": trainingstime_value,
                "Category": category
            }
            existing2 = db.table_select("socadditionalvalues", "first_name", first_name=first_name, last_name=last_name, PisteYear=pisteyear)
            if existing2:
                db.table_update("socadditionalvalues", data2, first_name=first_name, last_name=last_name, PisteYear=pisteyear)
            else:
                db.table_insert("socadditionalvalues", data2)
            st.success("Wert gespeichert!")
    else:
        st.info("Bitte zuerst einen Athleten auswählen.")

    st.markdown("---")
    st.subheader("🔹 CSV-Import")

    # Beispiel-CSV
    example = pd.DataFrame([{
        "first_name": "Max",
        "last_name": "Mustermann",
        "PisteYear": 2024,
        "q1": 1,
        "q2": 0.5,
        "q3": 2,
        "q4": 2,
        "q5": 1,
        "q6": 2,
        "q7": 1,
        "q8": 2,
        "q9": 1,
        "q10": 2,
        "trainingtime": 12,
        "trainingsince": "2018"
    }])
    st.download_button(
        "📄 Beispiel-CSV herunterladen",
        example.to_csv(index=False).encode("utf-8"),
        file_name="trainingsperformance_beispiel.csv",
        mime="text/csv"
    )

    uploaded_file = st.file_uploader("CSV-Datei mit Trainingsperformance-Werten hochladen", type="csv")
    if uploaded_file:
        st.info("Datei geladen. Klicke auf '📤 Import starten', um den Import auszuführen.")
        if st.button("📤 Import starten", key="trainingsperformance_import_submit"):
            try:
                df = read_uploaded_csv_with_fallback(uploaded_file)
            except UnicodeDecodeError as e:
                st.error(f"❌ Datei konnte nicht gelesen werden (Encoding): {e}")
                return
            except Exception as e:
                st.error(f"❌ Datei konnte nicht gelesen werden: {e}")
                return

            required_cols = {"first_name", "last_name", "PisteYear", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10", "trainingtime", "trainingsince"}
            if not required_cols.issubset(df.columns):
                st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_cols)}")
                return

            inserted = 0
            skipped = []
            # Athleten-Liste für Lookup laden
            athletes_db = db.table_select('athletes', 'first_name, last_name, birthdate')
            athlete_lookup_name = {
                (a['first_name'].strip().lower(), a['last_name'].strip().lower()): a
                for a in athletes_db
            }
            for _, row in df.iterrows():
                first = str(row['first_name']).strip().lower()
                last = str(row['last_name']).strip().lower()
                csv_birthdate = str(row.get('birthdate', '')).strip().split(' ')[0]

                # Standardfall: Match über Vorname/Nachname (birthdate ist in required_cols nicht enthalten)
                found = (first, last) in athlete_lookup_name

                # Falls birthdate im CSV dennoch vorhanden ist, nur dann zusätzlich prüfen
                if found and csv_birthdate:
                    athlete_birthdate = str(athlete_lookup_name[(first, last)].get('birthdate') or '').strip().split(' ')[0]
                    found = athlete_birthdate == csv_birthdate

                if not found:
                    skipped.append({"first_name": row["first_name"], "last_name": row["last_name"], "birthdate": row.get("birthdate", "")})
                    continue
                try:
                    data = {col: row[col] for col in required_cols}
                    existing = db.table_select("trainingsperformance", "first_name", first_name=row["first_name"], last_name=row["last_name"], PisteYear=row["PisteYear"])
                    if existing:
                        db.table_update("trainingsperformance", data, first_name=row["first_name"], last_name=row["last_name"], PisteYear=row["PisteYear"])
                    else:
                        db.table_insert("trainingsperformance", data)

                    inserted += 1
                except Exception as e:
                    st.warning(f"Fehler bei {row['first_name']} {row['last_name']}: {e}")
            st.success(f"✅ {inserted} Werte importiert.")
            if skipped:
                st.warning("Folgende Personen wurden nicht importiert, da sie nicht in der Athletenliste stehen:")
                st.dataframe(pd.DataFrame(skipped))

def get_trainingsince_value(pisteyear, trainingsince, first_name, last_name):
    athlete = db.table_select('athletes', 'vintage', first_name=first_name, last_name=last_name)
    if not athlete:
        return None
    vintage = athlete[0]['vintage']
    try:
        age = int(pisteyear) - int(vintage)
        trainingsjahre = int(pisteyear) - int(trainingsince)
    except Exception:
        return None

    ref = db.table_select('pistereftrainingsince', '*', age=age)
    if not ref:
        return None
    ref_row = ref[0]
    col = str(trainingsjahre)
    if col in ref_row:
        return ref_row[col]
    return None

def get_trainingstime_value(pisteyear, trainingstime, first_name, last_name):
    athlete = db.table_select('athletes', 'vintage', first_name=first_name, last_name=last_name)
    if not athlete:
        return None
    vintage = athlete[0]['vintage']
    try:
        age = int(pisteyear) - int(vintage)
        stunden = int(trainingstime)
    except Exception:
        return None

    ref = db.table_select('pistereftrainingtime', '*', age=age)
    if not ref:
        return None
    ref_row = ref[0]
    col = str(stunden)
    if col in ref_row:
        return ref_row[col]
    return None

def soc_full_calculation():
    st.header("🔢 SOC Full Calculation")
    agecategories = db.table_select('agecategories', '*')
    years = [str(y) for y in range(2024, 2031)]
    selected_year = st.selectbox("PisteYear wählen", years)
    if st.button("SOC Full Calculation starten"):
        pisteyear = str(selected_year)
        pisteyear_int = int(selected_year)
        injured_map = load_athleteyearstatus_map()

        athletes = db.table_select('athletes', 'id, first_name, last_name, birthdate, sex, vintage, bioage')
        athletes_lookup = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a for a in athletes}

        refcompresults = fetch_all_rows('pisterefcompresults', select='*', PisteYear=pisteyear)
        refcompresults_df = pd.DataFrame(refcompresults)

        pistedisciplines = db.table_select('pistedisciplines', 'id, name')
        comp_perf_id = next((d['id'] for d in pistedisciplines if d['name'] == "CompPerfPointsCalc"), None)
        comp_quality_id = next((d['id'] for d in pistedisciplines if d['name'] == "CompPerfQualityCalc"), None)
        comp_enhance_id = next((d['id'] for d in pistedisciplines if d['name'] == "CompPerfEnhance"), None)
        pistetotalinpoints_id = next((d['id'] for d in pistedisciplines if d['name'] == "PisteTotalinPoints"), None)
        if not (comp_perf_id and comp_quality_id and comp_enhance_id and pistetotalinpoints_id):
            st.error("Eine oder mehrere Disziplinen fehlen!")
            return

        scoretables = fetch_all_rows('scoretables', select='*', discipline_id=comp_perf_id)
        scoretables_quality = fetch_all_rows('scoretables', select='*', discipline_id=comp_quality_id)
        scoretables_enhance = fetch_all_rows('scoretables', select='*', discipline_id=comp_enhance_id)

        piste_results = fetch_all_rows("pisteresults", select="athlete_id, discipline_id, points, raw_result, TestYear")
        piste_results_df = pd.DataFrame(piste_results)

        # Bestehende Einträge für dieses Jahr löschen → danach immer frisch inserieren (kein Duplikat-Risiko)
        # Cast on both sides avoids int/nvarchar coercion issues when legacy values like 'global' exist.
        db.execute(
            "DELETE FROM [socadditionalvalues] "
            "WHERE CAST([PisteYear] AS NVARCHAR(10)) = CAST(%s AS NVARCHAR(10)) "
            "AND ISNULL([toolenvironment], '') <> 'injuryflags'",
            [pisteyear],
        )

        athlete_data_map = {}

        for _, row in refcompresults_df.iterrows():
            first_name = row['first_name']
            last_name = row['last_name']
            athlete = athletes_lookup.get((first_name.strip().lower(), last_name.strip().lower()))
            if not athlete:
                continue

            key = (athlete['first_name'], athlete['last_name'], pisteyear)
            if key not in athlete_data_map:
                athlete_data_map[key] = {
                    "first_name": athlete['first_name'],
                    "last_name": athlete['last_name'],
                    "birthdate": athlete['birthdate'],
                    "sex": athlete['sex'],
                    "PisteYear": pisteyear,
                    "Category": get_category_from_agecategories(athlete.get('vintage'), pisteyear_int, agecategories)
                }

            athlete_data_map[key]["injured"] = "yes" if injured_map.get(key, False) else "no"
            athlete_data_map[key]["injured"] = "yes" if injured_map.get((_norm_str(athlete['first_name']), _norm_str(athlete['last_name']), _norm_str(pisteyear)), False) else "no"

            bioage = athlete.get("bioage")
            bioage_map = {"q1": -1, "q2": -0.5, "q3": 0.5, "q4": 1}
            bioagevalue = bioage_map.get(str(bioage).lower(), 0) if bioage else 0
            athlete_data_map[key]["bioagevalue"] = bioagevalue

            mirwald_rows = db.table_select("pistemirwald", "bioentwstand", first_name=athlete['first_name'], last_name=athlete['last_name'], PisteYear=pisteyear)
            mirwald_map = {3: 1, 2: 0, 1: -1}
            mirwaldvalue = 0
            if mirwald_rows and "bioentwstand" in mirwald_rows[0]:
                try:
                    bioentwstand = int(mirwald_rows[0]["bioentwstand"])
                    mirwaldvalue = mirwald_map.get(bioentwstand, 0)
                except Exception:
                    mirwaldvalue = 0
            athlete_data_map[key]["mirwaldvalue"] = mirwaldvalue

            env_row = db.table_select("pisteenvironment", "toolenvvalue", first_name=athlete['first_name'], last_name=athlete['last_name'], PisteYear=pisteyear)
            if env_row:
                athlete_data_map[key]["toolenvironment"] = env_row[0].get("toolenvvalue")

            trainings_row = db.table_select("trainingsperformance", '*',
                first_name=athlete['first_name'],
                last_name=athlete['last_name'],
                PisteYear=pisteyear)
            if trainings_row:
                t = trainings_row[0]
                athlete_data_map[key]["trainingperf"] = sum([t.get("q2", 0), t.get("q3", 0), t.get("q4", 0), t.get("q5", 0), t.get("q7", 0), t.get("q8", 0), t.get("q9", 0), t.get("q10", 0)])
                athlete_data_map[key]["resilience"] = t.get("q1", 0) + t.get("q6", 0)
                athlete_data_map[key]["trainingsince"] = get_trainingsince_value(
                    pisteyear,
                    t.get("trainingsince"),
                    athlete['first_name'],
                    athlete['last_name']
                )
                athlete_data_map[key]["trainingtime"] = get_trainingstime_value(
                    pisteyear,
                    t.get("trainingtime"),
                    athlete['first_name'],
                    athlete['last_name']
                )

            refaverage = row.get('refaverage')
            if refaverage not in (None, "", "nan"):
                note = None
                try:
                    value_float = float(refaverage)
                    for s in scoretables:
                        rmin = float(s['result_min'])
                        rmax = float(s['result_max'])
                        if rmin <= value_float <= rmax:
                            note = s['points']
                            break
                except Exception:
                    pass
                athlete_data_map[key]["competitions"] = note

            pistepointsdurchschnitt_id = next((d['id'] for d in pistedisciplines if d['name'].strip().lower() == "pistepointsdurchschnitt"), None)
            pistetotalinpoints_id = next((d['id'] for d in pistedisciplines if d['name'] == "PisteTotalinPoints"), None)
            scoretable_rows = fetch_all_rows('scoretables', select='*', discipline_id=pistetotalinpoints_id)

            piste_result = piste_results_df[
                (piste_results_df['athlete_id'].astype(str) == str(athlete['id'])) &
                (piste_results_df['discipline_id'].astype(str) == str(pistepointsdurchschnitt_id)) &
                (piste_results_df['TestYear'].astype(str) == str(pisteyear))
            ]
            if not piste_result.empty:
                raw_val = piste_result.iloc[0]['raw_result']
                if raw_val is not None:
                    db.table_update("pisteresults", {"points": raw_val},
                        athlete_id=athlete['id'],
                        discipline_id=pistepointsdurchschnitt_id,
                        TestYear=pisteyear)
                    piste_results_df.loc[
                        (piste_results_df['athlete_id'].astype(str) == str(athlete['id'])) &
                        (piste_results_df['discipline_id'].astype(str) == str(pistepointsdurchschnitt_id)) &
                        (piste_results_df['TestYear'].astype(int) == int(pisteyear)),
                        'points'
                    ] = raw_val

            piste_result = piste_results_df[
                (piste_results_df['athlete_id'].astype(str) == str(athlete['id'])) &
                (piste_results_df['discipline_id'].astype(str) == str(pistepointsdurchschnitt_id)) &
                (piste_results_df['TestYear'].astype(int) == int(pisteyear))
            ]
            piste_value = None
            if not piste_result.empty:
                avg_points = piste_result.iloc[0]['points']
                avg_points_rounded = round(float(avg_points), 1)
                piste_value = get_points_with_next_higher(scoretable_rows, avg_points_rounded)
            athlete_data_map[key]["piste"] = piste_value

            performance = row.get('performance')
            if performance not in (None, "", "nan"):
                compenhance = None
                try:
                    value_float = float(performance)
                    for s in scoretables_enhance:
                        rmin = float(s['result_min'])
                        rmax = float(s['result_max'])
                        if rmin <= value_float <= rmax:
                            compenhance = s['points']
                            break
                except Exception:
                    pass
                athlete_data_map[key]["compenhancement"] = compenhance

            pointsaverageref = row.get('pointsaverageref%')
            if pointsaverageref not in (None, "", "nan"):
                note_quality = None
                try:
                    value_float = float(pointsaverageref)
                    for s in scoretables_quality:
                        rmin = float(s['result_min'])
                        rmax = float(s['result_max'])
                        if rmin <= value_float <= rmax:
                            note_quality = s['points']
                            break
                except Exception:
                    pass
                athlete_data_map[key]["quality"] = note_quality

        competitions = db.table_select('competitions', 'Name, PisteYear', PisteYear=pisteyear)
        comp_names = set(c['Name'] for c in competitions)
        compresults = fetch_all_rows('compresults', select='first_name, last_name, Competition, NationalTeam')
        for key in athlete_data_map:
            first_name, last_name, year = key
            relevant_results = [
                r for r in compresults
                if r['first_name'].strip().lower() == first_name.strip().lower()
                and r['last_name'].strip().lower() == last_name.strip().lower()
                and r.get('Competition') in comp_names
                and str(r.get('NationalTeam') or '').lower() == 'yes'
            ]
            athlete_data_map[key]["CompPointsNationalTeam"] = "no" if athlete_data_map[key].get("injured") == "yes" else ("yes" if relevant_results else "no")

        compresults_regio = fetch_all_rows('compresults', select='first_name, last_name, Competition, RegionalTeam')
        for key in athlete_data_map:
            first_name, last_name, year = key
            relevant_results_regio = [
                r for r in compresults_regio
                if isinstance(r, dict)
                and r.get('first_name', '').strip().lower() == first_name.strip().lower()
                and r.get('last_name', '').strip().lower() == last_name.strip().lower()
                and r.get('Competition') in comp_names
                and str(r.get('RegionalTeam') or '').strip().lower() == 'yes'
            ]
            athlete_data_map[key]["CompPointsRegionalTeam"] = "no" if athlete_data_map[key].get("injured") == "yes" else ("yes" if relevant_results_regio else "no")

        # --- Alle berechneten Daten frisch einfügen ---
        for data in athlete_data_map.values():
            db.table_insert("socadditionalvalues", {k: v for k, v in data.items() if k != "injured"})

        # --- totalpoints berechnen und speichern ---
        fields = [
            "competitions", "trainingperf", "piste", "compenhancement",
            "resilience", "trainingtime", "trainingsince", "toolenvironment", "quality", "bioagevalue", "mirwaldvalue"
        ]
        for key, data in athlete_data_map.items():
            existing = db.table_select("socadditionalvalues", '*',
                first_name=data['first_name'],
                last_name=data['last_name'],
                PisteYear=data['PisteYear'])
            if existing:
                row_vals = existing[0]
                total = 0
                for f in fields:
                    try:
                        val = row_vals.get(f)
                        if val not in (None, "", "nan"):
                            total += float(val)
                    except Exception:
                        continue
                db.table_update("socadditionalvalues", {"totalpoints": total},
                    first_name=data['first_name'],
                    last_name=data['last_name'],
                    PisteYear=data['PisteYear'])

        # --- pisterefminpoints-Check: pisteminregio und pisteminnational setzen ---
        refminpoints = db.table_select("pisterefminpoints", '*')
        refminpoints_df = pd.DataFrame(refminpoints)

        for key, data in athlete_data_map.items():
            row = db.table_select("socadditionalvalues", "totalpoints, birthdate, PisteYear",
                first_name=data['first_name'],
                last_name=data['last_name'],
                PisteYear=data['PisteYear'])
            if not row or row[0].get("totalpoints") in (None, "", "nan"):
                continue
            totalpoints = float(row[0]["totalpoints"])
            birthdate = row[0].get("birthdate")
            pisteyear = int(row[0].get("PisteYear"))
            if not birthdate:
                continue
            vintage = int(str(birthdate)[:4])
            age = pisteyear - vintage

            ref_row = refminpoints_df[refminpoints_df["age"].astype(str) == str(age)]
            if ref_row.empty:
                continue
            ref_row = ref_row.iloc[0]
            regio_min = ref_row.get("regio_min")
            national_min = ref_row.get("national_min")
            if regio_min in (None, "", "nan") or national_min in (None, "", "nan"):
                continue
            try:
                regio_min = float(regio_min)
                national_min = float(national_min)
            except Exception:
                continue

            pisteminregio = "Yes" if totalpoints >= regio_min else "No"
            pisteminnational = "Yes" if totalpoints >= national_min else "No"

            db.table_update("socadditionalvalues", {
                "pisteminregio": pisteminregio,
                "pisteminnational": pisteminnational
            }, first_name=data['first_name'],
               last_name=data['last_name'],
               PisteYear=data['PisteYear'])

        # --- Talentcard berechnen und speichern ---
        for key, data in athlete_data_map.items():
            row = db.table_select("socadditionalvalues",
                "pisteminregio, pisteminnational, CompPointsNationalTeam, CompPointsRegionalTeam",
                first_name=data['first_name'],
                last_name=data['last_name'],
                PisteYear=data['PisteYear'])

            if not row:
                continue

            pisteminregio = str(row[0].get("pisteminregio", "")).lower()
            pisteminnational = str(row[0].get("pisteminnational", "")).lower()
            comp_points_nt = str(row[0].get("CompPointsNationalTeam", "")).lower()
            comp_points_regio = str(row[0].get("CompPointsRegionalTeam", "")).lower()

            if athlete_data_map[key].get("injured") == "yes":
                talentcard = "noCard"
                db.table_update(
                    "socadditionalvalues",
                    {"CompPointsNationalTeam": "no", "CompPointsRegionalTeam": "no"},
                    first_name=data['first_name'],
                    last_name=data['last_name'],
                    PisteYear=data['PisteYear']
                )
            elif pisteminnational == "yes" and comp_points_nt == "yes":
                talentcard = "National"
                db.table_update(
                    "socadditionalvalues",
                    {"CompPointsRegionalTeam": "no"},
                    first_name=data['first_name'],
                    last_name=data['last_name'],
                    PisteYear=data['PisteYear']
                )
            elif pisteminregio == "yes" and comp_points_regio == "yes":
                talentcard = "Regional"
            else:
                talentcard = "noCard"

            db.table_update("socadditionalvalues", {"talentcard": talentcard},
                first_name=data['first_name'],
                last_name=data['last_name'],
                PisteYear=data['PisteYear'])

        st.success(f"Berechnung abgeschlossen und alle Einträge für {selected_year} aktualisiert.")

def show_full_piste_results_soc():
    st.header("📊 Full PISTE Results SOC")

    # Daten laden
    soc_df = pd.DataFrame(fetch_all_rows("socadditionalvalues", select="*"))
    if not soc_df.empty and "toolenvironment" in soc_df.columns:
        soc_df = soc_df[soc_df["toolenvironment"].fillna("").astype(str).str.lower() != "injuryflags"].copy()
    if soc_df.empty:
        st.info("Keine Daten in socadditionalvalues gefunden.")
        return

    injury_map = load_athleteyearstatus_map()

    # Nur gewünschte Spalten anzeigen (inkl. CompPointsNationalTeam und talentcard)
    show_cols = [
        "first_name", "last_name", "Category", "sex", "PisteYear",
        "competitions", "trainingperf", "piste", "compenhancement",
        "resilience", "trainingtime", "trainingsince", "toolenvironment",
        "quality", "bioagevalue", "mirwaldvalue", "totalpoints", "pisteminregio", "pisteminnational", "CompPointsRegionalTeam", "CompPointsNationalTeam", "talentcard"
    ]
    # Füge fehlende Spalten als leere Spalten hinzu (für robustes Verhalten)
    for col in show_cols:
        if col not in soc_df.columns:
            soc_df[col] = None
    soc_df = soc_df[show_cols]
    soc_df["injured"] = soc_df.apply(
        lambda row: "yes"
        if injury_map.get((
            str(row.get("first_name") or "").strip().lower(),
            str(row.get("last_name") or "").strip().lower(),
            str(row.get("PisteYear") or "").strip(),
        ), False)
        else "no",
        axis=1,
    )

    # Filter
    st.subheader("🔎 Filter")
    years = sorted(soc_df["PisteYear"].dropna().unique())
    current_year = datetime.datetime.now().year
    year_default_index = next((index for index, value in enumerate(years) if str(value) == str(current_year)), 0)
    selected_year = st.selectbox("Jahr", years, index=year_default_index, key=f"soc_year_filter_{get_app_version()}")
    year = [selected_year]

    last_names = sorted(soc_df["last_name"].dropna().unique())
    last_name = st.selectbox("Nachname", ["Alle"] + last_names)
    first_names = sorted(soc_df["first_name"].dropna().unique())
    first_name = st.selectbox("Vorname", ["Alle"] + first_names)
    sexes = sorted(soc_df["sex"].dropna().unique())
    sex = st.selectbox("Geschlecht", ["Alle"] + sexes)
    categories = sorted(soc_df["Category"].dropna().unique())
    category = st.multiselect("Kategorie", categories, default=categories)
    talentcard_values = ["Alle", "Verletzt"] + sorted([v for v in soc_df["talentcard"].dropna().unique() if v != ""])
    talentcard_filter = st.selectbox("Talentcard", list(dict.fromkeys(talentcard_values)), key="talentcard_filter_v2")

    # Anwenden der Filter
    filtered = soc_df[
        soc_df["PisteYear"].astype(str).isin([str(y) for y in year]) &
        (soc_df["first_name"].str.lower().str.strip() == first_name.lower().strip() if first_name != "Alle" else True) &
        (soc_df["last_name"].str.lower().str.strip() == last_name.lower().strip() if last_name != "Alle" else True) &
        soc_df["Category"].astype(str).isin([str(c) for c in category]) &
        (soc_df["sex"].astype(str) == str(sex) if sex != "Alle" else True) &
        (
            soc_df["injured"] == "yes"
            if talentcard_filter == "Verletzt"
            else (soc_df["talentcard"] == talentcard_filter if talentcard_filter != "Alle" else True)
        )
    ]

    st.dataframe(filtered)
    st.download_button(
        "📥 Gefilterte Ergebnisse als CSV",
        filtered.to_csv(index=False, encoding='utf-8-sig'),
        file_name="full_piste_results_soc.csv",
        mime="text/csv"
    )

    import io

    # XLSX-Export
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        filtered.to_excel(writer, index=False, sheet_name="Full PISTE Results SOC")
    output.seek(0)
    st.download_button(
        "📥 Gefilterte Ergebnisse als Excel",
        output.getvalue(),
        file_name="full_piste_results_soc.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # --- Grafik: Kurve und Durchschnittswert für Totalpunkte ---
    if not filtered.empty and "totalpoints" in filtered.columns:
        df_plot = filtered.copy()
        df_plot["totalpoints"] = pd.to_numeric(df_plot["totalpoints"], errors="coerce")
        df_plot = df_plot.dropna(subset=["totalpoints"])
        df_plot = df_plot.sort_values("totalpoints", ascending=True).reset_index(drop=True)
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(df_plot.index + 1, df_plot["totalpoints"], marker="o", label="Totalpunkte")
        mean_val = df_plot["totalpoints"].mean()
        ax.axhline(mean_val, color="red", linestyle="--", label=f"Ø Totalpunkte: {mean_val:.1f}")
        ax.set_xlabel("Athlet (sortiert)")
        ax.set_ylabel("Totalpunkte")
        ax.set_title("Totalpunkte aller gefilterten Athleten")
        ax.legend()
        st.pyplot(fig)

    # --- Grafik für Talentcard-Verteilung ---
    if not filtered.empty and "talentcard" in filtered.columns:
        chart_labels = filtered.apply(
            lambda row: "Verletzt" if str(row.get("injured", "")).strip().lower() == "yes" else row.get("talentcard"),
            axis=1,
        )
        card_counts = chart_labels.value_counts().reindex(["Verletzt", "National", "Regional", "noCard"], fill_value=0)
        fig2, ax2 = plt.subplots(figsize=(5, 3))
        bars = ax2.bar(card_counts.index, card_counts.values, color=["#9467bd", "#1f77b4", "#2ca02c", "#d62728"])
        ax2.set_ylabel("Anzahl Athleten")
        ax2.set_title("Verteilung Talentcard")
        for bar in bars:
            height = bar.get_height()
            ax2.annotate(f"{int(height)}", xy=(bar.get_x() + bar.get_width() / 2, height),
                         xytext=(0, 3), textcoords="offset points", ha="center", va="bottom")
        st.pyplot(fig2)

def vergleich_big_competitions():
    st.header("🏆 Vergleich Big Competitions")

    # Daten laden
    compresultsbig = pd.DataFrame(fetch_all_rows("compresultsbig", select="*"))
    compresults = pd.DataFrame(fetch_all_rows("compresults", select="*"))
    competitions = pd.DataFrame(fetch_all_rows("competitions", select="*"))

    if compresultsbig.empty or compresults.empty or competitions.empty:
        st.info("Nicht genügend Daten vorhanden.")
        # Import-Bereich trotzdem anzeigen!
        show_big_comp_import()
        return

    # Personenauswahl ohne Vorauswahl
    all_names = sorted(set((row["first_name"], row["last_name"]) for _, row in compresults.iterrows()))
    name_options = [f"{fn} {ln}" for fn, ln in all_names]
    selected_name = st.selectbox("Person auswählen", [""] + name_options, index=0)
    if not selected_name:
        st.info("Bitte eine Person auswählen.")
        return
    sel_first, sel_last = selected_name.split(" ", 1)

    # Jahr ohne Vorauswahl
    years_big = sorted(compresultsbig["year"].dropna().unique())
    selected_year_big = st.selectbox("Jahr (Big Competitions)", [""] + years_big, index=0)
    if not selected_year_big:
        st.info("Bitte ein Jahr auswählen.")
        return

    # Vergleichswettkampf ohne Vorauswahl
    competitions_big = sorted(compresultsbig[compresultsbig["year"] == selected_year_big]["competition"].dropna().unique())
    selected_competition_big = st.selectbox("Vergleichswettkampf (Big Competition)", [""] + competitions_big, index=0)
    if not selected_competition_big:
        st.info("Bitte einen Vergleichswettkampf auswählen.")
        return
    # Jahr aus competitions.Date
    competitions["year"] = competitions["Date"].astype(str).str[:4]
    years_comp = sorted(competitions["year"].dropna().unique())
    selected_year_comp = st.selectbox("Jahr (Wettkämpfe)", [""] + years_comp, index=0)
    if not selected_year_comp:
        st.info("Bitte ein Jahr für Wettkämpfe auswählen.")
        return

    # Filter für Person und Jahr
    person_results = compresults[
        (compresults["first_name"] == sel_first) &
        (compresults["last_name"] == sel_last)
    ]
    # Filter competitions auf das gewählte Jahr
    competitions_year = competitions[competitions["year"] == str(selected_year_comp)]

    # Filter big results auf Jahr und Vergleichswettkampf
    big_results = compresultsbig[
        (compresultsbig["year"] == selected_year_big) &
        (compresultsbig["competition"] == selected_competition_big)
    ]

    # Mapping für schnellen Zugriff: (discipline, sex, category, rank) -> points
    big_map = {}
    for _, row in big_results.iterrows():
        key = (
            str(row["discipline"]).strip().lower(),
            str(row["sex"]).strip().lower(),
            str(row["category"]).strip().lower(),
            str(row["rank"]).strip()
        )
        big_map[key] = row["points"]

    output_rows = []
    for _, comp in competitions_year.iterrows():
        comp_name = comp["Name"] if "Name" in comp else comp.get("name", "")
        comp_discipline = comp.get("Discipline", None)
        comp_sex = comp.get("sex", None)
        comp_category = comp.get("category", None)
        comp_date = comp.get("Date", "")[:10]
        # Hole alle Ergebnisse dieser Person für diesen Wettkampf
        person_comp = person_results[person_results["Competition"] == comp_name]
        if person_comp.empty:
            continue
        for _, res in person_comp.iterrows():
            # Vereinheitliche die Keys!
            discipline = str(res.get("Discipline", comp_discipline)).strip().lower()
            sex = str(res.get("sex", comp_sex)).strip().lower()
            # Hier: CategoryStart aus compresults, category aus compresultsbig
            category = str(res.get("CategoryStart", comp_category)).strip().lower()
            points = res.get("Points", None)
            try:
                points = float(points)
            except Exception:
                points = None
            row_out = {
                "Competition": comp_name,
                "Datum": comp_date,
                "Discipline": discipline,
                "sex": sex,
                "category": category,
                "Points": points,
                "Vergleichswettkampf": selected_competition_big  # NEU
            }

            # Für alle gewünschten Ränge vergleichen
            for rank in ["1", "2", "3", "QualF", "QualHF"]:
                key = (discipline, sex, category, rank)
                big_points = big_map.get(key)
                try:
                    big_points = float(big_points)
                except Exception:
                    big_points = None
                percent = None
                if big_points not in (None, "", "nan") and points not in (None, "", "nan"):
                    try:
                        percent = round((points / big_points) * 100, 1) if big_points != 0 else None
                    except Exception:
                        percent = None
                row_out[f"% zu Rank {rank}"] = percent
            output_rows.append(row_out)

    # --- CSV-Import für compresultsbig IMMER anzeigen ---
    show_big_comp_import()

    if not output_rows:
        st.info("Keine passenden Vergleiche gefunden.")
        return

    df_out = pd.DataFrame(output_rows)
    # Optional: Vergleichswettkampf-Spalte nach vorne
    cols = ["Vergleichswettkampf"] + [c for c in df_out.columns if c != "Vergleichswettkampf"]
    df_out = df_out[cols]
    st.download_button("📥 Vergleich als CSV herunterladen", df_out.to_csv(index=False, encoding='utf-8-sig'), file_name="vergleich_big_competitions.csv", mime="text/csv")
    st.dataframe(df_out)

# Hilfsfunktion für den Importbereich (damit er immer angezeigt wird)
def show_big_comp_import():
    st.markdown("---")
    st.subheader("📤 Big Competitions Ergebnisse importieren (CSV)")

    example = pd.DataFrame([{
        "competition": "Swiss Open",
        "year": 2024,
        "discipline": "1m",
        "category": "Jugend B",
        "sex": "male",
        "rank": "1",
        "points": 400
    }])
    st.download_button("📄 Beispiel-CSV herunterladen", example.to_csv(index=False).encode("utf-8"), file_name="big_compresults_beispiel.csv", mime="text/csv")

    uploaded_file = st.file_uploader("CSV-Datei mit Big Competitions Ergebnissen hochladen", type=["csv"])
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        required_cols = {"competition", "year", "discipline", "category", "sex", "rank", "points"}
        if not required_cols.issubset(df.columns):
            st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_cols)}")
            return

        # Lade bestehende Einträge für schnellen Vergleich
        existing_rows = pd.DataFrame(fetch_all_rows("compresultsbig", select="competition,year,discipline,category,sex,rank"))
        existing_keys = set(
            tuple(str(row[c]).strip().lower() for c in ["competition", "year", "discipline", "category", "sex", "rank"])
            for _, row in existing_rows.iterrows()
        )

        inserted = 0
        skipped = []
        for _, row in df.iterrows():
            key = tuple(str(row[c]).strip().lower() for c in ["competition", "year", "discipline", "category", "sex", "rank"])
            if key in existing_keys:
                skipped.append({c: row[c] for c in required_cols})
                continue
            # Insert
            try:
                db.table_insert("compresultsbig", {
                    "competition": row["competition"],
                    "year": int(row["year"]),
                    "discipline": row["discipline"],
                    "category": row["category"],
                    "sex": row["sex"],
                    "rank": str(row["rank"]),
                    "points": float(row["points"])
                })
                inserted += 1
                existing_keys.add(key)
            except Exception as e:
                st.warning(f"Fehler beim Import: {row.to_dict()} | {e}")

        st.success(f"✅ {inserted} neue Ergebnisse importiert.")
        if skipped:
            st.warning(f"{len(skipped)} Einträge waren bereits vorhanden und wurden nicht importiert:")
            st.dataframe(pd.DataFrame(skipped))

def athleten_anzeigen():
    st.header("👥 Athleten anzeigen & exportieren")

    # Daten laden
    try:
        df = pd.DataFrame(fetch_all_rows("athletes", select="*"))
    except Exception as e:
        st.error(f"Athleten konnten nicht geladen werden: {type(e).__name__}: {e}")
        return

    if df.empty:
        st.info("Keine Athleten gefunden.")
        return

    # Nur gewünschte Spalten
    show_cols = ["first_name", "last_name", "birthdate", "club", "category", "sex", "nationalteam", "vintage", "bioage"]
    for col in show_cols:
        if col not in df.columns:
            df[col] = None
    df = df[show_cols]

    def _options(series):
        values = (
            series.dropna()
            .astype(str)
            .str.strip()
        )
        values = values[values != ""]
        return sorted(values.unique().tolist())

    # Filter
    st.subheader("🔎 Filter")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        first_name = st.text_input("Vorname", "")
        last_name = st.text_input("Nachname", "")
    with col2:
        club = st.selectbox("Verein", ["Alle"] + _options(df["club"]))
        category = st.selectbox("Kategorie", ["Alle"] + _options(df["category"]))
    with col3:
        sex = st.selectbox("Geschlecht", ["Alle"] + _options(df["sex"]))
        nationalteam = st.selectbox("Nationalteam", ["Alle"] + _options(df["nationalteam"]))
    with col4:
        vintage = st.selectbox("Jahrgang", ["Alle"] + _options(df["vintage"]))

    filtered = df.copy()
    if first_name:
        filtered = filtered[filtered["first_name"].str.contains(first_name, case=False, na=False)]
    if last_name:
        filtered = filtered[filtered["last_name"].str.contains(last_name, case=False, na=False)]
    if club != "Alle":
        filtered = filtered[filtered["club"] == club]
    if category != "Alle":
        filtered = filtered[filtered["category"] == category]
    if sex != "Alle":
        filtered = filtered[filtered["sex"] == sex]
    if nationalteam != "Alle":
        filtered = filtered[filtered["nationalteam"] == nationalteam]
    if vintage != "Alle":
        filtered = filtered[filtered["vintage"].astype(str) == str(vintage)]

    st.dataframe(filtered)
    st.download_button("📥 Gefilterte Athleten als CSV", filtered.to_csv(index=False, encoding='utf-8-sig'), file_name="athleten.csv", mime="text/csv")

def selektionen_wettkaempfe():
    st.header("🏅 Selektionen Wettkämpfe")

    # Alle Competitions auf einmal laden
    competitions = fetch_all_rows('competitions', select='Name, PisteYear')
    comp_year_map = {c['Name']: c.get('PisteYear') for c in competitions if c.get('Name')}

    compresults = db.table_select('compresults', '*')
    selectionpoints = fetch_all_rows('selectionpoints', select='Competition, year, Discipline, sex, category, points')
    df_selectionpoints = pd.DataFrame(selectionpoints)

    def _norm_text(val):
        return str(val or "").strip().lower()

    def _safe_float(val):
        if val in (None, "", "nan"):
            return None
        try:
            if isinstance(val, str):
                val = val.strip().replace("%", "").replace(",", ".")
            return float(val)
        except Exception:
            return None

    def _is_yes(val):
        return _norm_text(val) == "yes"

    def _calc_limit_pct(result_row, limit_competition, sex_fallback=None):
        points_val = _safe_float(result_row.get("Points"))
        if points_val is None:
            return None, None

        discipline = _norm_text(result_row.get("Discipline"))
        sex = _norm_text(result_row.get("sex")) or _norm_text(sex_fallback)
        category = _norm_text(result_row.get("CategoryStart"))

        lim = df_selectionpoints[
            (df_selectionpoints["Competition"].astype(str).str.strip().str.lower() == _norm_text(limit_competition))
            & (df_selectionpoints["year"].astype(str).str.strip() == str(selected_year).strip())
            & (df_selectionpoints["Discipline"].astype(str).str.strip().str.lower() == discipline)
            & (df_selectionpoints["sex"].astype(str).str.strip().str.lower() == sex)
            & (df_selectionpoints["category"].astype(str).str.strip().str.lower() == category)
        ]
        if lim.empty:
            return None, None

        limit_val = _safe_float(lim.iloc[0].get("points"))
        if not limit_val:
            return None, None

        return limit_val, round((points_val / limit_val) * 100, 1)

    # Schneller: Jahre aus compresults + Mapping
    years = sorted(
        set(
            str(comp_year_map.get(r.get('Competition')))
            for r in compresults
            if comp_year_map.get(r.get('Competition'))
        ),
        reverse=True
    )
    selected_year = st.selectbox("Jahr wählen", years)

    selektionstypen = {
        "Nationalkader": "NationalTeam",
        "JEM": "JEM",
        "EM": "EM",
        "WM": "WM"
    }
    selected_tab = st.selectbox("Selektionstyp", list(selektionstypen.keys()))

    # Filter nach Jahr (Competition → PisteYear)
    filtered_year = [
        r for r in compresults
        if comp_year_map.get(r.get('Competition')) and str(comp_year_map.get(r.get('Competition'))) == str(selected_year)
    ]

    # Filter nach Selektionstyp
    spalte = selektionstypen[selected_tab]
    filtered = [r for r in filtered_year if _is_yes(r.get(spalte, ""))]

    # Anzeige-Spalten
    show_cols = ["first_name", "last_name", "sex", "CategoryStart", "Competition", "Discipline", "Points"]

    def _pct_style(val):
        if val in (None, "", "nan"):
            return ""
        try:
            v = float(val)
        except Exception:
            return ""
        if v >= 100:
            return "background-color: #d1fae5; color: #065f46; font-weight: 600;"
        if v >= 90:
            return "background-color: #ffedd5; color: #9a3412; font-weight: 600;"
        return "background-color: #f3f4f6; color: #374151;"

    df = pd.DataFrame(filtered)
    if selected_tab in ["JEM", "EM"] and not df.empty:
        # Robuste Verknüpfung über Name; Sex bei Zusatzdisziplinen kann fehlen/abweichen.
        yes_athletes = set(
            (
                _norm_text(r.get("first_name")),
                _norm_text(r.get("last_name")),
            )
            for _, r in df.iterrows()
        )

        sex_by_athlete = {}
        for _, r in df.iterrows():
            key = (_norm_text(r.get("first_name")), _norm_text(r.get("last_name")))
            sex_val = _norm_text(r.get("sex"))
            if key != ("", "") and sex_val and key not in sex_by_athlete:
                sex_by_athlete[key] = sex_val

        integrated_rows = []
        for r in filtered_year:
            athlete_key = (
                _norm_text(r.get("first_name")),
                _norm_text(r.get("last_name")),
            )
            if athlete_key not in yes_athletes:
                continue

            athlete_name_key = (_norm_text(r.get("first_name")), _norm_text(r.get("last_name")))
            sex_fallback = sex_by_athlete.get(athlete_name_key)

            limit_val, pct = _calc_limit_pct(r, selected_tab, sex_fallback=sex_fallback)
            is_yes = _is_yes(r.get(spalte, ""))
            is_extra_90 = pct is not None and pct >= 90

            # Hauptliste integriert: Selektion=yes ODER zusätzliche Disziplin >=90%
            if not is_yes and not is_extra_90:
                continue

            if pct is None:
                ampel = "⚪"
            elif pct >= 100:
                ampel = "🟢"
            elif pct >= 90:
                ampel = "🟠"
            else:
                ampel = "⚪"

            integrated_rows.append({
                "Ampel": ampel,
                "Quelle": "Direkt qualifiziert" if is_yes else "Zusatzdisziplin 90+",
                "first_name": r.get("first_name"),
                "last_name": r.get("last_name"),
                "sex": r.get("sex"),
                "CategoryStart": r.get("CategoryStart"),
                "Competition": r.get("Competition"),
                "Discipline": r.get("Discipline"),
                "Points": _safe_float(r.get("Points")),
                f"{selected_tab} Limite": limit_val,
                "% zur Limite": pct,
            })

        df_show = pd.DataFrame(integrated_rows)
        if not df_show.empty:
            key_cols = ["first_name", "last_name", "sex", "CategoryStart", "Competition", "Discipline"]
            df_show = (
                df_show.sort_values("% zur Limite", ascending=False, na_position="last")
                .drop_duplicates(subset=key_cols, keep="first")
                .sort_values(["last_name", "first_name", "Competition", "Discipline"])
                .reset_index(drop=True)
            )

            # Zusatzfilter für die integrierte JEM/EM-Tabelle
            st.subheader("🔎 Tabellenfilter")
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                first_filter = st.text_input("Vorname enthält", key=f"sel_{selected_tab}_first_filter")
            with col_f2:
                last_filter = st.text_input("Nachname enthält", key=f"sel_{selected_tab}_last_filter")
            with col_f3:
                threshold_filter = st.selectbox(
                    "Schwelle",
                    ["Alle", ">=100%", "nur 90% bis <100%"],
                    key=f"sel_{selected_tab}_threshold_filter",
                )

            categories = sorted([c for c in df_show["CategoryStart"].dropna().astype(str).unique().tolist() if c.strip()])
            selected_categories = st.multiselect(
                "Kategorie",
                categories,
                default=categories,
                key=f"sel_{selected_tab}_category_filter",
            )

            df_filtered_show = df_show.copy()
            if first_filter:
                df_filtered_show = df_filtered_show[df_filtered_show["first_name"].astype(str).str.contains(first_filter, case=False, na=False)]
            if last_filter:
                df_filtered_show = df_filtered_show[df_filtered_show["last_name"].astype(str).str.contains(last_filter, case=False, na=False)]
            if selected_categories:
                df_filtered_show = df_filtered_show[df_filtered_show["CategoryStart"].astype(str).isin(selected_categories)]
            if threshold_filter == ">=100%":
                df_filtered_show = df_filtered_show[pd.to_numeric(df_filtered_show["% zur Limite"], errors="coerce") >= 100]
            elif threshold_filter == "nur 90% bis <100%":
                pct_num = pd.to_numeric(df_filtered_show["% zur Limite"], errors="coerce")
                df_filtered_show = df_filtered_show[(pct_num >= 90) & (pct_num < 100)]

            st.dataframe(df_filtered_show.style.map(_pct_style, subset=["% zur Limite"]))
            st.download_button("📥 Ergebnisse als CSV herunterladen", df_filtered_show.to_csv(index=False, encoding='utf-8-sig'), file_name=f"{selected_tab}_{selected_year}.csv", mime="text/csv")
        else:
            st.info("Keine passenden Einträge gefunden.")
    else:
        if not df.empty:
            df_show = df[show_cols]
            st.dataframe(df_show)
            st.download_button("📥 Ergebnisse als CSV herunterladen", df_show.to_csv(index=False, encoding='utf-8-sig'), file_name=f"{selected_tab}_{selected_year}.csv", mime="text/csv")
        else:
            st.info("Keine passenden Einträge gefunden.")

    # --- NEU: Einzigartige Liste (jede Person nur einmal) ---
    st.subheader("👤 Einzigartige Liste (jede Person nur einmal)")
    if not df.empty:
        unique_cols = ["first_name", "last_name", "sex", "CategoryStart"]
        df_unique = df.drop_duplicates(subset=unique_cols)[unique_cols]
        st.dataframe(df_unique)
        st.download_button(
            "📥 Einzigartige Liste als CSV herunterladen",
            df_unique.to_csv(index=False, encoding='utf-8-sig'),
            file_name=f"{selected_tab}_{selected_year}_einzigartig.csv",
            mime="text/csv"
        )
    else:
        st.info("Keine Einträge für die einzigartige Liste gefunden.")

    # Die frühere separate Zusatzliste ist in die Hauptliste integriert.

def referenztabellen_anzeigen():
    st.header("📚 Referenz- und Bewertungstabellen")

    try:
        ensure_kaderthresholds_table()
    except Exception as e:
        st.warning(f"Kader-Schwellen konnten nicht initialisiert werden: {e}")

    pistedisciplines = pd.DataFrame(fetch_all_rows("pistedisciplines", select="id,name"))
    discipline_name_by_id = {}
    if not pistedisciplines.empty:
        discipline_name_by_id = dict(zip(pistedisciplines["id"], pistedisciplines["name"]))

    def _norm(v):
        if pd.isna(v):
            return None
        if isinstance(v, pd.Timestamp):
            return v.date().isoformat()
        if isinstance(v, datetime.datetime):
            return v.date().isoformat()
        if isinstance(v, datetime.date):
            return v.isoformat()
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        return v

    def _render_inline_table(title, table_name, columns, key_prefix, filters=None, int_id=False, sort_by=None, persist_columns=None, disabled_cols=None, preprocess_fn=None, hidden_cols=None):
        st.subheader(title)
        rows = fetch_all_rows(table_name, select="*", **(filters or {}))
        df = pd.DataFrame(rows)

        def _normalize_id_value(v):
            if pd.isna(v):
                return None
            if isinstance(v, str):
                s = v.strip()
                if not s or s.lower() == "nan":
                    return None
                if int_id:
                    try:
                        return str(int(float(s)))
                    except Exception:
                        return None
                return s
            if int_id:
                try:
                    return str(int(float(v)))
                except Exception:
                    return None
            return str(v)

        for col in columns:
            if col not in df.columns:
                df[col] = None

        if sort_by:
            safe_sort = [c for c in sort_by if c in df.columns]
            if safe_sort and not df.empty:
                df = df.sort_values(safe_sort)

        if preprocess_fn:
            df = preprocess_fn(df)

        editable = df[columns].copy().reset_index(drop=True)
        persist_cols = persist_columns or columns
        disabled = disabled_cols or (["id"] if "id" in columns else [])
        hidden = set(hidden_cols or [])
        column_config = {col: None for col in hidden if col in editable.columns}
        edited = st.data_editor(
            editable,
            hide_index=True,
            num_rows="dynamic",
            disabled=disabled,
            column_config=column_config,
            key=f"{key_prefix}_editor",
        )

        if st.button(f"💾 {title} speichern", key=f"{key_prefix}_save"):
            if "id" not in columns:
                st.error("Diese Tabelle kann nicht gespeichert werden (id-Spalte fehlt).")
                return

            orig = editable.copy()
            new = edited.copy()

            orig["id"] = orig["id"].apply(_normalize_id_value)
            new["id"] = new["id"].apply(_normalize_id_value)

            orig_name_by_id = {}
            if table_name == "competitions" and "Name" in orig.columns:
                for _, orig_row in orig.iterrows():
                    rid = orig_row.get("id")
                    if rid:
                        name_val = _norm(orig_row.get("Name"))
                        orig_name_by_id[str(rid)] = str(name_val or "").strip()

            orig_ids = {v for v in orig["id"].tolist() if v}
            new_ids = {v for v in new["id"].tolist() if v}

            for del_id in sorted(orig_ids - new_ids):
                db.table_delete(table_name, id=int(del_id) if int_id else del_id)

            if int_id:
                int_existing = []
                for v in orig_ids:
                    try:
                        int_existing.append(int(v))
                    except Exception:
                        pass
                next_id = (max(int_existing) + 1) if int_existing else 1

            cascade_compresults_total = 0
            cascade_ref_total = 0

            for _, row in new.iterrows():
                row_id = _normalize_id_value(row.get("id"))
                payload = {c: _norm(row.get(c)) for c in persist_cols if c != "id"}
                payload = {k: v for k, v in payload.items() if v is not None}

                if not payload:
                    continue

                if not row_id:
                    if int_id:
                        while str(next_id) in orig_ids:
                            next_id += 1
                        payload["id"] = next_id
                        db.table_insert(table_name, payload)
                        orig_ids.add(str(next_id))
                        next_id += 1
                    else:
                        db.table_insert(table_name, payload)
                else:
                    db.table_update(table_name, payload, id=int(row_id) if int_id else row_id)

                    if table_name == "competitions":
                        old_name = orig_name_by_id.get(str(row_id), "")
                        new_name = str(_norm(row.get("Name")) or "").strip()
                        if old_name and new_name and old_name.lower() != new_name.lower():
                            cascade_counts = cascade_competition_rename(old_name, new_name)
                            cascade_compresults_total += cascade_counts["compresults"]
                            cascade_ref_total += cascade_counts["pisterefcompresults"]

            if table_name == "competitions":
                st.success(
                    f"{title} gespeichert. Verknüpfungen aktualisiert: "
                    f"compresults={cascade_compresults_total}, "
                    f"pisterefcompresults={cascade_ref_total}."
                )
            else:
                st.success(f"{title} gespeichert.")
            st.rerun()

    def _add_discipline_name(df):
        if "discipline_id" in df.columns:
            df = df.copy()
            df["discipline_name"] = df["discipline_id"].map(lambda v: discipline_name_by_id.get(v, "Unbekannt"))
        return df

    # Haupttabellen
    _render_inline_table(
        title="🏅 Scoretabelle",
        table_name="scoretables",
        columns=["id", "discipline_name", "discipline_id", "category", "sex", "result_min", "result_max", "points"],
        persist_columns=["id", "discipline_id", "category", "sex", "result_min", "result_max", "points"],
        disabled_cols=["id", "discipline_name"],
        hidden_cols=["id", "discipline_id"],
        preprocess_fn=_add_discipline_name,
        key_prefix="scoretables",
        int_id=False,
        sort_by=["discipline_id", "category", "sex", "result_min"],
    )

    _render_inline_table(
        title="🎯 Selectionpoints",
        table_name="selectionpoints",
        columns=["id", "Competition", "year", "category", "Discipline", "sex", "points", "difficulty"],
        key_prefix="selectionpoints",
        int_id=True,
        sort_by=["Competition", "year", "category", "Discipline", "sex"],
    )

    st.subheader("🧮 Kader %-Schwellen")
    try:
        threshold_rows = fetch_all_rows(
            "socadditionalvalues",
            select="id, first_name, last_name, CompPointsNationalTeam, CompPointsRegionalTeam, quality",
            toolenvironment="kaderthresholds",
        )
        df_thr = pd.DataFrame(threshold_rows)
        for c in ["id", "first_name", "last_name", "CompPointsNationalTeam", "CompPointsRegionalTeam", "quality"]:
            if c not in df_thr.columns:
                df_thr[c] = None
        df_thr = df_thr[["id", "first_name", "last_name", "CompPointsNationalTeam", "CompPointsRegionalTeam", "quality"]].copy()
        df_thr = df_thr.rename(
            columns={
                "first_name": "discipline",
                "last_name": "category_group",
                "CompPointsNationalTeam": "national_percent",
                "CompPointsRegionalTeam": "regional_percent",
                "quality": "notes",
            }
        )
        df_thr = df_thr.sort_values(["discipline", "category_group"], na_position="last").reset_index(drop=True)

        edited_thr = st.data_editor(
            df_thr,
            hide_index=True,
            num_rows="dynamic",
            key="kaderthresholds_editor",
        )

        if st.button("💾 🧮 Kader %-Schwellen speichern", key="kaderthresholds_save"):
            orig = df_thr.copy()
            new = edited_thr.copy()

            def _norm_id(v):
                if pd.isna(v):
                    return None
                try:
                    return str(int(float(v)))
                except Exception:
                    return None

            orig["id"] = orig["id"].apply(_norm_id)
            new["id"] = new["id"].apply(_norm_id)

            orig_ids = {v for v in orig["id"].tolist() if v}
            new_ids = {v for v in new["id"].tolist() if v}
            for del_id in sorted(orig_ids - new_ids):
                db.table_delete("socadditionalvalues", id=int(del_id))

            for _, r in new.iterrows():
                rid = _norm_id(r.get("id"))
                discipline = _norm(r.get("discipline"))
                category_group = _norm(r.get("category_group")) or "all"
                nat = _norm(r.get("national_percent"))
                reg = _norm(r.get("regional_percent"))
                notes = _norm(r.get("notes"))

                if not discipline:
                    continue

                payload = {
                    "toolenvironment": "kaderthresholds",
                    "PisteYear": "global",
                    "first_name": discipline,
                    "last_name": category_group,
                    "CompPointsNationalTeam": nat,
                    "CompPointsRegionalTeam": reg,
                    "quality": notes,
                }
                if rid:
                    db.table_update("socadditionalvalues", payload, id=int(rid))
                else:
                    db.table_insert("socadditionalvalues", payload)

            st.success("Kader %-Schwellen gespeichert.")
            st.rerun()
    except Exception as e:
        st.warning(f"Kader-Schwellen konnten nicht angezeigt werden: {e}")

    _render_inline_table(
        title="🏟️ Wettkämpfe (Competitions)",
        table_name="competitions",
        columns=[
            "id",
            "Name",
            "Date",
            "PisteYear",
            "Type",
            "qual-Regional",
            "qual-National",
            "qual-JEM",
            "qual-EM",
            "qual-WM",
            "qual-Piste",
        ],
        key_prefix="competitions",
        int_id=True,
        sort_by=["Date", "Name"],
    )

    _render_inline_table(
        title="⏱️ Piste Ref Training Time",
        table_name="pistereftrainingtime",
        columns=["id", "age"] + [str(i) for i in range(4, 31)],
        key_prefix="pistereftrainingtime",
        int_id=True,
        sort_by=["age"],
    )

    _render_inline_table(
        title="📅 Piste Ref Training Since",
        table_name="pistereftrainingsince",
        columns=["id", "age"] + [str(i) for i in range(0, 15)],
        key_prefix="pistereftrainingsince",
        int_id=True,
        sort_by=["age"],
    )

    _render_inline_table(
        title="🔢 Piste Ref Min Points",
        table_name="pisterefminpoints",
        columns=["id", "age", "points_max", "regio_min", "national_min"],
        key_prefix="pisterefminpoints",
        int_id=True,
        sort_by=["age"],
    )

    _render_inline_table(
        title="🏆 Piste Ref Comp Points",
        table_name="pisterefcomppoints",
        columns=["id", "Discipline", "sex"] + [str(i) for i in range(8, 20)] + [f"quality{i}" for i in range(8, 20)],
        key_prefix="pisterefcomppoints",
        int_id=True,
        sort_by=["Discipline", "sex"],
    )

    if not pistedisciplines.empty:
        special_disciplines = [
            ("🏅 Piste Points (PisteTotalinPoints)", "PisteTotalinPoints", "piste_totalinpoints"),
            ("📈 Leistungsentwicklung (CompPerfEnhance)", "CompPerfEnhance", "comp_perf_enhance"),
            ("🏅 Wettkampf Performance (CompPerfPointsCalc)", "CompPerfPointsCalc", "comp_perf_points"),
            ("🤸 Sprung Qualität (CompPerfQualityCalc)", "CompPerfQualityCalc", "comp_perf_quality"),
        ]
        for title, disc_name, key_prefix in special_disciplines:
            matches = pistedisciplines[pistedisciplines["name"] == disc_name]
            if matches.empty:
                st.info(f"Disziplin '{disc_name}' nicht gefunden.")
                continue
            discipline_id = matches["id"].iloc[0]
            _render_inline_table(
                title=title,
                table_name="scoretables",
                columns=["id", "discipline_name", "discipline_id", "category", "sex", "result_min", "result_max", "points"],
                persist_columns=["id", "discipline_id", "category", "sex", "result_min", "result_max", "points"],
                disabled_cols=["id", "discipline_name", "discipline_id"],
                hidden_cols=["id", "discipline_id"],
                preprocess_fn=_add_discipline_name,
                key_prefix=key_prefix,
                filters={"discipline_id": discipline_id},
                int_id=False,
                sort_by=["category", "sex", "result_min"],
            )

def athleten_eingeben():
    st.header("📝 Neuen Athleten hinzufügen")

    # Sekundäre Aktionen direkt hier verfügbar machen
    st.markdown("#### ⚙️ Zusätzliche Aktionen")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📥 Athleten importieren"):
            import_athletes()
    with col2:
        if st.button("✏️ Athleten bearbeiten"):
            edit_athletes()

    st.markdown("---")

    # Standardformular zum Hinzufügen
    first_name = st.text_input("Vorname")
    last_name = st.text_input("Nachname")
    birthdate = st.date_input("Geburtsdatum", min_value=datetime.date(1920, 1, 1), max_value=datetime.date.today())
    sex = st.selectbox("Geschlecht", ["male", "female"])

    teams = db.table_select('team', 'FullName, ShortName')
    club_options = [t['FullName'] for t in teams if t.get('FullName')]
    club = st.selectbox("Verein", club_options)

    nationalteam = st.selectbox("Nationalteam", ["yes", "no"])
    vintage = birthdate.year
    full_name = f"{first_name} {last_name}"
    category = get_category_from_testyear(vintage, datetime.date.today().year)

    # Quartal berechnen und in bioage speichern
    bioage = get_birth_quarter(birthdate)

    if st.button("Athlet speichern"):
        # Prüfen, ob Athlet bereits existiert
        existing = db.table_select('athletes', 'id',
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            birthdate=birthdate.strftime('%Y-%m-%d'))
        if existing:
            st.error(f"Athlet {full_name} mit Geburtsdatum {birthdate.strftime('%Y-%m-%d')} existiert bereits!")
        else:
            db.table_insert('athletes', {
                'first_name': first_name,
                'last_name': last_name,
                'birthdate': birthdate.strftime('%Y-%m-%d'),
                'sex': sex,
                'club': club,
                'nationalteam': nationalteam,
                'vintage': vintage,
                'full_name': full_name,
                'category': category,
                'bioage': bioage
            })
            st.success(f"Athlet {full_name} gespeichert!")

def show_full_piste_results_clubs():
    st.header("📊 Full PISTE Results for Clubs")

    # Daten laden
    soc_df = pd.DataFrame(fetch_all_rows("socadditionalvalues", select="*"))
    athletes_df = pd.DataFrame(fetch_all_rows("athletes", select="first_name,last_name,club,birthdate,sex"))

    if soc_df.empty or athletes_df.empty:
        st.info("Keine Daten gefunden.")
        return

    # Merge für Club, Birthdate, Sex
    merged = soc_df.merge(
        athletes_df,
        how="left",
        left_on=["first_name", "last_name"],
        right_on=["first_name", "last_name"],
        suffixes=("", "_athlete")
    )

    # Alter berechnen (aus PisteYear und birthdate)
    merged["Age"] = merged.apply(
        lambda r: int(r["PisteYear"]) - int(str(r["birthdate"])[:4]) if pd.notnull(r["birthdate"]) and pd.notnull(r["PisteYear"]) else None,
        axis=1
    )

    # Bio berechnen
    bio_fields = [
        "trainingperf", "compenhancement", "resilience", "trainingtime",
        "trainingsince", "toolenvironment", "quality", "bioagevalue", "mirwaldvalue"
    ]
    merged["Bio"] = merged[bio_fields].apply(
        lambda row: sum([float(row[f]) for f in bio_fields if pd.notnull(row[f]) and str(row[f]) not in ("", "nan")]), axis=1
    )

    # Spalten umbenennen und zusammenstellen
    show_cols = {
        "PisteYear": "Piste Year",
        "first_name": "First Name",
        "last_name": "Last Name",
        "birthdate": "Birthdate",
        "Age": "Age",
        "Category": "Category",
        "sex_athlete": "Sex",
        "club": "Club",
        "piste": "Piste Sport",
        "Bio": "Bio",
        "competitions": "Performance",
        "totalpoints": "Totalpoints",
        "pisteminregio": "Piste Regional Min",
        "CompPointsRegionalTeam": "Competition RegionalTeam",
        "pisteminnational": "Piste National Min",
        "CompPointsNationalTeam": "Competition NationalTeam",
        "talentcard": "SOC"
        

    }
    # Füge fehlende Spalten als None hinzu
    for k in show_cols:
        if k not in merged.columns:
            merged[k] = None

    df_show = merged[list(show_cols.keys())].rename(columns=show_cols)

    # Filter
    clubs = sorted(df_show["Club"].dropna().unique())
    socs = sorted(df_show["SOC"].dropna().unique())
    years = sorted(df_show["Piste Year"].dropna().unique())

    club = st.selectbox("Club", ["Alle"] + clubs)
    soc = st.selectbox("SOC", ["Alle"] + socs)
    year = st.selectbox("Piste Year", ["Alle"] + [str(y) for y in years])

    filtered = df_show.copy()
    if club != "Alle":
        filtered = filtered[filtered["Club"] == club]
    if soc != "Alle":
        filtered = filtered[filtered["SOC"] == soc]
    if year != "Alle":
        filtered = filtered[filtered["Piste Year"].astype(str) == year]

    st.dataframe(filtered)

    # CSV-Export
    st.download_button(
        "📥 Gefilterte Ergebnisse als CSV",
        filtered.to_csv(index=False, encoding='utf-8-sig'),
        file_name="full_piste_results_clubs.csv",
        mime="text/csv"
    )

    # XLSX-Export
    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        filtered.to_excel(writer, index=False, sheet_name="Full PISTE Results Clubs")
    output.seek(0)
    st.download_button(
        "📥 Gefilterte Ergebnisse als Excel",
        output.getvalue(),
        file_name="full_piste_results_clubs.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# Hauptmenü
def main():
    if "page" not in st.session_state:
        st.session_state["page"] = "Startseite"

    menu = [
        "Startseite",
        "Athleten eingeben",
        "Athleten importieren",
        "Athleten bearbeiten",
        "Athleten löschen",
        "Athleten anzeigen",
        "Piste Mirwald",
        "Piste Resultate anzeigen",
        "Piste Ergebnisse eingeben",
        "Piste Ergebnisse bearbeiten",
        "Piste Punkte neu berechnen",
        "Wettkampfauswertungen",
        "Wettkampf-Bewertung",
        "Wettkampfresultate eingeben",
        "Wettkampfresultate korrigieren",
        "Wettkaempfe Top 3",
        "Wettkampf-Performance pro Athlet",
        "Piste RefPoint Competition Analyse",
        "Tool Environment",
        "Piste Mirwald",
        "Trainingsperformance - Resilienz",
        "SOC Full Calculation",
        "Full PISTE Results SOC",
        "Full PISTE Results for Clubs",
        "Selektionen Wettkämpfe",
        "Vergleich BIG Competitions",
        "Referenz- und Bewertungstabellen"
    ]
    st.sidebar.title("🏠 Navigation")
    st.sidebar.caption(f"Version: {get_app_version()}")
    selected = st.sidebar.radio("Wähle eine Seite", menu, index=menu.index(st.session_state["page"]))
    if selected != st.session_state["page"]:
        st.session_state["page"] = selected
        st.rerun()
    st.session_state["page"] = selected

    if selected == "Startseite":
        startseite()        
    elif selected == "Athleten eingeben":
        athleten_eingeben()
    elif selected == "Athleten importieren":
        import_athletes()
    elif selected == "Athleten bearbeiten":
        edit_athletes()
    elif selected == "Athleten löschen":
        delete_athlete()
    elif selected == "Athleten anzeigen":
        athleten_anzeigen()
    elif selected == "Piste Mirwald":
        bio_mirwald()
    elif selected == "Piste Resultate anzeigen":
        auswertung_starten()
    elif selected == "Piste Ergebnisse eingeben":
        manage_results_entry()
    elif selected == "Piste Ergebnisse bearbeiten":
        manage_pisteresults_correction()
    elif selected == "Piste Punkte neu berechnen":
        punkte_neuberechnen()
    elif selected == "Wettkampfauswertungen":
        auswertung_wettkampf()
    elif selected == "Wettkampf-Bewertung":
        bewertung_wettkampf()
    elif selected == "Wettkampfresultate eingeben":
        manage_compresults_entry()
    elif selected == "Wettkampfresultate korrigieren":
        manage_compresults_correction()
    elif selected == "Piste RefPoint Competition Analyse":
        piste_refpoint_wettkampf_analyse()
    elif selected == "Wettkaempfe Top 3":
        show_top3_wettkaempfe()
    elif selected == "Wettkampf-Performance pro Athlet":
        wettkampf_performance_per_athlete()
    elif selected == "Tool Environment":
        manage_tool_environment()
    elif selected == "Trainingsperformance - Resilienz":
        manage_trainingsperformance_resilienz()
    elif selected == "SOC Full Calculation":
        soc_full_calculation()
    elif selected == "Full PISTE Results SOC":
        show_full_piste_results_soc()
    elif selected == "Full PISTE Results for Clubs":
        show_full_piste_results_clubs()
    elif selected == "Selektionen Wettkämpfe":
        selektionen_wettkaempfe()
    elif selected == "Vergleich BIG Competitions":
        vergleich_big_competitions()
    elif selected == "Referenz- und Bewertungstabellen":
        referenztabellen_anzeigen()

        st.session_state["user"] = None

# --- APP START ---
if __name__ == "__main__":
    if "user" not in st.session_state:
        st.session_state["user"] = None

    if st.session_state["user"]:
        logout_button()
        main()  # <-- Navigation über das Hauptmenü
    else:
        login_view()


