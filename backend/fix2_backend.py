import re

main_py = "/Users/bhaskerbobby/Desktop/AiBridge/AiBridge_new/backend/main.py"

new_endpoints = '''

@app.get("/exchange/mapping/{mapping_id}")
async def get_exchange_mapping(mapping_id: str, current_user=Depends(get_current_user)):
    """Get a single exchange mapping with full details."""
    import psycopg2 as pg2
    try:
        pg = pg2.connect(host=os.getenv("PG_HOST","localhost"), port=int(os.getenv("PG_PORT",5432)),
                dbname=os.getenv("PG_DB","aibridge"), user=os.getenv("PG_USER","bhaskerbobby"),
                password=os.getenv("PG_PASSWORD",""))
        cur = pg.cursor()
        cur.execute("""
            SELECT m.id, m.name, m.target_schema, m.schedule_cron,
                   m.requirements, m.stored_file_path, m.stored_file_name,
                   m.stored_file_type, m.last_run_at, m.last_run_status,
                   json_agg(json_build_object(
                       \'id\', t.id, \'source_name\', t.source_name,
                       \'target_table\', t.target_table, \'load_mode\', t.load_mode,
                       \'load_order\', t.load_order, \'enabled\', t.enabled,
                       \'requirements\', t.requirements
                   ) ORDER BY t.load_order) as tables
            FROM public.exchange_mappings m
            LEFT JOIN public.exchange_mapping_tables t ON t.mapping_id = m.id
            WHERE m.id = %s AND m.user_id::text = %s
            GROUP BY m.id
        """, (mapping_id, str(current_user.id),))
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        pg.close()
        if not row:
            raise HTTPException(status_code=404, detail="Mapping not found")
        result = dict(zip(cols, row))
        for k, v in result.items():
            if hasattr(v, "isoformat"):
                result[k] = v.isoformat()
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Exchange Mapping Detail] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/exchange/mapping/{mapping_id}/upload-file")
async def upload_mapping_file(mapping_id: str, file: UploadFile = File(...),
                               current_user=Depends(get_current_user)):
    """Store a file permanently for a mapping so it can be re-run without re-upload."""
    import psycopg2 as pg2, shutil
    try:
        storage_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exchange_files")
        os.makedirs(storage_dir, exist_ok=True)
        suffix = "." + file.filename.rsplit(".", 1)[-1].lower()
        stored_name = f"{mapping_id}{suffix}"
        stored_path = os.path.join(storage_dir, stored_name)
        with open(stored_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        pg = pg2.connect(host=os.getenv("PG_HOST","localhost"), port=int(os.getenv("PG_PORT",5432)),
                dbname=os.getenv("PG_DB","aibridge"), user=os.getenv("PG_USER","bhaskerbobby"),
                password=os.getenv("PG_PASSWORD",""))
        cur = pg.cursor()
        cur.execute("""
            UPDATE public.exchange_mappings
            SET stored_file_path = %s, stored_file_name = %s, stored_file_type = %s,
                updated_at = NOW()
            WHERE id = %s AND user_id::text = %s
        """, (stored_path, file.filename, suffix.lstrip("."), mapping_id, str(current_user.id),))
        pg.commit()
        pg.close()
        return {"success": True, "stored_file_name": file.filename, "path": stored_path}
    except Exception as e:
        print(f"[Upload Mapping File] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

'''

with open(main_py, "r") as f:
    content = f.read()

# Insert before the existing /exchange/history endpoint
insert_before = '@app.get("/exchange/history")'
if insert_before not in content:
    print("ERROR: Could not find insertion point '@app.get(\"/exchange/history\")'")
    exit(1)

if 'get_exchange_mapping' in content:
    print("Endpoints already exist in main.py — skipping.")
else:
    content = content.replace(insert_before, new_endpoints + insert_before)
    with open(main_py, "w") as f:
        f.write(content)
    print("Backend endpoints added successfully!")

# Also create the exchange_files directory
import os
storage_dir = "/Users/bhaskerbobby/Desktop/AiBridge/AiBridge_new/backend/exchange_files"
os.makedirs(storage_dir, exist_ok=True)
print(f"Storage directory ready: {storage_dir}")