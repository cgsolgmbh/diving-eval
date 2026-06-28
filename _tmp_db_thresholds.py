import db

# discipline ids
names=['CompPerfPointsCalc','CompPerfQualityCalc','CompPerfEnhance']
ids={}
for n in names:
    r=db.query('SELECT id,name FROM [pistedisciplines] WHERE name=%s',[n])
    if r:
        ids[n]=r[0]['id']
print('ids',ids)

for n,did in ids.items():
    print('\n---',n,'---')
    rows=db.query('SELECT result_min,result_max,points FROM [scoretables] WHERE discipline_id=%s ORDER BY TRY_CAST(result_min as float)',[did])
    for x in rows:
        print(x)

print('\n--- Celia 2026 source values ---')
r=db.query('SELECT [pointsaverageref%], quality, performance FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s AND PisteYear=%s',['Celia','Greuter','2026'])
print(r[0] if r else None)
