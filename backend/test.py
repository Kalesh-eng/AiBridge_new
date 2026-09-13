import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', user='postgres', password='postgres123')
cur = conn.cursor()
cur.execute('SELECT id, name, connector_type FROM public.connectors WHERE name = %s', ('insdwh',))
print(cur.fetchone())
conn.close()