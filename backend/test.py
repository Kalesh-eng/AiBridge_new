import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', user='postgres', password='postgres123')
cur = conn.cursor()
cur.execute('SELECT id, name, target_schema, last_run_status FROM public.exchange_mappings')
for r in cur.fetchall(): print(r)
conn.close()
