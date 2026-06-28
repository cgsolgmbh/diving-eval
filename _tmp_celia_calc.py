import re
from pathlib import Path

root = Path('sqltables')

# 1) Celia rows from pisterefcompresults
text = (root / 'pisterefcompresults_rows.sql').read_text(encoding='utf-8', errors='ignore')
rows = []
for m in re.finditer(r"\((\d+), 'Celia', 'Greuter'.*?\)", text):
    tup = m.group(0)
    parts = []
    cur = ''
    in_q = False
    for ch in tup[1:-1]:
        if ch == "'":
            in_q = not in_q
            cur += ch
            continue
        if ch == ',' and not in_q:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
    parts.append(cur.strip())
    # indexes by table schema
    row_id = parts[0]
    age = parts[3]
    refaverage = parts[16]
    piste_year = parts[17]
    performance = parts[18]
    pointsavgref = parts[23]
    rows.append((piste_year.strip("'"), row_id, age.strip("'"), refaverage.strip("'"), performance, pointsavgref.strip("'")))

print('Celia pisterefcompresults:')
for r in sorted(rows):
    print(r)

# 2) discipline id lookup
pdisc = (root / 'pistedisciplines_rows.sql').read_text(encoding='utf-8', errors='ignore')
id_by_name = {}
for m in re.finditer(r"\('([^']+)', '([^']+)', '([^']*)'\)", pdisc):
    id_by_name[m.group(2)] = m.group(1)

enh_id = id_by_name.get('CompPerfEnhance')
print('CompPerfEnhance id:', enh_id)

# 3) score ranges for enhance
sct = (root / 'scoretables_rows.sql').read_text(encoding='utf-8', errors='ignore')
ranges = []
pat = re.compile(r"\('([^']+)', '([^']+)', '([^']+)', '([^']+)', (null|'[^']*'), '([^']+)', '([^']+)'\)")
for m in pat.finditer(sct):
    _id, disc, resmax, points, sex, resmin, category = m.groups()
    if disc != enh_id:
        continue
    try:
        ranges.append((float(resmin), float(resmax), float(points), category))
    except Exception:
        pass
ranges.sort(key=lambda x: x[0])
print('CompPerfEnhance ranges:')
for r in ranges:
    print(r)

# 4) Celia row in socadditionalvalues (show 2026 if present)
soc = (root / 'socadditionalvalues_rows.sql').read_text(encoding='utf-8', errors='ignore')
for m in re.finditer(r"\((\d+),\s*'[^']*',\s*'Celia',\s*'Greuter'.*?\)", soc):
    tup = m.group(0)
    parts=[]
    cur=''
    in_q=False
    for ch in tup[1:-1]:
        if ch == "'":
            in_q = not in_q
            cur += ch
            continue
        if ch == ',' and not in_q:
            parts.append(cur.strip())
            cur=''
        else:
            cur += ch
    parts.append(cur.strip())
    year = parts[7].strip("'")
    total = parts[15].strip("'")
    compenh = parts[14].strip("'")
    comps = parts[11].strip("'")
    quality = parts[13].strip("'")
    print('SOC row:', year, 'total=', total, 'competitions=', comps, 'compenhancement=', compenh, 'quality=', quality)
