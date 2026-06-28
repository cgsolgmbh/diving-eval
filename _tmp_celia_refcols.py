import db

for comp in ['Regio RZW Winter 24','JSM Sommer 24','JSM Winter 24','Regio RZW Sommer 24','JSM Sommer 25','Bergen Open 2025','Winter-Cup 2025','Regio RZW Winter 26','Regio RZW Sommer 26']:
    rows = db.query("SELECT Competition, Discipline, Points, AveragePoints, [PisteRefPoints2024%], [PisteRefPoints2025%], [PisteRefPoints2026%] FROM [compresults] WHERE first_name=%s AND last_name=%s AND Competition=%s ORDER BY Discipline", ['Celia','Greuter', comp])
    if rows:
        print('\n###', comp)
        for r in rows:
            print(r)
