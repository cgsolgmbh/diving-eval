import db

r = db.query("SELECT age,discipline1,pointsaverage1,pointsaverage2,pointsaverage3,pointsaverageaverage,[pointsaverageref%],performance,quality FROM [pisterefcompresults] WHERE first_name=%s AND last_name=%s AND PisteYear=%s",['Celia','Greuter','2026'])
print('pisterefcompresults 2026:', r[0] if r else None)
if not r:
    raise SystemExit
row=r[0]
age=str(row.get('age'))
disc=row.get('discipline1')
sex='female'
ref=db.query("SELECT * FROM [pisterefcomppoints] WHERE LOWER(LTRIM(RTRIM(Discipline)))=LOWER(LTRIM(RTRIM(%s))) AND LOWER(LTRIM(RTRIM(sex)))=LOWER(LTRIM(RTRIM(%s)))",[disc,sex])
print('ref row found', bool(ref))
if ref:
    qcol='quality'+age
    refv=ref[0].get(qcol)
    print('quality col', qcol, 'refv', refv)
    try:
        refv=float(refv)
        cur_pct=float(row.get('pointsaverageref%'))
        cur_avg=float(row.get('pointsaverageaverage'))
        target_pct=80.1
        target_avg=refv*target_pct/100.0
        print('cur_avg',cur_avg,'cur_pct',cur_pct,'target_avg_for_80.1',round(target_avg,4),'delta_avg',round(target_avg-cur_avg,4))
        # top3 total delta needed
        print('delta_total_top3_points', round((target_avg-cur_avg)*3,4))
    except Exception as e:
        print('calc error',e)
