import db

for year in ['2024','2025','2026']:
    rows = db.query("SELECT * FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s AND PisteYear=%s", ['Celia','Greuter',year])
    print('\nYEAR', year, 'count', len(rows))
    for r in rows[:3]:
        print(r)

print('\n--- compresults Celia rows (raw input) ---')
rows = db.query("SELECT Competition, Discipline, CategoryStart, Points, AveragePoints, PisteRefPoints2024%, PisteRefPoints2025%, PisteRefPoints2026%, JEM, [JEM%], EM, [EM%], WM, [WM%], RegionalTeam, NationalTeam, timestamp FROM [compresults] WHERE first_name=%s AND last_name=%s ORDER BY Competition, Discipline", ['Celia','Greuter'])
for r in rows:
    print(r)
