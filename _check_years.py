import os, sys
sys.path.insert(0, '/home/site/wwwroot')
import db
r = db.query("SELECT PisteYear, COUNT(*) as cnt FROM [pisterefcompresults] GROUP BY PisteYear ORDER BY PisteYear")
for row in r:
    print(f"PisteYear={row['PisteYear']}: {row['cnt']} Eintraege")
