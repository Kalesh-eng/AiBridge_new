"""
sql_safety.py — SQL Safety Guard for AIBridge.

BLOCKS dangerous SQL operations from running unless the user explicitly
overrides with i_understand_destructive=True.

Categories:
  CRITICAL    → blocks always until override (DROP TABLE, TRUNCATE, DROP SCHEMA, DROP DATABASE)
  HIGH        → blocks always until override (DELETE without WHERE, UPDATE without WHERE)
  MEDIUM      → warns but allows (ALTER TABLE DROP COLUMN, etc.)
  LOW         → just notes (DDL changes in general)

Usage:
    from sql_safety import check_sql_safety

    result = check_sql_safety(sql_text)
    if result["blocked"]:
        raise HTTPException(400, detail=result)

Override:
    result = check_sql_safety(sql_text, allow_destructive=True)
"""

import re


# ── Pattern definitions ──────────────────────────────────────────────────────

CRITICAL_PATTERNS = [
    {
        "pattern":  r'\bDROP\s+TABLE\s+(?!IF\s+EXISTS)',
        "name":     "DROP TABLE without IF EXISTS",
        "category": "CRITICAL",
        "message":  "DROP TABLE without IF EXISTS can fail or destroy data unexpectedly. Use DROP TABLE IF EXISTS or override."
    },
    {
        "pattern":  r'\bDROP\s+SCHEMA\b',
        "name":     "DROP SCHEMA",
        "category": "CRITICAL",
        "message":  "DROP SCHEMA destroys an entire schema with all its tables. Override required."
    },
    {
        "pattern":  r'\bDROP\s+DATABASE\b',
        "name":     "DROP DATABASE",
        "category": "CRITICAL",
        "message":  "DROP DATABASE destroys an entire database. This is almost never what you want from ETL. Override required."
    },
    {
        "pattern":  r'\bTRUNCATE\b',
        "name":     "TRUNCATE",
        "category": "CRITICAL",
        "message":  "TRUNCATE removes ALL rows from a table without WHERE clause. Override required."
    },
]

HIGH_PATTERNS = [
    {
        "pattern":  r'\bDELETE\s+FROM\s+[\w\.]+\s*(?:;|$)',  # DELETE FROM x; with no WHERE
        "name":     "DELETE without WHERE",
        "category": "HIGH",
        "message":  "DELETE without a WHERE clause removes ALL rows. Override required."
    },
    {
        "pattern":  r'\bDELETE\s+FROM\s+[\w\.]+\s+(?!WHERE)\w+',  # DELETE FROM x JOIN/USING (no WHERE)
        "name":     "DELETE without WHERE",
        "category": "HIGH",
        "message":  "DELETE without a WHERE clause removes ALL rows. Override required."
    },
    {
        "pattern":  r'\bUPDATE\s+[\w\.]+\s+SET\s+.+?(?:;|$)(?!.*\bWHERE\b)',
        "name":     "UPDATE without WHERE",
        "category": "HIGH",
        "message":  "UPDATE without WHERE updates EVERY row. Override required."
    },
]

MEDIUM_PATTERNS = [
    {
        "pattern":  r'\bDROP\s+COLUMN\b',
        "name":     "DROP COLUMN",
        "category": "MEDIUM",
        "message":  "Dropping a column permanently destroys data in that column.",
        "warn_only": True
    },
    {
        "pattern":  r'\bDROP\s+CONSTRAINT\b',
        "name":     "DROP CONSTRAINT",
        "category": "MEDIUM",
        "message":  "Dropping a constraint may allow invalid data to be inserted.",
        "warn_only": True
    },
    {
        "pattern":  r'\bGRANT\s+',
        "name":     "GRANT",
        "category": "MEDIUM",
        "message":  "GRANT statement modifies database permissions.",
        "warn_only": True
    },
    {
        "pattern":  r'\bREVOKE\s+',
        "name":     "REVOKE",
        "category": "MEDIUM",
        "message":  "REVOKE statement removes database permissions.",
        "warn_only": True
    },
]


# ── Main check function ──────────────────────────────────────────────────────

def check_sql_safety(sql: str,
                     allow_destructive: bool = False,
                     script_name: str = "script") -> dict:
    """
    Check a single SQL statement (or multi-statement) for dangerous operations.

    Args:
        sql:               The SQL to check
        allow_destructive: If True, dangerous patterns return as warnings, not blocks
        script_name:       Friendly name for error messages

    Returns:
        {
            "blocked":  bool,           # True = should NOT execute
            "violations": [             # all matches found
                {
                    "name":      "DROP TABLE without IF EXISTS",
                    "category":  "CRITICAL",
                    "message":   "...",
                    "snippet":   "the matched SQL fragment",
                    "blocks":    True
                }
            ],
            "warnings": [...]           # non-blocking notes
        }
    """
    if not sql or not isinstance(sql, str):
        return {"blocked": False, "violations": [], "warnings": []}

    # Strip comments and normalize whitespace for matching
    sql_norm = _strip_comments(sql)
    sql_upper = sql_norm.upper()

    violations = []
    warnings   = []

    # Check CRITICAL patterns
    for p in CRITICAL_PATTERNS:
        for match in re.finditer(p["pattern"], sql_upper, re.IGNORECASE | re.DOTALL):
            snippet = _get_snippet(sql_norm, match.start(), match.end())
            v = {
                "name":     p["name"],
                "category": p["category"],
                "message":  p["message"],
                "snippet":  snippet,
                "blocks":   not allow_destructive
            }
            if allow_destructive:
                warnings.append(v)
            else:
                violations.append(v)

    # Check HIGH patterns (need extra logic for DELETE/UPDATE - WHERE check)
    if not _has_where_clause(sql_norm):
        for p in HIGH_PATTERNS:
            for match in re.finditer(p["pattern"], sql_upper, re.IGNORECASE | re.DOTALL):
                snippet = _get_snippet(sql_norm, match.start(), match.end())
                v = {
                    "name":     p["name"],
                    "category": p["category"],
                    "message":  p["message"],
                    "snippet":  snippet,
                    "blocks":   not allow_destructive
                }
                if allow_destructive:
                    warnings.append(v)
                else:
                    violations.append(v)

    # Check MEDIUM patterns (always warn, never block)
    for p in MEDIUM_PATTERNS:
        for match in re.finditer(p["pattern"], sql_upper, re.IGNORECASE | re.DOTALL):
            snippet = _get_snippet(sql_norm, match.start(), match.end())
            warnings.append({
                "name":     p["name"],
                "category": p["category"],
                "message":  p["message"],
                "snippet":  snippet,
                "blocks":   False
            })

    blocked = len(violations) > 0

    return {
        "blocked":     blocked,
        "violations":  violations,
        "warnings":    warnings,
        "script_name": script_name,
        "summary":     _build_summary(violations, warnings, script_name, blocked)
    }


def check_pipeline_safety(scripts: list,
                          allow_destructive: bool = False) -> dict:
    """
    Check an entire pipeline's worth of SQL scripts.
    Returns aggregate result + per-script results.
    """
    all_blocked     = False
    all_violations  = []
    all_warnings    = []
    per_script      = []

    for s in scripts:
        sql  = s.get("sql", "")
        name = s.get("name", "unknown")
        result = check_sql_safety(sql, allow_destructive, script_name=name)
        per_script.append({
            "script_name": name,
            "blocked":     result["blocked"],
            "violations":  result["violations"],
            "warnings":    result["warnings"]
        })
        if result["blocked"]:
            all_blocked = True
        all_violations.extend(result["violations"])
        all_warnings.extend(result["warnings"])

    return {
        "blocked":           all_blocked,
        "total_violations":  len(all_violations),
        "total_warnings":    len(all_warnings),
        "violations":        all_violations,
        "warnings":          all_warnings,
        "per_script":        per_script,
        "message":           _build_pipeline_summary(all_blocked, all_violations, all_warnings)
    }


# ── Helper functions ─────────────────────────────────────────────────────────

def _strip_comments(sql: str) -> str:
    """Remove SQL comments to avoid false matches inside comments."""
    sql = re.sub(r'--[^\n]*', '', sql)
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql


def _has_where_clause(sql: str) -> bool:
    """Rough check — does the SQL contain a WHERE clause anywhere?"""
    return bool(re.search(r'\bWHERE\b', sql, re.IGNORECASE))


def _get_snippet(sql: str, start: int, end: int, context: int = 30) -> str:
    """Get a snippet showing the dangerous SQL fragment with context."""
    snippet_start = max(0, start - context)
    snippet_end   = min(len(sql), end + context)
    snippet = sql[snippet_start:snippet_end].strip()
    snippet = re.sub(r'\s+', ' ', snippet)
    if snippet_start > 0:
        snippet = "..." + snippet
    if snippet_end < len(sql):
        snippet = snippet + "..."
    return snippet[:200]


def _build_summary(violations: list, warnings: list,
                   script_name: str, blocked: bool) -> str:
    if blocked:
        return (f"🛑 BLOCKED: '{script_name}' contains "
                f"{len(violations)} dangerous operation(s) — "
                f"override required to proceed.")
    elif warnings:
        return (f"⚠ '{script_name}' has {len(warnings)} warning(s) — "
                f"review before execution.")
    else:
        return f"✓ '{script_name}' passed safety checks."


def _build_pipeline_summary(blocked: bool, violations: list, warnings: list) -> str:
    if blocked:
        names = ", ".join(set(v["name"] for v in violations))
        return (f"🛑 Pipeline BLOCKED — found {len(violations)} dangerous operation(s): {names}. "
                f"Set allow_destructive=True to override (and accept responsibility).")
    elif warnings:
        return f"⚠ Pipeline has {len(warnings)} warning(s) — review before execution."
    else:
        return "✓ Pipeline passed all safety checks."


# ── For standalone testing ───────────────────────────────────────────────────

if __name__ == "__main__":
    test_cases = [
        ("Safe DDL",
         "CREATE TABLE IF NOT EXISTS test (id INT);"),
        ("Safe DROP",
         "DROP TABLE IF EXISTS test;"),
        ("Dangerous DROP",
         "DROP TABLE test;"),
        ("Dangerous DELETE",
         "DELETE FROM customers;"),
        ("Safe DELETE",
         "DELETE FROM customers WHERE inactive = TRUE;"),
        ("TRUNCATE",
         "TRUNCATE TABLE staging.stg_orders;"),
        ("UPDATE without WHERE",
         "UPDATE customers SET status = 'active';"),
        ("Safe UPSERT",
         "INSERT INTO customers (id, name) VALUES (1, 'a') ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;"),
    ]

    print("=" * 70)
    print("SQL SAFETY GUARD — Test Results")
    print("=" * 70)
    for name, sql in test_cases:
        result = check_sql_safety(sql, script_name=name)
        status = "🛑 BLOCKED" if result["blocked"] else "✓ OK"
        print(f"\n{status} — {name}")
        print(f"  SQL: {sql[:80]}")
        if result["violations"]:
            for v in result["violations"]:
                print(f"  ✗ {v['name']}: {v['message']}")
        if result["warnings"]:
            for w in result["warnings"]:
                print(f"  ⚠ {w['name']}: {w['message']}")
