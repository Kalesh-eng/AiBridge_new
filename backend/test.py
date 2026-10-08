"""
fix_types.py
============
Patches main.py to permanently fix:
  1. Currency columns ($1,234.56) → strip $ and commas → NUMERIC
  2. Date columns (YYYY-MM-DD, MM/DD/YYYY etc.) → cast to DATE
  3. Boolean columns (true/false/yes/no) → BOOLEAN

Run from E:\\AIBRIDGE_Claude\\backend:
    python fix_types.py

Or with explicit path:
    python fix_types.py "E:\\AIBRIDGE_Claude\\backend\\main.py"
"""

import sys, os, shutil, re

PATH = sys.argv[1] if len(sys.argv) > 1 else r"E:\AIBRIDGE_Claude\backend\main.py"

# ── anchor: the col_defs loop we're replacing ────────────────────────────────
OLD = """                col_defs = []
                for col, dtype in zip(df.columns, df.dtypes):
                    if 'int' in str(dtype):    col_defs.append(f'"{col}" BIGINT')
                    elif 'float' in str(dtype): col_defs.append(f'"{col}" NUMERIC')
                    elif 'bool' in str(dtype):  col_defs.append(f'"{col}" BOOLEAN')
                    else:                        col_defs.append(f'"{col}" TEXT')

                tgt_cur.execute(f"CREATE TABLE {full_table} ({', '.join(col_defs)})")
                tgt.commit()

                                # Insert — columns already cleaned above, _safe() defined above
                col_names    = ', '.join([f'"{c}"' for c in df.columns])
                placeholders = ', '.join(['%s'] * len(df.columns))
                cols = list(df.columns)
                rows = [tuple(_safe(rec[c]) for c in cols) for rec in df.to_dict('records')]
                psycopg2.extras.execute_batch(
                    tgt_cur,
                    f"INSERT INTO {full_table} ({col_names}) VALUES ({placeholders})",
                    rows, page_size=500
                )"""

NEW = """                # ── Smart type inference (permanent fix) ─────────────────────
                import re as _re
                from datetime import date as _date

                _DATE_PATS = [
                    _re.compile(r'^\\d{4}-\\d{2}-\\d{2}$'),           # 2024-01-15
                    _re.compile(r'^\\d{2}/\\d{2}/\\d{4}$'),           # 01/15/2024
                    _re.compile(r'^\\d{2}-\\d{2}-\\d{4}$'),           # 15-01-2024
                    _re.compile(r'^\\d{4}/\\d{2}/\\d{2}$'),           # 2024/01/15
                ]
                _CURRENCY_RE = _re.compile(r'^[\\$£€¥]?[\\s]?[\\d,]+(\\.\\d+)?$')
                _BOOL_VALS   = {'true','false','yes','no','1','0','t','f','y','n'}

                def _infer_pg_type(series):
                    """Infer best PostgreSQL type from a pandas Series of strings."""
                    vals = series.dropna().astype(str).str.strip()
                    vals = vals[vals != '']
                    if len(vals) == 0:
                        return 'TEXT', series

                    sample = vals.head(200)

                    # Boolean
                    if sample.str.lower().isin(_BOOL_VALS).all():
                        bool_map = {'true':True,'yes':True,'1':True,'t':True,'y':True,
                                    'false':False,'no':False,'0':False,'f':False,'n':False}
                        return 'BOOLEAN', series.map(
                            lambda v: bool_map.get(str(v).strip().lower()) if str(v).strip() != '' else None
                        )

                    # Currency / numeric  ($1,234.56  or  1234.56)
                    stripped = sample.str.replace(r'[\\$£€¥,\\s]', '', regex=True)
                    try:
                        stripped.astype(float)
                        # Cast the whole column
                        def _to_num(v):
                            if v is None or str(v).strip() == '': return None
                            try: return float(str(v).replace('$','').replace('£','').replace('€','').replace('¥','').replace(',','').strip())
                            except: return None
                        return 'NUMERIC', series.map(_to_num)
                    except (ValueError, TypeError):
                        pass

                    # Date
                    def _is_date(v):
                        s = str(v).strip()
                        return any(p.match(s) for p in _DATE_PATS)
                    if sample.apply(_is_date).all():
                        import pandas as _pd
                        def _to_date(v):
                            if v is None or str(v).strip() == '': return None
                            try:
                                return _pd.to_datetime(str(v).strip()).date()
                            except: return None
                        return 'DATE', series.map(_to_date)

                    return 'TEXT', series

                # Infer types and cast columns
                col_defs  = []
                cast_cols = {}
                for col in df.columns:
                    orig_dtype = str(df[col].dtype)
                    if 'int' in orig_dtype:
                        col_defs.append(f'"{col}" BIGINT')
                    elif 'float' in orig_dtype:
                        col_defs.append(f'"{col}" NUMERIC')
                    elif 'bool' in orig_dtype:
                        col_defs.append(f'"{col}" BOOLEAN')
                    else:
                        pg_type, casted = _infer_pg_type(df[col])
                        col_defs.append(f'"{col}" {pg_type}')
                        if pg_type != 'TEXT':
                            cast_cols[col] = casted
                            print(f'[Exchange]   {col} → {pg_type}')

                # Apply casts to df
                for col, casted_series in cast_cols.items():
                    df[col] = casted_series

                tgt_cur.execute(f"CREATE TABLE {full_table} ({', '.join(col_defs)})")
                tgt.commit()

                # Insert — columns already cleaned above, _safe() defined above
                col_names    = ', '.join([f'"{c}"' for c in df.columns])
                placeholders = ', '.join(['%s'] * len(df.columns))
                cols = list(df.columns)
                rows = [tuple(_safe(rec[c]) for c in cols) for rec in df.to_dict('records')]
                psycopg2.extras.execute_batch(
                    tgt_cur,
                    f"INSERT INTO {full_table} ({col_names}) VALUES ({placeholders})",
                    rows, page_size=500
                )"""

# ── Read ──────────────────────────────────────────────────────────────────────
if not os.path.exists(PATH):
    print(f"[fix] ERROR: {PATH} not found"); sys.exit(1)

content = open(PATH, encoding='utf-8').read()

if NEW.strip()[:80] in content:
    print("[fix] ✓ Smart type inference already applied. No changes made.")
    sys.exit(0)

if OLD.strip()[:80] not in content:
    print("[fix] ERROR: Could not find anchor text in main.py.")
    print("  The file may have changed. Paste lines 4575-4597 to Claude.")
    sys.exit(1)

# ── Backup + patch ────────────────────────────────────────────────────────────
bak = PATH + ".typebak"
shutil.copy2(PATH, bak)
print(f"[fix] Backup: {bak}")

patched = content.replace(OLD.strip(), NEW.strip(), 1)
open(PATH, 'w', encoding='utf-8').write(patched)
print("[fix] ✓ main.py patched!")
print()
print("What changed:")
print("  - Currency cols ($1,234.56) → stripped to float → NUMERIC")
print("  - Date cols (YYYY-MM-DD etc.) → cast to Python date → DATE")
print("  - Boolean cols (true/false/yes/no) → BOOLEAN")
print("  - All other text stays TEXT")
print()
print("Next: restart backend, re-run the Exchange load, then check:")
print("  SELECT column_name, data_type FROM information_schema.columns")
print("  WHERE table_schema = 'exchange' AND table_name = 'opportunities';")