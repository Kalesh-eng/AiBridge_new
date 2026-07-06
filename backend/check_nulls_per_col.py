import psycopg2
conn = psycopg2.connect(host='localhost', port=5433, dbname='postgres', 
                        user='postgres', password='postgres123')
cur = conn.cursor()

cur.execute("""
    SELECT 
        COUNT(*) FILTER (WHERE "Brand" IS NULL) as brand_nulls,
        COUNT(*) FILTER (WHERE "Fuel_Type" IS NULL) as fuel_nulls,
        COUNT(*) FILTER (WHERE "Engine_CC" IS NULL) as engine_nulls,
        COUNT(*) FILTER (WHERE "Horsepower" IS NULL) as hp_nulls,
        COUNT(*) FILTER (WHERE "Transmission" IS NULL) as trans_nulls,
        COUNT(*) FILTER (WHERE "City" IS NULL) as city_nulls,
        COUNT(*) FILTER (WHERE "Price" IS NULL) as price_nulls,
        COUNT(*) FILTER (WHERE "Color" IS NULL) as color_nulls,
        COUNT(*) FILTER (WHERE "Owner_Type" IS NULL) as owner_nulls,
        COUNT(*) as total
    FROM staging.stg_raw_used_car_10k_sample
""")
row = cur.fetchone()
cols = ['Brand', 'Fuel_Type', 'Engine_CC', 'Horsepower', 'Transmission',
        'City', 'Price', 'Color', 'Owner_Type', 'TOTAL']
for col, val in zip(cols, row):
    print(f"{col}: {val} nulls")

cur.close()
conn.close()