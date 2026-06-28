from pathlib import Path
import re

def parse_tuples(values_text):
    tuples=[]
    i=0
    n=len(values_text)
    while i<n:
        while i<n and values_text[i] not in '(': i+=1
        if i>=n: break
        i+=1
        fields=[]
        cur=[]
        in_q=False
        while i<n:
            ch=values_text[i]
            if in_q:
                if ch=="'":
                    if i+1<n and values_text[i+1]=="'":
                        cur.append("'")
                        i+=2
                        continue
                    in_q=False
                    i+=1
                    continue
                cur.append(ch)
                i+=1
                continue
            else:
                if ch=="'":
                    in_q=True
                    i+=1
                    continue
                if ch==',':
                    fields.append(''.join(cur).strip())
                    cur=[]
                    i+=1
                    continue
                if ch==')':
                    fields.append(''.join(cur).strip())
                    i+=1
                    tuples.append(fields)
                    break
                cur.append(ch)
                i+=1
    return tuples

# parse disciplines
pdisc = Path('sqltables/pistedisciplines_rows.sql').read_text(encoding='utf-8', errors='ignore')
vals = pdisc.split('VALUES',1)[1]
dt = parse_tuples(vals)
name_to_id = {t[1]: t[0] for t in dt if len(t)>=2}
enh_id = name_to_id.get('CompPerfEnhance')
print('enh_id', enh_id)

# parse scoretable
st = Path('sqltables/scoretables_rows.sql').read_text(encoding='utf-8', errors='ignore')
vals = st.split('VALUES',1)[1]
rows = parse_tuples(vals)
filtered=[]
for t in rows:
    if len(t)<7:
        continue
    disc=t[1]
    if disc!=enh_id:
        continue
    try:
        rmax=float(t[2])
        pts=float(t[3])
        rmin=float(t[5])
        cat=None if t[6].lower()=='null' else t[6]
        filtered.append((rmin,rmax,pts,cat))
    except Exception:
        pass
filtered.sort(key=lambda x:(x[3] or '', x[0]))
print('count',len(filtered))
for r in filtered:
    print(r)

# quick helper current perf for Celia 2026 from dump
txt = Path('sqltables/pisterefcompresults_rows.sql').read_text(encoding='utf-8', errors='ignore')
vals = txt.split('VALUES',1)[1]
pr = parse_tuples(vals)
for t in pr:
    if len(t)>=19 and t[1]=='Celia' and t[2]=='Greuter' and t[17]=='2026':
        print('Celia 2026 refavg/perf', t[16], t[18])
