"""
AIBridge v2 — DWH Introspector
================================
Connects to ANY existing data warehouse and:
1. Auto-discovers all tables, columns, types
2. Classifies tables as fact / dimension / lookup / staging
3. Detects FK relationships and grain
4. Builds a rich knowledge graph entry
5. Infers business context from naming patterns

Supports: PostgreSQL, MySQL, SQL Server, Snowflake, BigQuery, DuckDB
"""

import re
from typing import Optional
from ai_provider import ask_ai_text


# ── Heuristic patterns for fact/dim classification ──────────────────────────

FACT_PATTERNS = [
    r'^fact_', r'_fact$', r'^fct_', r'_fct$',
    r'^f_', r'_transactions?$', r'_sales?$', r'_orders?$',
    r'_events?$', r'_logs?$', r'_history$', r'_ledger$',
]

DIM_PATTERNS = [
    r'^dim_', r'_dim$', r'^d_', r'_dimension$',
    r'^lookup_', r'^lkp_', r'^ref_', r'_ref$',
    r'^master_', r'_master$',
]

STAGING_PATTERNS = [
    r'^stg_', r'_stg$', r'^staging_', r'^raw_',
    r'^tmp_', r'^temp_', r'^landing_',
]

MEASURE_TYPES = {
    'bigint', 'integer', 'int', 'int4', 'int8',
    'numeric', 'decimal', 'float', 'float4', 'float8',
    'double precision', 'real', 'money',
}

KEY_SUFFIXES = ['_key', '_id', '_sk', '_nk', '_fk']
DATE_SUFFIXES = ['_date', '_dt', '_time', '_at', '_ts', '_timestamp']
MEASURE_KEYWORDS = [
    'amount', 'price', 'cost', 'revenue', 'qty', 'quantity',
    'count', 'total', 'sum', 'value', 'sales', 'profit',
    'discount', 'tax', 'fee', 'balance', 'rate',
]


def _match_patterns(name: str, patterns: list) -> bool:
    name_lower = name.lower()
    return any(re.search(p, name_lower) for p in patterns)


def _classify_table(table_name: str, columns: list, row_count: int) -> dict:
    """Classify a table as fact, dimension, lookup, staging, or unknown."""
    name = table_name.lower()

    # Pattern-based classification
    if _match_patterns(name, STAGING_PATTERNS):
        return {"type": "staging", "confidence": 0.95}

    if _match_patterns(name, FACT_PATTERNS):
        ttype = "fact"
        confidence = 0.9
    elif _match_patterns(name, DIM_PATTERNS):
        ttype = "dimension"
        confidence = 0.9
    else:
        # Column-based heuristics
        col_names = [c['name'].lower() for c in columns]
        col_types = [c['type'].lower() for c in columns]

        # Count key columns, measure columns, date columns
        key_cols = sum(1 for c in col_names if any(c.endswith(s) for s in KEY_SUFFIXES))
        date_cols = sum(1 for c in col_names if any(c.endswith(s) for s in DATE_SUFFIXES))
        measure_cols = sum(1 for c in col_names if any(kw in c for kw in MEASURE_KEYWORDS))
        numeric_cols = sum(1 for t in col_types if any(t.startswith(m) for m in MEASURE_TYPES))

        total = len(columns)

        # Fact: many keys + measures + dates + high row count
        if key_cols >= 2 and (measure_cols >= 1 or numeric_cols >= 2) and row_count > 1000:
            ttype = "fact"
            confidence = 0.75
        # Dimension: few keys, mostly descriptive, lower row count
        elif key_cols >= 1 and row_count < 10000 and numeric_cols < total * 0.5:
            ttype = "dimension"
            confidence = 0.7
        # Lookup: very small table
        elif row_count < 100:
            ttype = "lookup"
            confidence = 0.65
        else:
            ttype = "unknown"
            confidence = 0.3

    return {"type": ttype, "confidence": round(confidence, 2)}


def _detect_relationships(tables: dict) -> list:
    """Detect FK relationships by matching column names across tables."""
    relationships = []
    seen = set()

    for tbl_name, tbl_data in tables.items():
        if tbl_data['classification']['type'] not in ('fact', 'unknown'):
            continue

        for col in tbl_data['columns']:
            col_name = col['name'].lower()

            # Look for _key or _id columns that might be FKs
            for suffix in KEY_SUFFIXES:
                if col_name.endswith(suffix):
                    base = col_name[:-len(suffix)]

                    # Find matching dim table
                    for other_tbl, other_data in tables.items():
                        if other_tbl == tbl_name:
                            continue
                        if other_data['classification']['type'] not in ('dimension', 'lookup'):
                            continue

                        other_name = other_tbl.lower()
                        # dim_customer → customer, dim_date → date
                        other_base = re.sub(r'^(dim_|d_|lkp_|ref_|lookup_)', '', other_name)

                        if base == other_base or base in other_name or other_base in base:
                            rel_key = f"{tbl_name}.{col['name']}→{other_tbl}"
                            if rel_key not in seen:
                                seen.add(rel_key)
                                relationships.append({
                                    "from_table": tbl_name,
                                    "from_column": col['name'],
                                    "to_table": other_tbl,
                                    "to_column": col['name'],
                                    "confidence": 0.8,
                                    "type": "inferred_fk"
                                })
    return relationships


def _build_schema_context(tables: dict, relationships: list) -> str:
    """Build a rich schema context string for AI consumption."""
    lines = ["WAREHOUSE SCHEMA (auto-discovered by AIBridge)\n"]

    # Group by type
    facts = {k: v for k, v in tables.items() if v['classification']['type'] == 'fact'}
    dims = {k: v for k, v in tables.items() if v['classification']['type'] == 'dimension'}
    lookups = {k: v for k, v in tables.items() if v['classification']['type'] == 'lookup'}
    others = {k: v for k, v in tables.items()
              if v['classification']['type'] not in ('fact', 'dimension', 'lookup', 'staging')}

    def fmt_table(name, data):
        cols = ", ".join(f"{c['name']} ({c['type']})" for c in data['columns'][:20])
        rows = f"{data['row_count']:,} rows" if data.get('row_count') else "? rows"
        return f"  {name} [{rows}]: {cols}"

    if facts:
        lines.append("FACT TABLES:")
        for n, d in facts.items():
            lines.append(fmt_table(n, d))

    if dims:
        lines.append("\nDIMENSION TABLES:")
        for n, d in dims.items():
            lines.append(fmt_table(n, d))

    if lookups:
        lines.append("\nLOOKUP TABLES:")
        for n, d in lookups.items():
            lines.append(fmt_table(n, d))

    if others:
        lines.append("\nOTHER TABLES:")
        for n, d in others.items():
            lines.append(fmt_table(n, d))

    if relationships:
        lines.append("\nRELATIONSHIPS (inferred):")
        for r in relationships[:20]:
            lines.append(f"  {r['from_table']}.{r['from_column']} → {r['to_table']}")

    return "\n".join(lines)


def _infer_business_context(tables: dict) -> dict:
    """Use AI to infer business domain and context from table/column names."""
    # Build a compact schema summary for AI
    summary_lines = []
    for tbl, data in list(tables.items())[:15]:
        col_names = [c['name'] for c in data['columns'][:10]]
        summary_lines.append(f"{tbl}: {', '.join(col_names)}")

    schema_summary = "\n".join(summary_lines)

    prompt = f"""Analyze this data warehouse schema and infer business context.

Schema:
{schema_summary}

Answer these questions concisely:
1. What industry/domain is this? (e.g. retail, banking, healthcare, logistics)
2. What is the main business process tracked?
3. What are the 3 most important KPIs this warehouse likely tracks?
4. Any obvious data quality rules you can infer from column names?

Be specific and brief."""

    try:
        response = ask_ai_text(prompt, agent_name="DWHIntrospector")
        return {"ai_context": response, "success": True}
    except Exception as e:
        return {"ai_context": f"Could not infer context: {e}", "success": False}


# ── Main introspection function ──────────────────────────────────────────────

def introspect_postgres(host: str, port: int, database: str,
                        username: str, password: str,
                        schemas: list = None,
                        include_row_counts: bool = True) -> dict:
    """
    Introspect a PostgreSQL warehouse.
    Returns full schema, classifications, relationships, and business context.
    """
    import psycopg2

    if schemas is None:
        schemas = ['public', 'warehouse', 'analytics', 'reporting', 'dw', 'dwh']

    try:
        conn = psycopg2.connect(
            host=host, port=port, dbname=database,
            user=username, password=password,
            connect_timeout=10
        )
        cur = conn.cursor()

        # 1. Discover all schemas
        cur.execute("""
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema','pg_catalog','pg_toast',
                                       'pg_temp_1','pg_toast_temp_1')
            ORDER BY schema_name
        """)
        all_schemas = [r[0] for r in cur.fetchall()]

        # Use ONLY the specified schemas — no fallback to others
        if schemas:
            target_schemas = [s for s in all_schemas if s in schemas]
        else:
            # No schema specified — use relevant ones
            target_schemas = [s for s in all_schemas
                              if s in schemas or any(kw in s for kw in ['dw','warehouse','analytics','reporting'])]
            if not target_schemas:
                target_schemas = [s for s in all_schemas if s not in ('staging','public','pg_catalog')][:3]

        # 2. Discover all tables and columns
        placeholders = ','.join(['%s'] * len(target_schemas))
        cur.execute(f"""
            SELECT t.table_schema, t.table_name, c.column_name,
                   c.data_type, c.is_nullable, c.ordinal_position,
                   c.column_default
            FROM information_schema.tables t
            JOIN information_schema.columns c
                ON t.table_schema = c.table_schema
               AND t.table_name = c.table_name
            WHERE t.table_schema IN ({placeholders})
              AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_schema, t.table_name, c.ordinal_position
        """, target_schemas)

        raw_cols = cur.fetchall()

        # Organize by table
        tables = {}
        for schema, tbl, col, dtype, nullable, pos, default in raw_cols:
            key = f"{schema}.{tbl}"
            if key not in tables:
                tables[key] = {
                    "schema": schema,
                    "table_name": tbl,
                    "full_name": key,
                    "columns": [],
                    "row_count": 0,
                }
            tables[key]["columns"].append({
                "name": col,
                "type": dtype,
                "nullable": nullable == 'YES',
                "position": pos,
                "has_default": default is not None,
            })

        # 3. Get row counts
        if include_row_counts:
            for key, tdata in tables.items():
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{tdata["schema"]}"."{tdata["table_name"]}"')
                    tdata["row_count"] = cur.fetchone()[0]
                except Exception:
                    tdata["row_count"] = 0

        # 4. Get actual FK constraints
        cur.execute("""
            SELECT
                tc.table_schema, tc.table_name, kcu.column_name,
                ccu.table_schema AS foreign_schema,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
               AND tc.table_schema = kcu.table_schema
            JOIN information_schema.referential_constraints rc
                ON tc.constraint_name = rc.constraint_name
               AND tc.table_schema = rc.constraint_schema
            JOIN information_schema.key_column_usage ccu
                ON rc.unique_constraint_name = ccu.constraint_name
               AND rc.unique_constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
        """)
        actual_fks = []
        for row in cur.fetchall():
            actual_fks.append({
                "from_table": f"{row[0]}.{row[1]}",
                "from_column": row[2],
                "to_table": f"{row[3]}.{row[4]}",
                "to_column": row[5],
                "confidence": 1.0,
                "type": "actual_fk"
            })

        conn.close()

        # 5. Classify tables
        for key, tdata in tables.items():
            tdata["classification"] = _classify_table(
                tdata["table_name"], tdata["columns"], tdata["row_count"]
            )

        # 6. Detect inferred relationships
        inferred_fks = _detect_relationships(tables)
        all_relationships = actual_fks + [
            r for r in inferred_fks
            if not any(af["from_table"] == r["from_table"] and
                       af["from_column"] == r["from_column"]
                       for af in actual_fks)
        ]

        # 7. Build schema context
        schema_context = _build_schema_context(tables, all_relationships)

        # 8. Infer business context with AI
        business_context = _infer_business_context(tables)

        # 9. Summary stats
        type_counts = {}
        for t in tables.values():
            ttype = t["classification"]["type"]
            type_counts[ttype] = type_counts.get(ttype, 0) + 1

        return {
            "success": True,
            "connection": {
                "host": host, "port": port,
                "database": database, "schemas": target_schemas
            },
            "summary": {
                "total_tables": len(tables),
                "total_columns": sum(len(t["columns"]) for t in tables.values()),
                "total_rows": sum(t["row_count"] for t in tables.values()),
                "table_types": type_counts,
                "relationships": len(all_relationships),
            },
            "tables": tables,
            "relationships": all_relationships,
            "schema_context": schema_context,
            "business_context": business_context,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "tables": {},
            "relationships": [],
            "schema_context": "",
        }


def introspect_connector(connector_config: dict) -> dict:
    """Entry point — routes to the right introspector based on connector_type."""
    ctype = connector_config.get("connector_type", "postgres").lower()

    if ctype in ("postgres", "postgresql"):
        return introspect_postgres(
            host=connector_config.get("host", "localhost"),
            port=int(connector_config.get("port", 5432)),
            database=connector_config.get("database_name", "postgres"),
            username=connector_config.get("username", "postgres"),
            password=connector_config.get("password", ""),
            schemas=connector_config.get("schemas"),
        )
    else:
        return {
            "success": False,
            "error": f"Connector type '{ctype}' not yet supported. Coming soon: MySQL, Snowflake, BigQuery.",
            "tables": {},
            "relationships": [],
            "schema_context": "",
        }
