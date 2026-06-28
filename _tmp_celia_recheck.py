import db

first,last,year='Celia','Greuter','2026'

r = db.query("SELECT first_name,last_name,PisteYear,refaverage,performance,[pointsaverageref%],quality,pointsaverage1,pointsaverage2,pointsaverage3,pointsaverageaverage FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s AND PisteYear=%s", [first,last,year])
print('pisterefcompresults:', r[0] if r else None)

soc = db.query("SELECT PisteYear,competitions,compenhancement,quality,totalpoints FROM [socadditionalvalues] WHERE first_name=%s AND last_name=%s AND PisteYear=%s", [first,last,year])
print('socadditionalvalues:', soc[0] if soc else None)

# thresholds for enhancement
pid = db.query("SELECT id FROM [pistedisciplines] WHERE name=%s", ['CompPerfEnhance'])
if pid:
    did = pid[0]['id']
    thr = db.query("SELECT result_min,result_max,points FROM [scoretables] WHERE discipline_id=%s ORDER BY TRY_CAST(result_min as float)", [did])
    print('enhancement thresholds:')
    for t in thr:
        print(t)

# compute missing delta to reach enhancement=3 (performance >=0)
cur = r[0] if r else None
if cur:
    cur_perf = float(cur['performance']) if cur.get('performance') not in (None,'','nan') else None
    cur_ref = float(cur['refaverage']) if cur.get('refaverage') not in (None,'','nan') else None
    prev = db.query("SELECT PisteYear,refaverage FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s AND TRY_CAST(PisteYear as int) < TRY_CAST(%s as int) ORDER BY TRY_CAST(PisteYear as int)",[first,last,year])
    prev_vals=[float(x['refaverage']) for x in prev if x.get('refaverage') not in (None,'','nan')]
    print('prev years:', prev)
    if cur_ref is not None and prev_vals:
        prev_avg = sum(prev_vals)/len(prev_vals)
        need_prev_avg_for_zero = cur_ref
        delta_prev_avg = prev_avg - need_prev_avg_for_zero
        print('calc: cur_ref=',round(cur_ref,4),'prev_avg=',round(prev_avg,4),'delta_prev_avg_needed=',round(delta_prev_avg,4))
        print('=> total reduction needed across 2024+2025 refaverage sum =', round(delta_prev_avg*len(prev_vals),4))
        print('current_performance=', cur_perf)
