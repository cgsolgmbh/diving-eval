import db

first,last='Celia','Greuter'

print('--- pisterefcompresults ---')
rows = db.query("SELECT PisteYear, refaverage, performance, [pointsaverageref%], quality FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s ORDER BY TRY_CAST(PisteYear as int)",[first,last])
for r in rows:
    print(r)

print('\n--- relevant compresults ref columns ---')
for comp in ['Regio RZW Sommer 24','JSM Sommer 25','Bergen Open 2025','Regio RZW Winter 24','JSM Sommer 24','JSM Winter 24']:
    rows = db.query("SELECT Competition, Discipline, Points, [PisteRefPoints2024%], [PisteRefPoints2025%], [PisteRefPoints2026%], [timestamp] FROM [compresults] WHERE first_name=%s AND last_name=%s AND Competition=%s ORDER BY Discipline", [first,last,comp])
    if rows:
        print('\n###', comp)
        for r in rows:
            print(r)
