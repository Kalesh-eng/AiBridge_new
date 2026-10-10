import psycopg2

pg = psycopg2.connect(
    host="localhost", port=5432,
    dbname="aibridge", user="bhaskerbobby", password=""
)
cur = pg.cursor()

cur.execute("""
    ALTER TABLE public.exchange_mappings 
    ADD COLUMN IF NOT EXISTS stored_file_path TEXT,
    ADD COLUMN IF NOT EXISTS stored_file_name TEXT,
    ADD COLUMN IF NOT EXISTS stored_file_type VARCHAR(20)
""")

pg.commit()
pg.close()
print("DB migration done!")