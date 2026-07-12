import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres',
                         user='postgres', password='postgres123')
cur = conn.cursor()
cur.execute("""SELECT artifacts->'sql_scripts'->'scripts' FROM pipelines WHERE id = 'c916dcf1-d588-4314-8920-89106a242fd9'""")
scripts = cur.fetchone()[0]
for s in scripts:
    print(f"\n=== {s['name']} ===")
    sql = s['sql']
    # Show first 300 chars
    print(sql[:300])
cur.close()
conn.close()