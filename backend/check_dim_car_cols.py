import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', 
                        user='postgres', password='postgres123')
cur = conn.cursor()

# Check Horsepower precision in staging
cur.execute("""
    SELECT column_name, data_type, numeric_precision, numeric_scale
    FROM information_schema.columns
    WHERE table_schema='staging' AND table_name='stg_raw_used_car_10k_sample'
    AND column_name IN ('Horsepower', 'Engine_CC', 'Mileage_kmpl')
""")
print("Staging precision:")
for r in cur.fetchall():
    print(f"  {r}")

# Check actual values
cur.execute('SELECT "Horsepower" FROM staging.stg_raw_used_car_10k_sample WHERE "Horsepower" IS NOT NULL LIMIT 3')
print("Sample Horsepower values:", [r[0] for r in cur.fetchall()])

# Count mismatches
cur.execute("""
    SELECT COUNT(*) FROM staging.stg_car_listings src
    WHERE EXISTS (
        SELECT 1 FROM warehouse.dim_car dc
        WHERE dc.brand IS NOT DISTINCT FROM src."Brand"
        AND dc.model IS NOT DISTINCT FROM src."Model"
        AND dc.year IS NOT DISTINCT FROM src."Year"
        AND dc.engine_cc IS NOT DISTINCT FROM src."Engine_CC"
        AND dc.mileage_kmpl IS NOT DISTINCT FROM src."Mileage_kmpl"
        AND dc.max_power IS NOT DISTINCT FROM src."Horsepower"
    )
""")
print("Rows matching with max_power:", cur.fetchone()[0])

cur.close()
conn.close()