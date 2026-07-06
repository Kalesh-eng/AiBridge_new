"""
agents/migration_agent.py — AIBridge Migration Agent
Scans existing warehouse, reverse engineers data model,
parses mapping files (Informatica XML, dbt YML, SSIS, BRD).
"""
import re
import json
import psycopg2
import psycopg2.extras
from datetime import datetime
from ai_provider import ask_ai


def scan_warehouse(connection: dict, warehouse_schema: str = "warehouse", sub_mode: str = "reverse") -> dict:
    """
    Scan existing warehouse — discover all dim/fact tables,
    column types, row counts, FK relationships.
    Returns reverse data model.
    """
    try:
        conn = psycopg2.connect(
            host     = connection.get("host", "localhost"),
            port     = int(connection.get("port", 5432)),
            dbname   = connection.get("database", ""),
            user     = connection.get("username", ""),
            password = connection.get("password", "")
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Step 1: Discover all tables in warehouse schema
        cur.execute("""
            SELECT t.table_name,
                   pg_size_pretty(pg_total_relation_size(
                       quote_ident(t.table_schema)||'.'||quote_ident(t.table_name)
                   )) AS size
            FROM information_schema.tables t
            WHERE t.table_schema = %s
            AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_name
        """, (warehouse_schema,))
        all_tables = cur.fetchall()

        # Step 2: Get row counts and columns for each table
        tables = []
        all_columns = {}
        for tbl in all_tables:
            name = tbl["table_name"]
            # Get row count
            try:
                cur.execute(f'SELECT COUNT(*) as cnt FROM "{warehouse_schema}"."{name}"')
                row_count = cur.fetchone()["cnt"]
            except Exception:
                row_count = 0

            # Get columns
            cur.execute("""
                SELECT column_name, data_type, is_nullable,
                       character_maximum_length, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (warehouse_schema, name))
            cols = cur.fetchall()
            all_columns[name] = [dict(c) for c in cols]

            # Classify as dim or fact
            if name.startswith("dim_"):
                tbl_type = "dim"
            elif name.startswith("fact_"):
                tbl_type = "fact"
            else:
                tbl_type = "other"

            # Format row count
            if row_count >= 1_000_000:
                row_count_str = f"{row_count/1_000_000:.1f}M"
            elif row_count >= 1_000:
                row_count_str = f"{row_count/1_000:.0f}K"
            else:
                row_count_str = str(row_count)

            tables.append({
                "name":      name,
                "type":      tbl_type,
                "row_count": row_count_str,
                "columns":   [dict(c) for c in cur.fetchall()] if False else [dict(c) for c in cols],
                "size":      tbl["size"]
            })

        # Step 3: Get FK relationships
        cur.execute("""
            SELECT
                kcu.table_name AS from_table,
                kcu.column_name AS from_column,
                ccu.table_name AS to_table,
                ccu.column_name AS to_column
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = %s
        """, (warehouse_schema,))
        fk_relationships = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        # Step 4: AI analysis
        dim_tables  = [t for t in tables if t["type"] == "dim"]
        fact_tables = [t for t in tables if t["type"] == "fact"]

        schema_summary = f"Warehouse schema: {warehouse_schema}\n"
        schema_summary += f"Dimension tables ({len(dim_tables)}):\n"
        for t in dim_tables:
            cols = ", ".join(c["column_name"] for c in t["columns"][:8])
            schema_summary += f"  {t['name']} ({t['row_count']} rows): {cols}\n"
        schema_summary += f"\nFact tables ({len(fact_tables)}):\n"
        for t in fact_tables:
            cols = ", ".join(c["column_name"] for c in t["columns"][:8])
            schema_summary += f"  {t['name']} ({t['row_count']} rows): {cols}\n"

        ai_prompt = f"""You are a data warehouse expert. Analyze this existing warehouse schema and provide:
1. The business domain (retail, banking, healthcare, education, etc.)
2. A 2-3 sentence summary of what this warehouse tracks
3. Key KPIs that can be derived from this schema

WAREHOUSE SCHEMA:
{schema_summary}

Return ONLY valid JSON:
{{
  "domain": "retail",
  "summary": "2-3 sentence description",
  "kpis": ["KPI 1", "KPI 2", "KPI 3"],
  "coverage_estimate": 95
}}"""

        try:
            ai_result = ask_ai(ai_prompt, agent_name="MigrationAgent")
            domain   = ai_result.get("domain", "unknown")
            summary  = ai_result.get("summary", "")
            kpis     = ai_result.get("kpis", [])
            coverage = ai_result.get("coverage_estimate", 90)
        except Exception:
            domain   = "unknown"
            summary  = f"Warehouse with {len(dim_tables)} dimensions and {len(fact_tables)} fact tables."
            kpis     = []
            coverage = 90

        # Step 5: Build data dictionary
        dictionary = []
        for t in dim_tables + fact_tables:
            col_summary = ", ".join(c["column_name"] for c in t["columns"][:5])
            dictionary.append({
                "table":       t["name"],
                "type":        t["type"],
                "row_count":   t["row_count"],
                "description": f"{t['type'].capitalize()} table with {len(t['columns'])} columns. Key columns: {col_summary}."
            })

        return {
            "success":    True,
            "tables":     tables,
            "domain":     domain,
            "ai_summary": summary,
            "kpis":       kpis,
            "coverage":   coverage,
            "mappings":   [],   # populated when mapping files are uploaded
            "gaps":       [],   # populated after AI gap analysis
            "dictionary": dictionary,
            "fk_relationships": fk_relationships,
            "scanned_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"success": False, "error": str(e), "tables": []}


def parse_informatica_xml(xml_content: str) -> list:
    """Parse Informatica PowerCenter XML mapping file. Returns column mappings."""
    mappings = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_content)
        # Find all CONNECTOR elements (source → target mappings)
        for connector in root.iter("CONNECTOR"):
            mappings.append({
                "source": connector.get("FROMFIELD", ""),
                "target": connector.get("TOFIELD", ""),
                "transformation": connector.get("TRANSFORMATION", "direct"),
                "mapped": True
            })
    except Exception as e:
        print(f"[MigrationAgent] Informatica XML parse error: {e}")
    return mappings


def parse_dbt_yml(yml_content: str) -> list:
    """Parse dbt schema.yml file. Returns column mappings."""
    mappings = []
    try:
        import yaml
        data = yaml.safe_load(yml_content)
        for model in (data.get("models") or []):
            model_name = model.get("name", "")
            for col in (model.get("columns") or []):
                mappings.append({
                    "target": f"{model_name}.{col.get('name', '')}",
                    "source": col.get("name", ""),
                    "transformation": "direct",
                    "description": col.get("description", ""),
                    "mapped": True
                })
    except Exception as e:
        print(f"[MigrationAgent] dbt YML parse error: {e}")
    return mappings


def detect_gaps(tables: list, mappings: list) -> list:
    """
    Detect columns in warehouse tables that have no source mapping.
    Returns list of gaps with suggestions.
    """
    gaps = []
    mapped_targets = {m.get("target", "").lower() for m in mappings}

    for table in tables:
        for col in table.get("columns", []):
            col_name = col["column_name"]
            # Skip surrogate keys and system columns
            if col_name.endswith("_key") or col_name in (
                "loaded_at", "updated_at", "created_at", "period_id"
            ):
                continue
            full_name = f"{table['name']}.{col_name}".lower()
            if full_name not in mapped_targets and mappings:
                gaps.append({
                    "column": f"{table['name']}.{col_name}",
                    "table":  table["name"],
                    "reason": f"Column '{col_name}' has no source mapping. How was this derived?"
                })
    return gaps
