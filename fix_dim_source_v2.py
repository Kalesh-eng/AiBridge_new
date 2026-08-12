with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    content = f.read()

old = '''            # Fix 0b-pre3: For dim scripts reading from narrow stg_<entity> tables,
            # redirect to stg_car_listings or stg_raw_* which has all columns
            if script.get("name", "").startswith("dim_") and "FROM staging." in sql:
                import re as _re_stg
                # Find which staging table this script reads from
                _stg_match = _re_stg.search(r'FROM\s+staging\.(stg_\w+)\s+s\b', sql, _re_stg.IGNORECASE)
                if _stg_match:
                    _src_tbl = _stg_match.group(1)
                    # If reading from narrow entity table (not raw_ and not car_listings/fact)
                    # check if the raw staging table exists in the ctx staging tables
                    _is_narrow = (
                        not _src_tbl.startswith("stg_raw_") and
                        "listings" not in _src_tbl and
                        "fact" not in _src_tbl
                    )
                    if _is_narrow:
                        # Find raw staging table from connection
                        try:
                            _cur_check = conn.cursor()
                            _cur_check.execute("""
                                SELECT table_name FROM information_schema.columns
                                WHERE table_schema = %s AND table_name LIKE 'stg_raw_%%'
                                GROUP BY table_name ORDER BY COUNT(*) DESC LIMIT 1
                            """, (staging_schema,))
                            _raw_row = _cur_check.fetchone()
                            if _raw_row:
                                _raw_tbl = _raw_row[0]
                                # Only redirect if the entity table has fewer columns than raw
                                _cur_check.execute("""
                                    SELECT COUNT(*) FROM information_schema.columns
                                    WHERE table_schema = %s AND table_name = %s
                                """, (staging_schema, _src_tbl))
                                _narrow_cols = _cur_check.fetchone()[0]
                                _cur_check.execute("""
                                    SELECT COUNT(*) FROM information_schema.columns
                                    WHERE table_schema = %s AND table_name = %s
                                """, (staging_schema, _raw_tbl))
                                _raw_cols = _cur_check.fetchone()[0]
                                if _narrow_cols < _raw_cols and _narrow_cols <= 3:
                                    # Also find stg_car_listings if it exists (better source)
                                    _cur_check.execute("""
                                        SELECT table_name FROM information_schema.columns
                                        WHERE table_schema = %s AND table_name LIKE 'stg_%%listings%%'
                                        GROUP BY table_name ORDER BY COUNT(*) DESC LIMIT 1
                                    """, (staging_schema,))
                                    _listings_row = _cur_check.fetchone()
                                    _best_src = _listings_row[0] if _listings_row else _raw_tbl
                                    sql = _re_stg.sub(
                                        f'FROM staging.{_best_src} s',
                                        sql, count=1, flags=_re_stg.IGNORECASE
                                    )
                                    log(f"[SQLPatch] Redirected {script.get('name')} source: {_src_tbl} → {_best_src} (narrow table fix)")
                            _cur_check.close()
                        except Exception as _e_stg:
                            pass  # silent fail — don't break the pipeline'''

new = '''            # Fix 0b-pre3: For dim scripts reading from narrow stg_<entity> tables,
            # redirect to stg_car_listings or stg_raw_* which has all columns
            # Uses staging_cols (already built above) — no DB query needed
            if script.get("name", "").startswith("dim_") and "FROM staging." in sql:
                import re as _re_stg
                _stg_match = _re_stg.search(r'FROM\s+staging\.(stg_\w+)\s+s\\b', sql, _re_stg.IGNORECASE)
                if _stg_match:
                    _src_tbl = _stg_match.group(1)
                    _is_narrow = (
                        not _src_tbl.startswith("stg_raw_") and
                        "listings" not in _src_tbl and
                        "fact" not in _src_tbl and
                        _src_tbl in staging_cols and
                        len(staging_cols[_src_tbl]) <= 3
                    )
                    if _is_narrow:
                        # Find best wide source from staging_cols
                        _listings_tbls = [t for t in staging_cols if "listings" in t]
                        _raw_tbls = [t for t in staging_cols if t.startswith("stg_raw_")]
                        _best_src = (_listings_tbls[0] if _listings_tbls else
                                     (_raw_tbls[0] if _raw_tbls else raw_tbl))
                        if _best_src and _best_src != _src_tbl:
                            sql = sql.replace(
                                f"FROM staging.{_src_tbl} s",
                                f"FROM staging.{_best_src} s",
                                1
                            )
                            log(f"[SQLPatch] Redirected {script.get('name')} source: {_src_tbl} → {_best_src} (narrow table fix)")'''

if old in content:
    content = content.replace(old, new, 1)
    print("✓ Fixed dim source redirect to use staging_cols")
else:
    print("Pattern not found")

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
    lines = content.splitlines()
    for j in range(max(0,e.lineno-3), min(len(lines),e.lineno+2)):
        print(f"  {j+1}: {lines[j]}")
