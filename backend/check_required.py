import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', user='postgres', password='postgres')
cur = conn.cursor()
cur.execute("SELECT artifacts->'required_columns' FROM pipelines WHERE id='eb854e1e-5469-4c5a-8256-eb543a0c3c15'")
result = cur.fetchone()[0]
print("Required columns:", result)
cur.close(); conn.close()
