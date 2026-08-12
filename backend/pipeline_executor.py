"""
pipeline_executor.py — v2.1
Universal ETL executor — any source DB → any target DB.

v2.1: Generic intermediate staging auto-creation.
      - _auto_create_intermediate_staging() runs before warehouse scripts
      - Detects missing staging tables referenced in SQL scripts
      - Creates them via SELECT DISTINCT from raw staging table
      - Works for ANY domain, ANY file — zero hardcoding
      - Handles single flat-file CSV/Excel sources generically
v2.0: Full any-to-any DB support + DuckDB source support.
      Chunked insert for 1M+ rows (50K per chunk).
v1.6: Every log line gets HH:MM:SS timestamp prefix.
"""

import psycopg2
import psycopg2.extras
from datetime import datetime

from universal_connector import (
    extract_table_universal, discover_schemas, discover_tables,
    discover_columns, get_schema_text_for_ai, recount_warehouse_rows,
    _pg_connect, _is_same_db, get_universal_connection
)
from sql_dialect import convert_scripts, get_dialect_info


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_connection(host, port, database, username, password):
    """Legacy PostgreSQL connection — kept for backwards compatibility."""
    return psycopg2.connect(host=host, port=port, dbname=database,
                            user=username, password=password)


def _cfg(d: dict) -> dict:
    """Ensure config dict has connector_type and database keys."""
    d = dict(d)
    if "connector_type" not in d:
        d["connector_type"] = "postgres"
    if "database" not in d and "database_name" in d:
        d["database"] = d["database_name"]
    return d


def _is_pg(config: dict) -> bool:
    ct = config.get("connector_type", "postgres").lower()
    return ct in ("postgres", "postgresql", "redshift")


def _is_duckdb(config: dict) -> bool:
    return config.get("connector_type", "").lower() == "duckdb"


def _extract_from_duckdb(source_config: dict, table_name: str,
                          target_config: dict, staging_schema: str,
                          selected_columns: list = None,
                          should_stop_fn=None, log_fn=None) -> dict:
    """
    Extract a DuckDB table → staging PostgreSQL.
    source_config.username = path to DuckDB file
    source_config.database_name = DuckDB table name
    """
    import duckdb
    import pandas as pd

    duckdb_path = source_config.get("username", "./aibridge.duckdb")
    con         = duckdb.connect(duckdb_path, read_only=True)

    try:
        if selected_columns:
            cols_sql = ", ".join(f'"{c}"' for c in selected_columns)
            df       = con.execute(f'SELECT {cols_sql} FROM "{table_name}"').df()
        else:
            df       = con.execute(f'SELECT * FROM "{table_name}"').df()
        con.close()
    except Exception as e:
        con.close()
        return {"success": False, "error": str(e), "rows": 0}

    # Write to staging PostgreSQL
    try:
        pg_conn = _pg_connect(target_config)
        pg_conn.autocommit = True
        cur     = pg_conn.cursor()

        stg_table = f"stg_{table_name}"

        # Drop + recreate staging table
        cur.execute(f'DROP TABLE IF EXISTS "{staging_schema}"."{stg_table}"')

        # Build CREATE TABLE from DataFrame dtypes
        type_map = {
            "int64": "BIGINT", "int32": "INTEGER", "float64": "NUMERIC(20,6)",
            "float32": "NUMERIC(10,4)", "bool": "BOOLEAN", "object": "TEXT",
            "datetime64[ns]": "TIMESTAMP"
        }
        col_defs = []
        for col, dtype in df.dtypes.items():
            pg_type = type_map.get(str(dtype), "TEXT")
            col_defs.append(f'"{col}" {pg_type}')

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{staging_schema}"."{stg_table}" (
                {", ".join(col_defs)}
            )
        """)

        # Chunked insert — handles 1M+ rows without timeout or memory issues
        CHUNK_SIZE     = 50_000
        df             = df.where(pd.notna(df), None)
        placeholders   = ", ".join(["%s"] * len(df.columns))
        total_inserted = 0

        pg_conn.autocommit = False
        for start in range(0, len(df), CHUNK_SIZE):
            chunk = df.iloc[start:start + CHUNK_SIZE]
            rows  = [tuple(row) for row in chunk.itertuples(index=False, name=None)]
            cur.executemany(
                f'INSERT INTO "{staging_schema}"."{stg_table}" VALUES ({placeholders})',
                rows
            )
            pg_conn.commit()
            total_inserted += len(chunk)
            print(f"[DuckDB Extract] ✓ {total_inserted:,}/{len(df):,} rows loaded...")

        cur.close(); pg_conn.close()

        return {"success": True, "rows": total_inserted, "columns": list(df.columns)}

    except Exception as e:
        return {"success": False, "error": str(e), "rows": 0}


# ── Extract: any source → any target staging ──────────────────────────────────

def extract_to_staging(source_tables: list, source_config: dict,
                       target_config: dict, source_schema: str = "raw",
                       staging_schema: str = "staging",
                       source_columns: dict = None,
                       should_stop_fn=None, log_fn=None) -> dict:
    logs           = []
    total          = 0
    source_columns = source_columns or {}
    source_config  = _cfg(source_config)
    target_config  = _cfg(target_config)
    src_type       = source_config.get("connector_type", "postgres").upper()
    tgt_type       = target_config.get("connector_type", "postgres").upper()

    def lg(msg):
        line = f"[{_ts()}] [Extract] {msg}"
        print(line); logs.append(line)

    lg("━━━ EXTRACT PHASE STARTED ━━━")
    lg(f"Source: {source_config.get('host')}/{source_config.get('database')}/{source_schema} [{src_type}]")
    lg(f"Target: {target_config.get('host')}/{target_config.get('database')}/{staging_schema} [{tgt_type}]")
    lg(f"Tables to extract: {len(source_tables)} — {source_tables}")

    if not source_tables:
        lg("✗ ERROR: No source tables provided.")
        return {"success": False, "error": "No source tables", "logs": logs, "rows": 0}

    # Ensure staging schema exists in target
    try:
        _ensure_schema(target_config, staging_schema)
        lg(f"✓ Schema '{staging_schema}' ready")
    except Exception as e:
        lg(f"✗ Could not create staging schema: {e}")
        return {"success": False, "error": str(e), "logs": logs, "rows": 0}

    for table in source_tables:
        sel_cols = source_columns.get(table)
        try:
            if sel_cols:
                lg(f"→ Extracting {table} ({len(sel_cols)} selected columns)")
            else:
                lg(f"→ Extracting {table} (ALL columns)")

            # ── DuckDB source ─────────────────────────────────────────────────
            if _is_duckdb(source_config):
                result = _extract_from_duckdb(
                    source_config  = source_config,
                    table_name     = table,
                    target_config  = target_config,
                    staging_schema = staging_schema,
                    selected_columns = sel_cols
                )
            else:
                result = extract_table_universal(
                    source_config=source_config, target_config=target_config,
                    source_schema=source_schema, table=table,
                    staging_schema=staging_schema, selected_columns=sel_cols
                )

            if result["success"]:
                total += result["rows"]
                lg(f"✓ {staging_schema}.stg_{table} ← {source_schema}.{table} — {result['rows']} rows")
            else:
                lg(f"✗ FAILED to extract {table}: {result.get('error', 'unknown')}")
                raise Exception(result.get("error", "extract failed"))

        except Exception as e:
            lg(f"✗ FAILED to extract {table}: {e}")
            return {"success": False, "error": str(e), "logs": logs, "rows": total}

    lg(f"━━━ EXTRACT COMPLETE — {len(source_tables)} tables, {total} rows total ━━━")
    return {"success": True, "rows": total, "logs": logs,
            "tables_extracted": len(source_tables)}


def _auto_create_dim_indexes(target_config: dict, warehouse_schema: str,
                              table_name: str, log) -> None:
    """
    Auto-create indexes on dimension tables after loading.
    Generic — detects all non-key, non-system text/integer columns
    and creates indexes on them for fast fact table JOINs.
    No hardcoding of column names.
    """
    try:
        conn = _pg_connect(target_config)
        conn.autocommit = True
        cur  = conn.cursor()

        # Get all columns in this dim table
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (warehouse_schema, table_name))
        cols = cur.fetchall()

        # Index candidates: non-system, non-surrogate columns
        skip_cols = {
            'is_current', 'valid_from', 'valid_to', 'updated_at',
            'created_at', 'loaded_at', 'effective_start_date',
            'effective_end_date', 'period_id'
        }
        indexable_types = {
            'text', 'varchar', 'character varying', 'char',
            'integer', 'bigint', 'smallint', 'numeric', 'boolean'
        }

        index_cols = []
        for col, dtype in cols:
            # Skip surrogate keys (ends with _key) and system cols
            if col.endswith('_key') or col in skip_cols:
                continue
            if any(t in dtype.lower() for t in indexable_types):
                index_cols.append(col)

        # Create individual index per column
        for col in index_cols:
            idx_name = f"idx_{table_name}_{col}"
            try:
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {warehouse_schema}.{table_name}("{col}");
                """)
                log(f"[AutoIndex] ✓ {warehouse_schema}.{table_name}(\"{col}\")")
            except Exception as e:
                log(f"[AutoIndex] ⚠ {table_name}.{col}: {e}")

        cur.close()
        conn.close()

    except Exception as e:
        log(f"[AutoIndex] Warning: {e}")


def _expand_composite_joins(sql_scripts: list, target_config: dict,
                             warehouse_schema: str, staging_schema: str, log) -> list:
    """
    Generic fix for fact-to-dim JOIN row multiplication.

    When a fact table joins a dimension that has no natural key
    (surrogate-only dim), the JOIN must match on ALL of that dim's
    columns — not just a subset (e.g. brand+model+year) — or rows
    with the same partial key but different other attributes
    (e.g. different engine_cc/seats) will all match, multiplying
    the fact table row count (acts like a partial cross join).

    Source column names are resolved by querying the staging table's
    ACTUAL columns directly (not by scanning the fact SQL text, since
    the fact script often doesn't reference every dim attribute column
    — those only appear in the separate dim-building script).

    Fully generic — works for ANY domain, ANY dim/fact names.
    """
    # universal: runs for all target DB types
    # (expand composite joins for any target)

    import re
    try:
        conn = _pg_connect(target_config)
        cur  = conn.cursor()

        # Get all warehouse dim tables and their columns (include numeric_scale
        # upfront so we don't need a separate DB round-trip per column later)
        cur.execute("""
            SELECT table_name, column_name, data_type, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name LIKE 'dim_%%'
            ORDER BY table_name, ordinal_position
        """, (warehouse_schema,))
        dim_cols = {}
        dim_col_scale = {}
        for tbl, col, dtype, scale in cur.fetchall():
            dim_cols.setdefault(tbl, []).append((col, dtype))
            dim_col_scale[(tbl, col)] = scale if scale is not None else 2

        # Get ALL staging table columns (across all staging tables) so we can
        # resolve dim column → actual source column name, even if the fact
        # script's own SQL text never mentions that source column.
        cur.execute("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """, (staging_schema,))
        staging_cols_by_table = {}
        all_staging_cols = set()
        for tbl, col in cur.fetchall():
            staging_cols_by_table.setdefault(tbl, []).append(col)
            all_staging_cols.add(col)

        cur.close(); conn.close()

        # Build a single lookup: normalized_name -> actual_column_name
        # normalized = lowercase, no underscores (so Fuel_Type == fueltype == FuelType)
        src_col_lookup = {}
        for col in all_staging_cols:
            key = col.lower().replace('_', '')
            # Prefer not overwriting if already set (first match wins, stable)
            src_col_lookup.setdefault(key, col)

        skip_cols = {
            'is_current', 'valid_from', 'valid_to', 'updated_at',
            'created_at', 'loaded_at', 'effective_start_date',
            'effective_end_date'
        }

        patched = []
        for script in sql_scripts:
            sql = script.get("sql", "")
            if not script.get("name", "").startswith("fact_"):
                patched.append(script)
                continue

            original = sql
            join_pattern = re.compile(
                r'JOIN\s+warehouse\.(dim_\w+)\s+(\w+)\s+ON\s+(.+?)'
                r'(?=\s+JOIN\s+warehouse\.|$|\s+WHERE\s|\s+ON\s+CONFLICT)',
                re.IGNORECASE | re.DOTALL
            )

            def expand_join(m):
                dim_table = m.group(1).lower()
                alias     = m.group(2)
                condition = m.group(3).strip().rstrip(';')

                # dim_date is a generated calendar dimension (full_date, year,
                # quarter, month, day, day_of_week, month_name) — its columns
                # are DERIVED from a date series, not sourced from the staging
                # table column-for-column like dim_car/dim_seller are. It must
                # NEVER go through composite-attribute expansion; it's always
                # joined via the dedicated year+Jan-1st pattern handled by
                # _patch_sql_column_names's fix_date_join, applied earlier.
                if dim_table == 'dim_date':
                    return m.group(0)

                if dim_table not in dim_cols:
                    return m.group(0)

                all_cols = [c for c, dt in dim_cols[dim_table]
                            if not c.endswith('_key') and c not in skip_cols]
                if not all_cols:
                    return m.group(0)

                referenced = sum(1 for c in all_cols
                                  if re.search(rf'\b{alias}\.{c}\b', condition, re.IGNORECASE))

                if referenced < len(all_cols) and referenced < len(all_cols) * 0.8:
                    new_conditions = []
                    missing = []
                    for col, dtype in dim_cols[dim_table]:
                        if col.endswith('_key') or col in skip_cols or col not in all_cols:
                            continue
                        key = col.lower().replace('_', '')
                        src_col = src_col_lookup.get(key)
                        # Also try fuzzy match for renamed columns
                        # e.g. max_power -> Horsepower, accident_history -> Accidents
                        if not src_col:
                            best = None
                            best_score = 0
                            for sc in all_staging_cols:
                                sc_key = sc.lower().replace('_', '')
                                # containment check
                                if key in sc_key or sc_key in key:
                                    score = len(set(key) & set(sc_key)) / max(len(key), len(sc_key), 1)
                                    if score > best_score:
                                        best_score = score
                                        best = sc
                                # partial word match (first 4 chars)
                                elif len(key) >= 4 and len(sc_key) >= 4:
                                    if key[:4] == sc_key[:4]:
                                        score = 0.4
                                        if score > best_score:
                                            best_score = score
                                            best = sc
                            if best and best_score > 0.3:
                                src_col = best
                        if not src_col:
                            missing.append(col)
                            continue
                        # Skip columns that are entirely NULL in the dim table
                        # (e.g. accident_history=NULL because stg_car had no Accidents col)
                        # A NULL JOIN condition would return 0 rows
                        try:
                            _null_chk_cur = conn.cursor()
                            _null_chk_cur.execute(
                                f"SELECT COUNT(*) FROM {warehouse_schema}.{dim_table} "
                                f"WHERE {col} IS NOT NULL LIMIT 1"
                            )
                            _non_null_count = _null_chk_cur.fetchone()[0]
                            _null_chk_cur.close()
                            if _non_null_count == 0:
                                missing.append(col)
                                continue
                        except Exception:
                            pass
                        if 'numeric' in dtype.lower() or 'decimal' in dtype.lower():
                            # dim column is rounded (e.g. NUMERIC(10,2)) but the
                            # staging source column often has higher raw precision
                            # (e.g. NUMERIC(20,6)) — round BOTH sides to the dim's
                            # actual scale before comparing, or equality will almost
                            # always fail on floating-point-style mismatches.
                            scale = dim_col_scale.get((dim_table, col), 2)
                            new_conditions.append(
                                f'ROUND({alias}.{col}, {scale}) = ROUND(src."{src_col}"::numeric, {scale})'
                            )
                        elif 'char' in dtype.lower() or 'text' in dtype.lower():
                            # Cast both sides to text to handle source columns that may
                            # be integer/bigint (e.g. Accidents=BIGINT, accident_history=VARCHAR)
                            # TRIM(bigint) causes "function btrim(bigint) does not exist"
                            new_conditions.append(
                                f'TRIM({alias}.{col}::text) = TRIM(src."{src_col}"::text)'
                            )
                        else:
                            new_conditions.append(f'{alias}.{col} = src."{src_col}"')

                    # Expand JOIN with whatever columns we resolved
                    # If some dim columns are missing from source, use the ones we have
                    # This prevents row explosion from partial JOINs
                    if new_conditions:
                        if missing:
                            log(f"[SQLPatch] Partial JOIN expand on {dim_table} "
                                f"— skipping missing source cols: {missing}. "
                                f"Using {len(new_conditions)} available columns.")
                        else:
                            log(f"[SQLPatch] Expanding JOIN on {dim_table} from "
                                f"{referenced} to {len(new_conditions)} columns "
                                f"(prevents row multiplication, numeric columns rounded "
                                f"to match precision)")
                        new_cond_str = " AND ".join(new_conditions)
                        return f"JOIN warehouse.{dim_table} {alias} ON {new_cond_str}"

                return m.group(0)

            sql = join_pattern.sub(expand_join, sql)

            if sql != original:
                script = {**script, "sql": sql}
                log(f"[SQLPatch] ✓ Composite JOIN expanded for: {script.get('name')}")

            patched.append(script)

        return patched

    except Exception as e:
        log(f"[SQLPatch] Composite JOIN check warning: {e}")
        return sql_scripts


def _patch_sql_column_names(sql_scripts: list, target_config: dict,
                             staging_schema: str, log,
                             warehouse_schema: str = "warehouse",
                             is_snapshot_source: bool = False) -> list:
    """
    Pre-execution SQL patcher — fixes known AI column hallucinations.

    Scans actual staging table columns and replaces wrong column names
    in generated SQL with correct ones.

    Generic patterns fixed:
    1. Invented date columns (listing_date, transaction_date) → actual year/date col
    2. Wrong column names (Accident_History → Accidents)
    3. src.None → removed from SQL
    """
    import re  # ← import at top of function, not inside loop!
    import difflib

    # universal: runs for all target DB types
    # (connection handled per-DB below)

    try:
        ct = target_config.get("connector_type", "postgres").lower()
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(target_config)
        elif ct == "snowflake":
            from universal_connector import _snowflake_connect
            conn = _snowflake_connect(target_config)
        elif ct in ("mysql", "mariadb"):
            from universal_connector import _mysql_connect
            conn = _mysql_connect(target_config)
        elif ct in ("sqlserver", "mssql", "azuresql"):
            from universal_connector import _sqlserver_connect
            conn = _sqlserver_connect(target_config)
        else:
            conn = _pg_connect(target_config)
        cur  = conn.cursor()

        # Get all staging table columns
        cur.execute("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """, (staging_schema,))
        rows = cur.fetchall()
        cur.close(); conn.close()

        # Build column map: table → {col_lower: actual_col}
        staging_cols = {}
        for tbl, col, dtype in rows:
            staging_cols.setdefault(tbl, {})[col.lower()] = (col, dtype)

        # Find the raw staging table (most columns)
        raw_tbl = max(staging_cols, key=lambda t: len(staging_cols[t])) \
                  if staging_cols else None
        if not raw_tbl:
            return sql_scripts

        actual_cols = staging_cols[raw_tbl]  # {col_lower: (col, dtype)}
        actual_col_names = {v[0] for v in actual_cols.values()}  # actual names

        # Find date/year column
        date_col = None
        year_col = None
        for col_lower, (col, dtype) in actual_cols.items():
            if dtype in ('date', 'timestamp', 'timestamptz') and not date_col:
                date_col = col
            if 'year' in col_lower and dtype in ('bigint', 'integer', 'int', 'smallint'):
                year_col = col

        # Fetch warehouse dim/fact column types upfront — needed to detect
        # type mismatches (e.g. dim.accident_history VARCHAR vs
        # staging.Accidents bigint) and insert explicit CASTs automatically,
        # the same class of bug as the TRIM/precision issues above.
        warehouse_col_types = {}  # {(table, column): data_type}
        try:
            conn2 = _pg_connect(target_config)
            cur2  = conn2.cursor()
            cur2.execute("""
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
            """, (warehouse_schema,))
            for tbl, col, dtype in cur2.fetchall():
                warehouse_col_types[(tbl, col)] = dtype
            cur2.close(); conn2.close()
        except Exception:
            pass

        patched = []
        for script in sql_scripts:
            sql = script.get("sql", "")
            original = sql

            # Fix 0: src.None or src."None" → remove FIRST before other fixes
            # This happens when AI's join_on_source_col is None (no natural key)
            if 'src.None' in sql or 'src."None"' in sql or 'business_key' in sql.lower():
                log(f"[SQLPatch] Removing src.None/business_key from {script.get('name')}")
                # Remove from SELECT
                sql = sql.replace('src."None"', '')
                sql = sql.replace('src.None', '')
                # Remove business_key from INSERT column list
                sql = re.sub(r'\bbusiness_key\s*,\s*', '', sql, flags=re.IGNORECASE)
                sql = re.sub(r',\s*\bbusiness_key\b', '', sql, flags=re.IGNORECASE)
                # Remove business_key column from CREATE TABLE
                sql = re.sub(
                    r',?\s*business_key\s+INTEGER\s+UNIQUE\s+NOT\s+NULL\s*,?',
                    ',', sql, flags=re.IGNORECASE
                )
                sql = re.sub(
                    r'business_key\s+INTEGER\s+UNIQUE\s+NOT\s+NULL\s*,\s*',
                    '', sql, flags=re.IGNORECASE
                )
                # Remove ON CONFLICT (business_key) entirely
                sql = re.sub(
                    r'ON\s+CONFLICT\s*\(\s*business_key\s*\)\s*DO\s+\w+[^;]*',
                    '', sql, flags=re.IGNORECASE
                )
                sql = re.sub(
                    r'ON\s+CONFLICT\s*\(\s*business_key\s*\)',
                    '', sql, flags=re.IGNORECASE
                )
                # Clean up all comma issues after removal
                sql = re.sub(r',\s*,', ',', sql)
                sql = re.sub(r',\s*\)', ')', sql)
                sql = re.sub(r'\(\s*,', '(', sql)
                sql = re.sub(r'SELECT\s*,', 'SELECT', sql)
                sql = re.sub(r'SELECT\s+,', 'SELECT ', sql)
                sql = re.sub(r',\s*\)', ')', sql)
                log(f"[SQLPatch] ✓ src.None/business_key removed")

            # Fix: Convert ON CONFLICT (col) DO UPDATE to WHERE NOT EXISTS
            # Generic: extracts the conflict column and builds IS NOT DISTINCT FROM conditions
            # Works for any dim table, any column name
            if script.get("name", "").startswith("dim_") and "ON CONFLICT" in sql.upper() and "DO UPDATE" in sql.upper():
                import re as _re_wne
                # Extract conflict column name: ON CONFLICT (brand) DO UPDATE...
                _conf_m = _re_wne.search(r'ON\s+CONFLICT\s*\(([^)]+)\)\s*DO\s+UPDATE', sql, _re_wne.IGNORECASE)
                # Extract INSERT column list to build WHERE NOT EXISTS conditions
                _ins_m = _re_wne.search(r'INSERT\s+INTO\s+\S+\s*\(([^)]+)\)', sql, _re_wne.IGNORECASE)
                _from_m = _re_wne.search(r'FROM\s+(staging\.\w+)\s+(\w+)', sql, _re_wne.IGNORECASE)
                _wh_tbl_m = _re_wne.search(r'INSERT\s+INTO\s+(warehouse\.\w+)', sql, _re_wne.IGNORECASE)

                if _ins_m and _from_m and _wh_tbl_m:
                    _ins_cols = [c.strip() for c in _ins_m.group(1).split(',')]
                    _alias = _from_m.group(2)
                    _wh_tbl = _wh_tbl_m.group(1)
                    # Skip system/surrogate columns
                    _skip = {'updated_at','created_at','loaded_at','is_current','valid_from','valid_to'}
                    _skip_sfx = {'_key'}
                    _biz_cols = [c for c in _ins_cols
                                 if c.lower() not in _skip
                                 and not any(c.lower().endswith(s) for s in _skip_sfx)]
                    # Build IS NOT DISTINCT FROM conditions for each business column
                    # Match warehouse col to staging col via position in SELECT
                    _sel_m = _re_wne.search(
                        r'SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM\s+staging',
                        sql, _re_wne.IGNORECASE | _re_wne.DOTALL
                    )
                    _sel_vals = []
                    if _sel_m:
                        _sv_str = _sel_m.group(1)
                        _d = 0; _cur = []
                        for _ch in _sv_str:
                            if _ch == '(': _d += 1; _cur.append(_ch)
                            elif _ch == ')': _d -= 1; _cur.append(_ch)
                            elif _ch == ',' and _d == 0: _sel_vals.append(''.join(_cur).strip()); _cur = []
                            else: _cur.append(_ch)
                        if _cur: _sel_vals.append(''.join(_cur).strip())

                    _conditions = []
                    for _idx, _wc in enumerate(_biz_cols):
                        if _idx < len(_sel_vals):
                            _sv = _sel_vals[_idx].strip()
                            _conditions.append(f'd.{_wc.lower()}::text IS NOT DISTINCT FROM ({_sv})::text')
                        else:
                            _conditions.append(f'd.{_wc.lower()}::text IS NOT DISTINCT FROM {_alias}."{_wc}"::text')

                    if _conditions:
                        _wne = ' AND '.join(_conditions)
                        # Remove ON CONFLICT DO UPDATE block
                        sql = _re_wne.sub(
                            r'\s*ON\s+CONFLICT\s*\([^)]+\)\s*DO\s+UPDATE[^;]*',
                            '', sql, flags=_re_wne.IGNORECASE | _re_wne.DOTALL
                        )
                        # Add WHERE NOT EXISTS before the semicolon at end of INSERT
                        sql = _re_wne.sub(
                            r'(FROM\s+staging\.\w+\s+\w+)(\s*;)',
                            lambda m, t=_wh_tbl, w=_wne: m.group(1) + ' WHERE NOT EXISTS (SELECT 1 FROM ' + t + ' d WHERE ' + w + ')' + m.group(2),
                            sql, count=1, flags=_re_wne.IGNORECASE
                        )
                    else:
                        sql = _re_wne.sub(
                            r'\s*ON\s+CONFLICT\s*\([^)]+\)\s*DO\s+UPDATE[^;]*',
                            '', sql, flags=_re_wne.IGNORECASE | _re_wne.DOTALL
                        )
                        log(f"[SQLPatch] Stripped ON CONFLICT DO UPDATE from dim: {script.get('name')}")
                else:
                    sql = re.sub(
                        r'\s*ON\s+CONFLICT\s*(?:\([^)]*\))?\s*DO\s+UPDATE[^;]*',
                        '', sql, flags=re.IGNORECASE | re.DOTALL
                    )
                    log(f"[SQLPatch] Stripped ON CONFLICT DO UPDATE from dim: {script.get('name')}")

            # Fix 0b: SERIAL PRIMARY KEY INTEGER → always fix regardless of src.None
            if re.search(r'SERIAL\s+PRIMARY\s+KEY\s+INTEGER', sql, re.IGNORECASE):
                log(f"[SQLPatch] Fixing SERIAL PRIMARY KEY syntax in {script.get('name')}")
                sql = re.sub(
                    r'SERIAL\s+PRIMARY\s+KEY\s+INTEGER\s+(?:UNIQUE\s+)?(?:NOT\s+NULL\s+)?',
                    'SERIAL PRIMARY KEY ',
                    sql, flags=re.IGNORECASE
                )

            # Fix 0c0: Remove duplicate column definitions in CREATE TABLE
            # AI generates e.g. "Brand INTEGER UNIQUE" AND "brand VARCHAR" -> duplicate error
            if 'CREATE TABLE' in sql.upper():
                def fix_create_table_dedup(m):
                    full = m.group(0)
                    paren_start = full.index('(')
                    depth = 0
                    paren_end = paren_start
                    for i2, ch in enumerate(full[paren_start:], paren_start):
                        if ch == '(':
                            depth += 1
                        elif ch == ')':
                            depth -= 1
                            if depth == 0:
                                paren_end = i2
                                break
                    cols_block = full[paren_start+1:paren_end]
                    cols = []
                    depth2 = 0
                    current = []
                    for ch in cols_block:
                        if ch == '(':
                            depth2 += 1
                            current.append(ch)
                        elif ch == ')':
                            depth2 -= 1
                            current.append(ch)
                        elif ch == ',' and depth2 == 0:
                            cols.append(''.join(current).strip())
                            current = []
                        else:
                            current.append(ch)
                    if current:
                        cols.append(''.join(current).strip())
                    seen = {}
                    kept = []
                    changed = False
                    for col_def in cols:
                        tokens = col_def.split()
                        if not tokens:
                            continue
                        col_name_raw = tokens[0].strip('"').lower()
                        if col_name_raw.upper() in ('PRIMARY', 'UNIQUE', 'FOREIGN', 'CHECK', 'CONSTRAINT'):
                            kept.append(col_def)
                            continue
                        if col_name_raw not in seen:
                            seen[col_name_raw] = len(kept)
                            kept.append(col_def)
                        else:
                            existing_idx = seen[col_name_raw]
                            existing = kept[existing_idx]
                            eu = existing.upper()
                            nu = col_def.upper()
                            changed = True
                            if ('INTEGER' in eu or 'SERIAL' in eu) and ('VARCHAR' in nu or 'TEXT' in nu or 'CHAR' in nu):
                                kept[existing_idx] = col_def
                            # else drop the duplicate silently
                    if changed:
                        return full[:paren_start+1] + ', '.join(kept) + full[paren_end:]
                    return full
                sql = re.sub(
                    r'CREATE TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+\S+\s*\([^;]+\)',
                    fix_create_table_dedup,
                    sql,
                    flags=re.IGNORECASE | re.DOTALL
                )
                if sql != original:
                    log(f"[SQLPatch] Dedup CREATE TABLE columns in {script.get('name')}")

            # Fix 0c0b: Remove duplicate column names from INSERT column list
            def dedup_insert_cols(m):
                cols_str = m.group(1)
                orig_cols = [c.strip() for c in cols_str.split(',')]
                seen_ins = set()
                kept_ins = []
                for orig in orig_cols:
                    normalized = orig.strip('"').lower()
                    if normalized not in seen_ins:
                        seen_ins.add(normalized)
                        kept_ins.append(orig)
                if len(kept_ins) < len(orig_cols):
                    log(f"[SQLPatch] Dedup INSERT cols in {script.get('name')}: removed {len(orig_cols)-len(kept_ins)} duplicate(s)")
                    return m.group(0).replace(cols_str, ', '.join(kept_ins))
                return m.group(0)
            sql = re.sub(
                r'INSERT\s+INTO\s+\S+\s*\(([^)]+)\)',
                dedup_insert_cols,
                sql,
                flags=re.IGNORECASE
            )
            # Fix 0c0c: Dedup SELECT values to match deduped INSERT col count
            try:
                import re as _re3
                # Find ALL INSERT...SELECT pairs (handles multi-statement SQL)
                for _m in list(_re3.finditer(
                    r'INSERT\s+INTO\s+\S+\s*\(([^)]+)\)\s*SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM\s+',
                    sql, _re3.IGNORECASE | _re3.DOTALL
                )):
                    _icols = [c.strip() for c in _m.group(1).split(',')]
                    _svals_str = _m.group(2)
                    _svals = []
                    _d = 0; _cur = []
                    for _ch in _svals_str:
                        if _ch == '(': _d += 1; _cur.append(_ch)
                        elif _ch == ')': _d -= 1; _cur.append(_ch)
                        elif _ch == ',' and _d == 0: _svals.append(''.join(_cur).strip()); _cur = []
                        else: _cur.append(_ch)
                    if _cur: _svals.append(''.join(_cur).strip())
                    _seen_s = set()
                    _kept_s = []
                    for _sv in _svals:
                        _key = _sv.strip()
                        for _pfx in ['src."', 's."', 'src.', 's.']:
                            if _key.lower().startswith(_pfx.lower()):
                                _key = _key[len(_pfx):]
                                break
                        _key = _key.strip('"').lower()
                        if _key not in _seen_s:
                            _seen_s.add(_key)
                            _kept_s.append(_sv)
                    _kept_s = _kept_s[:len(_icols)]
                    if len(_kept_s) < len(_svals):
                        log(f"[SQLPatch] Dedup SELECT values in {script.get('name')}: removed {len(_svals)-len(_kept_s)} duplicate(s)")
                        sql = sql.replace(
                            f"SELECT {_svals_str} FROM",
                            f"SELECT {', '.join(_kept_s)} FROM",
                            1
                        )
            except Exception:
                pass

            # Fix 0c0e: Quote all unquoted alias.Column references in SELECT
            # e.g. s.Brand -> s."Brand", s.City -> s."City"
            # Unquoted refs are folded to lowercase by PostgreSQL, causing column not found
            if 'INSERT INTO' in sql.upper() and 'SELECT' in sql.upper():
                import re as _re5
                def _quote_col_ref(m):
                    alias = m.group(1)
                    col = m.group(2)
                    return f'{alias}."{col}"'
                sql = _re5.sub(
                    r'\b([a-z]+)\.([A-Z][A-Za-z0-9_]*)(?!")',
                    _quote_col_ref,
                    sql
                )

            # Fix 0c0d: Add DISTINCT to dim INSERT SELECT DISTINCT
            # dim_seller should have 4 rows not 9998
            if script.get("name", "").startswith("dim_") and "INSERT INTO" in sql.upper():
                import re as _re4
                # Replace SELECT (not already DISTINCT) with SELECT DISTINCT
                sql = _re4.sub(
                    r'SELECT(?!\s+DISTINCT)',
                    'SELECT DISTINCT',
                    sql,
                    count=1,
                    flags=_re4.IGNORECASE
                )

            # Fix 0c1: fact tables are append-only with no uniqueness
            # protection at all, so re-executing the same pipeline (e.g.
            # after fixing an unrelated error, or on a scheduled re-run)
            # silently duplicates the entire fact table's rows every time —
            # confirmed by a real test where fact_car_listings went from
            # 9,998 to 19,996 rows on a second identical run. Add a
            # period_id (YYYYMMDD) column tagging each load, and DELETE any
            # existing rows for today's period_id before inserting — this
            # makes same-day re-runs idempotent (replace, not duplicate)
            # while still preserving full historical audit trail across
            # different days, matching standard DWH incremental-load design.
            is_fact_script = script.get("name", "").startswith("fact_")
            has_period_id  = bool(re.search(r'\bperiod_id\b', sql, re.IGNORECASE))

            if is_fact_script and not has_period_id:
                tbl_name = script.get("name", "")

                if is_snapshot_source:
                    # Snapshot source (DuckDB/CSV/Excel): full refresh with period_id audit trail.
                    # DELETE ALL rows before INSERT so row count stays stable across runs.
                    period_expr = "TO_CHAR(CURRENT_DATE, 'YYYYMMDD')::BIGINT"
                    # Add period_id column
                    sql_new = re.sub(
                        r'(CREATE TABLE IF NOT EXISTS warehouse\.\w+\s*\(\s*\w+\s+SERIAL\s+PRIMARY\s+KEY,)',
                        r'\1 period_id BIGINT,',
                        sql, count=1, flags=re.IGNORECASE
                    )
                    # Add period_id to INSERT column list
                    sql_new = re.sub(
                        rf'(INSERT\s+INTO\s+warehouse\.{re.escape(tbl_name)}\s*\()([^)]+)(\))',
                        rf'\1period_id, \2\3',
                        sql_new, count=1, flags=re.IGNORECASE
                    )
                    # Add period_id value to SELECT
                    sql_new = re.sub(
                        rf'(INSERT\s+INTO\s+warehouse\.{re.escape(tbl_name)}\s*\([^)]+\)\s*SELECT\s+)',
                        rf'\g<1>{period_expr}, ',
                        sql_new, count=1, flags=re.IGNORECASE
                    )
                    # DELETE ALL then INSERT
                    delete_all = f'DELETE FROM warehouse.{tbl_name}; '
                    sql_new = re.sub(
                        rf'(INSERT\s+INTO\s+warehouse\.{re.escape(tbl_name)})',
                        delete_all + r'\1', sql_new, count=1, flags=re.IGNORECASE
                    )
                    if sql_new != sql:
                        log(f"[SQLPatch] Snapshot: full refresh for {tbl_name} (DELETE ALL + INSERT with period_id)")
                        sql = sql_new
                else:
                    # Incremental source: period_id DELETE+INSERT for idempotency
                    period_expr = "TO_CHAR(CURRENT_DATE, 'YYYYMMDD')::BIGINT"
                    sql_new = re.sub(
                        r'(CREATE TABLE IF NOT EXISTS warehouse\.\w+\s*\(\s*\w+\s+SERIAL\s+PRIMARY\s+KEY,)',
                        r'\1 period_id BIGINT NOT NULL,',
                        sql, count=1, flags=re.IGNORECASE
                    )
                    sql_new = re.sub(
                        rf'(INSERT\s+INTO\s+warehouse\.{re.escape(tbl_name)}\s*\()([^)]+)(\))',
                        rf'\1period_id, \2\3',
                        sql_new, count=1, flags=re.IGNORECASE
                    )
                    sql_new = re.sub(
                        rf'(INSERT\s+INTO\s+warehouse\.{re.escape(tbl_name)}\s*\([^)]+\)\s*SELECT\s+)',
                        rf'\g<1>{period_expr}, ',
                        sql_new, count=1, flags=re.IGNORECASE
                    )
                    delete_stmt = (
                        f'DELETE FROM warehouse.{tbl_name} '
                        f'WHERE period_id = {period_expr}; '
                    )
                    sql_new = re.sub(
                        rf'(INSERT\s+INTO\s+warehouse\.{re.escape(tbl_name)})',
                        delete_stmt + r'\1', sql_new, count=1, flags=re.IGNORECASE
                    )
                    if sql_new != sql:
                        log(f"[SQLPatch] Incremental: period_id idempotency added to {tbl_name}")
                        sql = sql_new
            # Fix: convert = to IS NOT DISTINCT FROM in fact->dim JOIN conditions
            # Handles NULL values and type mismatches for any domain generically
            if script.get("name","").startswith("fact_") and "JOIN warehouse." in sql:
                import re as _re_nd
                def _fact_join_not_distinct(m):
                    full = m.group(0)
                    # Skip if already IS NOT DISTINCT FROM
                    if "IS NOT DISTINCT" in full:
                        return full
                    col1 = m.group(1)  # dc.brand
                    col2 = m.group(2)  # src."Brand"
                    # Skip dim_date joins — handled separately by fix_date_join
                    if "dim_date" in full.lower() or "dd." in full:
                        return full
                    return f"{col1} IS NOT DISTINCT FROM {col2}"
                sql = _re_nd.sub(
                    r'(\w+\.\w+)\s*=\s*((?:src|s)\."\w+"|ROUND\([^)]+\))',
                    _fact_join_not_distinct, sql
                )


            # Fix 0c2: dim tables with NO natural key (flat-file/no-ID sources)
            # frequently get "ON CONFLICT DO NOTHING" with no column list, or
            # rely solely on the auto-increment surrogate key as the only
            # constraint. Since the surrogate key is always unique (it's a
            # fresh SERIAL value every insert), this NEVER actually prevents
            # re-inserting the exact same business-attribute combination on
            # a second pipeline run — the dim table silently doubles in size
            # every re-execution instead of staying idempotent. Detect this
            # pattern and add an explicit composite UNIQUE constraint across
            # the dimension's actual attribute columns (derived from the
            # INSERT's SELECT DISTINCT column list), then rewrite
            # ON CONFLICT to reference it by name so duplicates are
            # correctly skipped on every subsequent run.
            is_dim_script = script.get("name", "").startswith("dim_")
            has_bare_on_conflict = bool(re.search(
                r'ON\s+CONFLICT\s+DO\s+NOTHING', sql, re.IGNORECASE
            )) and not re.search(r'ON\s+CONFLICT\s*\([^)]+\)', sql, re.IGNORECASE)
            has_real_unique = bool(re.search(
                r'UNIQUE\s*\(', sql, re.IGNORECASE
            )) or bool(re.search(
                r'\w+\s+\w+(?:\(\d+(?:,\d+)?\))?\s+UNIQUE\s+NOT\s+NULL', sql, re.IGNORECASE
            ))

            if is_dim_script and has_bare_on_conflict and not has_real_unique:
                # Extract the INSERT's target column list — this is the set
                # of business attributes that should define uniqueness for
                # a dim with no natural key (excludes surrogate key and
                # system/SCD-tracking columns).
                insert_match = re.search(
                    r'INSERT\s+INTO\s+warehouse\.\w+\s*\(([^)]+)\)', sql, re.IGNORECASE
                )
                skip_insert_cols = {
                    'valid_from', 'valid_to', 'is_current', 'updated_at',
                    'created_at', 'loaded_at', 'effective_start_date',
                    'effective_end_date'
                }
                if insert_match:
                    insert_cols = [c.strip() for c in insert_match.group(1).split(',')]
                    key_cols = [c for c in insert_cols if c.lower() not in skip_insert_cols]
                    if key_cols:
                        constraint_name = f"uq_{script.get('name')}_attrs"
                        key_cols_sql = ", ".join(key_cols)
                        log(f"[SQLPatch] Adding composite UNIQUE constraint on "
                            f"{script.get('name')}({key_cols_sql}) — prevents "
                            f"duplicate rows on re-execution (was relying only "
                            f"on auto-increment key, which never conflicts)")
                        # Insert the UNIQUE constraint into the CREATE TABLE,
                        # right before its closing paren.
                        sql = re.sub(
                            r'(CREATE TABLE IF NOT EXISTS warehouse\.\w+\s*\([^;]+?)\)\s*;',
                            lambda m: f'{m.group(1)}, CONSTRAINT {constraint_name} '
                                      f'UNIQUE ({key_cols_sql})); ',
                            sql, count=1, flags=re.IGNORECASE | re.DOTALL
                        )
                        # Rewrite the bare ON CONFLICT DO NOTHING to reference
                        # the new constraint's column list explicitly.
                        sql = re.sub(
                            r'ON\s+CONFLICT\s+DO\s+NOTHING',
                            f'ON CONFLICT ({key_cols_sql}) DO NOTHING',
                            sql, flags=re.IGNORECASE
                        )

            # Fix 0d: widen NUMERIC(p,s) column declarations in CREATE TABLE
            # to match the staging source column's ACTUAL precision/scale.
            # AI frequently declares a generic NUMERIC(10,2) for any decimal
            # column regardless of the source's real precision (e.g. source
            # is NUMERIC(20,6) but AI declares NUMERIC(10,2)). Comparing a
            # value rounded to 2 decimals against the raw 6-decimal source
            # in a JOIN/WHERE almost never matches — this previously caused
            # 99% of fact rows to silently fail to match their dimension.
            # Reads precision directly from PostgreSQL's information_schema
            # (proven reliable) rather than parsing DuckDB's DESCRIBE output
            # (unreliable — DuckDB's type strings don't consistently expose
            # precision/scale in a parseable format).
            if re.search(r'CREATE TABLE.*NUMERIC\(\d+,\d+\)', sql, re.IGNORECASE | re.DOTALL):
                try:
                    conn3 = _pg_connect(target_config)
                    cur3  = conn3.cursor()
                    cur3.execute("""
                        SELECT column_name, numeric_precision, numeric_scale
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        AND data_type IN ('numeric', 'decimal')
                    """, (staging_schema, raw_tbl))
                    src_numeric_precision = {
                        col: (prec, scale) for col, prec, scale in cur3.fetchall()
                        if prec is not None and scale is not None
                    }
                    cur3.close(); conn3.close()
                except Exception:
                    src_numeric_precision = {}

                # Build normalized lookup (lowercase, no underscores) so dim
                # column names (e.g. "engine_cc") resolve to source columns
                # (e.g. "Engine_CC") regardless of naming convention.
                src_prec_lookup = {}
                for col, (prec, scale) in src_numeric_precision.items():
                    key = col.lower().replace("_", "")
                    src_prec_lookup[key] = (prec, scale)

                def widen_numeric_decl(m):
                    col_name = m.group(1)
                    old_prec, old_scale = m.group(2), m.group(3)
                    # Always widen NUMERIC(10,2) to NUMERIC(20,6) for dim tables
                    # This handles cases where dim col name differs from source col name
                    if old_prec == "10" and old_scale == "2":
                        log(f"[SQLPatch] Widening {col_name} precision: NUMERIC(10,2) → NUMERIC(20,6) to match source")
                        return f"{col_name} NUMERIC(20,6)"
                    key = col_name.lower().replace("_", "")
                    if key in src_prec_lookup:
                        new_prec, new_scale = src_prec_lookup[key]
                        if (str(new_prec), str(new_scale)) != (old_prec, old_scale):
                            log(f"[SQLPatch] Widening {col_name} precision: "
                                f"NUMERIC({old_prec},{old_scale}) → "
                                f"NUMERIC({new_prec},{new_scale}) to match source")
                            return f'{col_name} NUMERIC({new_prec},{new_scale})'
                    return m.group(0)

                sql = re.sub(
                    r'(\w+)\s+NUMERIC\((\d+),(\d+)\)',
                    widen_numeric_decl, sql, flags=re.IGNORECASE
                )

            # Fix 0c: dim_date built with too-narrow a date range (legacy saved
            # pipelines). A narrow generate_series range (e.g. 2020-2030 only)
            # silently drops every fact row outside that range when INNER
            # JOINed — this caused 80% of rows to vanish with no error.
            # Widen to 1990-2035 regardless of what the saved SQL originally had.
            range_pattern = re.compile(
                r"generate_series\(\s*'(\d{4}-\d{2}-\d{2})'::DATE\s*,\s*"
                r"'(\d{4}-\d{2}-\d{2})'::DATE\s*,\s*'1 day'::INTERVAL\s*\)",
                re.IGNORECASE
            )
            rm = range_pattern.search(sql)
            if rm:
                start_year = int(rm.group(1)[:4])
                end_year   = int(rm.group(2)[:4])
                if start_year > 1990 or end_year < 2035:
                    log(f"[SQLPatch] Widening dim_date range from "
                        f"{rm.group(1)}..{rm.group(2)} to 1990-01-01..2035-12-31 "
                        f"(prevents silently dropping fact rows outside range)")
                    sql = range_pattern.sub(
                        "generate_series('1990-01-01'::DATE, '2035-12-31'::DATE, "
                        "'1 day'::INTERVAL)",
                        sql
                    )

            # Fix 1: invented date column in dim_date JOIN
            def fix_date_join(m):
                invented = m.group(1)
                if invented in actual_col_names:
                    return m.group(0)  # already correct
                if date_col:
                    log(f"[SQLPatch] dim_date join: '{invented}' → '{date_col}' (date col)")
                    return f'JOIN warehouse.dim_date dd ON dd.full_date = src."{date_col}"::DATE'
                elif year_col:
                    # IMPORTANT: dim_date typically has ~365 rows per year (one per day).
                    # Joining on year alone matches ALL of them, multiplying every fact
                    # row by ~365. Since the source only has a year (no real date),
                    # constrain to exactly ONE row per year (Jan 1st) so the JOIN
                    # stays 1:1 instead of exploding.
                    log(f"[SQLPatch] dim_date join: '{invented}' → year join on '{year_col}' "
                        f"(constrained to Jan 1st per year to avoid row multiplication)")
                    return (f'JOIN warehouse.dim_date dd ON dd.year = src."{year_col}" '
                            f'AND dd.month = 1 AND dd.day = 1')
                else:
                    log(f"[SQLPatch] dim_date join: no date/year col found — removing join")
                    return ''

            sql = re.sub(
                r'JOIN warehouse\.dim_date \w+ ON \w+\.full_date = src\."(\w+)"(?:::DATE)?',
                fix_date_join, sql, flags=re.IGNORECASE
            )

            # Fix 1b: also catch the year-only join pattern directly (e.g. if AI
            # or a previous patch already wrote "dd.year = src."Year"" without
            # the day constraint) — same row-multiplication risk applies.
            def constrain_year_join(m):
                full_match = m.group(0)
                if 'dd.month' in full_match.lower() and 'dd.day' in full_match.lower():
                    return full_match  # already constrained
                year_col_ref = m.group(1)
                log(f"[SQLPatch] dim_date join: constraining year-only join to "
                    f"Jan 1st per year (was matching all rows for that year)")
                return (f'JOIN warehouse.dim_date dd ON dd.year = src."{year_col_ref}" '
                        f'AND dd.month = 1 AND dd.day = 1')

            sql = re.sub(
                r'JOIN warehouse\.dim_date \w+ ON \w+\.year = src\."(\w+)"(?!\s+AND\s+\w+\.month)',
                constrain_year_join, sql, flags=re.IGNORECASE
            )

            # Fix 2: wrong column names (e.g. s."Accident_History" when actual is s."Accidents")
            def fix_col_ref(m):
                alias    = m.group(1)
                col_name = m.group(2)
                if col_name in actual_col_names:
                    return m.group(0)  # correct already
                # Try fuzzy match (substring first)
                col_lower = col_name.lower().replace("_", "")
                for al, (ac, _) in actual_cols.items():
                    if col_lower in al.replace("_", "") or al.replace("_", "") in col_lower:
                        log(f"[SQLPatch] Column: '{col_name}' → '{ac}'")
                        return f'{alias}."{ac}"'
                # Fuzzy fallback for cases like "Accident_History" vs "Accidents"
                # where neither is a substring of the other
                best_score = 0.0
                best_actual = None
                for al, (ac, _) in actual_cols.items():
                    score = difflib.SequenceMatcher(None, col_lower, al.replace("_", "")).ratio()
                    if score > best_score:
                        best_score = score
                        best_actual = ac
                if best_score >= 0.55 and best_actual:
                    log(f"[SQLPatch] Column (fuzzy): '{col_name}' → '{best_actual}'")
                    return f'{alias}."{best_actual}"'
                return m.group(0)  # no match, leave as is

            sql = re.sub(r'(s|src)\."(\w+)"', fix_col_ref, sql)

            # Fix 4: TRIM text-column equality comparisons, AND cast numeric/
            # text type mismatches between a warehouse dim column and its
            # matching staging source column. CSV sources frequently have
            # stray whitespace in text fields ("Toyota " vs "Toyota"), and
            # the data model sometimes declares a dim column as VARCHAR when
            # the actual source column is numeric (e.g. accident_history
            # VARCHAR vs Accidents bigint) — both cause silent JOIN/WHERE
            # mismatches or outright "operator does not exist" errors.
            # Reuses staging_cols[raw_tbl] already fetched above — no extra
            # DB round-trip needed for the source side.
            text_types = ('char', 'text', 'varchar')
            numeric_types = ('int', 'numeric', 'decimal', 'double', 'real', 'serial')
            col_type_by_name = {
                actual: dtype
                for actual, dtype in staging_cols.get(raw_tbl, {}).values()
            } if raw_tbl else {}

            # Resolve alias -> dim table name from "JOIN warehouse.dim_X alias"
            # patterns present in THIS script, so we can look up the dim
            # column's actual declared type in warehouse_col_types.
            # NOTE: regex captures (table_name, alias) in that order — must
            # invert to build {alias: table_name}.
            alias_to_table = {
                alias: tbl for tbl, alias in re.findall(
                    r'JOIN\s+warehouse\.(\w+)\s+(\w+)\b', sql, re.IGNORECASE
                )
            }
            # Dim build scripts use a bare "d" alias referring to the dim
            # table itself (e.g. "WHERE NOT EXISTS (SELECT 1 FROM
            # warehouse.dim_car d WHERE d.brand = s.brand ...)") — this isn't
            # a JOIN, so resolve it directly from the script's own name.
            # Only set as a fallback (never overwrite an alias already
            # resolved from a real JOIN above, e.g. fact scripts using "dc"
            # for warehouse.dim_car via an actual JOIN clause).
            script_table_name = script.get("name", "")
            if script_table_name.startswith("dim_"):
                alias_to_table.setdefault('d', script_table_name)

            def trim_equality(m):
                alias_col = m.group(1)
                src_alias = m.group(2)
                col_name  = m.group(3)
                parts = alias_col.split('.', 1)
                tbl_alias, dim_col = (parts[0], parts[1]) if len(parts) == 2 else (None, None)

                src_dtype = col_type_by_name.get(col_name, "")
                dim_table = alias_to_table.get(tbl_alias) if tbl_alias else None
                dim_dtype = warehouse_col_types.get((dim_table, dim_col), "") if dim_table else ""

                is_src_text = any(t in src_dtype.lower() for t in text_types)
                is_dim_text = any(t in dim_dtype.lower() for t in text_types)
                is_src_num  = any(t in src_dtype.lower() for t in numeric_types)
                is_dim_num  = any(t in dim_dtype.lower() for t in numeric_types)

                if dim_dtype and src_dtype and is_dim_text and is_src_num:
                    # dim is text, source is numeric — cast source to text
                    log(f"[SQLPatch] Type cast: {alias_col} (text) vs "
                        f"{src_alias}.\"{col_name}\" (numeric) — casting source to VARCHAR")
                    return f'{alias_col} = CAST({src_alias}."{col_name}" AS VARCHAR)'
                if dim_dtype and src_dtype and is_dim_num and is_src_text:
                    log(f"[SQLPatch] Type cast: {alias_col} (numeric) vs "
                        f"{src_alias}.\"{col_name}\" (text) — casting source to numeric")
                    return f'{alias_col} = CAST({src_alias}."{col_name}" AS NUMERIC)'
                if is_src_text:
                    return f'{alias_col} IS NOT DISTINCT FROM {src_alias}."{col_name}"'
                    return f'TRIM({alias_col}) = TRIM({src_alias}."{col_name}")'
                return m.group(0)

            sql = re.sub(
                r'(\w+\.\w+)\s*=\s*(s|src)\."(\w+)"',
                trim_equality, sql
            )


            # IS NOT DISTINCT FROM patch removed — causes O(n²) slow queries
            # WHERE NOT EXISTS with plain = is fast and index-friendly
            if sql != original:
                script = {**script, "sql": sql}
                log(f"[SQLPatch] ✓ Patched SQL for: {script.get('name')}")

            patched.append(script)

        return patched

    except Exception as e:
        log(f"[SQLPatch] Warning: {e}")
        return sql_scripts


def _auto_create_intermediate_staging(target_config: dict, staging_schema: str,
                                       sql_scripts: list, log,
                                       data_model: dict = None,
                                       pipeline_id: str = None) -> None:
    """
    Generically detect staging tables referenced in SQL scripts that don't exist
    and auto-create them via SELECT DISTINCT from the raw staging table.

    Uses data_model (if provided) to know exactly which columns each
    intermediate staging table needs — no hallucinated ID columns.

    Fully generic — works for ANY domain, ANY file, zero hardcoding.
    """
    # universal: runs for all target DB types
    ct_stg = target_config.get("connector_type", "postgres").lower()

    import re
    if ct_stg in ("postgres", "postgresql", "redshift"):
        conn = _pg_connect(target_config)
    elif ct_stg == "snowflake":
        from universal_connector import _snowflake_connect
        conn = _snowflake_connect(target_config)
    elif ct_stg in ("mysql", "mariadb"):
        from universal_connector import _mysql_connect
        conn = _mysql_connect(target_config)
    elif ct_stg in ("sqlserver", "mssql", "azuresql"):
        from universal_connector import _sqlserver_connect
        conn = _sqlserver_connect(target_config)
    else:
        conn = _pg_connect(target_config)
    conn.autocommit = True
    cur  = conn.cursor()

    try:
        # Step 1: Find all staging tables that actually exist
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
        """, (staging_schema,))
        existing_tables = {row[0] for row in cur.fetchall()}

        # Step 2: Find raw staging tables — ones extracted from source
        # Identified by: exist in staging AND have >= 5 columns (raw tables are wide)
        raw_staging = {}  # table_name → set of column names
        for tbl in existing_tables:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (staging_schema, tbl))
            cols = [row[0] for row in cur.fetchall()]
            if len(cols) >= 5:
                raw_staging[tbl] = cols

        if not raw_staging:
            return

        # Step 3: Find ALL staging table references in SQL scripts
        stg_pattern = re.compile(
            rf'{re.escape(staging_schema)}\.(stg_\w+)', re.IGNORECASE
        )
        referenced_tables = set()
        for script in sql_scripts:
            for match in stg_pattern.findall(script.get("sql", "")):
                referenced_tables.add(match.lower())

        # Step 4: Find missing tables
        missing_tables = {t for t in referenced_tables if t not in existing_tables}
        if not missing_tables:
            return

        log(f"[StagingBuilder] Found {len(missing_tables)} missing staging tables: {missing_tables}")
        log(f"[StagingBuilder] Will create from raw staging: {set(raw_staging.keys())}")

        # Step 5: Pick best raw staging table (most columns = most complete)
        best_raw = max(raw_staging, key=lambda t: len(raw_staging[t]))
        raw_cols = raw_staging[best_raw]  # actual column names in raw table
        raw_col_lower = {c.lower(): c for c in raw_cols}  # lowercase → actual name

        # Step 6: Build column map from data model if available
        # dim_name → [attribute columns needed]
        dim_col_map = {}
        if data_model:
            for dim in data_model.get("dimension_tables", []):
                dim_name = dim.get("name", "")  # e.g. dim_car
                # Derive stg table name from dim name: dim_car → stg_cars
                entity = dim_name.replace("dim_", "")  # car, seller, location
                # Handle plural forms generically
                if entity.endswith("s"):
                    stg_name       = f"stg_{entity}"           # sellers → stg_sellers
                elif entity.endswith("y"):
                    stg_name       = f"stg_{entity[:-1]}ies"   # city → stg_cities
                else:
                    stg_name       = f"stg_{entity}s"          # car → stg_cars
                stg_name_exact = f"stg_{entity}"               # stg_car (without s)

                # Collect all attribute column names from dim definition
                # Data model uses {"column": "brand", "source": "Brand"} format
                attrs = []
                seen_attrs = set()
                for attr in dim.get("attributes", []):
                    if isinstance(attr, str):
                        col = attr
                        src = attr
                    else:
                        # Try "source" first (actual raw column name), then "column"
                        src = attr.get("source", attr.get("name", attr.get("column", "")))
                        col = attr.get("column", attr.get("name", ""))
                    # Skip surrogate keys and system columns
                    if col and not col.endswith("_key") and col not in (
                        "is_current", "valid_from", "valid_to", "updated_at",
                        "created_at", "loaded_at"
                    ):
                        # Use source column name (actual raw name) for lookup
                        lookup = src.lower() if src else col.lower()
                        if lookup not in seen_attrs:
                            seen_attrs.add(lookup)
                            attrs.append(lookup)

                # Also add natural key
                nat_key = dim.get("natural_key_column", "")
                if nat_key and nat_key.lower() not in seen_attrs:
                    attrs.append(nat_key.lower())

                dim_col_map[stg_name]       = attrs
                dim_col_map[stg_name_exact] = attrs

            # For FACT tables — staging table needs ALL raw columns
            # (fact source needs measures + FK lookup columns, not just a few attrs)
            for fact in data_model.get("fact_tables", []):
                fact_name = fact.get("name", "")  # e.g. fact_car_listings
                entity = fact_name.replace("fact_", "")  # car_listings
                stg_fact_name = f"stg_{entity}"
                # Map to ALL raw columns — fact needs everything for FK joins + measures
                dim_col_map[stg_fact_name] = [c.lower() for c in raw_cols]

        # Step 7: Create each missing intermediate staging table
        for missing_tbl in missing_tables:
            # Find which columns to select
            select_cols = []

            if missing_tbl in dim_col_map:
                # Use data model attributes — map to actual raw column names
                for attr in dim_col_map[missing_tbl]:
                    if attr in raw_col_lower:
                        select_cols.append(raw_col_lower[attr])
                    else:
                        # Try fuzzy match — normalize and compare
                        attr_norm = attr.replace("_", "").lower()
                        best_match = None
                        best_score = 0
                        for raw_lower, raw_actual in raw_col_lower.items():
                            raw_norm = raw_lower.replace("_", "")
                            # Exact normalized match
                            if attr_norm == raw_norm:
                                best_match = raw_actual
                                best_score = 1.0
                                break
                        # Containment or common-prefix match
                        # e.g. accident_history -> accidents (share "accident" prefix)
                        if attr_norm in raw_norm or raw_norm in attr_norm:
                            score = len(set(attr_norm) & set(raw_norm)) / max(len(attr_norm), len(raw_norm), 1)
                            if score > best_score:
                                best_score = score
                                best_match = raw_actual
                        else:
                            # Common prefix match (accident_history vs accidents)
                            min_len = min(len(attr_norm), len(raw_norm))
                            common = sum(1 for i in range(min_len) if attr_norm[i] == raw_norm[i])
                            if common >= 6:  # at least 6 chars in common prefix
                                score = common / max(len(attr_norm), len(raw_norm), 1)
                                if score > best_score:
                                    best_score = score
                                    best_match = raw_actual

                        if best_match and best_score > 0.3:
                            select_cols.append(best_match)

            if not select_cols:
                # Fallback: scan SQL for s.column_name patterns
                col_pattern = re.compile(r'\bs\.(\w+)\b')
                for script in sql_scripts:
                    sql = script.get("sql", "")
                    if missing_tbl in sql.lower():
                        for col in col_pattern.findall(sql):
                            if col.lower() in raw_col_lower:
                                select_cols.append(raw_col_lower[col.lower()])

            # Remove duplicates preserving order
            seen = set()
            select_cols = [c for c in select_cols
                           if not (c.lower() in seen or seen.add(c.lower()))]

            # If still no columns detected:
            # For small lookup dims (seller, location) use text/categorical cols only
            if not select_cols:
                # Use non-numeric columns from raw staging (text/categorical attrs)
                try:
                    cur.execute("""
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                        ORDER BY ordinal_position
                    """, (staging_schema, best_raw))
                    all_col_info = cur.fetchall()
                    # For small dims → use text columns (likely categorical)
                    text_cols = [c for c, dt in all_col_info
                                 if any(t in dt.lower() for t in
                                        ('char', 'text', 'varchar', 'name'))]
                    if text_cols and len(text_cols) <= 10:
                        select_cols = text_cols
                    else:
                        log(f"[StagingBuilder] ⚠ Could not determine columns for {missing_tbl} — skipping")
                        continue
                except Exception:
                    log(f"[StagingBuilder] ⚠ Could not determine columns for {missing_tbl} — skipping")
                    continue

            # Round float columns to 2dp for consistent dim/fact matching
            try:
                cur.execute("""
                    SELECT column_name, data_type FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                """, (staging_schema, best_raw))
                _col_types = {r[0]: r[1] for r in cur.fetchall()}
            except Exception:
                _col_types = {}
            def _col_expr(c):
                dtype = _col_types.get(c, "")
                if any(t in dtype.lower() for t in ("float","double","real","numeric","decimal")):
                    return f'ROUND("{c}"::NUMERIC, 2) AS "{c}"'
                return f'"{c}"'
            cols_sql = ", ".join(_col_expr(c) for c in select_cols)
            create_sql = f"""
                DROP TABLE IF EXISTS "{staging_schema}"."{missing_tbl}";
                CREATE TABLE "{staging_schema}"."{missing_tbl}" AS
                SELECT DISTINCT {cols_sql}
                FROM "{staging_schema}"."{best_raw}";
            """

            try:
                cur.execute(create_sql)
                cur.execute(f'SELECT COUNT(*) FROM "{staging_schema}"."{missing_tbl}"')
                row_count = cur.fetchone()[0]
                log(f"[StagingBuilder] ✓ Created {staging_schema}.{missing_tbl} "
                    f"← {staging_schema}.{best_raw} "
                    f"({row_count:,} rows, {len(select_cols)} cols: {select_cols})")
            except Exception as e:
                log(f"[StagingBuilder] ✗ Could not create {missing_tbl}: {e}")

    finally:
        cur.close()
        conn.close()


def _ensure_schema(config: dict, schema_name: str):
    """Create schema in target DB if it doesn't exist."""
    ct = config.get("connector_type", "postgres").lower()
    if ct in ("postgres", "postgresql", "redshift"):
        conn = _pg_connect(config)
        conn.autocommit = True
        cur  = conn.cursor()
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')
        cur.close(); conn.close()
    elif ct == "mysql":
        from universal_connector import _mysql_connect
        conn = _mysql_connect(config)
        cur  = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{schema_name}`")
        cur.close(); conn.close()
    elif ct in ("sqlserver", "mssql", "azuresql"):
        from universal_connector import _sqlserver_connect
        conn = _sqlserver_connect(config)
        cur  = conn.cursor()
        cur.execute(f"IF NOT EXISTS (SELECT * FROM sys.schemas WHERE name='{schema_name}') EXEC('CREATE SCHEMA [{schema_name}]')")
        conn.commit(); cur.close(); conn.close()
    elif ct == "snowflake":
        from universal_connector import _snowflake_connect
        conn = _snowflake_connect(config)
        cur  = conn.cursor()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")
        cur.close(); conn.close()
    # BigQuery, Oracle, SQLite — skip schema creation


# ── Execute warehouse scripts on any target DB ────────────────────────────────

def execute_warehouse_scripts(
    pipeline_id, pipeline_name, sql_scripts,
    target_config, workspace_id, db_session=None,
    warehouse_schema="warehouse", staging_schema="staging",
    data_model=None,
    should_stop_fn=None, log_fn=None,
    source_connector_type=None,
) -> dict:
    started_at    = datetime.utcnow()
    logs          = []
    total_rows    = 0
    run_id        = f"{pipeline_id}_{started_at.strftime('%Y%m%d_%H%M%S')}"
    recoveries    = []
    target_config = _cfg(target_config)
    tgt_type      = target_config.get("connector_type", "postgres").lower()

    def log(msg):
        line = f"[{_ts()}] {msg}"
        print(f"[{run_id}] {line}"); logs.append(line)

    # Detect snapshot vs incremental source
    is_snapshot_source = (source_connector_type or "").lower() in ("duckdb", "csv", "excel", "file")

    # Detect snapshot vs incremental source
    # DuckDB = flat-file snapshot (full refresh each run)
    # PostgreSQL/MySQL etc = transactional (period_id incremental)
    is_snapshot_source = (source_connector_type or "").lower() in ("duckdb", "csv", "excel", "file")

    log("━━━ WAREHOUSE PHASE STARTED ━━━")
    log(f"Pipeline started: {pipeline_name}")
    log(f"Target DB: {tgt_type.upper()}")
    log(f"Source type: {'snapshot (full refresh)' if is_snapshot_source else 'incremental (period_id)'}")
    log(f"Received {len(sql_scripts)} scripts to execute")

    if not sql_scripts:
        log("⚠ No SQL scripts to execute")
        ended_at = datetime.utcnow()
        _save_run(run_id, pipeline_id, workspace_id, "failed",
                  started_at, ended_at, 0, logs, db_session)
        return {"success": False, "run_id": run_id,
                "error": "No SQL scripts", "logs": logs, "recoveries": []}

    # Convert SQL to target dialect if needed
    dialect_info = get_dialect_info(tgt_type)
    log(f"SQL dialect: {dialect_info['name']}")

    if tgt_type not in ("postgres", "postgresql", "redshift"):
        log(f"Converting SQL to {dialect_info['name']} dialect...")
        sql_scripts = convert_scripts(sql_scripts, tgt_type, staging_schema, warehouse_schema)
        log(f"✓ SQL converted to {dialect_info['name']} dialect")

    # Ensure warehouse + staging schemas exist
    try:
        _ensure_schema(target_config, staging_schema)
        _ensure_schema(target_config, warehouse_schema)
        log(f"✓ Schemas verified ({staging_schema}, {warehouse_schema})")
    except Exception as e:
        log(f"⚠ Schema creation warning: {e}")

    # ── Pre-execution SQL patch for known column issues ──────────────────────
    # Fix common AI hallucinations in generated SQL before running
    # Generic: scan actual staging columns and replace wrong names
    sql_scripts = _patch_sql_column_names(
        sql_scripts, target_config, staging_schema, log, warehouse_schema, is_snapshot_source
    )
    # ─────────────────────────────────────────────────────────────────────────

    # ── Auto-create intermediate staging tables ───────────────────────────────
    # Generically detect which staging tables the SQL scripts need but don't exist
    # and create them via SELECT DISTINCT from the raw staging table.
    # This handles single flat-file sources (CSV/Excel) where AI splits one
    # staging table into multiple entity-level staging tables.
    try:
        _auto_create_intermediate_staging(
            target_config  = target_config,
            staging_schema = staging_schema,
            sql_scripts    = sql_scripts,
            data_model     = data_model,
            log            = log,
            pipeline_id    = pipeline_id
        )
    except Exception as e:
        log(f"⚠ Intermediate staging creation warning: {e}")

    # Execute scripts
    for i, script in enumerate(sql_scripts):
        name  = script.get("name",  f"step_{i+1}")
        label = script.get("label", "")
        sql   = script.get("sql",   "").strip()

        if not sql:
            log(f"⊘ Skipping {name} — empty SQL")
            continue

        # Safety check (all targets)
        try:
            from sql_safety import check_sql_safety
            is_snapshot = (source_connector_type or "").lower() in ("duckdb", "csv", "excel")
            sf = check_sql_safety(sql, allow_destructive=is_snapshot, script_name=name)
            if sf["blocked"]:
                viol = sf["violations"][0]["name"] if sf["violations"] else "dangerous SQL"
                log(f"🛑 BLOCKED: {name} — {viol}")
                continue
        except Exception:
            pass

        log(f"Running: {name} ({label})")

        # For fact tables, expand any under-specified dim JOINs now that
        # dims are already loaded — prevents row multiplication bugs
        if _is_pg(target_config) and name.startswith("fact_"):
            try:
                expanded = _expand_composite_joins(
                    [{"name": name, "sql": sql}], target_config,
                    warehouse_schema, staging_schema, log
                )
                if expanded:
                    sql = expanded[0]["sql"]
            except Exception as e:
                log(f"⚠ Composite JOIN expansion warning: {e}")

        script_start = datetime.now()

        try:
            rows = _execute_sql_on_target(target_config, sql, warehouse_schema, staging_schema)
            total_rows += max(rows, 0)
            dur = (datetime.now() - script_start).total_seconds()
            log(f"✓ {name} complete — {rows} rows ({dur:.1f}s)")

            # Auto-create indexes on dim tables for fast fact JOIN
            if _is_pg(target_config) and name.startswith("dim_") and rows > 0:
                _auto_create_dim_indexes(target_config, warehouse_schema, name, log)

            # Safety check: fact tables shouldn't multiply rows vs source.
            # If fact row count is >3x the largest staging table, something
            # is wrong (usually an under-specified composite JOIN).
            if _is_pg(target_config) and name.startswith("fact_") and rows > 0:
                try:
                    conn = _pg_connect(target_config)
                    cur  = conn.cursor()
                    cur.execute(f"""
                        SELECT MAX(n_live_tup) FROM pg_stat_user_tables
                        WHERE schemaname = %s
                    """, (staging_schema,))
                    max_staging_rows = cur.fetchone()[0] or 0
                    cur.close(); conn.close()
                    if max_staging_rows and rows > max_staging_rows * 3:
                        log(f"⚠️ WARNING: {name} has {rows:,} rows but largest "
                            f"staging table has only {max_staging_rows:,} rows. "
                            f"This suggests a JOIN row-multiplication bug — "
                            f"please verify the fact table data is correct!")
                except Exception:
                    pass

        except Exception as script_err:
            error_msg = str(script_err)[:300]
            log(f"✗ {name} failed: {error_msg}")

            # Recovery Agent (PostgreSQL targets only for now)
            if _is_pg(target_config):
                log(f"🤖 Recovery Agent activated for {name}")
                try:
                    from recovery_agent import recover_pipeline
                    recovery = recover_pipeline(
                        failed_script=script.get("name"),
                        error_message=error_msg,
                        all_scripts=sql_scripts,
                        conn_config=target_config,
                        pipeline_id=pipeline_id,
                        workspace_id=workspace_id,
                        run_id=run_id,
                    )
                    if recovery.get("recovered"):
                        log(f"🤖 ✓ Recovery successful via {recovery.get('fix_method')}")
                        log(f"🤖 ✓ Recovered via {recovery.get('fix_method')}: {recovery.get('action_taken', '')}")
                    else:
                        log(f"🤖 ✗ Recovery failed: {recovery.get('summary')}")
                    recoveries.append(recovery)
                    _save_recovery_log(pipeline_id, run_id, workspace_id,
                                       name, error_msg, recovery, db_session)
                except Exception as recov_err:
                    log(f"🤖 ✗ Recovery agent crashed: {recov_err}")
            else:
                log(f"⚠ Recovery Agent not available for {tgt_type} — skipping")
            continue

    ended_at  = datetime.utcnow()
    duration  = (ended_at - started_at).seconds
    recovered = sum(1 for r in recoveries if r.get("recovered"))
    success   = (len(recoveries) == 0) or (recovered == len(recoveries))
    status    = "success" if success else "partial"

    # Per-table row count breakdown — far more useful than a single combined
    # total, since it immediately shows which table(s) have an unexpected
    # count (e.g. a fact table that's too high/low relative to its dims).
    if _is_pg(target_config):
        try:
            conn = _pg_connect(target_config)
            cur  = conn.cursor()
            table_names = [s.get("name") for s in sql_scripts if s.get("name")]
            counts = []
            for tbl in table_names:
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{warehouse_schema}"."{tbl}"')
                    counts.append((tbl, cur.fetchone()[0]))
                except Exception:
                    pass
            cur.close(); conn.close()
            if counts:
                breakdown = ", ".join(f"{t}={c:,}" for t, c in counts)
                log(f"📊 Warehouse row counts — {breakdown}")
        except Exception as e:
            log(f"⚠ Could not compute per-table row counts: {e}")

    log(f"━━━ Pipeline complete — {duration}s — {total_rows} total rows ━━━")
    if recoveries:
        log(f"🤖 Recovery Agent activated {len(recoveries)} times "
            f"({recovered} recovered, {len(recoveries) - recovered} failed)")
    log(f"Status: {status}")

    _save_run(run_id, pipeline_id, workspace_id, status,
              started_at, ended_at, total_rows, logs, db_session)

    return {"success": success, "run_id": run_id, "rows": total_rows,
            "duration_s": duration, "logs": logs, "recoveries": recoveries,
            "status": status, "scripts": [{"name": s.get("name"), "success": True}
                                           for s in sql_scripts]}


def _execute_sql_on_target(config: dict, sql: str,
                            warehouse_schema: str, staging_schema: str) -> int:
    """Execute SQL on any target database. Returns row count."""
    ct = config.get("connector_type", "postgres").lower()

    sql_clean = sql.replace("CREATE OR REPLACE TABLE", "CREATE TABLE IF NOT EXISTS")

    if ct in ("postgres", "postgresql", "redshift"):
        conn = _pg_connect(config)
        conn.autocommit = False
        cur  = conn.cursor()
        cur.execute(sql_clean)
        rows = cur.rowcount if cur.rowcount >= 0 else 0
        conn.commit(); cur.close(); conn.close()
        return rows

    elif ct == "mysql":
        from universal_connector import _mysql_connect
        conn = _mysql_connect(config)
        cur  = conn.cursor()
        # MySQL doesn't support multiple statements in one execute
        statements = [s.strip() for s in sql_clean.split(';') if s.strip()]
        total = 0
        for stmt in statements:
            cur.execute(stmt)
            total += cur.rowcount if cur.rowcount >= 0 else 0
        conn.commit(); cur.close(); conn.close()
        return total

    elif ct in ("sqlserver", "mssql", "azuresql"):
        from universal_connector import _sqlserver_connect
        conn = _sqlserver_connect(config)
        cur  = conn.cursor()
        statements = [s.strip() for s in sql_clean.split(';') if s.strip()]
        total = 0
        for stmt in statements:
            cur.execute(stmt)
            total += cur.rowcount if cur.rowcount >= 0 else 0
        conn.commit(); cur.close(); conn.close()
        return total

    elif ct == "oracle":
        from universal_connector import _oracle_connect
        conn = _oracle_connect(config)
        cur  = conn.cursor()
        statements = [s.strip() for s in sql_clean.split(';') if s.strip()
                      and not s.strip().startswith('--')]
        total = 0
        for stmt in statements:
            cur.execute(stmt)
            total += cur.rowcount if cur.rowcount >= 0 else 0
        conn.commit(); cur.close(); conn.close()
        return total

    elif ct == "snowflake":
        from universal_connector import _snowflake_connect
        conn = _snowflake_connect(config)
        cur  = conn.cursor()
        statements = [s.strip() for s in sql_clean.split(';') if s.strip()]
        total = 0
        for stmt in statements:
            cur.execute(stmt)
            total += cur.rowcount if cur.rowcount >= 0 else 0
        cur.close(); conn.close()
        return total

    elif ct == "bigquery":
        from universal_connector import _bigquery_connect
        client = _bigquery_connect(config)
        job    = client.query(sql_clean)
        result = job.result()
        return result.num_results or 0

    elif ct == "sqlite":
        from universal_connector import _sqlite_connect
        conn = _sqlite_connect(config)
        cur  = conn.cursor()
        statements = [s.strip() for s in sql_clean.split(';') if s.strip()]
        total = 0
        for stmt in statements:
            cur.execute(stmt)
            total += cur.rowcount if cur.rowcount >= 0 else 0
        conn.commit(); cur.close(); conn.close()
        return total

    else:
        raise ValueError(f"Cannot execute SQL on connector type: {ct}")


# ── Table / column inspection ─────────────────────────────────────────────────

def list_schemas(conn_config: dict) -> dict:
    conn_config = _cfg(conn_config)
    return discover_schemas(conn_config)


def list_columns_for_tables(conn_config: dict, source_schema: str,
                             table_names: list) -> dict:
    conn_config = _cfg(conn_config)
    result      = discover_columns(conn_config, source_schema, table_names)
    return {"success": result["success"],
            "tables":  result.get("tables", {}),
            "source_schema": source_schema}


def list_all_tables_by_schema(conn_config: dict, source_schema: str = "raw",
                               staging_schema: str = "staging",
                               warehouse_schema: str = "warehouse") -> dict:
    conn_config = _cfg(conn_config)
    ct          = conn_config.get("connector_type", "postgres").lower()

    # ── DuckDB source ─────────────────────────────────────────────────────────
    if ct == "duckdb":
        try:
            import duckdb
            duckdb_path = conn_config.get("username", "./aibridge.duckdb")
            table_name  = conn_config.get("database_name") or conn_config.get("database", "")
            con         = duckdb.connect(duckdb_path, read_only=True)
            cols        = con.execute(f'DESCRIBE "{table_name}"').fetchall()
            rows        = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            con.close()
            table_info  = [{
                "name":      table_name,
                "size":      f"{rows:,} rows",
                "col_count": len(cols),
                "full_name": table_name
            }]
            return {
                "success": True,
                "schemas": {
                    "raw":       table_info,
                    source_schema: table_info,
                    "staging":   [],
                    "warehouse": []
                },
                "source_schema": source_schema
            }
        except Exception as e:
            return {"success": False, "error": str(e), "schemas": {}}

    try:
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(conn_config)
            cur  = conn.cursor()
            schemas_to_check = list({source_schema, 'raw', staging_schema,
                                     warehouse_schema, 'staging', 'warehouse', 'public'})
            cur.execute("""
                SELECT t.table_schema, t.table_name,
                    pg_size_pretty(pg_total_relation_size(
                        quote_ident(t.table_schema)||'.'||quote_ident(t.table_name))) AS size,
                    (SELECT COUNT(*) FROM information_schema.columns c
                     WHERE c.table_schema = t.table_schema
                       AND c.table_name   = t.table_name) AS col_count
                FROM information_schema.tables t
                WHERE t.table_schema = ANY(%s) AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_schema, t.table_name
            """, (schemas_to_check,))
            rows   = cur.fetchall()
            cur.close(); conn.close()
            result = {"raw": [], "staging": [], "warehouse": [], "public": []}
            for sch, name, size, cols in rows:
                result.setdefault(sch, []).append({
                    "name": name, "size": size,
                    "col_count": cols, "full_name": f"{sch}.{name}"
                })
            if source_schema != "raw":
                result["raw"] = result.get(source_schema, [])
            return {"success": True, "schemas": result, "source_schema": source_schema}
        else:
            tables_result = discover_tables(conn_config, source_schema)
            tables        = tables_result.get("tables", [])
            return {
                "success": True,
                "schemas": {"raw": tables, source_schema: tables,
                            "staging": [], "warehouse": []},
                "source_schema": source_schema
            }
    except Exception as e:
        return {"success": False, "error": str(e), "schemas": {}}


def get_full_schema_for_ai(conn_config: dict, source_schema: str = "raw",
                            warehouse_schema: str = "warehouse",
                            staging_schema: str = "staging") -> str:
    conn_config = _cfg(conn_config)
    ct          = conn_config.get("connector_type", "postgres").lower()

    try:
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(conn_config)
            cur  = conn.cursor()
            schemas_to_check = list({source_schema, 'raw', staging_schema, warehouse_schema})
            cur.execute("""
                SELECT c.table_schema, c.table_name, c.column_name, c.data_type,
                    CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 'PK'
                         WHEN tc.constraint_type = 'FOREIGN KEY' THEN 'FK'
                         ELSE NULL END AS key_type
                FROM information_schema.columns c
                LEFT JOIN information_schema.key_column_usage ku
                       ON ku.table_schema = c.table_schema
                      AND ku.table_name   = c.table_name
                      AND ku.column_name  = c.column_name
                LEFT JOIN information_schema.table_constraints tc
                       ON tc.constraint_name = ku.constraint_name
                      AND tc.table_schema    = c.table_schema
                WHERE c.table_schema = ANY(%s)
                ORDER BY c.table_schema, c.table_name, c.ordinal_position
            """, (schemas_to_check,))
            rows = cur.fetchall()
            cur.close(); conn.close()
            tables = {}
            for sch, table, col, dtype, key in rows:
                kn = f"{sch}.{table}"
                tables.setdefault(kn, [])
                cd = f"{col} ({dtype}"
                if key: cd += f", {key}"
                cd += ")"
                tables[kn].append(cd)
            lines = []
            for tn, cols in sorted(tables.items()):
                lines.append(f"\n{tn}:")
                for c in cols: lines.append(f"  - {c}")
            return "\n".join(lines)
        else:
            return get_schema_text_for_ai(conn_config, source_schema)
    except Exception as e:
        print(f"Schema introspection failed: {e}")
        return ""


def get_table_preview(table_full_name: str, conn_config: dict, limit: int = 10) -> dict:
    conn_config = _cfg(conn_config)
    try:
        conn = _pg_connect(conn_config)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f"SELECT * FROM {table_full_name} LIMIT {limit}")
        rows    = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        cur.execute(f"SELECT COUNT(*) FROM {table_full_name}")
        total   = cur.fetchone()["count"]
        cur.close(); conn.close()
        return {"success": True, "table": table_full_name, "columns": columns,
                "rows": [list(r.values()) for r in rows], "row_count": total}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Logging helpers ───────────────────────────────────────────────────────────

def _save_run(run_id, pipeline_id, workspace_id, status,
              started_at, ended_at, rows, logs, db_session):
    if not db_session: return
    try:
        from database import PipelineRun
        run = PipelineRun(run_id=run_id, pipeline_id=pipeline_id,
                          workspace_id=workspace_id, status=status,
                          started_at=started_at, ended_at=ended_at,
                          rows_loaded=rows, log="\n".join(logs))
        db_session.add(run); db_session.commit()
    except Exception as e:
        print(f"Warning: Could not save pipeline run: {e}")


def _save_recovery_log(pipeline_id, run_id, workspace_id,
                       failed_script_name, error_msg, recovery, db_session):
    if not db_session: return
    try:
        from database import RecoveryLog
        rec = RecoveryLog(
            pipeline_id=pipeline_id, pipeline_run_id=run_id, workspace_id=workspace_id,
            failed_script=failed_script_name, error_message=error_msg[:2000],
            error_pattern="",
            action_taken=recovery.get("action_taken", "unknown"),
            fix_method=recovery.get("fix_method", "unknown"),
            fix_sql=(recovery.get("fixed_sql") or "")[:5000],
            recovered=recovery.get("recovered", False),
            attempts=recovery.get("attempts", {}),
            summary=recovery.get("summary", ""),
            started_at=datetime.utcnow(), ended_at=datetime.utcnow()
        )
        db_session.add(rec); db_session.commit()
        print("[Recovery] Logged to database (recovery_logs table)")
    except Exception as e:
        print(f"Warning: Could not save recovery log: {e}")


