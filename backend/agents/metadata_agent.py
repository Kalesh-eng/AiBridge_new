"""
agents/migration_agent.py — AIBridge Migration Agent v2
Scans existing warehouse using universal connector (any DB type).
Parses mapping files: Informatica XML, dbt YML, SSIS, ODI, BRD.
"""
from datetime import datetime
from ai_provider import ask_ai


def scan_warehouse(connection: dict, warehouse_schema: str = "warehouse", sub_mode: str = "reverse") -> dict:
    """
    Scan existing warehouse — supports ANY database type via universal_connector.
    Discovers all dim/fact tables, columns, row counts, FK relationships.
    """
    from universal_connector import _pg_connect, _is_same_db

    connector_type = connection.get("connector_type", "postgres").lower()

    try:
        # ── Connect using appropriate driver ──────────────────────────────────
        if connector_type in ("postgres", "postgresql", "redshift"):
            import psycopg2, psycopg2.extras
            conn = psycopg2.connect(
                host     = connection.get("host", "localhost"),
                port     = int(connection.get("port", 5432)),
                dbname   = connection.get("database") or connection.get("database_name", ""),
                user     = connection.get("username", ""),
                password = connection.get("password", "")
            )
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            tables, all_columns, fk_relationships = _scan_postgres(cur, warehouse_schema)
            cur.close(); conn.close()

        elif connector_type in ("mysql", "mariadb"):
            from universal_connector import _mysql_connect
            conn = _mysql_connect(connection)
            cur  = conn.cursor(dictionary=True)
            tables, all_columns, fk_relationships = _scan_mysql(cur, warehouse_schema)
            cur.close(); conn.close()

        elif connector_type in ("sqlserver", "mssql", "azuresql"):
            from universal_connector import _sqlserver_connect
            conn = _sqlserver_connect(connection)
            cur  = conn.cursor()
            tables, all_columns, fk_relationships = _scan_sqlserver(cur, warehouse_schema)
            cur.close(); conn.close()

        elif connector_type == "snowflake":
            from universal_connector import _snowflake_connect
            conn = _snowflake_connect(connection)
            cur  = conn.cursor()
            tables, all_columns, fk_relationships = _scan_snowflake(cur, warehouse_schema)
            cur.close(); conn.close()

        elif connector_type == "bigquery":
            from universal_connector import _bigquery_connect
            client = _bigquery_connect(connection)
            tables, all_columns, fk_relationships = _scan_bigquery(client, warehouse_schema)

        else:
            return {"success": False, "error": f"Unsupported connector type: {connector_type}"}

        # ── AI analysis ───────────────────────────────────────────────────────
        dim_tables  = [t for t in tables if t["type"] == "dim"]
        fact_tables = [t for t in tables if t["type"] == "fact"]

        schema_summary = f"Warehouse: {warehouse_schema} ({connector_type})\n"
        schema_summary += f"Dimensions ({len(dim_tables)}):\n"
        for t in dim_tables:
            cols = ", ".join(c["column_name"] for c in t.get("columns", [])[:6])
            schema_summary += f"  {t['name']} ({t['row_count']} rows): {cols}\n"
        schema_summary += f"Facts ({len(fact_tables)}):\n"
        for t in fact_tables:
            cols = ", ".join(c["column_name"] for c in t.get("columns", [])[:6])
            schema_summary += f"  {t['name']} ({t['row_count']} rows): {cols}\n"

        try:
            ai_result = ask_ai(f"""You are a data warehouse expert. Analyze this warehouse schema.
Return ONLY valid JSON:
{{
  "domain": "retail",
  "summary": "2-3 sentence description of what this warehouse tracks",
  "kpis": ["KPI 1", "KPI 2", "KPI 3"],
  "coverage_estimate": 95
}}

WAREHOUSE SCHEMA:
{schema_summary}""", agent_name="MigrationAgent")
            domain   = ai_result.get("domain", "unknown")
            summary  = ai_result.get("summary", "")
            kpis     = ai_result.get("kpis", [])
            coverage = ai_result.get("coverage_estimate", 90)
        except Exception:
            domain   = "unknown"
            summary  = f"Warehouse with {len(dim_tables)} dimensions and {len(fact_tables)} fact tables."
            kpis     = []
            coverage = 90

        # ── Data dictionary ───────────────────────────────────────────────────
        dictionary = []
        for t in dim_tables + fact_tables:
            col_summary = ", ".join(c["column_name"] for c in t.get("columns", [])[:5])
            dictionary.append({
                "table":       t["name"],
                "type":        t["type"],
                "row_count":   t["row_count"],
                "description": f"{t['type'].capitalize()} table with {len(t.get('columns', []))} columns. Key columns: {col_summary}."
            })

        return {
            "success":          True,
            "tables":           tables,
            "domain":           domain,
            "ai_summary":       summary,
            "kpis":             kpis,
            "coverage":         coverage,
            "mappings":         [],
            "gaps":             [],
            "dictionary":       dictionary,
            "fk_relationships": fk_relationships,
            "connector_type":   connector_type,
            "scanned_at":       datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"success": False, "error": str(e), "tables": []}


def _format_row_count(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}K"
    return str(n)


def _classify_table(name):
    if name.lower().startswith("dim_"):  return "dim"
    if name.lower().startswith("fact_"): return "fact"
    return "other"


def _scan_postgres(cur, schema):
    """Scan PostgreSQL/Redshift warehouse."""
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (schema,))
    table_names = [r["table_name"] for r in cur.fetchall()]

    tables = []
    all_columns = {}
    for name in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) as cnt FROM "{schema}"."{name}"')
            row_count = cur.fetchone()["cnt"]
        except Exception:
            row_count = 0

        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, name))
        cols = [dict(c) for c in cur.fetchall()]
        all_columns[name] = cols

        tables.append({
            "name":      name,
            "type":      _classify_table(name),
            "row_count": _format_row_count(row_count),
            "columns":   cols
        })

    cur.execute("""
        SELECT kcu.table_name AS from_table, kcu.column_name AS from_column,
               ccu.table_name AS to_table, ccu.column_name AS to_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s
    """, (schema,))
    fks = [dict(r) for r in cur.fetchall()]
    return tables, all_columns, fks


def _scan_mysql(cur, schema):
    """Scan MySQL/MariaDB warehouse."""
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (schema,))
    table_names = [r["table_name"] for r in cur.fetchall()]

    tables = []
    all_columns = {}
    for name in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) as cnt FROM `{schema}`.`{name}`')
            row_count = cur.fetchone()["cnt"]
        except Exception:
            row_count = 0

        cur.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, name))
        cols = [dict(c) for c in cur.fetchall()]
        all_columns[name] = cols
        tables.append({"name": name, "type": _classify_table(name), "row_count": _format_row_count(row_count), "columns": cols})

    return tables, all_columns, []


def _scan_sqlserver(cur, schema):
    """Scan SQL Server/Azure SQL warehouse."""
    cur.execute(f"""
        SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = '{schema}' AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)
    table_names = [r[0] for r in cur.fetchall()]

    tables = []
    all_columns = {}
    for name in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) FROM [{schema}].[{name}]')
            row_count = cur.fetchone()[0]
        except Exception:
            row_count = 0

        cur.execute(f"""
            SELECT COLUMN_NAME as column_name, DATA_TYPE as data_type, IS_NULLABLE as is_nullable
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{name}'
            ORDER BY ORDINAL_POSITION
        """)
        cols = [{"column_name": r[0], "data_type": r[1], "is_nullable": r[2]} for r in cur.fetchall()]
        all_columns[name] = cols
        tables.append({"name": name, "type": _classify_table(name), "row_count": _format_row_count(row_count), "columns": cols})

    return tables, all_columns, []


def _scan_snowflake(cur, schema):
    """Scan Snowflake warehouse."""
    cur.execute(f"SHOW TABLES IN SCHEMA {schema}")
    table_names = [r[1] for r in cur.fetchall()]

    tables = []
    all_columns = {}
    for name in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{name}"')
            row_count = cur.fetchone()[0]
        except Exception:
            row_count = 0

        cur.execute(f'DESCRIBE TABLE "{schema}"."{name}"')
        cols = [{"column_name": r[0], "data_type": r[1], "is_nullable": r[3]} for r in cur.fetchall()]
        all_columns[name] = cols
        tables.append({"name": name, "type": _classify_table(name), "row_count": _format_row_count(row_count), "columns": cols})

    return tables, all_columns, []


def _scan_bigquery(client, schema):
    """Scan BigQuery warehouse."""
    tables = []
    all_columns = {}
    dataset = client.get_dataset(schema)
    for tbl_ref in client.list_tables(dataset):
        name = tbl_ref.table_id
        try:
            tbl = client.get_table(tbl_ref)
            row_count = tbl.num_rows
            cols = [{"column_name": f.name, "data_type": f.field_type, "is_nullable": f.mode != "REQUIRED"} for f in tbl.schema]
        except Exception:
            row_count = 0; cols = []
        all_columns[name] = cols
        tables.append({"name": name, "type": _classify_table(name), "row_count": _format_row_count(row_count), "columns": cols})

    return tables, all_columns, []


def parse_informatica_xml(xml_content: str) -> list:
    """Parse Informatica PowerCenter XML — supports both individual mapping and repository XML."""
    mappings = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_content)

        # Repository XML — iterate all mappings
        for mapping in root.iter("MAPPING"):
            mapping_name = mapping.get("NAME", "")
            # Find target table
            targets = [t.get("NAME", "") for t in mapping.iter("TARGET")]
            target = targets[0] if targets else mapping_name

            # Get transformations (expressions)
            for transform in mapping.iter("TRANSFORMATION"):
                t_type = transform.get("TYPE", "")
                for field in transform.iter("TRANSFORMFIELD"):
                    src  = field.get("INPUTPORTS", field.get("NAME", ""))
                    tgt  = field.get("NAME", "")
                    expr = field.get("EXPRESSION", "direct")
                    if tgt:
                        mappings.append({
                            "target":         f"{target}.{tgt}",
                            "source":         src,
                            "transformation": expr if expr != tgt else "direct",
                            "mapping":        mapping_name,
                            "mapped":         bool(src)
                        })

            # Fallback: CONNECTOR elements
            for connector in mapping.iter("CONNECTOR"):
                mappings.append({
                    "target":         connector.get("TOFIELD", ""),
                    "source":         connector.get("FROMFIELD", ""),
                    "transformation": "direct",
                    "mapping":        mapping_name,
                    "mapped":         True
                })

    except Exception as e:
        print(f"[MigrationAgent] Informatica XML parse error: {e}")
    return mappings


def parse_dbt_yml(yml_content: str) -> list:
    """Parse dbt schema.yml file."""
    mappings = []
    try:
        import yaml
        data = yaml.safe_load(yml_content)
        for model in (data.get("models") or []):
            model_name = model.get("name", "")
            for col in (model.get("columns") or []):
                mappings.append({
                    "target":         f"{model_name}.{col.get('name', '')}",
                    "source":         col.get("name", ""),
                    "transformation": "direct",
                    "description":    col.get("description", ""),
                    "mapped":         True
                })
    except Exception as e:
        print(f"[MigrationAgent] dbt YML parse error: {e}")
    return mappings


def detect_gaps(tables: list, mappings: list) -> list:
    """Detect columns with no source mapping."""
    gaps = []
    mapped_targets = {m.get("target", "").lower() for m in mappings}
    skip_cols = {"loaded_at", "updated_at", "created_at", "period_id"}

    for table in tables:
        for col in table.get("columns", []):
            col_name = col["column_name"]
            if col_name.endswith("_key") or col_name in skip_cols:
                continue
            full_name = f"{table['name']}.{col_name}".lower()
            if full_name not in mapped_targets and mappings:
                gaps.append({
                    "column": f"{table['name']}.{col_name}",
                    "table":  table["name"],
                    "reason": f"Column '{col_name}' has no source mapping. How was this derived?"
                })
    return gaps