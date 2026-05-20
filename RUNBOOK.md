# Runbook: Release & Deployment (Azure Streamlit App)

## 1. Vorbereitung
- Stelle sicher, dass alle Änderungen getestet und committed sind.
- Prüfe, dass keine unerwünschten Dateien (Logs, Zips, result.json etc.) im Repo sind.
- Die .gitignore ist aktuell und schützt vor versehentlichem Commit von Junk-Dateien.

## 2. Deployment auslösen
- **Push auf main** (origin/main) triggert automatisch das Azure-Deployment via GitHub Actions.
- Nur die freigegebenen Dateien (app.py, db.py, startup.sh, requirements.txt, sqltables/, .streamlit/config.toml) werden deployed.
- Das Deployment läuft als GitHub Actions Workflow (.github/workflows/azure-deploy.yml).

## 3. Nach dem Deployment
- App-Status im Azure-Portal oder per Log-Download prüfen:
  - `az webapp log download --resource-group <RG> --name <APP>`
- Logs auf DB-Fehler, Encoding-Probleme oder neue Exceptions prüfen.
- Features wie „Athleten anzeigen“ und „Wettkampf-Performance pro Athlet“ testen.

## 4. Troubleshooting
- Bei DB-Fehlern: Verbindungseinstellungen und Secrets prüfen.
- Bei Encoding-Problemen: UTF-8-Handling in Streamlit und DB sicherstellen.
- Bei Deployment-Problemen: Workflow-Logs in GitHub Actions prüfen.

## 5. Sicherheit
- Keine Passwörter oder Secrets im Code oder in der git-Historie speichern.
- SQL-Admin-Passwort sollte aus Azure Key Vault bezogen werden (siehe unten).

---

## Azure Key Vault: SQL-Passwort sicher einbinden

1. **Secret im Key Vault anlegen**
   - Im Azure-Portal: Key Vault öffnen → „Secrets“ → „+ Generate/Import“
   - Name z.B. `SqlAdminPassword`, Wert: dein sicheres Passwort

2. **App Service Zugriff auf Key Vault erlauben**
   - Managed Identity für App Service aktivieren
   - Key Vault Access Policy: „Get“ für Secrets auf die App-Identity setzen

3. **App-Einstellung für Key Vault-Referenz setzen**
   - Im Azure-Portal unter App Service → „Configuration“
   - Neue Einstellung:
     - Name: `SQLADMIN_PASSWORD`
     - Wert: `@Microsoft.KeyVault(SecretUri=https://<keyvault-name>.vault.azure.net/secrets/SqlAdminPassword/<secret-version>)`

4. **Python-Code: Passwort aus Umgebungsvariable lesen**
   ```python
   import os
   sql_password = os.environ.get("SQLADMIN_PASSWORD")
   # ... für DB-Connection verwenden ...
   ```
   - Keine Änderung am Code nötig, wenn bereits Umgebungsvariable genutzt wird.

5. **Wichtig:**
   - Die Key Vault-Referenz wird beim Start vom App Service automatisch aufgelöst.
   - Kein direkter Zugriff auf Key Vault im Python-Code nötig!

---

**Tipp:**
- Für weitere Secrets (z.B. Connection Strings) gleiche Methode verwenden.
- Dokumentation: https://learn.microsoft.com/de-de/azure/app-service/app-service-key-vault-references

---

_Für Rückfragen oder Anpassungen einfach melden!_
