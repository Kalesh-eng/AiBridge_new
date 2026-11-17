import os; from dotenv import load_dotenv; load_dotenv()
import psycopg2
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='"'"'insdwh'"'"' ORDER BY table_name")
for row in cur.fetchall():
    print(row[0])
conn.close()
