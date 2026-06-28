import db

for year in ['2024','2025']:
    print('\n###', year)
    rows = db.query("SELECT Competition, Discipline, CategoryStart, Points, [AveragePoints], [PisteRefPoints2024%], [PisteRefPoints2025%], [PisteRefPoints2026%] FROM [compresults] WHERE first_name=%s AND last_name=%s AND PisteYear=%s ORDER BY Competition, Discipline", ['Celia','Greuter',year])
    for r in rows:
        print(r)

print('\n### selectionpoints matches for Celia rows')
rows = db.query("SELECT Competition, Discipline, CategoryStart, year, points, [year] FROM [selectionpoints] WHERE [sex]=%s AND [category]=%s ORDER BY Competition, Discipline, year", ['female','Jugend A'])
print('selectionpoints sample count', len(rows))
for r in rows[:10]:
    print(r)
