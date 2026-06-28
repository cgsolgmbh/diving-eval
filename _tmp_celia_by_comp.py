import db

competitions = [
    'Regio RZW Winter 24',
    'JSM Sommer 24',
    'JSM Winter 24',
    'Regio RZW Sommer 24',
    'JSM Sommer 25',
    'Bergen Open 2025',
    'Winter-Cup 2025',
    'Regio RZW Winter 26',
    'Regio RZW Sommer 26'
]

for comp in competitions:
    rows = db.query("SELECT Competition, Discipline, CategoryStart, Points, AveragePoints, [JEM%], [EM%], [WM%], RegionalTeam, NationalTeam FROM [compresults] WHERE first_name=%s AND last_name=%s AND Competition=%s ORDER BY Discipline", ['Celia','Greuter', comp])
    if rows:
        print('\n###', comp)
        for r in rows:
            print(r)
