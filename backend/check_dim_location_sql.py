import psycopg2, json
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', user='postgres', 
                        password='postgres123')
cur = conn.cursor()
cur.execute("""SELECT artifacts->'sql_scripts'->'scripts' FROM pipelines WHERE id = '67073e27-9c45-4fe1-ae07-082e4989d7e6'""")
r = cur.fetchone()
scripts = r[0]
for s in scripts:
    if s['name'] in ('dim_location', 'fact_car_listing'):
        print(f"=== {s['name']} ===")
        print(s['sql'][:500])
        print()
cur.close()
conn.close()
