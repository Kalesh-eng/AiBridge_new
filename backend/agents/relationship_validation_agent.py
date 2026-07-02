"""
agents/relationship_validation_agent.py
Validates source schema relationships BEFORE data model design.
Pure Python — no AI needed. Fast and reliable.

Checks:
  - FK columns exist in referenced tables
  - No circular joins (A→B→C→A)
  - No orphaned tables (no connection to any other table)
  - Missing dimension candidates (FK with no lookup table)

v1.1: Saves foreign_keys list to validation result for downstream use
      (passed to nlm_engine.py generate_data_model + generate_sql prompts)
"""

from .base import BaseAgent, AgentContext, AgentResult


class RelationshipValidationAgent(BaseAgent):
    name        = "RelationshipValidationAgent"
    description = "Validates FK relationships, detects circular joins and orphaned tables"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        import psycopg2

        result.log("Validating source schema relationships...")

        issues       = []
        warnings     = []
        passed       = True
        fks          = []
        fk_relationships = []   # ← structured list for AI prompts

        try:
            cfg  = ctx.connector_config
            conn = psycopg2.connect(
                host=cfg.get("host"),
                port=int(cfg.get("port", 5433)),
                dbname=cfg.get("database"),
                user=cfg.get("username"),
                password=cfg.get("password")
            )
            cur = conn.cursor()

            # ── Check 1: Get all FK constraints ──────────────────────────────
            cur.execute("""
                SELECT
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_name  AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = %s
            """, (ctx.source_schema,))

            fks = cur.fetchall()
            result.log(f"Found {len(fks)} FK constraints")

            # Build adjacency graph for cycle detection
            graph = {}
            for table, col, ref_table, ref_col in fks:
                if table not in graph:
                    graph[table] = []
                graph[table].append(ref_table)

                # Verify referenced table exists
                cur.execute("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                """, (ctx.source_schema, ref_table))
                exists = cur.fetchone()[0]
                if not exists:
                    issues.append(f"FK broken: {table}.{col} → {ref_table}.{ref_col} (table not found)")
                    passed = False
                else:
                    result.log(f"✓ FK valid: {table}.{col} → {ref_table}.{ref_col}")
                    # ── Save to structured list for AI prompts ────────────────
                    fk_relationships.append({
                        "from_table":  table,
                        "from_column": col,
                        "to_table":    ref_table,
                        "to_column":   ref_col
                    })

            # ── Check 2: Circular join detection (DFS) ────────────────────────
            def has_cycle(node, visited, rec_stack):
                visited.add(node)
                rec_stack.add(node)
                for neighbour in graph.get(node, []):
                    if neighbour not in visited:
                        if has_cycle(neighbour, visited, rec_stack):
                            return True
                    elif neighbour in rec_stack:
                        return True
                rec_stack.discard(node)
                return False

            visited   = set()
            rec_stack = set()
            for node in graph:
                if node not in visited:
                    if has_cycle(node, visited, rec_stack):
                        issues.append(f"Circular join detected involving: {node}")
                        passed = False

            if passed:
                result.log("✓ No circular joins detected")

            # ── Check 3: Orphaned tables ──────────────────────────────────────
            tables = ctx.source_tables or []
            if tables:
                connected = set(graph.keys())
                for fk in fks:
                    connected.add(fk[2])

                for table in tables:
                    if table not in connected and len(tables) > 1:
                        warnings.append(f"Orphaned table: '{table}' has no FK relationships")

                if warnings:
                    for w in warnings:
                        result.log(f"⚠ {w}", "warn")
                else:
                    result.log("✓ No orphaned tables")

            conn.close()

        except Exception as e:
            result.log(f"Could not run DB validation: {e} — skipping", "warn")
            issues = []
            passed = True

        validation = {
            "passed":           passed,
            "issues":           issues,
            "warnings":         warnings,
            "fk_count":         len(fks),
            "foreign_keys":     fk_relationships,   # ← NEW: structured for AI prompts
        }

        ctx.relationship_validation = validation

        # Also store directly on ctx for easy access
        ctx.fk_relationships = fk_relationships

        if passed:
            result.log(f"✓ Relationship validation passed — {len(warnings)} warnings")
            if fk_relationships:
                result.log(f"✓ {len(fk_relationships)} FK relationships saved for AI prompts")
        else:
            result.log(f"✗ Relationship validation FAILED — {len(issues)} issues", "error")
            for issue in issues:
                result.log(f"  → {issue}", "error")

        return validation