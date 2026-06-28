import db

first,last='Celia','Greuter'
print('--- pisterefcompresults ---')
rows = db.query("SELECT PisteYear, refaverage, performance, [pointsaverageref%], quality, pointsaverage1, pointsaverage2, pointsaverage3, pointsaverageaverage FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s ORDER BY TRY_CAST(PisteYear as int)",[first,last])
for r in rows:
    print(r)

print('--- socadditionalvalues ---')
rows = db.query("SELECT PisteYear, competitions, compenhancement, quality, totalpoints, piste, trainingperf, resilience, trainingtime, trainingsince, toolenvironment, bioagevalue, mirwaldvalue FROM [socadditionalvalues] WHERE first_name=%s AND last_name=%s ORDER BY TRY_CAST(PisteYear as int)",[first,last])
for r in rows:
    print(r)

print('--- enhancement thresholds ---')
pid = db.query("SELECT id FROM [pistedisciplines] WHERE name=%s", ['CompPerfEnhance'])
if pid:
    did = pid[0]['id']
    thr = db.query("SELECT result_min, result_max, points FROM [scoretables] WHERE discipline_id=%s ORDER BY TRY_CAST(result_min as float)",[did])
    for t in thr:
        print(t)

print('--- current 2026 math ---')
if rows:
    pass
r2026 = next((r for r in db.query("SELECT PisteYear, refaverage, performance FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s AND PisteYear=%s", [first,last,'2026'])), None)
if r2026:
    prev = db.query("SELECT PisteYear, refaverage FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s AND TRY_CAST(PisteYear as int) < 2026 ORDER BY TRY_CAST(PisteYear as int)",[first,last])
    vals=[float(x['refaverage']) for x in prev if x.get('refaverage') not in (None,'','nan')]
    if vals:
        prev_avg=sum(vals)/len(vals)
        print({'prev_avg':prev_avg,'cur_ref':float(r2026['refaverage']),'performance':float(r2026['performance']) if r2026.get('performance') not in (None,'','nan') else None})
        print({'need_prev_avg_for_zero': float(r2026['refaverage']), 'sum_reduction_needed': round((prev_avg-float(r2026['refaverage']))*len(vals),4)})
