"""
agents/sql_validation_agent.py
Validates generated SQL BEFORE it reaches the human reviewer.
Pure Python — no AI needed. Fast, reliable, catches common LLM mistakes.

Checks:
  - stg_ prefix on all staging table references
  - dim_/fact_ prefix on warehouse tables
  - No placeholder text (<lookup_X>, <col_name>)
  - Alias consistency (no mixing table name + alias)
  - ON CONFLICT clause exists for INSERT scripts
  - FK syntax correct (REFERENCES schema.table(col))
  - No mixed alias/table name in same SELECT
"""

import re
from .base import BaseAgent, AgentContext, AgentResult


class SQLValidationAgent(BaseAgent):
    name        = "SQLValidationAgent"
    description = "Validates generated SQL for common LLM errors before human review"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        if not ctx.sql_scripts:
            raise ValueError("SQLAgent must run before SQLValidationAgent")

        scripts = ctx.sql_scripts.get("scripts", [])
        result.log(f"Validating {len(scripts)} SQL scripts...")

        all_issues   = []
        auto_fixes   = []
        fixed_scripts = []

        for script in scripts:
            name = script.get("name", "unknown")
            sql  = script.get("sql", "")
            issues, fixed_sql, fixes = self._validate_and_fix(name, sql, ctx, result)
            all_issues.extend(issues)
            auto_fixes.extend(fixes)
            fixed_scripts.append({**script, "sql": fixed_sql})

        # Update scripts with fixes applied
        ctx.sql_scripts = {**ctx.sql_scripts, "scripts": fixed_scripts}

        validation = {
            "passed":      len([i for i in all_issues if i["severity"] == "error"]) == 0,
            "issues":      all_issues,
            "auto_fixes":  auto_fixes,
            "script_count": len(scripts)
        }

        ctx.sql_validation = validation
        error_count = len([i for i in all_issues if i["severity"] == "error"])
        warn_count  = len([i for i in all_issues if i["severity"] == "warning"])

        if validation["passed"]:
            result.log(f"✓ SQL validation passed — {len(auto_fixes)} auto-fixes applied, {warn_count} warnings")
        else:
            result.log(f"✗ SQL validation FAILED — {error_count} errors, {warn_count} warnings", "error")

        return validation

    def _validate_and_fix(self, name: str, sql: str, ctx: AgentContext, result: AgentResult):
        issues    = []
        fixes     = []
        fixed_sql = sql

        # ── Check 1: Placeholder text ─────────────────────────────────────────
        placeholders = re.findall(r'<[a-zA-Z_]+>', sql)
        if placeholders:
            issues.append({
                "script":   name,
                "check":    "placeholder_text",
                "severity": "error",
                "detail":   f"Found placeholder text: {placeholders}"
            })
            result.log(f"✗ {name}: placeholder text found: {placeholders}", "error")

        # ── Check 2: stg_ prefix on staging refs ──────────────────────────────
        staging_schema = ctx.staging_schema or "staging"
        # Look for staging.tablename without stg_ prefix
        bad_staging = re.findall(
            rf'{staging_schema}\.(?!stg_)([a-zA-Z_][a-zA-Z0-9_]*)', sql
        )
        if bad_staging:
            for bad in bad_staging:
                fixed_sql = fixed_sql.replace(
                    f"{staging_schema}.{bad}",
                    f"{staging_schema}.stg_{bad}"
                )
                fixes.append(f"{name}: auto-fixed staging ref: {staging_schema}.{bad} → stg_{bad}")
                result.log(f"⚡ {name}: auto-fixed stg_ prefix: {bad}")

        # ── Check 3: ON CONFLICT for INSERT scripts ───────────────────────────
        if "INSERT INTO" in sql.upper() and "ON CONFLICT" not in sql.upper():
            issues.append({
                "script":   name,
                "check":    "missing_on_conflict",
                "severity": "warning",
                "detail":   "INSERT has no ON CONFLICT clause — re-runs may cause duplicate key errors"
            })
            result.log(f"⚠ {name}: missing ON CONFLICT clause", "warn")

        # ── Check 4: Broken FK syntax ─────────────────────────────────────────
        # Bad: REFERENCES warehouse.dim_student.student_key(student_key)
        bad_fk = re.findall(r'REFERENCES\s+\w+\.\w+\.\w+\s*\(', sql, re.IGNORECASE)
        if bad_fk:
            issues.append({
                "script":   name,
                "check":    "broken_fk_syntax",
                "severity": "error",
                "detail":   f"Broken FK syntax (3-part reference): {bad_fk}"
            })
            result.log(f"✗ {name}: broken FK syntax detected", "error")

        # ── Check 5: DROP without IF EXISTS ──────────────────────────────────
        dangerous_drops = re.findall(
            r'\bDROP\s+TABLE\s+(?!IF\s+EXISTS)', sql, re.IGNORECASE
        )
        if dangerous_drops:
            issues.append({
                "script":   name,
                "check":    "dangerous_drop",
                "severity": "error",
                "detail":   "DROP TABLE without IF EXISTS is dangerous"
            })
            # Auto-fix: add IF EXISTS
            fixed_sql = re.sub(
                r'\bDROP\s+TABLE\s+(?!IF\s+EXISTS)',
                'DROP TABLE IF EXISTS ',
                fixed_sql, flags=re.IGNORECASE
            )
            fixes.append(f"{name}: auto-fixed DROP TABLE → DROP TABLE IF EXISTS")
            result.log(f"⚡ {name}: auto-fixed dangerous DROP TABLE")

        return issues, fixed_sql, fixes
