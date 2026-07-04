"""
recovery_agent.py — AIBridge Recovery Agent (v1.10)

v1.10: Added Pattern 9 — null value in NOT NULL FK column → DROP NOT NULL + retry.
       Fixed Pattern 6 indentation bug — bad_table scoping crash resolved.
v1.9:  Added Pattern 4b (ON CONFLICT missing UNIQUE) and Pattern 6 (hallucinated table).
v1.8:  Fixed Pattern 7 indentation bug.
v1.7:  Pattern 7 smart dedup.
v1.6:  Pattern 7 + SCD Type 2 removal.
v1.5:  Added Pattern 7 and Pattern 8.
v1.4:  AI receives BOTH staging + warehouse schemas.
v1.3:  Better AI prompt + fixed DB logging.
v1.2:  AI-powered universal recovery.
v1.1:  _connect() helper.
v1.0:  Initial pattern-based recovery.
"""

import re
import uuid
import json
import psycopg2
from datetime import datetime


def _connect(conn_config: dict):
    return psycopg2.connect(
        host     = conn_config.get("host",     "localhost"),
        port     = int(conn_config.get("port", 5433)),
        dbname   = conn_config.get("database", "postgres"),
        user     = conn_config.get("username", "postgres"),
        password = conn_config.get("password", "")
    )


def recover_pipeline(failed_script, error_message, all_scripts, conn_config,
                     pipeline_id="", workspace_id="", run_id=""):
    recovery_id = str(uuid.uuid4())[:8]
    print(f"[RecoveryAgent {recovery_id}] Recovery started for failed script: {failed_script}")
    print(f"[RecoveryAgent {recovery_id}] Error: {error_message[:200]}")

    script_sql = ""
    for s in all_scripts:
        if s.get("name") == failed_script:
            script_sql = s.get("sql", "")
            break

    if not script_sql:
        print(f"[RecoveryAgent {recovery_id}] Could not find SQL for script: {failed_script}")
        result = {"recovered": False, "fix_method": "script_not_found",
                  "action_taken": "skip",
                  "summary": f"Could not find SQL for script '{failed_script}'"}
        _log_to_db(result, pipeline_id, workspace_id, run_id, failed_script, error_message, conn_config)
        return result

    pattern_result = _try_pattern_fix(recovery_id, failed_script, error_message, script_sql, conn_config)

    if pattern_result["recovered"]:
        _log_to_db(pattern_result, pipeline_id, workspace_id, run_id, failed_script, error_message, conn_config)
        return pattern_result

    print(f"[RecoveryAgent {recovery_id}] Pattern fix failed — trying AI-powered fix")
    ai_result = _try_ai_fix(recovery_id, failed_script, error_message, script_sql, all_scripts, conn_config)
    _log_to_db(ai_result, pipeline_id, workspace_id, run_id, failed_script, error_message, conn_config)
    return ai_result


def _try_pattern_fix(recovery_id, failed_script, error_message, script_sql, conn_config):
    error_lower = error_message.lower()

    # Pattern 1 + 6: relation does not exist
    if "relation" in error_lower and "does not exist" in error_lower:
        match = re.search(r'relation "([^"]+)" does not exist', error_message)
        if match:
            bad_table = match.group(1)

            # Pattern 1a: staging table missing stg_ prefix
            if "staging." in bad_table and not bad_table.split(".")[-1].startswith("stg_"):
                table_name = bad_table.split(".")[-1]
                fixed_sql  = script_sql.replace(bad_table, f"staging.stg_{table_name}")
                print(f"[RecoveryAgent {recovery_id}] Pattern fix: added stg_ prefix to {bad_table}")
                return _try_execute(recovery_id, fixed_sql, conn_config,
                                    "add_stg_prefix", f"Added stg_ prefix: {bad_table} → stg_{table_name}")

            # Pattern 6: staging table has stg_ prefix but genuinely doesn't exist
            # (AI hallucinated a dimension from a column, not an actual table)
            if "staging." in bad_table and bad_table.split(".")[-1].startswith("stg_"):
                print(f"[RecoveryAgent {recovery_id}] Pattern fix: staging table {bad_table} does not exist — skipping script")
                dim_name = failed_script  # e.g. dim_term

                # Drop FK constraints referencing this hallucinated dimension
                drop_fk_sql = f"""
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT tc.constraint_name, tc.table_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.referential_constraints rc
            ON tc.constraint_name = rc.constraint_name
        JOIN information_schema.key_column_usage kcu2
            ON rc.unique_constraint_name = kcu2.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND kcu2.table_name = '{dim_name}'
        AND tc.table_schema = 'warehouse'
    LOOP
        EXECUTE 'ALTER TABLE warehouse.' || r.table_name ||
                ' DROP CONSTRAINT IF EXISTS ' || r.constraint_name;
    END LOOP;
END $$;
"""
                try:
                    conn = _connect(conn_config)
                    conn.autocommit = True
                    cur  = conn.cursor()
                    cur.execute(drop_fk_sql)
                    conn.close()
                    print(f"[RecoveryAgent {recovery_id}] Pattern fix: dropped FK constraints referencing {dim_name}")
                except Exception as e:
                    print(f"[RecoveryAgent {recovery_id}] Could not drop FK constraints: {e}")

                # Create empty warehouse table so downstream scripts don't fail
                create_match = re.search(
                    r'CREATE TABLE IF NOT EXISTS warehouse\.\w+\s*\(([^;]+)\);',
                    script_sql, re.IGNORECASE | re.DOTALL
                )
                if create_match:
                    create_sql = f"CREATE TABLE IF NOT EXISTS warehouse.{failed_script} ({create_match.group(1)});"
                    result = _try_execute(recovery_id, create_sql, conn_config,
                                         "create_empty_table",
                                         f"Created empty {failed_script} + dropped FK constraints — source table {bad_table} does not exist")
                    if result["recovered"]:
                        return result

                return {"recovered": False, "fix_method": "staging_table_missing",
                        "action_taken": "none",
                        "summary": f"Staging table {bad_table} does not exist — AI hallucinated this dimension"}

    # Pattern 2: SCD Type 2 is_current in JOIN conditions
    if "is_current" in error_lower and "does not exist" in error_lower:
        fixed_sql = re.sub(r'\s+AND\s+\w+\.is_current\s*=\s*TRUE', '', script_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r'\s+AND\s+\w+\.is_current\s*=\s*true', '', fixed_sql, flags=re.IGNORECASE)
        if fixed_sql != script_sql:
            print(f"[RecoveryAgent {recovery_id}] Pattern fix: removed is_current from JOIN")
            return _try_execute(recovery_id, fixed_sql, conn_config,
                                "remove_is_current", "Removed SCD Type 2 is_current from JOIN condition")

    # Pattern 3: broken FK syntax (3-part reference)
    if "syntax error" in error_lower and "references" in script_sql.lower():
        fixed_sql = re.sub(
            r'REFERENCES\s+(\w+)\.(\w+)\.(\w+)\s*\((\w+)\)',
            r'REFERENCES \1.\2(\3)',
            script_sql, flags=re.IGNORECASE
        )
        if fixed_sql != script_sql:
            print(f"[RecoveryAgent {recovery_id}] Pattern fix: fixed broken FK syntax")
            return _try_execute(recovery_id, fixed_sql, conn_config,
                                "fix_fk_syntax", "Fixed broken FK REFERENCES syntax")

    # Pattern 4: duplicate key / ON CONFLICT missing
    if "duplicate key" in error_lower or "unique constraint" in error_lower:
        if "ON CONFLICT" not in script_sql.upper():
            fixed_sql = re.sub(
                r'(INSERT INTO[^;]+)(;?\s*$)',
                r'\1\nON CONFLICT DO NOTHING\2',
                script_sql, flags=re.IGNORECASE | re.DOTALL
            )
            print(f"[RecoveryAgent {recovery_id}] Pattern fix: added ON CONFLICT DO NOTHING")
            return _try_execute(recovery_id, fixed_sql, conn_config,
                                "add_on_conflict", "Added ON CONFLICT DO NOTHING")

    # Pattern 4b: ON CONFLICT column has no UNIQUE constraint
    if "no unique or exclusion constraint" in error_lower:
        conflict_col = re.search(r'ON CONFLICT\s*\((\w+)\)', script_sql, re.IGNORECASE)
        if conflict_col:
            col       = conflict_col.group(1)
            fixed_sql = script_sql
            # Try to add UNIQUE to column definition in CREATE TABLE
            fixed_sql = re.sub(
                rf'\b({col})\b(\s+(?:INTEGER|VARCHAR|TEXT|BIGINT|SMALLINT|NUMERIC)[^,\n]*?)(?<!UNIQUE)(\s*[,\n])',
                rf'\1\2 UNIQUE\3',
                fixed_sql, count=1, flags=re.IGNORECASE
            )
            if fixed_sql != script_sql:
                print(f"[RecoveryAgent {recovery_id}] Pattern fix: added UNIQUE to {col}")
                return _try_execute(recovery_id, fixed_sql, conn_config,
                                    "add_unique_constraint",
                                    f"Added UNIQUE constraint to {col} for ON CONFLICT")
            # Fallback: simplify ON CONFLICT to DO NOTHING
            fixed_sql = re.sub(
                r'ON CONFLICT\s*\(\w+\)\s*DO UPDATE SET',
                'ON CONFLICT DO NOTHING --',
                script_sql, flags=re.IGNORECASE
            )
            fixed_sql = re.sub(
                r'ON CONFLICT\s*\(\w+\)\s*DO NOTHING',
                'ON CONFLICT DO NOTHING',
                fixed_sql, flags=re.IGNORECASE
            )
            if fixed_sql != script_sql:
                print(f"[RecoveryAgent {recovery_id}] Pattern fix: simplified ON CONFLICT to DO NOTHING")
                return _try_execute(recovery_id, fixed_sql, conn_config,
                                    "simplify_on_conflict",
                                    "Simplified ON CONFLICT to DO NOTHING")

    # Pattern 9: null value in NOT NULL FK column — make it nullable and retry
    # Happens when fact table has term_key NOT NULL but dim_term doesn't exist or join returns null
    if "null value in column" in error_lower and "not-null constraint" in error_lower:
        null_col = re.search(r'null value in column "([^"]+)"', error_message)
        tbl_name = re.search(r'of relation "([^"]+)"', error_message)
        if null_col and tbl_name:
            col = null_col.group(1)
            tbl = tbl_name.group(1)
            alter_sql = f"ALTER TABLE warehouse.{tbl} ALTER COLUMN {col} DROP NOT NULL;"
            print(f"[RecoveryAgent {recovery_id}] Pattern fix: making {col} nullable in {tbl}")
            result = _try_execute(recovery_id, alter_sql, conn_config,
                                  "drop_not_null", f"Made {col} nullable in warehouse.{tbl}")
            if result["recovered"]:
                print(f"[RecoveryAgent {recovery_id}] Column made nullable — retrying original script...")
                return _try_execute(recovery_id, script_sql, conn_config,
                                    "retry_after_nullable", f"Retried after making {col} nullable")
            return result

    # Pattern 5: column missing from existing table — ALTER TABLE ADD COLUMN
    col_missing = re.search(r'column "([^"]+)" of relation "([^"]+)" does not exist', error_message)
    if col_missing:
        col_name  = col_missing.group(1)
        tbl_name  = col_missing.group(2)
        col_type  = _guess_column_type(col_name, script_sql)
        alter_sql = f"ALTER TABLE warehouse.{tbl_name} ADD COLUMN IF NOT EXISTS {col_name} {col_type};"
        print(f"[RecoveryAgent {recovery_id}] Pattern fix: ALTER TABLE ADD COLUMN {col_name} {col_type}")
        result = _try_execute(recovery_id, alter_sql, conn_config,
                              "alter_add_column", f"Added missing column {col_name} to {tbl_name}")
        if result["recovered"]:
            print(f"[RecoveryAgent {recovery_id}] Column added — retrying original script...")
            return _try_execute(recovery_id, script_sql, conn_config,
                                "retry_after_alter", f"Retried after adding {col_name}")
        return result

    # Pattern 7: source_ prefix — smart dedup v3
    source_col_match = re.search(r'column (?:"?)(?:\w+\.)?source_(\w+)', error_message)
    if source_col_match:
        fixed_sql       = script_sql
        all_source_cols = set(re.findall(r'\bsource_(\w+)\b', fixed_sql))

        for col in all_source_cols:
            insert_select_match = re.search(
                r'(INSERT\s+INTO[^;]+SELECT[^;]+)', fixed_sql, re.IGNORECASE | re.DOTALL
            )
            already_in_dml = False
            if insert_select_match:
                dml_text       = insert_select_match.group(1)
                already_in_dml = bool(re.search(rf'\b(?!source_){re.escape(col)}\b', dml_text))

            if already_in_dml:
                fixed_sql = re.sub(
                    rf'\bsource_{col}\b(?=\s+(?:INTEGER|VARCHAR|TEXT|DATE|TIMESTAMP|BOOLEAN|NUMERIC|SERIAL|BIGINT|SMALLINT))',
                    col, fixed_sql, flags=re.IGNORECASE
                )
                fixed_sql = re.sub(rf'\bsource_{col}\b(?=\s*[,\)])', col, fixed_sql)
                fixed_sql = re.sub(rf',\s*\w+\.source_{col}\b', '', fixed_sql)
                fixed_sql = re.sub(rf',\s*source_{col}\b', '', fixed_sql)
                fixed_sql = re.sub(rf'\bsource_{col}\s*,', '', fixed_sql)
                fixed_sql = re.sub(rf'\bsource_{col}\b', '', fixed_sql)
            else:
                fixed_sql = re.sub(rf'\bsource_{col}\b', col, fixed_sql)

        fixed_sql = re.sub(r'\s+AND\s+\w+\.is_current\s*=\s*(TRUE|true|FALSE|false)',
                           '', fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r'\bWHERE\s+\w+\.is_current\s*=\s*(TRUE|true)\s*',
                           'WHERE ', fixed_sql, flags=re.IGNORECASE)
        fixed_sql = re.sub(r'UPDATE\s+\S+\s+SET\s+is_current\s*=\s*FALSE[^;]+;',
                           '', fixed_sql, flags=re.IGNORECASE | re.DOTALL)
        fixed_sql = re.sub(r',\s*,', ',', fixed_sql)
        fixed_sql = re.sub(r'\(\s*,', '(', fixed_sql)
        fixed_sql = re.sub(r',\s*\)', ')', fixed_sql)
        fixed_sql = re.sub(r',\s*\n\s*\)', '\n)', fixed_sql)

        if fixed_sql != script_sql:
            print(f"[RecoveryAgent {recovery_id}] Pattern fix: removed source_ prefix (smart dedup v3)")
            return _try_execute(recovery_id, fixed_sql, conn_config,
                                "remove_source_prefix_and_scd",
                                "Removed source_ prefix (smart dedup v3) + SCD Type 2 cleanup")

    # Pattern 8: SCD Type 2 column in INSERT/SELECT (is_current, valid_from, valid_to)
    for scd_col in ["is_current", "valid_from", "valid_to"]:
        if f'column "{scd_col}"' in error_message and "does not exist" in error_lower:
            fixed_sql = script_sql
            fixed_sql = re.sub(rf',\s*{scd_col}\b', '', fixed_sql, flags=re.IGNORECASE)
            fixed_sql = re.sub(rf'\b{scd_col}\s*,', '', fixed_sql, flags=re.IGNORECASE)
            fixed_sql = re.sub(rf'\b{scd_col}\b', '', fixed_sql, flags=re.IGNORECASE)
            fixed_sql = re.sub(
                rf',?\s*(TRUE|FALSE|true|false|CURRENT_DATE|NULL)\s+AS\s+{scd_col}\s*,?',
                '', fixed_sql, flags=re.IGNORECASE)
            fixed_sql = re.sub(rf'\s+AND\s+\w+\.{scd_col}\s*=\s*\S+', '', fixed_sql, flags=re.IGNORECASE)
            fixed_sql = re.sub(rf'\bWHERE\s+\w+\.{scd_col}\s*=\s*\S+\s*', 'WHERE TRUE ',
                               fixed_sql, flags=re.IGNORECASE)
            fixed_sql = re.sub(r',\s*,', ',', fixed_sql)
            fixed_sql = re.sub(r'\(\s*,', '(', fixed_sql)
            fixed_sql = re.sub(r',\s*\)', ')', fixed_sql)
            fixed_sql = re.sub(r',\s*\n\s*\)', '\n)', fixed_sql)
            fixed_sql = re.sub(r'\(\s+\)', '()', fixed_sql)

            if fixed_sql != script_sql:
                print(f"[RecoveryAgent {recovery_id}] Pattern fix: removed SCD column {scd_col}")
                return _try_execute(recovery_id, fixed_sql, conn_config,
                                    "remove_scd_column",
                                    f"Removed SCD Type 2 column {scd_col} from INSERT/SELECT/JOIN")


    # Pattern 10: dim_date JOIN on non-existent date column
    # AI invents listing_date, transaction_date etc that don't exist in flat files
    # Fix: use year-based JOIN + fix column case issues
    if "does not exist" in error_lower and "date" in error_lower:
        date_join = re.search(
            r'JOIN\s+warehouse\.dim_date\s+(\w+)\s+ON\s+[^\n;]+',
            script_sql, re.IGNORECASE
        )
        if date_join:
            alias = date_join.group(1)
            new_join = (
                f'JOIN warehouse.dim_date {alias} ON '
                f'{alias}.year = src."Year" '
                f'AND {alias}.month = 1 AND {alias}.day = 1'
            )
            fixed_sql = re.sub(
                r'JOIN\s+warehouse\.dim_date\s+\w+\s+ON\s+[^\n;]+',
                new_join, script_sql, flags=re.IGNORECASE
            )
            if fixed_sql != script_sql:
                # Fix column case issues in the patched SQL
                try:
                    conn_fix = _connect(conn_config)
                    conn_fix.autocommit = True
                    cur_fix = conn_fix.cursor()
                    stg_match = re.search(r'FROM\s+staging\.(stg_\w+)', fixed_sql, re.IGNORECASE)
                    if stg_match:
                        stg_tbl = stg_match.group(1)
                        cur_fix.execute(
                            "SELECT column_name FROM information_schema.columns WHERE table_schema='staging' AND table_name=%s",
                            (stg_tbl,)
                        )
                        actual_cols = {r[0].lower(): r[0] for r in cur_fix.fetchall()}
                        def fix_col_case(m):
                            col = m.group(1)
                            actual = actual_cols.get(col.lower())
                            if actual and actual != col:
                                return f'src."{actual}"'
                            return m.group(0)
                        fixed_sql = re.sub(r'src\."(\w+)"', fix_col_case, fixed_sql)
                    cur_fix.close(); conn_fix.close()
                except Exception as _ce:
                    print(f"[RecoveryAgent {recovery_id}] Column case fix warning: {_ce}")
                print(f"[RecoveryAgent {recovery_id}] Pattern fix: dim_date join → year join on Year")
                return _try_execute(recovery_id, fixed_sql, conn_config,
                                    "fix_date_join",
                                    "Fixed dim_date JOIN: invented date col → year join on Year + column case fixes")

    return {"recovered": False, "fix_method": "no_pattern_match",
            "action_taken": "none", "summary": "No pattern matched"}


def _guess_column_type(col_name, sql=""):
    col_lower = col_name.lower()
    if col_lower.endswith("_date") or col_lower == "date":           return "DATE"
    if col_lower.endswith("_at"):                                     return "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    if col_lower.endswith("_pct") or col_lower.endswith("_percent"):  return "NUMERIC(5,2)"
    if col_lower.endswith("_amount") or col_lower.endswith("_price"): return "NUMERIC(15,2)"
    if col_lower.endswith("_count") or col_lower.endswith("_qty"):    return "INTEGER"
    if col_lower.endswith("_key"):                                    return "INTEGER"
    if col_lower.endswith("_id"):                                     return "INTEGER"
    if col_lower.startswith("is_") or col_lower.startswith("has_"):   return "BOOLEAN DEFAULT TRUE"
    if col_lower in ("valid_from", "effective_date", "start_date"):   return "DATE DEFAULT CURRENT_DATE"
    if col_lower in ("valid_to", "expiry_date", "end_date"):          return "DATE"
    if col_lower in ("year", "month", "day", "quarter", "week"):      return "INTEGER"
    return "VARCHAR(255)"


def _try_ai_fix(recovery_id, failed_script, error_message, script_sql, all_scripts, conn_config):
    from ai_provider import ask_ai
    print(f"[RecoveryAgent {recovery_id}] Asking AI to fix SQL...")

    staging_context   = _get_schema_context(conn_config, "staging")
    warehouse_context = _get_schema_context(conn_config, "warehouse")

    prompt = f"""You are a PostgreSQL expert fixing a failed SQL script.

FAILED SCRIPT NAME: {failed_script}

ERROR MESSAGE:
{error_message}

FAILED SQL:
{script_sql}

STAGING TABLES — columns available in source staging layer:
{staging_context}

WAREHOUSE TABLES — columns that actually exist in the warehouse right now:
{warehouse_context}

CRITICAL RULES:
1. NEVER use DROP TABLE — tables may have FK dependencies
2. If a table exists but is missing a column → use ALTER TABLE ADD COLUMN IF NOT EXISTS
3. If SCD Type 2 columns (is_current, valid_from, valid_to) appear but table has no such column
   → remove those conditions from JOINs and those columns from INSERT lists
4. If column has invented prefix (source_, raw_, stg_) → use exact column name from schemas above
5. NEVER use column names not present in the schemas above
6. Keep ON CONFLICT clause and all schema prefixes (warehouse., staging.)
7. Return complete fixed SQL

Return JSON: {{"fixed_sql": "... complete fixed SQL ...", "fix_description": "what was fixed and why"}}"""

    try:
        ai_response = ask_ai(prompt)
        fixed_sql   = ai_response.get("fixed_sql", "").strip()
        fix_desc    = ai_response.get("fix_description", "AI fix")

        if not fixed_sql:
            print(f"[RecoveryAgent {recovery_id}] AI returned empty SQL")
            return {"recovered": False, "fix_method": "ai_empty_response",
                    "action_taken": "none", "summary": "AI returned empty SQL"}

        fixed_sql = fixed_sql.replace("```sql", "").replace("```", "").strip()
        print(f"[RecoveryAgent {recovery_id}] AI fix: {fix_desc[:100]}")
        print(f"[RecoveryAgent {recovery_id}] Applying AI fix...")

        result = _try_execute(recovery_id, fixed_sql, conn_config, "ai_fix", fix_desc)
        if result["recovered"]:
            print(f"[RecoveryAgent {recovery_id}] ✓ AI fix succeeded: {fix_desc[:80]}")
        else:
            print(f"[RecoveryAgent {recovery_id}] ✗ AI fix failed: {result['summary'][:80]}")
        return result

    except Exception as e:
        print(f"[RecoveryAgent {recovery_id}] AI fix error: {e}")
        return {"recovered": False, "fix_method": "ai_error",
                "action_taken": "none", "summary": str(e)}


def _try_execute(recovery_id, fixed_sql, conn_config, fix_method, fix_desc):
    try:
        conn = _connect(conn_config)
        conn.autocommit = False
        cur  = conn.cursor()
        cur.execute(fixed_sql)
        conn.commit()
        conn.close()
        print(f"[RecoveryAgent {recovery_id}] ✓ Fixed SQL executed successfully")
        return {"recovered": True, "fix_method": fix_method,
                "action_taken": fix_desc, "fixed_sql": fixed_sql,
                "summary": f"✓ Recovered via {fix_method}: {fix_desc}"}
    except Exception as e:
        print(f"[RecoveryAgent {recovery_id}] ✗ Fix prepared but failed to apply — {e}")
        return {"recovered": False, "fix_method": fix_method,
                "action_taken": fix_desc, "fixed_sql": fixed_sql,
                "summary": f"Fix prepared but failed to apply — {str(e)[:200]}"}


def _get_schema_context(conn_config, schema_name):
    try:
        conn = _connect(conn_config)
        cur  = conn.cursor()
        cur.execute("""
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """, (schema_name,))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return f"No tables found in {schema_name} schema"
        context = ""; current_table = None
        for table, col, dtype, nullable in rows:
            if table != current_table:
                context += f"\n{schema_name}.{table}:\n"; current_table = table
            context += f"  - {col} ({dtype}){' (nullable)' if nullable == 'YES' else ''}\n"
        return context
    except Exception as e:
        return f"Could not fetch {schema_name} schema: {e}"


def _get_staging_context(conn_config):
    return _get_schema_context(conn_config, "staging")

def _get_warehouse_context(conn_config):
    return _get_schema_context(conn_config, "warehouse")


def _log_to_db(result, pipeline_id, workspace_id, run_id,
               failed_script, error_message, conn_config):
    try:
        conn = _connect(conn_config)
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO recovery_logs
                (id, pipeline_id, pipeline_run_id, workspace_id,
                 failed_script, error_message, error_pattern,
                 action_taken, fix_method, fix_sql,
                 recovered, attempts, summary,
                 started_at, ended_at)
            VALUES
                (gen_random_uuid(), %s, %s, %s,
                 %s, %s, %s,
                 %s, %s, %s,
                 %s, %s::json, %s,
                 NOW(), NOW())
        """, (
            pipeline_id or "", run_id or "", workspace_id or "",
            failed_script, (error_message or "")[:500],
            result.get("fix_method", ""), result.get("action_taken", ""),
            result.get("fix_method", ""), result.get("fixed_sql", ""),
            result.get("recovered", False), json.dumps({"attempts": 1}),
            (result.get("summary", ""))[:500]
        ))
        conn.commit(); conn.close()
        print("[Recovery] Logged to database (recovery_logs table)")
    except Exception as e:
        print(f"[Recovery] Could not log to DB: {e}")