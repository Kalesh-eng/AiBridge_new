import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', user='postgres', password='postgres123')
cur = conn.cursor()
cur.execute('CREATE SCHEMA IF NOT EXISTS insdwh')
conn.commit()
cur.execute('SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s', ('insdwh',))
print('Schema:', cur.fetchone())
conn.close()
