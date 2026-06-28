import db

queries = [
    ('2024','1m','female','16'),
    ('2024','3m','female','16'),
    ('2025','1m','female','17'),
    ('2025','3m','female','17'),
    ('2026','1m','female','18'),
    ('2026','3m','female','18'),
]

for y,disc,sex,age in queries:
    rows = db.query("SELECT Discipline, sex, ["+age+"] AS refval FROM [pisterefcomppoints] WHERE LOWER(LTRIM(RTRIM(Discipline)))=LOWER(LTRIM(RTRIM(%s))) AND LOWER(LTRIM(RTRIM(sex)))=LOWER(LTRIM(RTRIM(%s)))", [disc, sex])
    if rows:
        print(y, disc, rows[0]['refval'])

print('\nCelia top3 rows exact with refbasis:')
rows = [
    ('2024','Regio RZW Winter 24','1m',239.9,'female','16'),
    ('2024','JSM Sommer 24','3m',235.6,'female','16'),
    ('2024','JSM Winter 24','1m',223.05,'female','16'),
    ('2025','Regio RZW Sommer 24','3m',288,'female','17'),
    ('2025','JSM Sommer 25','1m',259,'female','17'),
    ('2025','Bergen Open 2025','3m',268.1,'female','17'),
]
for year,comp,disc,pts,sex,age in rows:
    ref = db.query("SELECT ["+age+"] AS refval FROM [pisterefcomppoints] WHERE LOWER(LTRIM(RTRIM(Discipline)))=LOWER(LTRIM(RTRIM(%s))) AND LOWER(LTRIM(RTRIM(sex)))=LOWER(LTRIM(RTRIM(%s)))", [disc, sex])[0]['refval']
    refpct = round((float(pts)/float(ref))*100,1)
    print({'year':year,'comp':comp,'disc':disc,'points':pts,'refbasis':float(ref),'refpct':refpct})
