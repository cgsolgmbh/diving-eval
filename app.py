import streamlit as st
# --- JavaScript-Snippet für OAuth-Token-Handling ---
st.components.v1.html("""
<script>
window.addEventListener('DOMContentLoaded', (event) => {
    if (window.location.hash) {
        const params = new URLSearchParams(window.location.hash.substr(1));
        if (params.get('access_token')) {
            const url = new URL(window.location);
            url.searchParams.set('access_token', params.get('access_token'));
            url.searchParams.set('refresh_token', params.get('refresh_token'));
            setTimeout(function() {
                window.location.replace(url.toString().split('#')[0]);
            }, 100); // 100ms Verzögerung
        }
    }
});
</script>
""")
import datetime
import pandas as pd
from supabase import create_client, Client
import importlib
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# 🔑 Supabase-Konfiguration
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Token aus URL-Fragment holen (nur beim allerersten Aufruf nach OAuth)
if "access_token" not in st.session_state:
    params = st.query_params
    if "access_token" in params:
        st.session_state["access_token"] = params["access_token"]
        st.session_state["refresh_token"] = params.get("refresh_token")
        # User holen und Session setzen
        user = supabase.auth.get_user(st.session_state["access_token"])
        st.session_state["user"] = user
        # Kein st.rerun() mehr hier!
        # Seite wird ohnehin durch das JavaScript-Snippet neu geladen
        # und der Token ist dann aus der URL verschwunden
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
    return supabase.table('pistedisciplines').select('id, name').execute().data

@st.cache_data
def get_athletes():
    return supabase.table('athletes').select('id, full_name, sex, vintage, category').execute().data

@st.cache_data
def get_agecategories():
    return supabase.table('agecategories').select('*').execute().data

@st.cache_data
def get_scoretables():
    return supabase.table('scoretables').select('*').execute().data

def fetch_all_rows(table, select="*", **filters):
    """Lädt alle Zeilen aus einer Supabase-Tabelle in Blöcken von 1000."""
    all_rows = []
    offset = 0
    while True:
        query = supabase.table(table).select(select).range(offset, offset + 999)
        for key, value in filters.items():
            query = query.eq(key, value)
        rows = query.execute().data
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000
    return all_rows

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
        score_rows = supabase.table('scoretables').select('*')\
            .eq('discipline_id', discipline_id)\
            .eq('category', category.strip())\
            .eq('sex', sex.capitalize())\
            .execute().data
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

# --- LOGIN-MODUL ---
if "user" not in st.session_state:
    st.session_state["user"] = None

def login_view():
    st.title("🔐 Login erforderlich")
    email = st.text_input("E-Mail")
    password = st.text_input("Passwort", type="password")

    # Klassischer Login
    if st.button("Einloggen") and email and password:
        try:
            auth_result = supabase.auth.sign_in_with_password({"email": email, "password": password})
            user = auth_result.user

            if not user:
                st.error("Login fehlgeschlagen – Benutzer nicht gefunden.")
                return

            erlaubte_emails = [
                "chris@greuters.com"
                "christian.greuter@outlook.com",
                "christian.greuter@cgsol.ch",
                "christian.greuter@swiss-aquatics.ch",
                "christian.finger@swiss-aquatics.ch"
            ]

            if user.email not in erlaubte_emails:
                st.error("⛔ Zugriff verweigert: Du bist nicht berechtigt.")
                return

            # 🔑 Login erfolgreich, Session speichern
            st.session_state["user"] = user
            st.rerun()

        except Exception as e:
            st.error(f"Login fehlgeschlagen: {e}")

    st.markdown("---")
    st.markdown("Oder mit Microsoft anmelden:")

    # Azure OAuth-Login
    redirect_url = st.secrets["OAUTH_REDIRECT_URL"]
    oauth_url = (
        f"{SUPABASE_URL}/auth/v1/authorize"
        f"?provider=azure"
        f"&redirect_to={redirect_url}"
    )
    st.markdown(
        f'''
        <a href="{oauth_url}" target="_blank" style="text-decoration:none;">
            <button style="
                background-color:#2d7ff9;
                color:white;
                padding:0.5em 1.5em;
                border:none;
                border-radius:4px;
                font-size:1.1em;
                cursor:pointer;
            ">
                🔵 Mit Microsoft anmelden
            </button>
        </a>
        ''',
        unsafe_allow_html=True
    )

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
    """Lädt alle Zeilen aus einer Supabase-Tabelle in Blöcken von 1000."""
    all_rows = []
    offset = 0
    while True:
        query = supabase.table(table).select(select).range(offset, offset + 999)
        for key, value in filters.items():
            query = query.eq(key, value)
        rows = query.execute().data
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000
    return all_rows

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

# Punkteberechnung
def get_points(discipline_id, result, category, sex):
    try:
        if not discipline_id or not category or not sex:
            return 0

        score_rows = supabase.table('scoretables').select('*')\
            .eq('discipline_id', discipline_id)\
            .eq('category', category.strip())\
            .eq('sex', sex.capitalize())\
            .execute().data

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
    categories = supabase.table('agecategories').select('*').execute().data
    for cat in categories:
        if cat['min_age'] <= age <= cat['max_age']:
            return cat['category']
    return "Unbekannt"

# Ergebnisseingabe
def get_athletes():
    # Holt alle Athleten aus Supabase, auch bei mehr als 1000 Einträgen
    all_athletes = []
    page = 0
    page_size = 1000
    while True:
        result = supabase.table("athletes").select("*").range(page * page_size, (page + 1) * page_size - 1).execute()
        data = result.data if hasattr(result, "data") else result.get("data", [])
        if not data:
            break
        all_athletes.extend(data)
        if len(data) < page_size:
            break
        page += 1
    return all_athletes

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

    selected_athlete_name = st.selectbox("Wähle einen Athleten", list(athlete_names.keys()))
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

                existing = supabase.table('pisteresults').select('id').eq('athlete_id', athlete_id)\
                    .eq('discipline_id', discipline_id).eq('TestYear', int(test_year)).execute().data

                if existing:
                    supabase.table('pisteresults').update({
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex
                    }).eq('id', existing[0]['id']).execute()
                else:
                    supabase.table('pisteresults').insert({
                        'athlete_id': athlete_id,
                        'discipline_id': discipline_id,
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(test_year)
                    }).execute()

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

                existing = supabase.table('pisteresults').select('id').eq('athlete_id', athlete_id)\
                    .eq('discipline_id', discipline_id).eq('TestYear', test_year).execute().data

                if existing:
                    supabase.table('pisteresults').update({
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex
                    }).eq('id', existing[0]['id']).execute()
                else:
                    supabase.table('pisteresults').insert({
                        'athlete_id': athlete_id,
                        'discipline_id': discipline_id,
                        'raw_result': raw_result,
                        'points': points,
                        'category': category,
                        'sex': sex,
                        'TestYear': test_year
                    }).execute()
            inserted_count += 1

        st.success(f"✅ {inserted_count} Ergebnisse importiert.")
        if skipped_rows:
            st.warning(f"⚠️ {len(skipped_rows)} Zeile(n) konnten keinem Athleten zugeordnet werden:")
            st.dataframe(pd.DataFrame(skipped_rows))

# Athleten bearbeiten
def edit_athletes():
    st.header("✏️ Athleten bearbeiten")
    athletes = supabase.table('athletes').select('*').execute().data
    athlete_names = {f"{a['first_name']} {a['last_name']}": a['id'] for a in athletes}
    selected_name = st.selectbox("Athlet auswählen", list(athlete_names.keys()))

    if selected_name:
        athlete_id = athlete_names[selected_name]
        athlete = supabase.table('athletes').select('*').eq('id', athlete_id).execute().data[0]

        first_name = st.text_input("Vorname", athlete['first_name'])
        last_name = st.text_input("Nachname", athlete['last_name'])
        birthdate = st.date_input("Geburtsdatum", datetime.datetime.strptime(athlete['birthdate'], "%Y-%m-%d").date())
        sex = st.selectbox("Geschlecht", ["male", "female"], index=0 if athlete['sex'] == "male" else 1)
        teams = supabase.table('team').select('ShortName').execute().data
        club_options = [t['ShortName'] for t in teams if t.get('ShortName')]
        default_index = club_options.index(athlete['club']) if athlete['club'] in club_options else 0
        club = st.selectbox("Verein", club_options, index=default_index)
        nationalteam = st.selectbox("Nationalteam", ["yes", "no"], index=0 if athlete['nationalteam'] == "yes" else 1)

        if st.button("Aktualisieren"):
            vintage = birthdate.year
            full_name = f"{first_name} {last_name}"
            category = get_category_from_testyear(vintage, datetime.date.today().year)
            supabase.table('athletes').update({
                'first_name': first_name,
                'last_name': last_name,
                'birthdate': birthdate.strftime('%Y-%m-%d'),
                'sex': sex,
                'club': club,
                'nationalteam': nationalteam,
                'vintage': vintage,
                'full_name': full_name,
                'category': category
            }).eq('id', athlete_id).execute()
            st.success("Athletendaten aktualisiert.")

# Auswertung starten
def auswertung_starten():
    st.header("📈 Piste Resultate anzeigen")

    # Daten laden (jetzt mit Caching und Utilitys)
    results = fetch_all_rows("pisteresults", select="*")
    athletes = get_athletes()
    disciplines = get_pistedisciplines()

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


def manage_scoretable():
    st.header("📋 Scoretabelle verwalten")

    disciplines = supabase.table('pistedisciplines').select('id, name').execute().data
    discipline_map = {d['name']: d['id'] for d in disciplines}
    selected_discipline = st.selectbox("Disziplin auswählen", list(discipline_map.keys()))

    categories = supabase.table('agecategories').select('category').execute().data
    category_options = sorted(list(set(c['category'] for c in categories)))

    if selected_discipline:
        discipline_id = discipline_map[selected_discipline]
        entries = supabase.table('scoretables').select('*').eq('discipline_id', discipline_id).order('result_min').execute().data

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
                                supabase.table('scoretables').update({
                                    'result_min': new_min,
                                    'result_max': new_max,
                                    'points': new_points,
                                    'category': new_category,
                                    'sex': new_sex
                                }).eq('id', entry['id']).execute()
                                st.success("Eintrag aktualisiert.")
                                st.rerun()
                            else:
                                st.error("❗ 'Bis' muss größer oder gleich 'Von' sein.")
                    with col2:
                        if st.button("🗑️ Löschen", key=f"delete_{entry['id']}"):
                            supabase.table('scoretables').delete().eq('id', entry['id']).execute()
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
                supabase.table('scoretables').insert({
                    'discipline_id': discipline_id,
                    'result_min': result_min,
                    'result_max': result_max,
                    'points': points,
                    'category': new_category,
                    'sex': new_sex
                }).execute()
                st.success("Eintrag hinzugefügt!")
                st.rerun()
            else:
                st.error("❗ 'Bis' muss größer oder gleich 'Von' sein.")

def import_athletes():
    st.header("📥 Athleten importieren")

    # Button für Bioage-Update ALLER Athleten
    if st.button("🔄 Bioage für alle bestehenden Athleten berechnen und speichern"):
        athletes = supabase.table("athletes").select("id, birthdate").execute().data
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
                supabase.table("athletes").update({"bioage": bioage}).eq("id", athlete_id).execute()
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
                existing = supabase.table('athletes').select('id').eq('first_name', row['first_name'].strip())\
                    .eq('last_name', row['last_name'].strip())\
                    .eq('birthdate', birthdate).execute().data
                if existing:
                    skipped_duplicates.append({
                        "first_name": row['first_name'],
                        "last_name": row['last_name'],
                        "birthdate": birthdate
                    })
                    continue

                supabase.table('athletes').insert({
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
                }).execute()
                inserted += 1
            except Exception as e:
                st.warning(f"Fehler beim Einfügen von {row['first_name']} {row['last_name']}: {e}")

        if skipped_duplicates:
            st.warning(f"{len(skipped_duplicates)} Athlet(en) wurden nicht importiert, da sie bereits existieren:")
            st.dataframe(pd.DataFrame(skipped_duplicates))

        st.success(f"✅ {inserted} Athleten erfolgreich importiert.")

def delete_athlete():
    st.header("🗑️ Athlet löschen")
    athletes = supabase.table('athletes').select('id, first_name, last_name, birthdate, club').execute().data

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
                supabase.table('pisteresults').delete().eq('athlete_id', athlete_id).execute()
                # Athlet löschen
                supabase.table('athletes').delete().eq('id', athlete_id).execute()
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

            supabase.table("pisteresults").update({
                "points": new_points,
                "category": category
            }).eq("id", entry["id"]).execute()
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
                    supabase.table('pisteresults').update({
                        'raw_result': total_points,
                        'points': total_points,
                        'category': category,
                        'sex': sex
                    }).eq('id', existing_total[0]['id']).execute()
                else:
                    supabase.table('pisteresults').insert({
                        'athlete_id': athlete_id,
                        'discipline_id': pistetotalpoints_id,
                        'raw_result': total_points,
                        'points': total_points,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(selected_year)
                    }).execute()

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
                    supabase.table('pisteresults').update({
                        'raw_result': avg_points,
                        'points': bewertung,
                        'category': category,
                        'sex': sex
                    }).eq('id', existing_avg[0]['id']).execute()
                else:
                    supabase.table('pisteresults').insert({
                        'athlete_id': athlete_id,
                        'discipline_id': pistepointsdurchschnitt_id,
                        'raw_result': avg_points,
                        'points': bewertung,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(selected_year)
                    }).execute()

            # --- PisteTotalinPoints speichern (Bewertung des Durchschnitts) ---
            if pistetotalinpoints_id:
                scoretable_rows = fetch_all_rows('scoretables', select='*', discipline_id=pistetotalinpoints_id)
                pistetotalinpoints_value = None
                for row in scoretable_rows:
                    try:
                        rmin = float(row['result_min'])
                        rmax = float(row['result_max'])
                        if rmin <= avg_points <= rmax:
                            pistetotalinpoints_value = row['points']
                            break
                    except Exception:
                        continue

                existing_totalin = fetch_all_rows(
                    'pisteresults',
                    select='id',
                    athlete_id=athlete_id,
                    discipline_id=pistetotalinpoints_id,
                    TestYear=selected_year
                )
                if existing_totalin:
                    supabase.table('pisteresults').update({
                        'raw_result': avg_points,
                        'points': pistetotalinpoints_value,
                        'category': category,
                        'sex': sex
                    }).eq('id', existing_totalin[0]['id']).execute()
                else:
                    supabase.table('pisteresults').insert({
                        'athlete_id': athlete_id,
                        'discipline_id': pistetotalinpoints_id,
                        'raw_result': avg_points,
                        'points': pistetotalinpoints_value,
                        'category': category,
                        'sex': sex,
                        'TestYear': int(selected_year)
                    }).execute()

        st.success(f"✅ {updated_count} Resultate für das Jahr {selected_year} wurden neu bewertet.")

def bewertung_wettkampf():
    st.header("🔄 Wettkampfbewertungen berechnen")

    selection_points = fetch_all_rows('selectionpoints')
    competitions = fetch_all_rows('competitions')
    agedives = fetch_all_rows('agedives')
    df_agedives = pd.DataFrame(agedives)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def safe_numeric(val):
        if val in ("", None):
            return None
        try:
            return float(val.replace("%", "")) if isinstance(val, str) and "%" in val else float(val)
        except Exception:
            return None

    def get_status(selection_row, qual_flag, points):
        if selection_row.empty:
            return "no", "", "no"
        limit = float(selection_row.iloc[0]['points'])
        percentage = round((points / limit) * 100, 1)
        if qual_flag:
            status = "yes" if points >= limit else "no"
        else:
            status = "no"
        national = "yes" if percentage >= 90 else "no"
        return status, f"{percentage}%", national

    if st.button("🔄 Alle Wettkampfbewertungen berechnen"):
        comp_results = fetch_all_rows('compresults')
        df_results = pd.DataFrame(comp_results)
        df_selection = pd.DataFrame(selection_points)
        df_comp = pd.DataFrame(competitions)

        for _, row in df_results.iterrows():
            comp_id = row["id"]
            sex = row["sex"]
            discipline = row["Discipline"]
            category = row["CategoryStart"]
            points = row["Points"]
            competition_name = row["Competition"]

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

            relevant_selection = df_selection[
                (df_selection['sex'] == sex) &
                (df_selection['Discipline'] == discipline) &
                (df_selection['category'] == category)
            ]

            jem_row = relevant_selection[relevant_selection['Competition'] == "JEM"]
            em_row = relevant_selection[relevant_selection['Competition'] == "EM"]
            wm_row = relevant_selection[relevant_selection['Competition'] == "WM"]

            jem_qual = bool(comp_row.get("qual-JEM", False))
            em_qual = bool(comp_row.get("qual-EM", False))
            wm_qual = bool(comp_row.get("qual-WM", False))

            jem, jem_pct, jem_nt = get_status(jem_row, jem_qual, points)
            em, em_pct, em_nt = get_status(em_row, em_qual, points)
            wm, wm_pct, wm_nt = get_status(wm_row, wm_qual, points)

            nationalteam = "yes" if "yes" in [jem_nt, em_nt, wm_nt] else "no"

            supabase.table('compresults').update({
                "JEM": jem,
                "JEM%": safe_numeric(jem_pct),
                "EM": em,
                "EM%": safe_numeric(em_pct),
                "WM": wm,
                "WM%": safe_numeric(wm_pct),
                "NationalTeam": nationalteam,
                "AveragePoints": average_points,
                "timestamp": now_str
            }).eq("id", comp_id).execute()
        st.success("Alle Wettkampfbewertungen wurden neu berechnet!")

    if st.button("🔄 Nur neue Einträge berechnen"):
        comp_results = fetch_all_rows('compresults')
        df_results = pd.DataFrame([r for r in comp_results if not r.get("timestamp")])
        df_selection = pd.DataFrame(selection_points)
        df_comp = pd.DataFrame(competitions)

        for _, row in df_results.iterrows():
            comp_id = row["id"]
            sex = row["sex"]
            discipline = row["Discipline"]
            category = row["CategoryStart"]
            points = row["Points"]
            competition_name = row["Competition"]

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

            relevant_selection = df_selection[
                (df_selection['sex'] == sex) &
                (df_selection['Discipline'] == discipline) &
                (df_selection['category'] == category)
            ]

            jem_row = relevant_selection[relevant_selection['Competition'] == "JEM"]
            em_row = relevant_selection[relevant_selection['Competition'] == "EM"]
            wm_row = relevant_selection[relevant_selection['Competition'] == "WM"]
            regional_row = relevant_selection[relevant_selection['Competition'] == "Regional"]

            jem_qual = bool(comp_row.get("qual-JEM", False))
            em_qual = bool(comp_row.get("qual-EM", False))
            wm_qual = bool(comp_row.get("qual-WM", False))
            regional_qual = bool(comp_row.get("qual-Regional", False))

            jem, jem_pct, jem_nt = get_status(jem_row, jem_qual, points)
            em, em_pct, em_nt = get_status(em_row, em_qual, points)
            wm, wm_pct, wm_nt = get_status(wm_row, wm_qual, points)

            nationalteam = "yes" if "yes" in [jem_nt, em_nt, wm_nt] else "no"

            # RegionalTeam-Berechnung
            regional_pct = None
            regionalteam = "no"
            if not regional_row.empty and 'value' in regional_row.columns:
                try:
                    ref_val = float(regional_row.iloc[0]['value'])
                    percent = round((float(points) / ref_val) * 100, 1) if ref_val else None
                    regional_pct = percent
                except:
                    pass

            excluded_synchro = (
                str(category).strip().lower() in ["jugend c", "jugend d"] and
                str(discipline).strip().lower() in ["1m synchro", "3m synchro", "platform synchro", "turm synchro"]
            )

            if regional_qual and not excluded_synchro and regional_pct is not None and regional_pct >= 70:
                regionalteam = "yes"

            supabase.table('compresults').update({
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
            }).eq("id", comp_id).execute()
        st.success("Neue Einträge wurden berechnet!")

    # TESTTOOL: Timestamps zurücksetzen
    with st.expander("🧪 Test-Tools"):
        if st.button("❌ Alle Timestamps in compresults zurücksetzen"):
            try:
                comp_results = fetch_all_rows("compresults")
                for row in comp_results:
                    supabase.table("compresults").update({"timestamp": None}).eq("id", row["id"]).execute()
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

    # Filter für die wichtigsten Felder
    with st.expander("🔎 Filter anzeigen"):
        first_name_filter = st.text_input("Vorname (Teilstring möglich)", "")
        last_name_filter = st.text_input("Nachname (Teilstring möglich)", "")
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

def manage_compresults_entry():
    st.header("🏅 Wettkampfresultate eingeben")

    # --- Neuen Wettkampf anlegen ---
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
                supabase.table("competitions").insert({
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
                }).execute()
                st.success("Wettkampf gespeichert!")
                st.session_state["show_new_comp_form"] = False
        st.stop()

    # --- Athleten und Wettkämpfe laden ---
    athletes = fetch_all_rows('athletes', select='id, first_name, last_name, sex')
    athlete_names = {f"{a['first_name']} {a['last_name']}": a for a in athletes}
    selected_athlete = st.selectbox("Athlet", list(athlete_names.keys()))
    athlete_data = athlete_names[selected_athlete] if selected_athlete else None

    competitions = fetch_all_rows('competitions', select='Name')
    competition_names = [c['Name'] for c in competitions]
    selected_competition = st.selectbox("Wettkampf", competition_names)

    discipline = st.selectbox("Disziplin", ["1m", "3m", "platform", "3m synchro", "platform synchro"])
    category_start = st.selectbox("Kategorie", ["Jugend A", "Jugend B", "Jugend C", "Jugend D", "Elite"])
    prefin = st.selectbox("PreFin", ["FinalOnly", "Preliminary", "Final"])
    points = st.number_input("Punkte", min_value=0.0, step=0.1, format="%.2f")
    difficulty = st.number_input("Difficulty", min_value=0.0, step=0.1, format="%.2f")

    if st.button("💾 Ergebnis speichern"):
        if athlete_data:
            supabase.table('compresults').insert({
                "first_name": athlete_data['first_name'],
                "last_name": athlete_data['last_name'],
                "sex": athlete_data['sex'],
                "Competition": selected_competition,
                "Discipline": discipline,
                "CategoryStart": category_start,
                "PreFin": prefin,
                "Points": points,
                "Difficulty": difficulty
            }).execute()
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
                supabase.table('compresults').insert({
                    "first_name": first,
                    "last_name": last,
                    "sex": athlete["sex"],
                    "Competition": row["Competition"],
                    "Discipline": row["Discipline"],
                    "CategoryStart": row["CategoryStart"],
                    "PreFin": row["PreFin"],
                    "Points": row["Points"],
                    "Difficulty": row["Difficulty"]
                }).execute()
                inserted += 1
            except Exception as e:
                st.warning(f"Fehler bei {first} {last}: {e}")
        st.success(f"✅ {inserted} Resultate importiert.")
        if skipped:
            st.warning("Folgende Athleten wurden nicht gefunden:")
            st.dataframe(pd.DataFrame(skipped))

def safe_numeric(val):
    if val in ("", None):
        return None
    try:
        return float(val.replace("%", "")) if isinstance(val, str) and "%" in val else float(val)
    except Exception:
        return None

def get_ref_value(ref_df, discipline, sex, age, ref_col_prefix=""):
    try:
        filtered = ref_df[
            (ref_df["Discipline"].astype(str).str.strip().str.lower() == str(discipline).strip().lower()) &
            (ref_df["sex"].astype(str).str.strip().str.lower() == str(sex).strip().lower())
        ]
        if filtered.empty:
            return None
        ref_col = f"{ref_col_prefix}{int(age)}" if ref_col_prefix else str(int(age))
        if ref_col not in filtered.columns:
            return None
        val = filtered.iloc[0][ref_col]
        return float(val) if val not in (None, "", "nan") else None
    except Exception:
        return None


def calculate_percent(points, ref_value):
    try:
        points = float(points)
        ref_value = float(ref_value)
        return round((points / ref_value) * 100, 1) if ref_value != 0 else None
    except Exception:
        return None


def piste_refpoint_wettkampf_analyse():
    st.header("📊 Piste RefPoint Wettkampf Analyse")

    # Lade die agecategories-Tabelle EINMAL am Anfang der Funktion:
    agecategories = supabase.table("agecategories").select("*").execute().data
    agecat_df = pd.DataFrame(agecategories)

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

        competitions = supabase.table('competitions').select('Name, PisteYear, qual-Regional, qual-National').execute().data
        compresults = supabase.table('compresults').select('*').execute().data
        athletes = supabase.table('athletes').select('id, vintage, first_name, last_name').execute().data
        pisterefcomppoints = supabase.table('pisterefcomppoints').select('*').execute().data

        comp_lookup = {c['Name']: c.get('PisteYear') for c in competitions}
        comp_qual_lookup = {c['Name']: c for c in competitions}
        athlete_vintage = {a['id']: a['vintage'] for a in athletes}
        athlete_name_lookup = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a['vintage'] for a in athletes}
        refpoints_df = pd.DataFrame(pisterefcomppoints)

        updated = 0

        for row in compresults:
            competition_name = row.get("Competition")
            piste_year = comp_lookup.get(competition_name)
            comp_row = comp_qual_lookup.get(competition_name, {})
            is_current_year = str(piste_year) == selected_year

            athlete_id = row.get("athlete_id")
            vintage = athlete_vintage.get(athlete_id)
            if not vintage:
                first = row.get("first_name", "").strip().lower()
                last = row.get("last_name", "").strip().lower()
                vintage = athlete_name_lookup.get((first, last))
            if not vintage:
                st.write("Kein vintage:", row)
                continue

            try:
                age = selected_year_int - int(vintage)
            except Exception:
                continue
            if not (9 <= age <= 19):
                continue

            discipline = row.get("Discipline")
            sex = row.get("sex")
            points = row.get("Points")
            if not (discipline and sex and points):
                continue

            if is_excluded_discipline_local(discipline, age, selected_year, agecat_df):
                continue

            ref_value = get_ref_value(refpoints_df, discipline, sex, age)
            percent = calculate_percent(points, ref_value)
            if ref_value is None:
                st.write("Kein Referenzwert:", discipline, sex, age)
                continue

            if is_current_year:
                colname = f"PisteRefPoints{selected_year}%"
                supabase.table('compresults').update({
                    colname: percent
                }).eq("id", row["id"]).execute()
                updated += 1

            category = row.get("CategoryStart", "").strip().lower()
            discipline_lower = discipline.strip().lower()
            val = comp_row.get("qual-Regional", "")
            regional_qual = (
                isinstance(val, bool) and val is True
            ) or (
                str(val).strip().lower() in ["true", "yes", "1"]
            )
            excluded_synchro = (
                category in ["jugend c", "jugend d"] and
                discipline_lower in ["1m synchro", "3m synchro", "platform synchro"]
            )
            if regional_qual and not excluded_synchro:
                regionalteam = "yes" if percent is not None and percent >= 70 else "no"
                supabase.table('compresults').update({
                    "RegionalTeam": regionalteam
                }).eq("id", row["id"]).execute()

            if category in ["jugend c", "jugend d"]:
                val_nat = comp_row.get("qual-National", "")
                national_qual = (
                    isinstance(val_nat, bool) and val_nat is True
                ) or (
                    str(val_nat).strip().lower() in ["true", "yes", "1"]
                )
                if discipline_lower not in ["3m synchro", "turm synchro"]:
                    nationalteam = "yes" if national_qual and percent is not None and percent >= 90 else "no"
                    supabase.table('compresults').update({
                        "NationalTeam": nationalteam
                    }).eq("id", row["id"]).execute()

        st.success(f"Berechnen abgeschlossen. {updated} Einträge für {selected_year} aktualisiert.")

        # --- Top-3-Wettkämpfe & AveragePoints ---
            athlete_top3 = {}
            for row in athlete_rows:
                athlete = row["athlete"]
                discipline = row["discipline"]
                result = to_float(row["result"])
                ref = to_float(row["reference_value"])
                year = to_int(row["year"])

                if athlete not in athlete_top3:
                    athlete_top3[athlete] = {}

                if discipline not in athlete_top3[athlete]:
                    athlete_top3[athlete][discipline] = []

                if ref and result:
                    refpoints = result / ref * 100
                    athlete_top3[athlete][discipline].append({
                        "year": year,
                        "refpoints": refpoints,
                        "result": result,
                        "ref": ref,
                    })

        # Berechne AveragePoints (Mittelwert Top 3 RefPoints)
        for athlete, disciplines in athlete_top3.items():
            for discipline, performances in disciplines.items():
                if is_excluded_discipline_local(discipline):
                    continue

                top3 = sorted(performances, key=lambda x: x["refpoints"], reverse=True)[:3]
                if len(top3) == 3:
                    averagepoints = mean([p["refpoints"] for p in top3])
                    refaverage = mean([p["ref"] for p in top3])
                    results = [p["result"] for p in top3]
                    years = [p["year"] for p in top3]

                    output.append({
                        "athlete": athlete,
                        "discipline": discipline,
                        "refaverage": refaverage,
                        "result1": results[0],
                        "result2": results[1],
                        "result3": results[2],
                        "year1": years[0],
                        "year2": years[1],
                        "year3": years[2],
                        "averagepoints": averagepoints,
                        "pointsaverageref%": averagepoints / refaverage * 100 if refaverage else None
                    })

        # --- Leistungsentwicklung ("Entwicklung") ---
        # Gruppiere RefAverages nach Athlet, Disziplin und Jahr
        dev_data = {}
        for row in output:
            athlete = row["athlete"]
            discipline = row["discipline"]
            year = row["year1"]  # alle Top3-Leistungen sind im gleichen Jahr oder nah dran
            refavg = row.get("refaverage")

            if not refavg:
                continue

            key = (athlete, discipline)
            if key not in dev_data:
                dev_data[key] = []
            dev_data[key].append((year, refavg))

        # Entwicklung berechnen (RefAverage Jahr vs. Vorjahr)
        for (athlete, discipline), year_data in dev_data.items():
            sorted_years = sorted(year_data, key=lambda x: x[0])
            for i in range(1, len(sorted_years)):
                year_now, ref_now = sorted_years[i]
                year_prev, ref_prev = sorted_years[i - 1]

                if ref_prev:
                    entwicklung = ref_now / ref_prev * 100
                    output.append({
                        "athlete": athlete,
                        "discipline": discipline,
                        "jahr": year_now,
                        "entwicklung": entwicklung
                    })

        # DiveQuality-Berechnung
        refcomppoints_df = pd.DataFrame(supabase.table("pisterefcomppoints").select("*").execute().data)
        compresults_df = pd.DataFrame(supabase.table("compresults").select("*").execute().data)
        competitions = supabase.table("competitions").select("Name, PisteYear").execute().data
        comp_map = {c["Name"]: c.get("PisteYear") for c in competitions}
        compresults_df["PisteYear"] = compresults_df["Competition"].map(comp_map)

        grouped = df.groupby(["first_name", "last_name"])

        for (first, last), group in grouped:
            group = group.sort_values("PisteYear")
            this_year_row = group[group["PisteYear"] == int(selected_year)]
            if this_year_row.empty:
                continue

            age = this_year_row.iloc[0].get("age")
            sex = this_year_row.iloc[0].get("sex")
            
            if not sex or not age:
                cr_fallback = compresults_df[
                    (compresults_df['first_name'].str.strip().str.lower() == first) &
                    (compresults_df['last_name'].str.strip().str.lower() == last) &
                    (compresults_df['PisteYear'] == int(selected_year))
                ]
                if not cr_fallback.empty:
                    sex = cr_fallback.iloc[0].get("sex")

            cr_rows = compresults_df[
                (compresults_df['first_name'].str.strip().str.lower() == first) &
                (compresults_df['last_name'].str.strip().str.lower() == last) &
                (compresults_df['PisteYear'] == int(selected_year)) &
                (compresults_df['Points'].notnull())
            ]

            quality_vals = []
            for _, cr in cr_rows.iterrows():
                discipline = cr.get("Discipline")
                avg_points = cr.get("AveragePoints")
                if is_excluded_discipline_local(discipline, age, selected_year, agecat_df):
                    continue
                if not (discipline and sex and avg_points and age):
                    continue
                ref_row = refcomppoints_df[
                    (refcomppoints_df["Discipline"].astype(str).str.lower() == str(discipline).lower()) &
                    (refcomppoints_df["sex"].astype(str).str.lower() == str(sex).lower())
                ]
                quality_col = f"quality{int(age)}"
                if ref_row.empty or quality_col not in ref_row.columns:
                    continue
                try:
                    ref_val = float(ref_row.iloc[0][quality_col])
                    avg_val = float(avg_points)
                    deviation = round(((avg_val - ref_val) / ref_val) * 100, 1) if ref_val else None
                    if deviation is not None:
                        quality_vals.append(deviation)
                except:
                    continue

            quality = round(sum(quality_vals) / len(quality_vals), 1) if quality_vals else None
            supabase.table("pisterefcompresults").update({"quality": quality})\
                .eq("first_name", this_year_row.iloc[0]["first_name"])\
                .eq("last_name", this_year_row.iloc[0]["last_name"])\
                .eq("PisteYear", int(selected_year)).execute()

def show_top3_wettkaempfe():
    st.header("🏆 Top 3 Wettkämpfe pro Athlet und Jahr")

    df = pd.DataFrame(fetch_all_rows("pisterefcompresults", select="*"))
    if df.empty:
        st.info("Keine Top-3-Wettkampf-Daten vorhanden.")
        return

    jahre = sorted(df["PisteYear"].dropna().unique())
    jahr = st.multiselect("Jahr", jahre, default=jahre)
    alter = sorted(df["age"].dropna().unique())
    age = st.multiselect("Alter", alter, default=alter)

    if st.button("Show Results"):
        filtered = df[df["PisteYear"].isin(jahr)]
        if age:
            filtered = filtered[filtered["age"].isin(age)]

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

def manage_tool_environment():
    st.header("🛠️ Tool Environment Werte eingeben oder importieren")

    # Athleten laden
    athletes = supabase.table('athletes').select('first_name, last_name, birthdate').execute().data
    athlete_names = [f"{a['first_name']} {a['last_name']}" for a in athletes]
    athlete_lookup = {(a['first_name'], a['last_name']): a for a in athletes}

     # Manuelle Eingabe
    st.subheader("🔹 Einzelnen Wert eingeben")
    pisteyear = st.number_input("PisteYear", min_value=2020, max_value=2100, value=datetime.date.today().year, step=1)
    selected_athlete = st.selectbox("Athlet auswählen", athlete_names)
    if selected_athlete:
        first_name, last_name = selected_athlete.split(" ", 1)
        athlete = athlete_lookup.get((first_name, last_name))
        birthdate = athlete['birthdate'] if athlete else ""
        st.write(f"Geburtsdatum: **{birthdate}**")
        toolenvironment = st.selectbox("Tool Environment Wert (1-5)", [1, 2, 3, 4, 5])

        if st.button("💾 Wert speichern"):
            # Kategorie berechnen
            vintage = None
            if athlete and athlete.get("birthdate"):
                vintage = int(str(athlete["birthdate"])[:4])
            category = get_category_from_testyear(vintage, pisteyear) if vintage else None

            data = {
                "first_name": first_name,
                "last_name": last_name,
                "birthdate": birthdate,
                "toolenvironment": toolenvironment,
                "PisteYear": pisteyear,
                "Category": category
            }
            existing = supabase.table("socadditionalvalues").select("first_name").eq("first_name", first_name).eq("last_name", last_name).eq("PisteYear", pisteyear).execute().data
            if existing:
                supabase.table("socadditionalvalues").update(data).eq("first_name", first_name).eq("last_name", last_name).eq("PisteYear", pisteyear).execute()
            else:
                supabase.table("socadditionalvalues").insert(data).execute()
            st.success("Wert gespeichert!")

    st.markdown("---")
    st.subheader("🔹 CSV-Import")

    # Beispiel-CSV
    example = pd.DataFrame([{
        "first_name": "Max",
        "last_name": "Mustermann",
        "birthdate": "2005-03-15",
        "toolenvvalue": 3,
        "PisteYear": 2025
    }])
    st.download_button("📄 Beispiel-CSV herunterladen", example.to_csv(index=False).encode("utf-8"), file_name="tool_environment_beispiel.csv", mime="text/csv")

    uploaded_file = st.file_uploader("CSV-Datei mit Tool Environment-Werten hochladen", type="csv")
    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        required_cols = {"first_name", "last_name", "birthdate", "toolenvvalue", "PisteYear"}
        if not required_cols.issubset(df.columns):
            st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_cols)}")
        else:
            inserted = 0
            skipped = []
            # Athleten-Liste für Lookup laden
            athletes_db = supabase.table('athletes').select('first_name, last_name, birthdate').execute().data
            for _, row in df.iterrows():
                found = any(
                    (str(row['first_name']).strip().lower() == a['first_name'].strip().lower() and
                    str(row['last_name']).strip().lower() == a['last_name'].strip().lower() and
                    str(row.get('birthdate', '')).strip() == str(a['birthdate']))
                    for a in athletes_db
                )
                if not found:
                    skipped.append({"first_name": row["first_name"], "last_name": row["last_name"], "birthdate": row.get("birthdate", "")})
                    continue
                try:
                    data = {
                        "first_name": row["first_name"],
                        "last_name": row["last_name"],
                        "birthdate": row["birthdate"],
                        "PisteYear": int(row["PisteYear"]),
                        "toolenvvalue": int(row["toolenvvalue"])
                    }
                    existing = supabase.table("pisteenvironment").select("first_name").eq("first_name", row["first_name"]).eq("last_name", row["last_name"]).eq("PisteYear", row["PisteYear"]).execute().data
                    if existing:
                        supabase.table("pisteenvironment").update(data).eq("first_name", row["first_name"]).eq("last_name", row["last_name"]).eq("PisteYear", row["PisteYear"]).execute()
                    else:
                        supabase.table("pisteenvironment").insert(data).execute()
                    inserted += 1
                except Exception as e:
                    st.warning(f"Fehler bei {row['first_name']} {row['last_name']}: {e}")
            st.success(f"✅ {inserted} Werte importiert.")
            if skipped:
                st.warning("Folgende Personen wurden nicht importiert, da sie nicht in der Athletenliste stehen:")
                st.dataframe(pd.DataFrame(skipped))

def bio_mirwald():
    st.header("🧬 Bio Mirwald Eingabe & Import")

    # --- Einzel-Eingabe ---
    athletes = supabase.table('athletes').select('first_name, last_name').execute().data
    athlete_names = [f"{a['first_name']} {a['last_name']}" for a in athletes]
    athlete_lookup = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a for a in athletes}

    st.subheader("Einzel-Eingabe")
    selected_name = st.selectbox("Athlet auswählen", athlete_names)
    pisteyear = st.number_input("PisteYear", min_value=2000, max_value=2100, value=datetime.date.today().year)
    bioentwstand = st.selectbox("bioentwstand", [1, 2, 3])

    if st.button("Speichern"):
        first_name, last_name = selected_name.split(" ", 1)
        supabase.table("pistemirwald").insert({
            "first_name": first_name,
            "last_name": last_name,
            "PisteYear": int(pisteyear),
            "bioentwstand": int(bioentwstand)
        }).execute()
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
        label="📄 Beispiel-CSV herunterladen",
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
                supabase.table("pistemirwald").insert({
                    "first_name": row['first_name'],
                    "last_name": row['last_name'],
                    "PisteYear": int(row['PisteYear']),
                    "bioentwstand": int(row['bioentwstand'])
                }).execute()
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
    athletes = supabase.table('athletes').select('first_name, last_name').execute().data
    athlete_names = [f"{a['first_name']} {a['last_name']}" for a in athletes]
    athlete_lookup = {(a['first_name'], a['last_name']): a for a in athletes}

    st.subheader("🔹 Einzelnen Wert eingeben")
    pisteyear = st.number_input("PisteYear", min_value=2020, max_value=2100, value=datetime.date.today().year, step=1)
    selected_athlete = st.selectbox("Athlet auswählen", athlete_names)
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
            existing = supabase.table("trainingsperformance").select("first_name").eq("first_name", first_name).eq("last_name", last_name).eq("PisteYear", pisteyear).execute().data
            if existing:
                supabase.table("trainingsperformance").update(data).eq("first_name", first_name).eq("last_name", last_name).eq("PisteYear", pisteyear).execute()
            else:
                supabase.table("trainingsperformance").insert(data).execute()
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
            existing2 = supabase.table("socadditionalvalues").select("first_name").eq("first_name", first_name).eq("last_name", last_name).eq("PisteYear", pisteyear).execute().data
            if existing2:
                supabase.table("socadditionalvalues").update(data2).eq("first_name", first_name).eq("last_name", last_name).eq("PisteYear", pisteyear).execute()
            else:
                supabase.table("socadditionalvalues").insert(data2).execute()
            st.success("Wert gespeichert!")

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
        df = pd.read_csv(uploaded_file)
        required_cols = {"first_name", "last_name", "PisteYear", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10", "trainingtime", "trainingsince"}
        if not required_cols.issubset(df.columns):
            st.error(f"❌ Die Datei muss folgende Spalten enthalten: {', '.join(required_cols)}")
            return

        inserted = 0
        skipped = []
        # Athleten-Liste für Lookup laden
        athletes_db = supabase.table('athletes').select('first_name, last_name, birthdate').execute().data
        athlete_lookup_full = {
            (a['first_name'].strip().lower(), a['last_name'].strip().lower(), str(a['birthdate'])): a
            for a in athletes_db
        }
        for _, row in df.iterrows():
            key = (str(row['first_name']).strip().lower(), str(row['last_name']).strip().lower(), str(row.get('birthdate', '')).strip())
            # Prüfe, ob Athlet existiert (alle drei Felder müssen stimmen)
            found = any(
                (str(row['first_name']).strip().lower() == a['first_name'].strip().lower() and
                str(row['last_name']).strip().lower() == a['last_name'].strip().lower() and
                str(row.get('birthdate', '')).strip() == str(a['birthdate']))
                for a in athletes_db
            )
            if not found:
                skipped.append({"first_name": row["first_name"], "last_name": row["last_name"], "birthdate": row.get("birthdate", "")})
                continue
            try:
                data = {col: row[col] for col in required_cols}
                existing = supabase.table("trainingsperformance").select("first_name").eq("first_name", row["first_name"]).eq("last_name", row["last_name"]).eq("PisteYear", row["PisteYear"]).execute().data
                if existing:
                    supabase.table("trainingsperformance").update(data).eq("first_name", row["first_name"]).eq("last_name", row["last_name"]).eq("PisteYear", row["PisteYear"]).execute()
                else:
                    supabase.table("trainingsperformance").insert(data).execute()

                inserted += 1
            except Exception as e:
                st.warning(f"Fehler bei {row['first_name']} {row['last_name']}: {e}")
        st.success(f"✅ {inserted} Werte importiert.")
        if skipped:
            st.warning("Folgende Personen wurden nicht importiert, da sie nicht in der Athletenliste stehen:")
            st.dataframe(pd.DataFrame(skipped))

def get_trainingsince_value(pisteyear, trainingsince, first_name, last_name):
    # Athletendaten laden
    athlete = supabase.table('athletes').select('vintage').eq('first_name', first_name).eq('last_name', last_name).execute().data
    if not athlete:
        return None
    vintage = athlete[0]['vintage']
    try:
        age = int(pisteyear) - int(vintage)
        trainingsjahre = int(pisteyear) - int(trainingsince)
    except Exception:
        return None

    # Wert aus pistereftrainingsince holen
    ref = supabase.table('pistereftrainingsince').select('*').eq('age', age).execute().data
    if not ref:
        return None
    ref_row = ref[0]
    col = str(trainingsjahre)
    if col in ref_row:
        return ref_row[col]
    return None

def get_trainingstime_value(pisteyear, trainingstime, first_name, last_name):
    # Athletendaten laden
    athlete = supabase.table('athletes').select('vintage').eq('first_name', first_name).eq('last_name', last_name).execute().data
    if not athlete:
        return None
    vintage = athlete[0]['vintage']
    try:
        age = int(pisteyear) - int(vintage)
        stunden = int(trainingstime)
    except Exception:
        return None

    # Wert aus pistereftrainingtime holen
    ref = supabase.table('pistereftrainingtime').select('*').eq('age', age).execute().data
    if not ref:
        return None
    ref_row = ref[0]
    col = str(stunden)
    if col in ref_row:
        return ref_row[col]
    return None

def soc_full_calculation():
    st.header("🔢 SOC Full Calculation")
    agecategories = supabase.table('agecategories').select('*').execute().data
    years = [str(y) for y in range(2024, 2031)]
    selected_year = st.selectbox("PisteYear wählen", years)
    if st.button("SOC Full Calculation starten"):
        pisteyear = int(selected_year)

        # Alle Athleten laden (jetzt inkl. bioage)
        athletes = supabase.table('athletes').select('id, first_name, last_name, birthdate, sex, vintage, bioage').execute().data
        athletes_lookup = {(a['first_name'].strip().lower(), a['last_name'].strip().lower()): a for a in athletes}

        # pisterefcompresults laden (enthält refaverage, performance, pointsaverageref%)
        refcompresults = supabase.table('pisterefcompresults').select('*').eq('PisteYear', pisteyear).execute().data
        refcompresults_df = pd.DataFrame(refcompresults)

        # pistedisciplines laden
        pistedisciplines = supabase.table('pistedisciplines').select('id, name').execute().data
        # IDs für die Scoretables
        comp_perf_id = next((d['id'] for d in pistedisciplines if d['name'] == "CompPerfPointsCalc"), None)
        comp_quality_id = next((d['id'] for d in pistedisciplines if d['name'] == "CompPerfQualityCalc"), None)
        comp_enhance_id = next((d['id'] for d in pistedisciplines if d['name'] == "CompPerfEnhance"), None)
        pistetotalinpoints_id = next((d['id'] for d in pistedisciplines if d['name'] == "PisteTotalinPoints"), None)
        if not (comp_perf_id and comp_quality_id and comp_enhance_id and pistetotalinpoints_id):
            st.error("Eine oder mehrere Disziplinen (CompPerfPointsCalc, CompPerfQualityCalc, CompPerfEnhance, PisteTotalinPoints) fehlen!")
            return

        # Scoretables laden
        scoretables = fetch_all_rows('scoretables', select='*', discipline_id=comp_perf_id)
        scoretables_quality = fetch_all_rows('scoretables', select='*', discipline_id=comp_quality_id)
        scoretables_enhance = fetch_all_rows('scoretables', select='*', discipline_id=comp_enhance_id)

        # Piste-Resultate laden
        piste_results = fetch_all_rows("pisteresults", select="athlete_id, discipline_id, points, raw_result, TestYear")
        piste_results_df = pd.DataFrame(piste_results)

        # Bestehende socadditionalvalues laden (für Update/Insert)
        existing_rows = fetch_all_rows("socadditionalvalues", select="*")
        existing_lookup = {
            (row['first_name'], row['last_name'], row['PisteYear']): row
            for row in existing_rows
        }

        # --- Sammle alle Daten pro Athlet/Jahr ---
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
                    "Category": get_category_from_agecategories(athlete.get('vintage'), pisteyear, agecategories)
                }

            # --- NEU: bioagevalue berechnen und speichern ---
            bioage = athlete.get("bioage")
            bioage_map = {"q1": -1, "q2": -0.5, "q3": 0.5, "q4": 1}
            bioagevalue = bioage_map.get(str(bioage).lower(), 0) if bioage else 0
            athlete_data_map[key]["bioagevalue"] = bioagevalue

            # --- NEU: Mirwald-Wert holen und speichern ---
            mirwald_rows = supabase.table("pistemirwald").select("bioentwstand").eq("first_name", athlete['first_name']).eq("last_name", athlete['last_name']).eq("PisteYear", pisteyear).execute().data
            mirwald_map = {3: 1, 2: 0, 1: -1}
            mirwaldvalue = 0
            if mirwald_rows and "bioentwstand" in mirwald_rows[0]:
                try:
                    bioentwstand = int(mirwald_rows[0]["bioentwstand"])
                    mirwaldvalue = mirwald_map.get(bioentwstand, 0)
                except Exception:
                    mirwaldvalue = 0
            athlete_data_map[key]["mirwaldvalue"] = mirwaldvalue

            # Tool Environment Wert aus pisteenvironment holen
            env_row = supabase.table("pisteenvironment").select("toolenvvalue").eq("first_name", athlete['first_name']).eq("last_name", athlete['last_name']).eq("PisteYear", pisteyear).execute().data
            if env_row:
                athlete_data_map[key]["toolenvironment"] = env_row[0].get("toolenvvalue")

            # Trainingsperformance/Resilienz aus trainingsperformance holen
            trainings_row = supabase.table("trainingsperformance").select("*")\
                .eq("first_name", athlete['first_name'])\
                .eq("last_name", athlete['last_name'])\
                .eq("PisteYear", pisteyear).execute().data
            if trainings_row:
                t = trainings_row[0]
                athlete_data_map[key]["trainingperf"] = sum([t.get("q2", 0), t.get("q3", 0), t.get("q4", 0), t.get("q5", 0), t.get("q7", 0), t.get("q8", 0), t.get("q9", 0), t.get("q10", 0)])
                athlete_data_map[key]["resilience"] = t.get("q1", 0) + t.get("q6", 0)
                # Hier wird der Referenzwert berechnet:
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

            # competitions
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

            # --- Piste: Bewertung des Durchschnitts (PistePointsDurchschnitt) mit Scoretabelle von PisteTotalinPoints ---
            pistepointsdurchschnitt_id = next((d['id'] for d in pistedisciplines if d['name'].strip().lower() == "pistepointsdurchschnitt"), None)
            pistetotalinpoints_id = next((d['id'] for d in pistedisciplines if d['name'] == "PisteTotalinPoints"), None)
            scoretable_rows = fetch_all_rows('scoretables', select='*', discipline_id=pistetotalinpoints_id)

            # piste
            # --- IDs der Disziplinen holen ---
            pistepointsdurchschnitt_id = next((d['id'] for d in pistedisciplines if d['name'].strip().lower() == "pistepointsdurchschnitt"), None)
            pistetotalinpoints_id = next((d['id'] for d in pistedisciplines if d['name'] == "PisteTotalinPoints"), None)
            scoretable_rows = fetch_all_rows('scoretables', select='*', discipline_id=pistetotalinpoints_id)

            # --- Wert aus raw_result nach points übertragen (nur für PistePointsDurchschnitt) ---
            piste_result = piste_results_df[
                (piste_results_df['athlete_id'].astype(str) == str(athlete['id'])) &
                (piste_results_df['discipline_id'].astype(str) == str(pistepointsdurchschnitt_id)) &
                (piste_results_df['TestYear'].astype(str) == str(pisteyear))
            ]
            if not piste_result.empty:
                raw_val = piste_result.iloc[0]['raw_result']
                if raw_val is not None:
                    supabase.table("pisteresults").update({"points": raw_val})\
                        .eq("athlete_id", athlete['id'])\
                        .eq("discipline_id", pistepointsdurchschnitt_id)\
                        .eq("TestYear", pisteyear).execute()
                    # Optional: auch im DataFrame aktualisieren
                    piste_results_df.loc[
                        (piste_results_df['athlete_id'].astype(str) == str(athlete['id'])) &
                        (piste_results_df['discipline_id'].astype(str) == str(pistepointsdurchschnitt_id)) &
                        (piste_results_df['TestYear'].astype(int) == int(pisteyear)),
                        'points'
                    ] = raw_val

            # --- piste: Bewertung des Durchschnitts (PistePointsDurchschnitt) mit Scoretabelle von PisteTotalinPoints ---
            # Jetzt wie gehabt den Wert aus points holen:
            piste_result = piste_results_df[
                (piste_results_df['athlete_id'].astype(str) == str(athlete['id'])) &
                (piste_results_df['discipline_id'].astype(str) == str(pistepointsdurchschnitt_id)) &
                (piste_results_df['TestYear'].astype(int) == int(pisteyear))
            ]
            piste_value = None
            if not piste_result.empty:
                avg_points = piste_result.iloc[0]['points']  # jetzt steht der Wert sicher in points!
                avg_points_rounded = round(float(avg_points), 1)
                for row_score in scoretable_rows:
                    try:
                        rmin = float(row_score['result_min'])
                        rmax = float(row_score['result_max'])
                        if rmin <= avg_points_rounded <= rmax:
                            piste_value = row_score['points']
                            break
                    except Exception:
                        continue
            athlete_data_map[key]["piste"] = piste_value

            # compenhancement
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

            # quality
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

            # CompPointsNationalTeam setzen, falls NationalTeam=yes in compresults für das Jahr ---
            competitions = supabase.table('competitions').select('Name, PisteYear').eq('PisteYear', pisteyear).execute().data
            comp_names = set(c['Name'] for c in competitions)
            compresults = fetch_all_rows('compresults', select='first_name, last_name, Competition, NationalTeam')

            # Für jeden Athlet/Jahr prüfen, ob NationalTeam=yes in einem relevanten Wettkampf
            for key in athlete_data_map:
                first_name, last_name, year = key
                relevant_results = [
                    r for r in compresults
                    if r['first_name'].strip().lower() == first_name.strip().lower()
                    and r['last_name'].strip().lower() == last_name.strip().lower()
                    and r.get('Competition') in comp_names
                    and r.get('NationalTeam', '').lower() == 'yes'
                ]
                # Wert als "yes"/"no" speichern
                athlete_data_map[key]["CompPointsNationalTeam"] = "yes" if relevant_results else "no"

            # CompPointsRegionalTeam setzen, falls RegionalTeam=yes in compresults für das Jahr ---
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
                athlete_data_map[key]["CompPointsRegionalTeam"] = "yes" if relevant_results_regio else "no"

        # --- Jetzt alle Daten in socadditionalvalues schreiben ---
        inserted = 0
        for key, data in athlete_data_map.items():
            existing = existing_lookup.get(key)
            if existing:
                supabase.table("socadditionalvalues").update(data)\
                    .eq("first_name", data['first_name'])\
                    .eq("last_name", data['last_name'])\
                    .eq("PisteYear", data['PisteYear']).execute()
            else:
                supabase.table("socadditionalvalues").insert(data).execute()
            inserted += 1

        # --- totalpoints berechnen und speichern ---
        fields = [
            "competitions", "trainingperf", "piste", "compenhancement",
            "resilience", "trainingtime", "trainingsince", "toolenvironment", "quality", "bioagevalue", "mirwaldvalue"
        ]
        for key, data in athlete_data_map.items():
            existing = supabase.table("socadditionalvalues").select("*")\
                .eq("first_name", data['first_name'])\
                .eq("last_name", data['last_name'])\
                .eq("PisteYear", data['PisteYear']).execute().data
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
                supabase.table("socadditionalvalues").update({"totalpoints": total})\
                    .eq("first_name", data['first_name'])\
                    .eq("last_name", data['last_name'])\
                    .eq("PisteYear", data['PisteYear']).execute()

        # --- pisterefminpoints-Check: pisteminregio und pisteminnational setzen ---
        # Lade Referenztabelle
        refminpoints = supabase.table("pisterefminpoints").select("*").execute().data
        refminpoints_df = pd.DataFrame(refminpoints)

        for key, data in athlete_data_map.items():
            # Hole totalpoints und vintage/age
            row = supabase.table("socadditionalvalues").select("totalpoints", "birthdate", "PisteYear")\
                .eq("first_name", data['first_name'])\
                .eq("last_name", data['last_name'])\
                .eq("PisteYear", data['PisteYear']).execute().data
            if not row or row[0].get("totalpoints") in (None, "", "nan"):
                continue
            totalpoints = float(row[0]["totalpoints"])
            birthdate = row[0].get("birthdate")
            pisteyear = int(row[0].get("PisteYear"))
            if not birthdate:
                continue
            vintage = int(str(birthdate)[:4])
            age = pisteyear - vintage

            # Hole Referenzwerte für dieses Alter
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

            supabase.table("socadditionalvalues").update({
                "pisteminregio": pisteminregio,
                "pisteminnational": pisteminnational
            }).eq("first_name", data['first_name'])\
              .eq("last_name", data['last_name'])\
              .eq("PisteYear", data['PisteYear']).execute()

        # --- Talentcard berechnen und speichern ---
        for key, data in athlete_data_map.items():
            # Hole aktuelle Werte aus socadditionalvalues
            row = supabase.table("socadditionalvalues").select(
                "pisteminregio", "pisteminnational", "CompPointsNationalTeam", "CompPointsRegionalTeam"
            ).eq("first_name", data['first_name'])\
            .eq("last_name", data['last_name'])\
            .eq("PisteYear", data['PisteYear']).execute().data

            if not row:
                continue

            pisteminregio = str(row[0].get("pisteminregio", "")).lower()
            pisteminnational = str(row[0].get("pisteminnational", "")).lower()
            comp_points_nt = str(row[0].get("CompPointsNationalTeam", "")).lower()
            comp_points_regio = str(row[0].get("CompPointsRegionalTeam", "")).lower()

            if pisteminnational == "yes" and comp_points_nt == "yes":
                talentcard = "National"
            elif pisteminregio == "yes" and comp_points_regio == "yes":
                talentcard = "Regional"
            else:
                talentcard = "noCard"

            supabase.table("socadditionalvalues").update({
                "talentcard": talentcard
            }).eq("first_name", data['first_name'])\
            .eq("last_name", data['last_name'])\
            .eq("PisteYear", data['PisteYear']).execute()

        st.success(f"Berechnung abgeschlossen. {inserted} Einträge für {selected_year} aktualisiert.")

def show_full_piste_results_soc():
    st.header("📊 Full PISTE Results SOC")

    # Daten laden
    soc_df = pd.DataFrame(fetch_all_rows("socadditionalvalues", select="*"))
    if soc_df.empty:
        st.info("Keine Daten in socadditionalvalues gefunden.")
        return

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

    # Filter
    st.subheader("🔎 Filter")
    years = sorted(soc_df["PisteYear"].dropna().unique())
    year = st.multiselect("Jahr", years, default=years)

    last_names = sorted(soc_df["last_name"].dropna().unique())
    last_name = st.selectbox("Nachname", ["Alle"] + last_names)
    first_names = sorted(soc_df["first_name"].dropna().unique())
    first_name = st.selectbox("Vorname", ["Alle"] + first_names)
    sexes = sorted(soc_df["sex"].dropna().unique())
    sex = st.selectbox("Geschlecht", ["Alle"] + sexes)
    categories = sorted(soc_df["Category"].dropna().unique())
    category = st.multiselect("Kategorie", categories, default=categories)
    talentcard_values = ["Alle"] + sorted([v for v in soc_df["talentcard"].dropna().unique() if v != ""])
    talentcard_filter = st.selectbox("Talentcard", talentcard_values)

    # Anwenden der Filter
    filtered = soc_df[
        soc_df["PisteYear"].astype(str).isin([str(y) for y in year]) &
        (soc_df["first_name"].str.lower().str.strip() == first_name.lower().strip() if first_name != "Alle" else True) &
        (soc_df["last_name"].str.lower().str.strip() == last_name.lower().strip() if last_name != "Alle" else True) &
        soc_df["Category"].astype(str).isin([str(c) for c in category]) &
        (soc_df["sex"].astype(str) == str(sex) if sex != "Alle" else True) &
        (soc_df["talentcard"] == talentcard_filter if talentcard_filter != "Alle" else True)
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
        card_counts = filtered["talentcard"].value_counts().reindex(["National", "Regional", "noCard"], fill_value=0)
        fig2, ax2 = plt.subplots(figsize=(5, 3))
        bars = ax2.bar(card_counts.index, card_counts.values, color=["#1f77b4", "#2ca02c", "#d62728"])
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
                supabase.table("compresultsbig").insert({
                    "competition": row["competition"],
                    "year": int(row["year"]),
                    "discipline": row["discipline"],
                    "category": row["category"],
                    "sex": row["sex"],
                    "rank": str(row["rank"]),
                    "points": float(row["points"])
                }).execute()
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
    df = pd.DataFrame(fetch_all_rows("athletes", select="*"))
    if df.empty:
        st.info("Keine Athleten gefunden.")
        return

    # Nur gewünschte Spalten
    show_cols = ["first_name", "last_name", "birthdate", "club", "category", "sex", "nationalteam", "vintage", "bioage"]
    for col in show_cols:
        if col not in df.columns:
            df[col] = None
    df = df[show_cols]

    # Filter
    st.subheader("🔎 Filter")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        first_name = st.text_input("Vorname", "")
        last_name = st.text_input("Nachname", "")
    with col2:
        club = st.selectbox("Verein", ["Alle"] + sorted(df["club"].dropna().unique().tolist()))
        category = st.selectbox("Kategorie", ["Alle"] + sorted(df["category"].dropna().unique().tolist()))
    with col3:
        sex = st.selectbox("Geschlecht", ["Alle"] + sorted(df["sex"].dropna().unique().tolist()))
        nationalteam = st.selectbox("Nationalteam", ["Alle"] + sorted(df["nationalteam"].dropna().unique().tolist()))
    with col4:
        vintage = st.selectbox("Jahrgang", ["Alle"] + sorted(df["vintage"].dropna().astype(str).unique().tolist()))

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

    # Alle compresults in Blöcken laden
    def fetch_all_compresults():
        all_rows = []
        offset = 0
        while True:
            rows = supabase.table('compresults').select('*').range(offset, offset + 999).execute().data
            if not rows:
                break
            all_rows.extend(rows)
            if len(rows) < 1000:
                break
            offset += 1000
        return all_rows

    compresults = fetch_all_compresults()

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
    filtered = [
        r for r in compresults
        if comp_year_map.get(r.get('Competition')) and str(comp_year_map.get(r.get('Competition'))) == str(selected_year)
    ]

    # Filter nach Selektionstyp
    spalte = selektionstypen[selected_tab]
    filtered = [r for r in filtered if str(r.get(spalte, "")).lower() == "yes"]

    # Anzeige-Spalten
    show_cols = ["first_name", "last_name", "sex", "CategoryStart", "Competition", "Discipline", "Points"]
    df = pd.DataFrame(filtered)
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

def referenztabellen_anzeigen():
    st.header("📚 Referenz- und Bewertungstabellen")

    # --- Scoretables ---
    st.subheader("🏅 Scoretabelle")
    score_df = pd.DataFrame(fetch_all_rows("scoretables", select="*"))
    pistedisciplines = pd.DataFrame(fetch_all_rows("pistedisciplines", select="id,name"))
    if not score_df.empty and not pistedisciplines.empty:
        # Mapping discipline_id → name
        disc_map = dict(zip(pistedisciplines["id"], pistedisciplines["name"]))
        score_df["name"] = score_df["discipline_id"].map(disc_map)
        show_cols = ["name", "category", "sex", "result_min", "result_max", "points"]
        for col in show_cols:
            if col not in score_df.columns:
                score_df[col] = None
        score_df = score_df[show_cols].sort_values(["name", "category", "sex", "result_min"])
        st.dataframe(score_df)
        st.download_button("📥 Scoretabelle als CSV", score_df.to_csv(index=False, encoding='utf-8-sig'), file_name="scoretables.csv", mime="text/csv")
    else:
        st.info("Keine Daten in scoretables oder pistedisciplines.")

    # --- Selectionpoints ---
    st.subheader("🎯 Selectionpoints")
    sel_df = pd.DataFrame(fetch_all_rows("selectionpoints", select="*"))
    if not sel_df.empty:
        show_cols = ["Competition", "year", "category", "Discipline", "sex", "points"]
        for col in show_cols:
            if col not in sel_df.columns:
                sel_df[col] = None
        sel_df = sel_df[show_cols]
        st.dataframe(sel_df)
        st.download_button("📥 Selectionpoints als CSV", sel_df.to_csv(index=False, encoding='utf-8-sig'), file_name="selectionpoints.csv", mime="text/csv")
    else:
        st.info("Keine Daten in selectionpoints.")

    # --- pistereftrainingtime ---
    st.subheader("⏱️ Piste Ref Training Time")
    reftrain_df = pd.DataFrame(fetch_all_rows("pistereftrainingtime", select="*"))
    if not reftrain_df.empty:
        cols = ["age"] + [str(i) for i in range(4, 31)]
        for col in cols:
            if col not in reftrain_df.columns:
                reftrain_df[col] = None
        reftrain_df = reftrain_df[cols]
        st.dataframe(reftrain_df)
        st.download_button("📥 pistereftrainingtime als CSV", reftrain_df.to_csv(index=False, encoding='utf-8-sig'), file_name="pistereftrainingtime.csv", mime="text/csv")
    else:
        st.info("Keine Daten in pistereftrainingtime.")

    # --- pistereftrainingsince ---
    st.subheader("📅 Piste Ref Training Since")
    refsince_df = pd.DataFrame(fetch_all_rows("pistereftrainingsince", select="*"))
    if not refsince_df.empty:
        cols = ["age"] + [str(i) for i in range(1, 10)]
        for col in cols:
            if col not in refsince_df.columns:
                refsince_df[col] = None
        refsince_df = refsince_df[cols]
        st.dataframe(refsince_df)
        st.download_button("📥 pistereftrainingsince als CSV", refsince_df.to_csv(index=False, encoding='utf-8-sig'), file_name="pistereftrainingsince.csv", mime="text/csv")
    else:
        st.info("Keine Daten in pistereftrainingsince.")

    # --- pisterefminpoints ---
    st.subheader("🔢 Piste Ref Min Points")
    refmin_df = pd.DataFrame(fetch_all_rows("pisterefminpoints", select="*"))
    if not refmin_df.empty:
        cols = ["age", "points_max", "regio_min", "national_min"]
        for col in cols:
            if col not in refmin_df.columns:
                refmin_df[col] = None
        refmin_df = refmin_df[cols]
        st.dataframe(refmin_df)
        st.download_button("📥 pisterefminpoints als CSV", refmin_df.to_csv(index=False, encoding='utf-8-sig'), file_name="pisterefminpoints.csv", mime="text/csv")
    else:
        st.info("Keine Daten in pisterefminpoints.")

    # --- pisterefcomppoints ---
    st.subheader("🏆 Piste Ref Comp Points")
    refcomp_df = pd.DataFrame(fetch_all_rows("pisterefcomppoints", select="*"))
    if not refcomp_df.empty:
        # Spalten für Alter 9-18 und quality9-quality18
        cols = ["Discipline", "sex"] + [str(i) for i in range(9, 19)] + [f"quality{i}" for i in range(9, 19)]
        for col in cols:
            if col not in refcomp_df.columns:
                refcomp_df[col] = None
        refcomp_df = refcomp_df[cols]
        st.dataframe(refcomp_df)
        st.download_button("📥 pisterefcomppoints als CSV", refcomp_df.to_csv(index=False, encoding='utf-8-sig'), file_name="pisterefcomppoints.csv", mime="text/csv")
    else:
        st.info("Keine Daten in pisterefcomppoints.")

    # --- Piste Points für PisteTotalinPoints ---
    st.subheader("🏅 Piste Points (PisteTotalinPoints)")
    pistedisciplines = pd.DataFrame(fetch_all_rows("pistedisciplines", select="id,name"))
    pistetotalinpoints_id = None
    if not pistedisciplines.empty:
        pistetotalinpoints_id = pistedisciplines[pistedisciplines["name"] == "PisteTotalinPoints"]["id"].iloc[0]
    if pistetotalinpoints_id:
        pistepoints_df = pd.DataFrame(fetch_all_rows("scoretables", select="*",
                                                    discipline_id=pistetotalinpoints_id))
        if not pistepoints_df.empty:
            pistepoints_df = pistepoints_df.sort_values("result_min")
            pistepoints_df = pistepoints_df[["result_min", "result_max", "points"]]
            pistepoints_df = pistepoints_df.rename(columns={
                "result_min": "Von (Durchschnitt)",
                "result_max": "Bis (Durchschnitt)",
                "points": "Piste Points"
            })
            st.dataframe(pistepoints_df)
            st.download_button("📥 Piste Points als CSV", pistepoints_df.to_csv(index=False, encoding='utf-8-sig'), file_name="piste_points.csv", mime="text/csv")
        else:
            st.info("Keine Piste Points für PisteTotalinPoints gefunden.")
    else:
        st.info("Disziplin 'PisteTotalinPoints' nicht gefunden.")

# --- CompPerfEnhance (Leistungsentwicklung) ---
    st.subheader("📈 Leistungsentwicklung (CompPerfEnhance)")
    comp_perf_enhance_id = None
    if not pistedisciplines.empty:
        comp_perf_enhance_id = pistedisciplines[pistedisciplines["name"] == "CompPerfEnhance"]["id"].iloc[0]
    if comp_perf_enhance_id:
        enhance_df = pd.DataFrame(fetch_all_rows("scoretables", select="*", discipline_id=comp_perf_enhance_id))
        if not enhance_df.empty:
            enhance_df = enhance_df.sort_values("result_min")
            show_cols = ["category", "sex", "result_min", "result_max", "points"]
            for col in show_cols:
                if col not in enhance_df.columns:
                    enhance_df[col] = None
            enhance_df = enhance_df[show_cols]
            st.dataframe(enhance_df)
            st.download_button("📥 Leistungsentwicklung als CSV", enhance_df.to_csv(index=False, encoding='utf-8-sig'), file_name="leistungsentwicklung.csv", mime="text/csv")
        else:
            st.info("Keine Daten für CompPerfEnhance gefunden.")
    else:
        st.info("Disziplin 'CompPerfEnhance' nicht gefunden.")

    # --- CompPerfPointsCalc (Wettkampf Performance) ---
    st.subheader("🏅 Wettkampf Performance (CompPerfPointsCalc)")
    comp_perf_points_id = None
    if not pistedisciplines.empty:
        comp_perf_points_id = pistedisciplines[pistedisciplines["name"] == "CompPerfPointsCalc"]["id"].iloc[0]
    if comp_perf_points_id:
        perf_points_df = pd.DataFrame(fetch_all_rows("scoretables", select="*", discipline_id=comp_perf_points_id))
        if not perf_points_df.empty:
            perf_points_df = perf_points_df.sort_values("result_min")
            show_cols = ["category", "sex", "result_min", "result_max", "points"]
            for col in show_cols:
                if col not in perf_points_df.columns:
                    perf_points_df[col] = None
            perf_points_df = perf_points_df[show_cols]
            st.dataframe(perf_points_df)
            st.download_button("📥 Wettkampf Performance als CSV", perf_points_df.to_csv(index=False, encoding='utf-8-sig'), file_name="wettkampf_performance.csv", mime="text/csv")
        else:
            st.info("Keine Daten für CompPerfPointsCalc gefunden.")
    else:
        st.info("Disziplin 'CompPerfPointsCalc' nicht gefunden.")

    # --- CompPerfQualityCalc (Sprung Qualität) ---
    st.subheader("🤸 Sprung Qualität (CompPerfQualityCalc)")
    comp_perf_quality_id = None
    if not pistedisciplines.empty:
        comp_perf_quality_id = pistedisciplines[pistedisciplines["name"] == "CompPerfQualityCalc"]["id"].iloc[0]
    if comp_perf_quality_id:
        perf_quality_df = pd.DataFrame(fetch_all_rows("scoretables", select="*", discipline_id=comp_perf_quality_id))
        if not perf_quality_df.empty:
            perf_quality_df = perf_quality_df.sort_values("result_min")
            show_cols = ["category", "sex", "result_min", "result_max", "points"]
            for col in show_cols:
                if col not in perf_quality_df.columns:
                    perf_quality_df[col] = None
            perf_quality_df = perf_quality_df[show_cols]
            st.dataframe(perf_quality_df)
            st.download_button("📥 Sprung Qualität als CSV", perf_quality_df.to_csv(index=False, encoding='utf-8-sig'), file_name="sprung_qualitaet.csv", mime="text/csv")
        else:
            st.info("Keine Daten für CompPerfQualityCalc gefunden.")
    else:
        st.info("Disziplin 'CompPerfQualityCalc' nicht gefunden.")

    # --- Total Points for Card ---
    st.subheader("🏅 Total Points for Card (pisterefminpoints)")
    cardpoints_df = pd.DataFrame(fetch_all_rows("pisterefminpoints", select="*"))
    if not cardpoints_df.empty:
        cols = ["age", "points_max", "regio_min", "national_min"]
        for col in cols:
            if col not in cardpoints_df.columns:
                cardpoints_df[col] = None
        cardpoints_df = cardpoints_df[cols]
        st.dataframe(cardpoints_df)
        st.download_button("📥 Total Points for Card als CSV", cardpoints_df.to_csv(index=False, encoding='utf-8-sig'), file_name="total_points_for_card.csv", mime="text/csv")
    else:
        st.info("Keine Daten in pisterefminpoints (Total Points for Card).")

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

    teams = supabase.table('team').select('ShortName').execute().data
    club_options = [t['ShortName'] for t in teams if t.get('ShortName')]
    club = st.selectbox("Verein", club_options)

    nationalteam = st.selectbox("Nationalteam", ["yes", "no"])
    vintage = birthdate.year
    full_name = f"{first_name} {last_name}"
    category = get_category_from_testyear(vintage, datetime.date.today().year)

    # Quartal berechnen und in bioage speichern
    bioage = get_birth_quarter(birthdate)

    if st.button("Athlet speichern"):
        # Prüfen, ob Athlet bereits existiert
        existing = supabase.table('athletes').select('id').eq('first_name', first_name.strip())\
            .eq('last_name', last_name.strip())\
            .eq('birthdate', birthdate.strftime('%Y-%m-%d')).execute().data
        if existing:
            st.error(f"Athlet {full_name} mit Geburtsdatum {birthdate.strftime('%Y-%m-%d')} existiert bereits!")
        else:
            supabase.table('athletes').insert({
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
            }).execute()
            st.success(f"Athlet {full_name} gespeichert!")

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
        "Piste Ergebnisse eingeben",
        "Piste Punkte neu berechnen",
        "Piste Resultate anzeigen",
        "Wettkampfresultate eingeben",
        "Wettkampfauswertungen",
        "Wettkampf-Bewertung",
        "Wettkaempfe Top 3",
        "Piste RefPoint Competition Analyse",
        "Tool Environment",
        "Piste Mirwald",
        "Trainingsperformance - Resilienz",
        "SOC Full Calculation",
        "Full PISTE Results SOC",
        "Selektionen Wettkämpfe",
        "Vergleich BIG Competitions",
        "Referenz- und Bewertungstabellen"
    ]
    st.sidebar.title("🏠 Navigation")
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
    elif selected == "Piste Punkte neu berechnen":
        punkte_neuberechnen()
    elif selected == "Wettkampfauswertungen":
        auswertung_wettkampf()
    elif selected == "Wettkampf-Bewertung":
        bewertung_wettkampf()
    elif selected == "Wettkampfresultate eingeben":
        manage_compresults_entry()
    elif selected == "Piste RefPoint Competition Analyse":
        piste_refpoint_wettkampf_analyse()
    elif selected == "Wettkaempfe Top 3":
        show_top3_wettkaempfe()
    elif selected == "Tool Environment":
        manage_tool_environment()
    elif selected == "Trainingsperformance - Resilienz":
        manage_trainingsperformance_resilienz()
    elif selected == "SOC Full Calculation":
        soc_full_calculation()
    elif selected == "Full PISTE Results SOC":
        show_full_piste_results_soc()
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
