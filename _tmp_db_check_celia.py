import db

first='Celia'
last='Greuter'

print('--- pisterefcompresults ---')
rows = db.query("SELECT first_name,last_name,PisteYear,refaverage,performance,[pointsaverageref%],quality FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s ORDER BY TRY_CAST(PisteYear as int)",[first,last])
for r in rows:
    print(r)

print('--- socadditionalvalues ---')
rows = db.query("SELECT first_name,last_name,PisteYear,competitions,compenhancement,quality,totalpoints,piste,trainingperf,resilience,trainingtime,trainingsince,toolenvironment,bioagevalue,mirwaldvalue FROM [socadditionalvalues] WHERE first_name=%s AND last_name=%s ORDER BY TRY_CAST(PisteYear as int)",[first,last])
for r in rows:
    print(r)

print('--- CompPerfEnhance scoretable ---')
pd = db.query("SELECT id,name FROM [pistedisciplines] WHERE name=%s", ['CompPerfEnhance'])
if pd:
    did = pd[0]['id'] if isinstance(pd[0], dict) else pd[0][0]
    st = db.query("SELECT result_min,result_max,points,category,sex FROM [scoretables] WHERE discipline_id=%s ORDER BY TRY_CAST(result_min as float)",[did])
    for r in st:
        print(r)
