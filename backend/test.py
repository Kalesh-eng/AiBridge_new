import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', user='postgres', password='postgres123')
cur = conn.cursor()
cur.execute(\"UPDATE public.connectors SET source_schema='exchange' WHERE name='exchange'\")
conn.commit()
print('Updated exchange connector schema to exchange')
conn.close()
