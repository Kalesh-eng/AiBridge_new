"""
agents/quality_agent.py — AIBridge QualityAgent v2.0

PRE-LOAD architecture:
  Runs AFTER ETLAgent (staging ready), BEFORE ExecutionAgent (warehouse load).

  1. Scans staging tables (stg_*) for bad data
  2. Quarantines bad rows → warehouse.dq_audit_log
  3. Deletes bad rows from staging
  4. ExecutionAgent loads ONLY clean rows to warehouse
  5. Pipeline NEVER fails due to data quality issues

Three check types (all $0 pure SQL):
  Level 1 — Null checks:      key columns must not be null
  Level 2 — Duplicate checks: no duplicate natural keys in staging
  Level 3 — Business rules:   domain rules (amount > 0, etc.) — AI generated once, cached

Smart classification:
  100% bad rate → LOAD FAILURE  → log to audit, truncate staging table
  Partial bad   → DATA ISSUE    → quarantine bad rows, keep clean rows

Audit table: warehouse.dq_audit_log
  check_date, pipeline_id, run_id, table_name, column_name,
  issue_type, reason, row_data (JSONB), check_type

v2.0: Pre-load architecture — bad data quarantined BEFORE warehouse load
v1.1: Post-load + audit table
v1.0: Post-load checks only
"""

import json
from datetime import datetime
from .base import BaseAgent, AgentContext, AgentResult


class QualityAgent(BaseAgent):
    name        = "QualityAgent"
    description = "Pre-load data quality — quarantines bad rows before warehouse load"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        result.log("Starting pre-load data quality checks...")

        target_config    = ctx.target_config if ctx.target_config else ctx.connector_config
        staging_schema   = ctx.staging_schema   or "staging"
        warehouse_schema = ctx.warehouse_schema  or "warehouse"
        pipeline_id      = ctx.pipeline_id       or "unknown"
        run_id           = ctx.run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        # Ensure audit table exists in warehouse schema
        _ensure_audit_table(target_config, warehouse_schema)
        result.log(f"✓ Audit table ready: {warehouse_schema}.dq_audit_log")

        # Discover staging tables — ONLY for this pipeline's source tables
        # Prevents cross-pipeline contamination (school/health tables in banking pipeline)
        if ctx.source_tables:
            stg_tables = [f"stg_{t}" for t in ctx.source_tables]
            # Verify they actually exist in staging
            existing   = _discover_staging_tables(target_config, staging_schema)
            stg_tables = [t for t in stg_tables if t in existing]
            result.log(f"Using pipeline source tables: {stg_tables}")
        else:
            stg_tables = _discover_staging_tables(target_config, staging_schema)

        if not stg_tables:
            result.log("⚠ No staging tables found — skipping quality checks")
            ctx.quality_result = _empty_report()
            return ctx.quality_result

        result.log(f"Found {len(stg_tables)} staging tables to check: {stg_tables}")

        null_checks   = []
        dup_checks    = []
        rule_checks   = []
        total_removed = 0

        # ── Level 1: Null checks on staging ──────────────────────────────────
        result.log("Level 1 — Null checks on staging tables...")
        for stg_table in stg_tables:
            checks, removed = _check_nulls_in_staging(
                target_config, staging_schema, warehouse_schema,
                stg_table, pipeline_id, run_id, result,
                required_columns=getattr(ctx, 'required_columns', {})
            )
            null_checks.extend(checks)
            total_removed += removed

        null_passed = sum(1 for c in null_checks if c["passed"])
        null_failed = len(null_checks) - null_passed
        result.log(f"Null checks: {null_passed} passed, {null_failed} failed")

        # ── Level 2: Duplicate checks on staging ─────────────────────────────
        result.log("Level 2 — Duplicate checks on staging tables...")
        for stg_table in stg_tables:
            check, removed = _check_duplicates_in_staging(
                target_config, staging_schema, warehouse_schema,
                stg_table, pipeline_id, run_id, result
            )
            if check:
                dup_checks.append(check)
                total_removed += removed

        dup_passed = sum(1 for c in dup_checks if c["passed"])
        dup_failed = len(dup_checks) - dup_passed
        result.log(f"Duplicate checks: {dup_passed} passed, {dup_failed} failed")

        # ── Level 3: Business rules on staging ───────────────────────────────
        result.log("Level 3 — Business rules on staging tables...")
        domain = _get_domain(ctx)
        rules  = _get_business_rules(ctx, domain, stg_tables, result)

        if rules:
            for rule in rules:
                check, removed = _check_business_rule_in_staging(
                    target_config, staging_schema, warehouse_schema,
                    rule, pipeline_id, run_id, result
                )
                rule_checks.append(check)
                total_removed += removed

            rule_passed = sum(1 for c in rule_checks if c["passed"])
            rule_failed = len(rule_checks) - rule_passed
            result.log(f"Business rules: {rule_passed} passed, {rule_failed} failed")

        # ── Summary ───────────────────────────────────────────────────────────
        audit_rows = _count_audit_rows(target_config, warehouse_schema, run_id)

        total_checks = len(null_checks) + len(dup_checks) + len(rule_checks)
        total_passed = (null_passed + dup_passed +
                        sum(1 for c in rule_checks if c["passed"]))
        score = round((total_passed / total_checks) * 100, 1) if total_checks > 0 else 100.0

        if score >= 95:   status = "passed";  emoji = "✅"
        elif score >= 80: status = "warning"; emoji = "⚠️"
        else:             status = "failed";  emoji = "❌"

        result.log(f"{emoji} Pre-load quality score: {score}% ({status})")
        result.log(f"Total: {total_passed}/{total_checks} checks passed")

        if total_removed > 0:
            result.log(f"🗑 {total_removed} bad rows quarantined → {warehouse_schema}.dq_audit_log")
            result.log(f"✓ Staging tables cleaned — warehouse will load ONLY clean data")

        failed_items = (
            [c for c in null_checks  if not c["passed"]] +
            [c for c in dup_checks   if not c["passed"]] +
            [c for c in rule_checks  if not c["passed"]]
        )

        if failed_items:
            result.log("Issues found and quarantined:")
            for item in failed_items:
                issue_type = item.get("issue_type", "")
                result.log(f"  ✗ {item['check']} [{issue_type}] — {item['message']}")

        report = {
            "score":          score,
            "status":         status,
            "emoji":          emoji,
            "domain":         domain,
            "stg_tables":     stg_tables,
            "total_checks":   total_checks,
            "total_passed":   total_passed,
            "total_failed":   total_checks - total_passed,
            "total_removed":  total_removed,
            "null_checks":    null_checks,
            "dup_checks":     dup_checks,
            "rule_checks":    rule_checks,
            "failed_items":   failed_items,
            "audit_rows":     audit_rows,
            "audit_table":    f"{warehouse_schema}.dq_audit_log",
            "run_id":         run_id,
            "phase":          "pre_load",
            "summary":        (
                f"{emoji} {score}% pre-load quality — "
                f"{total_passed}/{total_checks} checks passed"
                + (f", {total_removed} bad rows quarantined" if total_removed > 0 else "")
            )
        }

        ctx.quality_result = report
        return report


# ── Audit table ───────────────────────────────────────────────────────────────

def _ensure_audit_table(config: dict, warehouse_schema: str):
    """Create dq_audit_log if it doesn't exist."""
    try:
        conn = _pg_connect(config)
        conn.autocommit = True
        cur  = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS "{warehouse_schema}"."dq_audit_log" (
                audit_id       SERIAL PRIMARY KEY,
                check_date     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                pipeline_id    VARCHAR(100),
                run_id         VARCHAR(100),
                table_name     VARCHAR(200),
                column_name    VARCHAR(200),
                issue_type     VARCHAR(50),
                reason         TEXT,
                row_data       JSONB,
                check_type     VARCHAR(50),
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_dq_audit_pipeline
                ON "{warehouse_schema}"."dq_audit_log" (pipeline_id);
            CREATE INDEX IF NOT EXISTS idx_dq_audit_table
                ON "{warehouse_schema}"."dq_audit_log" (table_name);
            CREATE INDEX IF NOT EXISTS idx_dq_audit_date
                ON "{warehouse_schema}"."dq_audit_log" (check_date);
            CREATE INDEX IF NOT EXISTS idx_dq_audit_issue
                ON "{warehouse_schema}"."dq_audit_log" (issue_type);
        """)
        cur.close(); conn.close()
    except Exception as e:
        print(f"[QualityAgent] Could not create audit table: {e}")


def _write_audit_records(config: dict, warehouse_schema: str, records: list):
    """Write bad records to dq_audit_log."""
    if not records:
        return 0
    try:
        conn = _pg_connect(config)
        conn.autocommit = False
        cur  = conn.cursor()
        for rec in records:
            cur.execute(f"""
                INSERT INTO "{warehouse_schema}"."dq_audit_log"
                    (check_date, pipeline_id, run_id, table_name, column_name,
                     issue_type, reason, row_data, check_type)
                VALUES (CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                rec.get("pipeline_id", ""),
                rec.get("run_id", ""),
                rec.get("table_name", ""),
                rec.get("column_name", ""),
                rec.get("issue_type", ""),
                rec.get("reason", ""),
                json.dumps(rec.get("row_data", {})),
                rec.get("check_type", "")
            ))
        conn.commit()
        cur.close(); conn.close()
        return len(records)
    except Exception as e:
        print(f"[QualityAgent] Could not write audit records: {e}")
        return 0


def _count_audit_rows(config: dict, warehouse_schema: str, run_id: str) -> int:
    try:
        conn = _pg_connect(config)
        cur  = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*) FROM "{warehouse_schema}"."dq_audit_log"
            WHERE run_id = %s
        """, (run_id,))
        count = cur.fetchone()[0]
        cur.close(); conn.close()
        return count
    except Exception:
        return 0


# ── Staging table discovery ───────────────────────────────────────────────────

def _discover_staging_tables(config: dict, staging_schema: str) -> list:
    """Find all stg_* tables in staging schema."""
    try:
        conn = _pg_connect(config)
        cur  = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
              AND table_name LIKE 'stg_%%'
            ORDER BY table_name
        """, (staging_schema,))
        tables = [r[0] for r in cur.fetchall()]
        cur.close(); conn.close()
        return tables
    except Exception as e:
        print(f"[QualityAgent] Could not discover staging tables: {e}")
        return []


def _get_staging_columns(config: dict, staging_schema: str, table: str) -> list:
    """Get columns for a staging table."""
    try:
        conn = _pg_connect(config)
        cur  = conn.cursor()
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
              AND column_name != '_loaded_at'
            ORDER BY ordinal_position
        """, (staging_schema, table))
        cols = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]
        cur.close(); conn.close()
        return cols
    except Exception as e:
        print(f"[QualityAgent] Could not get columns for {table}: {e}")
        return []


def _get_row_count(config: dict, schema: str, table: str) -> int:
    try:
        conn = _pg_connect(config)
        cur  = conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        count = cur.fetchone()[0]
        cur.close(); conn.close()
        return count
    except Exception:
        return 0


def _pg_connect(config: dict):
    import psycopg2
    return psycopg2.connect(
        host=config.get("host"),
        port=int(config.get("port", 5432)),
        dbname=config.get("database") or config.get("database_name"),
        user=config.get("username"),
        password=config.get("password")
    )


# ── Level 1: Null checks on staging ──────────────────────────────────────────

def _check_nulls_in_staging(config: dict, staging_schema: str,
                              warehouse_schema: str, stg_table: str,
                              pipeline_id: str, run_id: str,
                              result: AgentResult,
                              required_columns: dict = None) -> tuple:
    """
    Check staging table for null values in key columns.
    Bad rows → dq_audit_log + deleted from staging.
    Returns (checks list, rows_removed count).
    """
    checks       = []
    rows_removed = 0
    columns      = _get_staging_columns(config, staging_schema, stg_table)
    if not columns:
        return checks, rows_removed

    # Determine which columns to check for nulls:
    # 1. If business defined required_columns — use those for this table
    # 2. Else fall back to _id/_key columns only
    col_names = [c["name"] for c in columns]
    required_columns = required_columns or {}

    # Find required cols for this staging table
    # required_columns keys are "target_table.target_column" — map to staging col names
    # Case-insensitive match — required cols may be lowercase, staging cols may be mixed case
    col_names_lower = {c.lower(): c for c in col_names}
    business_required = [
        col_names_lower[col.split(".")[-1].lower()]
        for col, is_req in required_columns.items()
        if is_req and col.split(".")[-1].lower() in col_names_lower
    ]

    if business_required:
        key_cols = business_required
        result.log(f"  Using {len(key_cols)} business-defined required columns for null checks")
    else:
        # Fall back to _id/_key columns
        key_cols = [
            c["name"] for c in columns
            if c["name"].endswith("_id") or c["name"].endswith("_key")
        ]
        if not key_cols:
            key_cols = []  # No key cols found — skip null checks
            result.log(f"  No required columns defined and no _id/_key columns — skipping null checks for {stg_table}")

    try:
        conn = _pg_connect(config)
        conn.autocommit = False
        cur  = conn.cursor()

        for col in key_cols:
            if col not in col_names:
                continue

            # Count nulls
            cur.execute(f"""
                SELECT COUNT(*) FROM "{staging_schema}"."{stg_table}"
                WHERE "{col}" IS NULL
            """)
            null_count = cur.fetchone()[0]

            cur.execute(f'SELECT COUNT(*) FROM "{staging_schema}"."{stg_table}"')
            total = cur.fetchone()[0]

            passed    = (null_count == 0)
            null_rate = (null_count / total) if total > 0 else 0

            # Critical columns: _id, _key suffix → delete rows with nulls
            # Non-critical columns: flag only → write to audit but keep rows
            is_critical = (col.endswith("_id") or col.endswith("_key"))

            if not passed:
                if null_rate == 1.0:
                    # Load failure — all rows null in this column
                    issue_type = "load_failure"
                    reason     = (f"All {total} rows have NULL {col} — "
                                  f"staging table {stg_table} failed to load correctly")
                    _write_audit_records(config, warehouse_schema, [{
                        "pipeline_id": pipeline_id,
                        "run_id":      run_id,
                        "table_name":  stg_table,
                        "column_name": col,
                        "issue_type":  "load_failure",
                        "reason":      reason,
                        "row_data":    {"null_count": null_count,
                                        "total_rows": total,
                                        "null_rate":  "100%"},
                        "check_type":  "null_check"
                    }])
                    if is_critical:
                        cur.execute(f'TRUNCATE TABLE "{staging_schema}"."{stg_table}"')
                        conn.commit()
                        rows_removed += total
                        print(f"[QualityAgent] 🗑 {total} rows removed from "
                              f"{stg_table} (load_failure — all NULL {col})")
                    else:
                        print(f"[QualityAgent] ⚠ {null_count} nulls in {stg_table}.{col} — flagged only (non-critical column)")

                else:
                    # Partial nulls
                    issue_type = "null_value"

                    # Write summary record to audit (not per-row for non-critical)
                    _write_audit_records(config, warehouse_schema, [{
                        "pipeline_id": pipeline_id,
                        "run_id":      run_id,
                        "table_name":  stg_table,
                        "column_name": col,
                        "issue_type":  "null_value",
                        "reason":      f"{null_count}/{total} rows have NULL {col} ({round(null_rate*100,1)}%)",
                        "row_data":    {"null_count": null_count, "total_rows": total,
                                        "null_rate": f"{round(null_rate*100,1)}%"},
                        "check_type":  "null_check"
                    }])

                    if is_critical:
                        # Delete rows only for critical columns
                        cur.execute(f"""
                            DELETE FROM "{staging_schema}"."{stg_table}"
                            WHERE "{col}" IS NULL
                        """)
                        deleted = cur.rowcount
                        conn.commit()
                        rows_removed += deleted
                        print(f"[QualityAgent] 🗑 {deleted} rows removed from "
                              f"{stg_table} (NULL {col} — critical column → audit log)")
                    else:
                        print(f"[QualityAgent] ⚠ {null_count} nulls in {stg_table}.{col} — flagged only (non-critical column)")

            checks.append({
                "check":      f"{stg_table}.{col} — null check",
                "table":      stg_table,
                "column":     col,
                "type":       "null_check",
                "issue_type": issue_type if not passed else None,
                "passed":     passed,
                "null_count": null_count,
                "total_rows": total,
                "null_rate":  round(null_rate * 100, 1),
                "message":    f"0 nulls in {total} rows" if passed
                              else (f"{null_count}/{total} nulls "
                                    f"({round(null_rate*100,1)}%) — quarantined"),
            })

        cur.close(); conn.close()

    except Exception as e:
        checks.append({
            "check":   f"{stg_table} — null check",
            "table":   stg_table,
            "type":    "null_check",
            "passed":  False,
            "message": f"Check failed: {str(e)[:100]}"
        })

    return checks, rows_removed


# ── Level 2: Duplicate checks on staging ─────────────────────────────────────

def _check_duplicates_in_staging(config: dict, staging_schema: str,
                                  warehouse_schema: str, stg_table: str,
                                  pipeline_id: str, run_id: str,
                                  result: AgentResult) -> tuple:
    """
    Check staging table for duplicate natural keys.
    Keeps first occurrence, quarantines duplicates.
    Returns (check dict, rows_removed count).
    """
    rows_removed = 0
    columns      = _get_staging_columns(config, staging_schema, stg_table)
    col_names    = [c["name"] for c in columns]

    # Find natural key column (_id suffix, not _loaded_at)
    id_col = next(
        (c for c in col_names
         if c.endswith("_id") and c != "_loaded_at"),
        None
    )
    if not id_col:
        # No natural key column found — check for fully duplicate rows (all columns identical)
        result.log(f"  No _id column in {stg_table} — checking for fully duplicate rows")
        try:
            import json
            conn2 = _pg_connect(config)
            conn2.autocommit = False
            cur2  = conn2.cursor()
            col_list = ", ".join(f'CAST("{c}" AS TEXT)' for c in col_names)
            cur2.execute(f"""
                SELECT COUNT(*) FROM (
                    SELECT {col_list}, COUNT(*)
                    FROM "{staging_schema}"."{stg_table}"
                    GROUP BY {col_list}
                    HAVING COUNT(*) > 1
                ) dupes
            """)
            dup_groups = cur2.fetchone()[0]
            cur2.execute(f'SELECT COUNT(*) FROM "{staging_schema}"."{stg_table}"')
            total2 = cur2.fetchone()[0]
            if dup_groups > 0:
                cur2.execute(f"""
                    SELECT row_to_json(t) FROM (
                        SELECT * FROM "{staging_schema}"."{stg_table}"
                        WHERE ({col_list}) IN (
                            SELECT {col_list}
                            FROM "{staging_schema}"."{stg_table}"
                            GROUP BY {col_list}
                            HAVING COUNT(*) > 1
                        )
                        LIMIT 1000
                    ) t
                """)
                bad_rows = [r[0] for r in cur2.fetchall()]
                _write_audit_records(config, warehouse_schema, [{
                    "pipeline_id": pipeline_id,
                    "run_id":      run_id,
                    "table_name":  stg_table,
                    "column_name": "all_columns",
                    "issue_type":  "duplicate_key",
                    "reason":      "Fully duplicate row (all columns identical)",
                    "row_data":    row if isinstance(row, str) else json.dumps(row),
                    "check_type":  "duplicate_check"
                } for row in bad_rows])
                cur2.execute(f"""
                    DELETE FROM "{staging_schema}"."{stg_table}"
                    WHERE ctid NOT IN (
                        SELECT MIN(ctid)
                        FROM "{staging_schema}"."{stg_table}"
                        GROUP BY {col_list}
                    )
                """)
                deleted = cur2.rowcount
                conn2.commit()
                cur2.close(); conn2.close()
                result.log(f"  🗑 {deleted} fully duplicate rows quarantined from {stg_table}")
                pct = round(((total2 - deleted) / total2 * 100), 1) if total2 > 0 else 100.0
                return {
                    "check":      f"{stg_table}: fully duplicate rows",
                    "table":      stg_table,
                    "column":     "all_columns",
                    "type":       "duplicate_check",
                    "issue_type": "duplicate_key",
                    "passed":     False,
                    "violations": deleted,
                    "total_rows": total2,
                    "pass_rate":  pct,
                    "message":    f"{deleted} fully duplicate rows quarantined"
                }, deleted
            cur2.close(); conn2.close()
            return {
                "check":      f"{stg_table}: fully duplicate rows",
                "table":      stg_table,
                "column":     "all_columns",
                "type":       "duplicate_check",
                "passed":     True,
                "violations": 0,
                "total_rows": total2,
                "pass_rate":  100.0,
                "message":    f"0 fully duplicate rows in {total2} rows"
            }, 0
        except Exception as e2:
            result.log(f"  Warning: full-row duplicate check failed: {e2}")
            return None, 0

    try:
        conn = _pg_connect(config)
        conn.autocommit = False
        cur  = conn.cursor()

        # Count duplicate groups
        cur.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT "{id_col}", COUNT(*) as cnt
                FROM "{staging_schema}"."{stg_table}"
                GROUP BY "{id_col}"
                HAVING COUNT(*) > 1
            ) dupes
        """)
        dup_groups = cur.fetchone()[0]

        cur.execute(f'SELECT COUNT(*) FROM "{staging_schema}"."{stg_table}"')
        total = cur.fetchone()[0]

        if dup_groups > 0:
            # Fetch duplicate rows for audit
            cur.execute(f"""
                SELECT row_to_json(t) FROM (
                    SELECT * FROM "{staging_schema}"."{stg_table}"
                    WHERE "{id_col}" IN (
                        SELECT "{id_col}"
                        FROM "{staging_schema}"."{stg_table}"
                        GROUP BY "{id_col}"
                        HAVING COUNT(*) > 1
                    )
                    LIMIT 1000
                ) t
            """)
            bad_rows = [r[0] for r in cur.fetchall()]

            # Write to audit
            _write_audit_records(config, warehouse_schema, [{
                "pipeline_id": pipeline_id,
                "run_id":      run_id,
                "table_name":  stg_table,
                "column_name": id_col,
                "issue_type":  "duplicate_key",
                "reason":      f"Duplicate value in key column {id_col}",
                "row_data":    row,
                "check_type":  "duplicate_check"
            } for row in bad_rows])

            # Keep only first occurrence, delete duplicates
            cur.execute(f"""
                DELETE FROM "{staging_schema}"."{stg_table}" a
                USING (
                    SELECT MIN(ctid) as keep_ctid, "{id_col}"
                    FROM "{staging_schema}"."{stg_table}"
                    GROUP BY "{id_col}"
                    HAVING COUNT(*) > 1
                ) b
                WHERE a."{id_col}" = b."{id_col}"
                  AND a.ctid != b.keep_ctid
            """)
            deleted = cur.rowcount
            conn.commit()
            rows_removed = deleted
            print(f"[QualityAgent] 🗑 {deleted} duplicate rows removed from "
                  f"{stg_table} → audit log")

        cur.close(); conn.close()

        passed = (dup_groups == 0)
        return {
            "check":      f"{stg_table}.{id_col} — duplicate check",
            "table":      stg_table,
            "column":     id_col,
            "type":       "duplicate_check",
            "passed":     passed,
            "dup_groups": dup_groups,
            "total_rows": total,
            "message":    f"0 duplicates in {total} rows" if passed
                          else f"{dup_groups} duplicate {id_col} groups — quarantined",
        }, rows_removed

    except Exception as e:
        return {
            "check":   f"{stg_table} — duplicate check",
            "table":   stg_table,
            "type":    "duplicate_check",
            "passed":  False,
            "message": f"Check failed: {str(e)[:100]}"
        }, 0


# ── Level 3: Business rules on staging ───────────────────────────────────────

def _get_domain(ctx: AgentContext) -> str:
    if ctx.business_result:
        return ctx.business_result.get("domain", "general")
    return "general"


def _get_business_rules(ctx: AgentContext, domain: str,
                        stg_tables: list, result: AgentResult) -> list:
    """Generate business rules via AI — cached per pipeline."""
    cached = _get_cached_rules(ctx, domain)
    if cached:
        result.log(f"✓ Using cached business rules ({len(cached)} rules)")
        return cached

    try:
        from ai_provider import ask_ai

        # Build schema hint from data model
        schema_text = ""
        if ctx.data_model:
            dm = ctx.data_model.get("data_model", {})
            for fact in dm.get("fact_tables", []):
                measures = [m.get("column") if isinstance(m, dict) else m
                            for m in fact.get("measures", [])]
                schema_text += f"\n{fact.get('name','')}: {', '.join(measures)}"

        # Map stg_ tables to source tables
        source_tables = [t.replace("stg_", "", 1) for t in stg_tables]

        prompt = f"""You are a data quality expert. Generate business rules to validate staging data.

DOMAIN: {domain}
STAGING TABLES: {', '.join(stg_tables)}
SOURCE TABLES:  {', '.join(source_tables)}
MEASURES: {schema_text or 'standard measures'}

Generate 3-6 practical data validation rules. Return ONLY valid JSON:
{{
  "rules": [
    {{
      "table":       "stg_transactions",
      "column":      "amount",
      "condition":   "amount > 0",
      "sql_where":   "amount <= 0",
      "description": "Transaction amount must be positive"
    }}
  ]
}}

RULES BY DOMAIN:
- finance/banking: amount > 0, balance >= 0
- healthcare:      bill_amount > 0, duration_mins BETWEEN 1 AND 1440
- education:       grade BETWEEN 0 AND 100

sql_where finds VIOLATING rows.
Only use tables from: {', '.join(stg_tables)}"""

        result.log(f"Asking AI to generate business rules for {domain} domain...")
        ai_result = ask_ai(prompt)
        rules     = ai_result.get("rules", [])
        table_set = set(stg_tables)
        rules     = [r for r in rules if r.get("table") in table_set]
        result.log(f"✓ AI generated {len(rules)} business rules")
        _cache_rules(ctx, domain, rules)
        return rules

    except Exception as e:
        result.log(f"⚠ Could not generate business rules: {e}")
        return _default_rules(domain, stg_tables)


def _default_rules(domain: str, stg_tables: list) -> list:
    rules = []
    for t in stg_tables:
        if domain in ("finance", "banking") and "transaction" in t:
            rules.append({
                "table": t, "column": "amount",
                "condition": "amount > 0", "sql_where": "amount <= 0",
                "description": "Amount must be positive"
            })
        elif domain == "healthcare" and "visit" in t:
            rules.append({
                "table": t, "column": "bill_amount",
                "condition": "bill_amount > 0", "sql_where": "bill_amount <= 0",
                "description": "Bill amount must be positive"
            })
    return rules


def _check_business_rule_in_staging(config: dict, staging_schema: str,
                                     warehouse_schema: str, rule: dict,
                                     pipeline_id: str, run_id: str,
                                     result: AgentResult) -> tuple:
    """
    Run business rule on staging table.
    Violating rows → audit log + deleted from staging.
    Returns (check dict, rows_removed count).
    """
    table     = rule.get("table", "")
    column    = rule.get("column", "")
    condition = rule.get("condition", "")
    sql_where = rule.get("sql_where", "")
    desc      = rule.get("description", condition)
    removed   = 0

    if not table or not sql_where:
        return {"check": f"Business rule: {desc}", "type": "business_rule",
                "passed": True, "message": "Skipped — incomplete rule"}, 0

    try:
        conn = _pg_connect(config)
        conn.autocommit = False
        cur  = conn.cursor()

        # Check table exists
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        """, (staging_schema, table))
        if cur.fetchone()[0] == 0:
            cur.close(); conn.close()
            return {"check": f"Business rule: {desc}", "type": "business_rule",
                    "passed": True, "message": f"Table {table} not found — skipped"}, 0

        # Check column exists
        if column:
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """, (staging_schema, table, column))
            if cur.fetchone()[0] == 0:
                cur.close(); conn.close()
                return {"check": f"Business rule: {desc}", "type": "business_rule",
                        "passed": True, "message": f"Column {column} not found — skipped"}, 0

        # Count violations
        cur.execute(f"""
            SELECT COUNT(*) FROM "{staging_schema}"."{table}"
            WHERE {sql_where}
        """)
        violations = cur.fetchone()[0]

        cur.execute(f'SELECT COUNT(*) FROM "{staging_schema}"."{table}"')
        total = cur.fetchone()[0]

        if violations > 0:
            # Fetch violating rows
            cur.execute(f"""
                SELECT row_to_json(t) FROM (
                    SELECT * FROM "{staging_schema}"."{table}"
                    WHERE {sql_where}
                    LIMIT 1000
                ) t
            """)
            bad_rows = [r[0] for r in cur.fetchall()]

            # Write to audit
            _write_audit_records(config, warehouse_schema, [{
                "pipeline_id": pipeline_id,
                "run_id":      run_id,
                "table_name":  table,
                "column_name": column,
                "issue_type":  "business_rule_violation",
                "reason":      f"Violated: {desc} (condition: {condition})",
                "row_data":    row,
                "check_type":  "business_rule"
            } for row in bad_rows])

            # Delete violating rows from staging
            cur.execute(f"""
                DELETE FROM "{staging_schema}"."{table}"
                WHERE {sql_where}
            """)
            removed = cur.rowcount
            conn.commit()
            print(f"[QualityAgent] 🗑 {removed} rows removed from "
                  f"{table} ({desc} violation → audit log)")

        cur.close(); conn.close()

        passed = (violations == 0)
        pct    = round(((total - violations) / total * 100), 1) if total > 0 else 100.0

        return {
            "check":      f"{table}: {desc}",
            "table":      table,
            "column":     column,
            "condition":  condition,
            "type":       "business_rule",
            "passed":     passed,
            "violations": violations,
            "total_rows": total,
            "pass_rate":  pct,
            "message":    f"{pct}% rows comply" if passed
                          else f"{violations} violations quarantined — {pct}% clean",
        }, removed

    except Exception as e:
        return {
            "check":   f"Business rule: {desc}",
            "type":    "business_rule",
            "passed":  False,
            "message": f"Rule check failed: {str(e)[:150]}"
        }, 0


# ── Rule caching ──────────────────────────────────────────────────────────────

_rule_cache: dict = {}

def _get_cached_rules(ctx: AgentContext, domain: str):
    return _rule_cache.get(f"{ctx.pipeline_id}:{domain}")

def _cache_rules(ctx: AgentContext, domain: str, rules: list):
    _rule_cache[f"{ctx.pipeline_id}:{domain}"] = rules


# ── Empty report ──────────────────────────────────────────────────────────────

def _empty_report() -> dict:
    return {
        "score": 100.0, "status": "passed", "emoji": "✅",
        "domain": "unknown", "stg_tables": [],
        "total_checks": 0, "total_passed": 0, "total_failed": 0,
        "total_removed": 0, "null_checks": [], "dup_checks": [],
        "rule_checks": [], "failed_items": [], "audit_rows": 0,
        "phase": "pre_load",
        "summary": "✅ No staging tables to check"
    }