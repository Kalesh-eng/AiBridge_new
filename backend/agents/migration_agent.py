"""
agents/migration_agent.py — AIBridge Migration Agent
Scans an existing warehouse of any supported type (PostgreSQL, MySQL/MariaDB,
SQL Server, Snowflake, BigQuery, Redshift, Oracle), reverse engineers the
data model, and parses mapping files (Informatica XML, dbt YML, SSIS, BRD).

DB drivers are imported lazily inside each adapter function below, so
AIBridge doesn't hard-require every warehouse driver to be installed —
only whichever ones you actually connect to. Missing-driver errors surface
as a clear "pip install X" message rather than an ImportError at module load.
"""
import re
import json
from datetime import datetime
from ai_provider import ask_ai


def _format_row_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def _classify_table(name: str) -> str:
    lname = name.lower()
    if lname.startswith("dim_"):
        return "dim"
    elif lname.startswith("fact_"):
        return "fact"
    return "other"


# ── Per-database introspection adapters ─────────────────────────────────────
# Each adapter takes (connection: dict, warehouse_schema: str) and returns:
#   {"raw_tables": [{"name", "columns": [{"column_name", "data_type",
#                     "is_nullable", "character_maximum_length",
#                     "numeric_precision", "numeric_scale"}, ...],
#                    "row_count": int, "size": str|None}, ...],
#    "fk_relationships": [{"from_table", "from_column", "to_table", "to_column"}, ...]}
#
# All adapters normalize column dict keys to this same lowercase shape
# regardless of what casing the underlying driver returns, so everything
# downstream (classification, AI summary, dictionary, gap detection) stays
# completely DB-agnostic.

def _introspect_postgres(connection: dict, warehouse_schema: str) -> dict:
    """PostgreSQL. Also used for Redshift, which is wire-compatible."""
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(
        host=connection.get("host", "localhost"),
        port=int(connection.get("port", 5432)),
        dbname=connection.get("database", ""),
        user=connection.get("username", ""),
        password=connection.get("password", "")
    )
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (warehouse_schema,))
    table_names = [r["table_name"] for r in cur.fetchall()]

    raw_tables = []
    for name in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) as cnt FROM "{warehouse_schema}"."{name}"')
            row_count = cur.fetchone()["cnt"]
        except Exception:
            row_count = 0

        size = None
        try:
            cur.execute("""
                SELECT pg_size_pretty(pg_total_relation_size(
                    quote_ident(%s)||'.'||quote_ident(%s)
                )) AS size
            """, (warehouse_schema, name))
            size = cur.fetchone()["size"]
        except Exception:
            pass

        cur.execute("""
            SELECT column_name, data_type, is_nullable,
                   character_maximum_length, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (warehouse_schema, name))
        columns = [dict(c) for c in cur.fetchall()]

        raw_tables.append({"name": name, "columns": columns, "row_count": row_count, "size": size})

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
    return {"raw_tables": raw_tables, "fk_relationships": fk_relationships}


def _introspect_mysql(connection: dict, warehouse_schema: str) -> dict:
    """MySQL / MariaDB. `warehouse_schema` falls back to the connected
    database name, since MySQL treats schema and database as the same thing."""
    try:
        import pymysql
        import pymysql.cursors
    except ImportError:
        raise RuntimeError("MySQL support requires the 'pymysql' package — run: pip install pymysql")

    database = connection.get("database", "")
    schema = warehouse_schema or database

    conn = pymysql.connect(
        host=connection.get("host", "localhost"),
        port=int(connection.get("port", 3306)),
        db=database,
        user=connection.get("username", ""),
        password=connection.get("password", ""),
        cursorclass=pymysql.cursors.DictCursor
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name AS table_name FROM information_schema.tables
        WHERE table_schema = %s AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (schema,))
    table_names = [r["table_name"] for r in cur.fetchall()]

    raw_tables = []
    for name in table_names:
        try:
            cur.execute(f"SELECT COUNT(*) as cnt FROM `{schema}`.`{name}`")
            row_count = cur.fetchone()["cnt"]
        except Exception:
            row_count = 0

        size = None
        try:
            cur.execute("""
                SELECT ROUND((data_length + index_length) / 1024 / 1024, 2) AS size_mb
                FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            """, (schema, name))
            row = cur.fetchone()
            if row and row.get("size_mb") is not None:
                size = f"{row['size_mb']} MB"
        except Exception:
            pass

        cur.execute("""
            SELECT column_name AS column_name, data_type AS data_type,
                   is_nullable AS is_nullable,
                   character_maximum_length AS character_maximum_length,
                   numeric_precision AS numeric_precision,
                   numeric_scale AS numeric_scale
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, name))
        columns = list(cur.fetchall())

        raw_tables.append({"name": name, "columns": columns, "row_count": row_count, "size": size})

    fk_relationships = []
    try:
        cur.execute("""
            SELECT
                table_name AS from_table,
                column_name AS from_column,
                referenced_table_name AS to_table,
                referenced_column_name AS to_column
            FROM information_schema.key_column_usage
            WHERE table_schema = %s AND referenced_table_name IS NOT NULL
        """, (schema,))
        fk_relationships = list(cur.fetchall())
    except Exception:
        pass

    cur.close()
    conn.close()
    return {"raw_tables": raw_tables, "fk_relationships": fk_relationships}


def _introspect_sqlserver(connection: dict, warehouse_schema: str) -> dict:
    try:
        import pyodbc
    except ImportError:
        raise RuntimeError("SQL Server support requires the 'pyodbc' package (plus a system ODBC driver) — run: pip install pyodbc")

    driver = connection.get("odbc_driver", "ODBC Driver 17 for SQL Server")
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={connection.get('host', 'localhost')},{connection.get('port', 1433)};"
        f"DATABASE={connection.get('database', '')};"
        f"UID={connection.get('username', '')};PWD={connection.get('password', '')}"
    )
    conn = pyodbc.connect(conn_str)
    cur = conn.cursor()
    schema = warehouse_schema or "dbo"

    cur.execute("""
        SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """, schema)
    table_names = [r[0] for r in cur.fetchall()]

    raw_tables = []
    for name in table_names:
        try:
            cur.execute(f"SELECT COUNT(*) FROM [{schema}].[{name}]")
            row_count = cur.fetchone()[0]
        except Exception:
            row_count = 0

        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
                   CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, schema, name)
        columns = [{
            "column_name": r[0], "data_type": r[1], "is_nullable": r[2],
            "character_maximum_length": r[3], "numeric_precision": r[4], "numeric_scale": r[5]
        } for r in cur.fetchall()]

        raw_tables.append({"name": name, "columns": columns, "row_count": row_count, "size": None})

    fk_relationships = []
    try:
        cur.execute("""
            SELECT
                fk_tab.TABLE_NAME AS from_table,
                fk_col.COLUMN_NAME AS from_column,
                pk_tab.TABLE_NAME AS to_table,
                pk_col.COLUMN_NAME AS to_column
            FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
            JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS fk_tab
                ON rc.CONSTRAINT_NAME = fk_tab.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS pk_tab
                ON rc.UNIQUE_CONSTRAINT_NAME = pk_tab.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE fk_col
                ON rc.CONSTRAINT_NAME = fk_col.CONSTRAINT_NAME
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE pk_col
                ON rc.UNIQUE_CONSTRAINT_NAME = pk_col.CONSTRAINT_NAME
                AND pk_col.ORDINAL_POSITION = fk_col.ORDINAL_POSITION
            WHERE fk_tab.TABLE_SCHEMA = ?
        """, schema)
        fk_relationships = [{
            "from_table": r[0], "from_column": r[1], "to_table": r[2], "to_column": r[3]
        } for r in cur.fetchall()]
    except Exception:
        pass

    cur.close()
    conn.close()
    return {"raw_tables": raw_tables, "fk_relationships": fk_relationships}


def _introspect_snowflake(connection: dict, warehouse_schema: str) -> dict:
    try:
        import snowflake.connector
    except ImportError:
        raise RuntimeError("Snowflake support requires the 'snowflake-connector-python' package — run: pip install snowflake-connector-python")

    schema = (warehouse_schema or "PUBLIC").upper()
    database = connection.get("database", "").upper()

    conn = snowflake.connector.connect(
        account=connection.get("account", ""),
        user=connection.get("username", ""),
        password=connection.get("password", ""),
        warehouse=connection.get("warehouse", ""),
        database=database,
        schema=schema
    )
    cur = conn.cursor(snowflake.connector.DictCursor)

    cur.execute(f"""
        SELECT TABLE_NAME FROM {database}.INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """, (schema,))
    table_names = [r["TABLE_NAME"] for r in cur.fetchall()]

    raw_tables = []
    for name in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) AS CNT FROM "{database}"."{schema}"."{name}"')
            row_count = cur.fetchone()["CNT"]
        except Exception:
            row_count = 0

        cur.execute(f"""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
                   CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
            FROM {database}.INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (schema, name))
        columns = [{
            "column_name": r["COLUMN_NAME"], "data_type": r["DATA_TYPE"],
            "is_nullable": r["IS_NULLABLE"],
            "character_maximum_length": r["CHARACTER_MAXIMUM_LENGTH"],
            "numeric_precision": r["NUMERIC_PRECISION"], "numeric_scale": r["NUMERIC_SCALE"]
        } for r in cur.fetchall()]

        raw_tables.append({"name": name, "columns": columns, "row_count": row_count, "size": None})

    cur.close()
    conn.close()
    # Snowflake doesn't enforce FKs in a way that's reliably introspectable
    # via INFORMATION_SCHEMA — skip rather than guess.
    return {"raw_tables": raw_tables, "fk_relationships": []}


def _introspect_bigquery(connection: dict, warehouse_schema: str) -> dict:
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError:
        raise RuntimeError("BigQuery support requires the 'google-cloud-bigquery' package — run: pip install google-cloud-bigquery")

    project_id = connection.get("project_id", "")
    dataset = warehouse_schema or connection.get("dataset", "")
    creds_json = connection.get("service_account_json", "")

    if creds_json:
        info = json.loads(creds_json) if isinstance(creds_json, str) else creds_json
        credentials = service_account.Credentials.from_service_account_info(info)
        client = bigquery.Client(project=project_id, credentials=credentials)
    else:
        client = bigquery.Client(project=project_id)

    table_names = [r["table_name"] for r in client.query(f"""
        SELECT table_name FROM `{project_id}.{dataset}.INFORMATION_SCHEMA.TABLES`
        WHERE table_type = 'BASE TABLE'
        ORDER BY table_name
    """).result()]

    raw_tables = []
    for name in table_names:
        try:
            row_count = list(client.query(
                f"SELECT COUNT(*) AS cnt FROM `{project_id}.{dataset}.{name}`"
            ).result())[0]["cnt"]
        except Exception:
            row_count = 0

        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("table_name", "STRING", name)]
        )
        columns = [{
            "column_name": r["column_name"], "data_type": r["data_type"],
            "is_nullable": r["is_nullable"],
            "character_maximum_length": None, "numeric_precision": None, "numeric_scale": None
        } for r in client.query(f"""
            SELECT column_name, data_type, is_nullable
            FROM `{project_id}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = @table_name
            ORDER BY ordinal_position
        """, job_config=job_config).result()]

        raw_tables.append({"name": name, "columns": columns, "row_count": row_count, "size": None})

    # BigQuery doesn't traditionally enforce FKs — relationships are usually
    # documented, not enforced. Skip rather than guess.
    return {"raw_tables": raw_tables, "fk_relationships": []}


def _introspect_oracle(connection: dict, warehouse_schema: str) -> dict:
    try:
        import oracledb
    except ImportError:
        raise RuntimeError("Oracle support requires the 'oracledb' package — run: pip install oracledb")

    owner = (warehouse_schema or connection.get("username", "")).upper()
    dsn = oracledb.makedsn(
        connection.get("host", "localhost"),
        int(connection.get("port", 1521)),
        service_name=connection.get("database", "")
    )
    conn = oracledb.connect(
        user=connection.get("username", ""),
        password=connection.get("password", ""),
        dsn=dsn
    )
    cur = conn.cursor()

    cur.execute("SELECT table_name FROM all_tables WHERE owner = :owner ORDER BY table_name", owner=owner)
    table_names = [r[0] for r in cur.fetchall()]

    raw_tables = []
    for name in table_names:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{owner}"."{name}"')
            row_count = cur.fetchone()[0]
        except Exception:
            row_count = 0

        cur.execute("""
            SELECT column_name, data_type, nullable,
                   char_length, data_precision, data_scale
            FROM all_tab_columns
            WHERE owner = :owner AND table_name = :tname
            ORDER BY column_id
        """, owner=owner, tname=name)
        columns = [{
            "column_name": r[0], "data_type": r[1], "is_nullable": r[2],
            "character_maximum_length": r[3], "numeric_precision": r[4], "numeric_scale": r[5]
        } for r in cur.fetchall()]

        raw_tables.append({"name": name, "columns": columns, "row_count": row_count, "size": None})

    fk_relationships = []
    try:
        cur.execute("""
            SELECT
                a.table_name AS from_table, a.column_name AS from_column,
                c_pk.table_name AS to_table, b.column_name AS to_column
            FROM all_cons_columns a
            JOIN all_constraints c ON a.owner = c.owner AND a.constraint_name = c.constraint_name
            JOIN all_constraints c_pk ON c.r_owner = c_pk.owner AND c.r_constraint_name = c_pk.constraint_name
            JOIN all_cons_columns b ON c_pk.owner = b.owner AND c_pk.constraint_name = b.constraint_name
            WHERE c.constraint_type = 'R' AND a.owner = :owner
        """, owner=owner)
        fk_relationships = [{
            "from_table": r[0], "from_column": r[1], "to_table": r[2], "to_column": r[3]
        } for r in cur.fetchall()]
    except Exception:
        pass

    cur.close()
    conn.close()
    return {"raw_tables": raw_tables, "fk_relationships": fk_relationships}


_ADAPTERS = {
    "postgres":   _introspect_postgres,
    "postgresql": _introspect_postgres,
    "redshift":   _introspect_postgres,   # Redshift is wire-compatible with Postgres
    "mysql":      _introspect_mysql,
    "mariadb":    _introspect_mysql,
    "sqlserver":  _introspect_sqlserver,
    "snowflake":  _introspect_snowflake,
    "bigquery":   _introspect_bigquery,
    "oracle":     _introspect_oracle,
}


def scan_warehouse(connection: dict, warehouse_schema: str = "warehouse", sub_mode: str = "reverse") -> dict:
    """
    Scan an existing warehouse of any supported type — discover all dim/fact
    tables, column types, row counts, FK relationships — and produce a
    reverse data model.

    Dispatches to the right DB adapter based on connection['connector_type']
    (also accepts 'db_type' for compatibility with saved connectors), falling
    back to 'postgresql' for older saved connectors that predate multi-DB
    support. Everything past introspection (AI analysis, dictionary
    generation, row-count formatting) is fully DB-agnostic.
    """
    db_type = (connection.get("connector_type") or connection.get("db_type") or "postgresql").lower()
    adapter = _ADAPTERS.get(db_type)
    if not adapter:
        return {
            "success": False,
            "error": f"Unsupported database type '{db_type}'. Supported: {', '.join(sorted(set(_ADAPTERS.keys())))}",
            "tables": []
        }

    try:
        introspected = adapter(connection, warehouse_schema)

        raw_tables = introspected["raw_tables"]
        fk_relationships = introspected["fk_relationships"]

        tables = []
        for t in raw_tables:
            tables.append({
                "name":      t["name"],
                "type":      _classify_table(t["name"]),
                "row_count": _format_row_count(t["row_count"]),
                "columns":   t["columns"],
                "size":      t.get("size")
            })

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
            "db_type":    db_type,
            "scanned_at": datetime.utcnow().isoformat()
        }

    except Exception as e:
        return {"success": False, "error": str(e), "tables": []}



def _informatica_trace_backward(iname, fname, instances, transforms, incoming, depth=0, seen=None):
    """Walk backward through a mapping's connector graph from (iname, fname),
    collecting any expressions found on Expression-type transformation ports,
    until a source or dead-end is reached. Returns (origin_instance,
    origin_field, expressions) so the caller can qualify the source with its
    originating table/instance, not just the bare field name."""
    if seen is None:
        seen = set()
    key = (iname, fname)
    if key in seen or depth > 25:
        return iname, fname, []
    seen.add(key)

    tr_name = instances.get(iname, {}).get("transformation", iname)
    tr = transforms.get(tr_name, {})
    expr = tr.get("fields", {}).get(fname, {}).get("expression", "")

    conn = incoming.get((iname, fname))
    if conn:
        origin_instance, origin_field, exprs = _informatica_trace_backward(
            conn["from_instance"], conn["from_field"], instances, transforms, incoming, depth + 1, seen
        )
        if expr and expr != fname:
            exprs = exprs + [expr]
        return origin_instance, origin_field, exprs

    # No CONNECTOR lands on this exact port — common for a computed output
    # port inside an Expression transformation, where the dependency on an
    # input port is implicit in the EXPRESSION text rather than a separate
    # CONNECTOR. Heuristically continue the trace from whichever INPUT port
    # of the same transformation is referenced in the expression.
    if expr:
        input_ports = [
            f for f, meta in tr.get("fields", {}).items()
            if meta.get("porttype", "").upper().startswith("INPUT") and f != fname
        ]
        referenced = [p for p in input_ports if re.search(r'\b' + re.escape(p) + r'\b', expr)]
        if referenced:
            origin_instance, origin_field, exprs = _informatica_trace_backward(
                iname, referenced[0], instances, transforms, incoming, depth + 1, seen
            )
            return origin_instance, origin_field, exprs + ([expr] if expr != fname else [])

    # Dead end. If this is a Lookup transformation, its real source isn't
    # wired via CONNECTOR at all — it's a transformation property. Use the
    # resolved lookup_table (from TABLEATTRIBUTE) if we found one, so the
    # mapping points at a real, extractable table instead of the Lookup's
    # internal instance name.
    if "Lookup" in tr.get("type", "") and tr.get("lookup_table"):
        return tr["lookup_table"], fname, ([expr] if expr and expr != fname else [])

    return iname, fname, ([expr] if expr and expr != fname else [])


def parse_informatica_xml(xml_content: str, source_file: str = None) -> list:
    """
    Parse an Informatica PowerCenter repository/mapping export.

    Real PowerCenter XML is structured as:
        REPOSITORY > FOLDER > (SOURCE | TARGET | MAPPING)
        MAPPING > TRANSFORMATION > TRANSFORMFIELD (has EXPRESSION for Expression
                                                     transformations)
        MAPPING > INSTANCE (aliases an instance name to a TRANSFORMATION_NAME)
        MAPPING > CONNECTOR (wires FROMINSTANCE.FROMFIELD -> TOINSTANCE.TOFIELD)

    The transformation logic lives on TRANSFORMFIELD@EXPRESSION inside
    Expression transformations, not on CONNECTOR — a mapping is really a
    graph you have to walk backward from each target port through however
    many Expression/Router/Lookup hops sit between it and its source.

    This walks that graph per MAPPING and per target-bound CONNECTOR,
    tracing back to the origin field and collecting any expressions
    encountered along the way. Falls back to a flat CONNECTOR scan for
    older/simpler exports that don't have the full nested structure.

    Returns mappings shaped as:
        {"source": <origin field>, "source_table": <origin instance/table name>,
         "target": "<table>.<column>" (lowercase),
         "transformation": <expression chain or "direct">,
         "mapping_name": <MAPPING NAME>, "mapped": True}

    `target` is deliberately "table.column" lowercase to match the format
    detect_gaps() compares against.
    """
    mappings = []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_content)
    except Exception as e:
        print(f"[MigrationAgent] Informatica XML parse error (invalid XML): {e}")
        return mappings

    # Workflow-level context: PowerCenter wraps mappings inside
    # WORKFLOW > SESSION elements, where SESSION typically carries a
    # MAPPINGNAME attribute linking back to the mapping it runs. This gives
    # each mapping a workflow_name for documentation/traceability purposes
    # (it isn't used for SQL generation). NOTE: exact SESSION/MAPPINGNAME
    # attribute naming can vary slightly across PowerCenter versions/export
    # tools — this hasn't been verified against a real repository export, so
    # if a mapping's workflow can't be found, it's left as None rather than
    # guessed.
    mapping_to_workflow = {}
    for wf in root.iter("WORKFLOW"):
        wf_name = wf.get("NAME", "")
        if not wf_name:
            continue
        for session in wf.iter("SESSION"):
            mn = session.get("MAPPINGNAME", "")
            if mn:
                mapping_to_workflow[mn] = wf_name

    folders = list(root.iter("FOLDER")) or [root]
    found_structured = False

    for folder in folders:
        # Table field definitions declared at folder level, used to recognize
        # which mapping instances are actually target tables.
        target_defs = {}
        for tgt in folder.iter("TARGET"):
            tname = tgt.get("NAME", "")
            if tname:
                target_defs[tname] = {f.get("NAME", "") for f in tgt.findall("TARGETFIELD")}

        for mapping in folder.iter("MAPPING"):
            mapping_name = mapping.get("NAME", "")

            # transformation name -> {"type": ..., "fields": {field: {porttype, expression}},
            #                         "lookup_table": <real table name, if this is a Lookup>}
            transforms = {}
            for tr in mapping.findall("TRANSFORMATION"):
                tr_name = tr.get("NAME", "")
                tr_type = tr.get("TYPE", "")
                fields = {}
                for tf in tr.findall("TRANSFORMFIELD"):
                    fname = tf.get("NAME", "")
                    fields[fname] = {
                        "porttype":   tf.get("PORTTYPE", ""),
                        "expression": (tf.get("EXPRESSION") or "").strip()
                    }

                # Lookup transformations don't get their source wired via
                # CONNECTOR — the real table they pull from is a transformation
                # property, typically a TABLEATTRIBUTE named "Lookup table name".
                # Without this, tracing dead-ends at the Lookup's own instance
                # name, which isn't a real, extractable table.
                lookup_table = None
                if "Lookup" in tr_type:
                    for attr in tr.findall("TABLEATTRIBUTE"):
                        attr_name = (attr.get("NAME") or "").strip().lower()
                        if "lookup table name" in attr_name or attr_name == "lookup sql override":
                            val = (attr.get("VALUE") or "").strip()
                            if val:
                                # Value may be schema-qualified or a full SQL
                                # override — take the last dotted segment as a
                                # best-effort table name if it looks like a
                                # simple reference, otherwise keep as-is.
                                lookup_table = val.split(".")[-1].strip('"') if "." in val and " " not in val else val
                                break

                transforms[tr_name] = {"type": tr_type, "fields": fields, "lookup_table": lookup_table}

            # instance name -> underlying transformation name + type
            instances = {}
            for inst in mapping.findall("INSTANCE"):
                iname = inst.get("NAME", "")
                instances[iname] = {
                    "transformation": inst.get("TRANSFORMATION_NAME", iname),
                    "type": inst.get("TRANSFORMATION_TYPE", "")
                }

            connectors = [{
                "from_instance": c.get("FROMINSTANCE", ""),
                "from_field":    c.get("FROMFIELD", ""),
                "to_instance":   c.get("TOINSTANCE", ""),
                "to_field":      c.get("TOFIELD", "")
            } for c in mapping.findall("CONNECTOR")]

            if not connectors:
                continue
            found_structured = True

            incoming = {(c["to_instance"], c["to_field"]): c for c in connectors}

            def instance_type(iname):
                if iname in instances:
                    return instances[iname]["type"]
                return transforms.get(iname, {}).get("type", "")

            def is_target_instance(iname):
                return "Target" in instance_type(iname) or iname in target_defs

            # For Lookup transformations we resolved a real table for (via
            # TABLEATTRIBUTE), also trace their INPUT port back to find what
            # feeds the lookup condition. This is a HINT, not a confirmed
            # join key — PowerCenter's actual LOOKUPCONDITION isn't reliably
            # parseable without a real sample export to verify the schema
            # against, so we surface it as a hint for the AI/human to verify
            # rather than asserting it as ground truth (same reasoning as
            # the Informatica parser's other tracing: don't guess silently).
            lookup_join_hints_by_table = {}
            for tr_name, tmeta in transforms.items():
                lk_table = tmeta.get("lookup_table")
                if not lk_table:
                    continue
                inst_name = next(
                    (iname for iname, imeta in instances.items() if imeta.get("transformation") == tr_name),
                    tr_name
                )
                input_ports = [
                    f for f, meta in tmeta.get("fields", {}).items()
                    if meta.get("porttype", "").upper().startswith("INPUT")
                ]
                if input_ports:
                    key_port = input_ports[0]
                    fed_instance, fed_field, _ = _informatica_trace_backward(
                        inst_name, key_port, instances, transforms, incoming
                    )
                    if fed_instance != inst_name or fed_field != key_port:  # only if it actually traced somewhere
                        lookup_join_hints_by_table[lk_table] = {
                            "fed_by_table": fed_instance, "fed_by_column": fed_field
                        }

            for c in connectors:
                if not is_target_instance(c["to_instance"]):
                    continue
                target_table = c["to_instance"]
                target_field = c["to_field"]
                origin_instance, origin_field, exprs = _informatica_trace_backward(
                    c["from_instance"], c["from_field"], instances, transforms, incoming
                )
                # de-dupe while preserving order
                transformation = " -> ".join(dict.fromkeys(exprs)) if exprs else "direct"

                # If tracing dead-ended at an internal transformation's own
                # instance name (e.g. an unresolvable Lookup with no usable
                # TABLEATTRIBUTE) rather than a real source table or a
                # resolved lookup table, flag it — this name is NOT a real,
                # extractable table and needs a human to resolve it.
                origin_tr_name = instances.get(origin_instance, {}).get("transformation", origin_instance)
                needs_review = origin_tr_name in transforms and transforms[origin_tr_name].get("type", "") not in ("", "Source Qualifier")

                mapping_entry = {
                    "source":         origin_field,
                    "source_table":   origin_instance,
                    "target":         f"{target_table}.{target_field}".lower(),
                    "transformation": transformation,
                    "mapping_name":   mapping_name,
                    "workflow_name":  mapping_to_workflow.get(mapping_name),
                    "source_file":    source_file,
                    "mapped":         True
                }
                join_hint = lookup_join_hints_by_table.get(origin_instance)
                if join_hint:
                    mapping_entry["lookup_join_hint"] = join_hint
                if needs_review:
                    mapping_entry["needs_review"] = True
                    mapping_entry["review_reason"] = (
                        f"Traced back to '{origin_instance}' ({transforms[origin_tr_name].get('type', 'unknown type')}), "
                        f"which isn't a real source table — likely a Lookup, Router, or other "
                        f"transformation whose actual data source couldn't be automatically resolved."
                    )
                mappings.append(mapping_entry)

    if found_structured:
        return mappings

    # ── Fallback: flat CONNECTOR scan for simpler/older exports ──
    for connector in root.iter("CONNECTOR"):
        to_instance = connector.get("TOINSTANCE", "")
        to_field    = connector.get("TOFIELD", "")
        target = f"{to_instance}.{to_field}".lower() if to_instance else to_field
        mappings.append({
            "source":         connector.get("FROMFIELD", ""),
            "source_table":   connector.get("FROMINSTANCE", ""),
            "target":         target,
            "transformation": connector.get("TRANSFORMATION", "direct"),
            "mapping_name":   None,
            "workflow_name":  None,
            "source_file":    source_file,
            "mapped":         True
        })
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


def _staging_table_name(source_table: str) -> str:
    """The REAL staging table naming convention, confirmed from
    universal_connector.py's extract_table_universal(): stg = f"stg_{table}"
    — the source table name is used EXACTLY as given, with NO case
    transformation. This matters because that function creates the table via
    a double-quoted identifier (CREATE TABLE "{staging_schema}"."{stg}"),
    and Postgres preserves case exactly for quoted identifiers rather than
    folding to lowercase. So source_table must match the real source
    table's name byte-for-byte, including case."""
    return f"stg_{source_table}"


# Best-effort cross-database type name -> PostgreSQL type mapping. A table
# can be reverse-engineered from any of the 7 supported warehouse types
# (scan_warehouse), but the actual deploy target is always PostgreSQL (per
# universal_connector.py: "Target (staging) is always PostgreSQL"). NOT
# exhaustive — covers common cases per DB. Anything unrecognized passes
# through as-is with a flag for the AI/human to verify rather than being
# silently trusted.
_TYPE_TRANSLATION = {
    # Oracle
    "varchar2": "VARCHAR", "nvarchar2": "VARCHAR", "number": "NUMERIC",
    "clob": "TEXT", "nclob": "TEXT", "long": "TEXT", "raw": "BYTEA",
    "binary_float": "REAL", "binary_double": "DOUBLE PRECISION",
    # MySQL / MariaDB
    "tinyint": "SMALLINT", "mediumint": "INTEGER", "int": "INTEGER",
    "datetime": "TIMESTAMP", "longtext": "TEXT", "mediumtext": "TEXT",
    "tinytext": "TEXT", "double": "DOUBLE PRECISION", "enum": "VARCHAR",
    # SQL Server
    "nvarchar": "VARCHAR", "ntext": "TEXT", "money": "NUMERIC",
    "smallmoney": "NUMERIC", "datetime2": "TIMESTAMP", "bit": "BOOLEAN",
    "uniqueidentifier": "UUID", "image": "BYTEA", "varbinary": "BYTEA",
    # Snowflake / BigQuery
    "variant": "JSONB", "object": "JSONB", "array": "JSONB",
    "string": "TEXT", "int64": "BIGINT", "float64": "DOUBLE PRECISION",
    "bool": "BOOLEAN", "bytes": "BYTEA", "timestamp_ntz": "TIMESTAMP",
    "timestamp_tz": "TIMESTAMPTZ",
}

_ALREADY_VALID_PG_TYPES = {
    "character varying", "varchar", "integer", "bigint", "smallint",
    "numeric", "decimal", "boolean", "timestamp", "timestamp without time zone",
    "timestamp with time zone", "date", "text", "real", "double precision",
    "uuid", "jsonb", "json", "bytea"
}


def _format_column_type(col: dict) -> str:
    """
    Format a scanned column's REAL data type (from scan_warehouse's
    information_schema introspection) as a PostgreSQL-valid type string, for
    use in generated CREATE TABLE statements — instead of leaving the AI to
    guess a type purely from the column name, which is what happened before
    this existed.

    Translates common non-Postgres type names to Postgres equivalents, since
    a table can be reverse-engineered from Oracle/MySQL/SQL
    Server/Snowflake/BigQuery/Redshift but the deploy target is always
    PostgreSQL. This mapping is best-effort, not exhaustive — an
    unrecognized type name is passed through as-is and flagged for
    verification rather than trusted blindly.
    """
    raw_type = (col.get("data_type") or "").strip()
    if not raw_type:
        return "unknown type — infer from context"

    key = raw_type.lower()
    base = _TYPE_TRANSLATION.get(key, raw_type)
    unrecognized = key not in _TYPE_TRANSLATION and key not in _ALREADY_VALID_PG_TYPES

    precision = col.get("numeric_precision")
    scale = col.get("numeric_scale")
    max_len = col.get("character_maximum_length")

    if base.upper() in ("NUMERIC", "DECIMAL") and precision:
        base = f"{base}({precision},{scale or 0})"
    elif base.upper() in ("VARCHAR", "CHARACTER VARYING") and max_len:
        base = f"VARCHAR({max_len})"

    suffix = " [UNRECOGNIZED SOURCE TYPE — verify before trusting]" if unrecognized else ""
    return f"{base}{suffix}"


def _quoted_staging_ref(schema: str, stg_table: str) -> str:
    """Build a schema.table reference safe to paste directly into generated
    SQL. Because universal_connector.py creates staging tables with quoted
    (case-preserving) identifiers, any staging table name that isn't already
    all-lowercase MUST be double-quoted when referenced, or Postgres will
    fold an unquoted reference to lowercase and silently miss the real
    table. All-lowercase names don't strictly need quoting but are quoted
    anyway here for consistency — quoting a lowercase identifier is a no-op
    in Postgres."""
    return f'{schema}."{stg_table}"'


def _default_label(tname: str, ttype: str) -> str:
    base = re.sub(r'^(dim_|fact_)', '', tname).replace('_', ' ').strip().title()
    word = 'dimension' if ttype == 'dim' else 'fact'
    return f"{base} {word} table"


def generate_sql_scripts(tables: list, mappings: list, gaps: list, resolutions: dict,
                          domain: str = "", staging_schema: str = "staging",
                          warehouse_schema: str = "warehouse") -> dict:
    """
    Generate SQL scripts to populate each dim/fact table from its identified
    sources, in the exact shape pipeline_executor.execute_warehouse_scripts()
    consumes:

        {"success": True,
         "sql_scripts": {"scripts": [{"name", "label", "schema", "sql"}, ...]},
         "generated_at": ...}

    Each script's "sql" is one complete
    "CREATE TABLE IF NOT EXISTS ... ; INSERT INTO ... SELECT ... FROM
    <staging_schema>.<staging table(s)> ..." statement — the same contract
    used by AIBridge's native build-from-scratch pipelines — so the result
    can be saved straight into a pipeline's artifacts.sql_scripts and run
    through the existing execution engine with no new execution path
    required.

    Staging table names and quoting follow the REAL convention confirmed
    from universal_connector.extract_table_universal(): "stg_<source table
    name>" with the source table's case preserved EXACTLY (no lowercasing),
    referenced via double-quoted identifiers since that function creates
    staging tables with quoted, case-preserving identifiers. A single target
    table can draw from multiple staging tables (e.g. a dimension enriched
    via a Lookup against a second source table); when that happens, every
    staging table involved is listed for the AI to JOIN across correctly.

    `resolutions` maps gap column names (or gap list index as a string) to the
    user's typed-in explanation of how that column should be derived, e.g.
    {"dim_customer.age_bracket": "Bucket date_of_birth into 5-year ranges"}.
    """
    try:
        mappings_by_table = {}
        for m in mappings:
            tbl = m.get("target", "").split(".")[0]
            mappings_by_table.setdefault(tbl, []).append(m)

        gap_lookup = {}
        for i, g in enumerate(gaps):
            resolution = resolutions.get(str(i)) or resolutions.get(g.get("column", ""))
            if resolution:
                gap_lookup[g["column"]] = resolution
        # Also honor resolutions keyed directly by "table.column" for
        # needs_review mappings — these aren't in `gaps` at all (detect_gaps
        # only flags columns with NO mapping; needs_review is a mapped-but-
        # unresolvable case), so they'd otherwise never be picked up here.
        for key, resolution in resolutions.items():
            if isinstance(key, str) and "." in key and resolution:
                gap_lookup.setdefault(key.lower(), resolution)

        scripts = []
        for table in tables:
            ttype = table.get("type")
            if ttype not in ("dim", "fact"):
                continue

            tname = table["name"]
            table_mappings = {m["target"]: m for m in mappings_by_table.get(tname, [])}

            # Every distinct staging table this target actually needs,
            # derived from each mapped column's real source_table — not
            # guessed, case preserved exactly as extract_table_universal
            # will have created it, and EXCLUDING any mapping flagged
            # needs_review (its "source_table" is an unresolved internal
            # transformation name, not a real extractable table).
            staging_tables_used = sorted(set(
                _staging_table_name(m["source_table"])
                for m in table_mappings.values()
                if m.get("source_table") and not m.get("needs_review")
            ))

            col_lines = []
            mapped_count = 0
            for col in table.get("columns", []):
                cname = col["column_name"]
                full = f"{tname}.{cname}".lower()
                real_type = _format_column_type(col)
                match = table_mappings.get(full)
                if match and match.get("needs_review"):
                    if full in gap_lookup:
                        # User resolved this via the Gaps tab — honor it,
                        # don't force UNRESOLVED just because the automatic
                        # trace couldn't find a real table on its own.
                        mapped_count += 1
                        col_lines.append(
                            f"  {cname} [{real_type}] <- {gap_lookup[full]}  (user-resolved — was flagged: {match.get('review_reason', 'needed manual review')})"
                        )
                    else:
                        # Traced to an unresolvable transformation (e.g. a
                        # Lookup with no discoverable table) and no user
                        # resolution given — don't treat this as mapped;
                        # surface it plainly rather than referencing a fake table.
                        col_lines.append(
                            f"  {cname} [{real_type}] <- UNRESOLVED: {match.get('review_reason', 'source could not be traced to a real table')}"
                        )
                elif match:
                    mapped_count += 1
                    expr = match["source"] if match.get("transformation") == "direct" else match["transformation"]
                    stg_note = ""
                    if match.get("source_table"):
                        stg_ref = _quoted_staging_ref(staging_schema, _staging_table_name(match['source_table']))
                        stg_note = f" (from {stg_ref})"
                    col_lines.append(f"  {cname} [{real_type}] <- {expr}{stg_note}")
                elif full in gap_lookup:
                    mapped_count += 1
                    col_lines.append(f"  {cname} [{real_type}] <- {gap_lookup[full]}  (user-resolved)")
                else:
                    col_lines.append(f"  {cname} [{real_type}] <- (unmapped — leave NULL / apply default)")

            # Collect any join hints for the staging tables actually in play,
            # so the AI has a concrete lead instead of guessing a join key
            # (e.g. it previously invented "ON src.CAR_ID = mk.CAR_ID" out of
            # thin air, which is silently wrong — worse than flagging it).
            join_hints_text = []
            for match in table_mappings.values():
                hint = match.get("lookup_join_hint")
                if hint and match.get("source_table") and not match.get("needs_review"):
                    stg_ref = _quoted_staging_ref(staging_schema, _staging_table_name(match["source_table"]))
                    fed_ref = f"{hint['fed_by_table']}.{hint['fed_by_column']}"
                    join_hints_text.append(f"  {stg_ref} is looked up using {fed_ref} as the key (UNCONFIRMED — the exact matching column name inside {stg_ref} could not be determined from the mapping file; verify before relying on this in production)")

            if staging_tables_used:
                quoted_refs = [_quoted_staging_ref(staging_schema, t) for t in staging_tables_used]
                staging_list_text = ", ".join(quoted_refs)
                if len(staging_tables_used) > 1:
                    if join_hints_text:
                        join_guidance = (
                            f"JOIN key hints (unconfirmed, verify manually):\n" + "\n".join(join_hints_text) + "\n"
                            f"Use these hints to write the JOIN, but add a \"-- REVIEW: unconfirmed join key\" "
                            f"comment on that JOIN line so a human verifies it before this runs in production."
                        )
                    else:
                        join_guidance = (
                            "No join key could be determined between these staging tables. Do NOT guess one. "
                            "Instead: SELECT only from the primary staging table, leave any column that would "
                            "have come from the other staging table(s) as NULL, and add a "
                            "\"-- REVIEW: could not determine join key with <table>\" comment for each such column."
                        )
                else:
                    join_guidance = ""
                staging_instruction = (
                    f"Source staging table(s) — use these EXACT references, quotes included, "
                    f"in your FROM/JOIN clauses (they are case-sensitive; do not lowercase or "
                    f"re-derive them): {staging_list_text}\n"
                    f"{join_guidance}\n"
                    f"Each column derivation below notes which staging table it actually comes from."
                )
            else:
                staging_list_text = "(none identified — every column is unmapped or user-resolved)"
                staging_instruction = (
                    "No staging table could be identified for this table's columns. "
                    "Write the CREATE TABLE statement only, and add a top-level "
                    "\"-- REVIEW:\" comment explaining that source data is unidentified "
                    "rather than fabricating a FROM clause."
                )

            ai_prompt = f"""You are a senior data engineer writing a migration SQL script for a PostgreSQL data warehouse pipeline.

Target table: {warehouse_schema}.{tname} ({ttype})
{staging_instruction}
Domain: {domain or 'unknown'}
Column derivations — format is "column_name [REAL existing column type] <- derivation".
The [type] shown is the ACTUAL type of this column in the real, already-existing
target table (from live database introspection, not a guess) — use it AS-IS
in your CREATE TABLE statement rather than inferring a different type from
the column name or expression. A type marked "[UNRECOGNIZED SOURCE TYPE —
verify before trusting]" means it came from a non-PostgreSQL source system
and couldn't be confidently translated — use your best judgment but flag it
with a "-- REVIEW: verify type" comment rather than asserting confidence you
don't have. Each derivation also notes which staging table it comes from,
unless marked user-resolved:
{chr(10).join(col_lines)}

IMPORTANT — the column derivations above may contain Informatica PowerCenter
expression syntax (e.g. TO_INTEGER(x), TO_CHAR(x), IIF(cond, a, b), DECODE(x,
v1, r1, v2, r2, default), INSTR(...), SUBSTR(...)). These are NOT valid
PostgreSQL. You MUST translate them to PostgreSQL equivalents, for example:
  TO_INTEGER(x)        -> x::INTEGER  or  CAST(x AS INTEGER)
  TO_CHAR(x)            -> x::TEXT  (PostgreSQL's own TO_CHAR takes a format
                            string as a 2nd arg — only use it that way, not
                            as a bare cast)
  IIF(cond, a, b)        -> CASE WHEN cond THEN a ELSE b END
  DECODE(x,v1,r1,...,d)  -> CASE WHEN x = v1 THEN r1 ... ELSE d END
  INSTR(str, sub)        -> POSITION(sub IN str)
Never emit an Informatica function name verbatim into the generated SQL —
translate it, or if you cannot confidently translate a specific expression,
leave that column NULL with a "-- REVIEW: could not translate expression:
<original expression>" comment instead of guessing.

Write ONE complete, runnable PostgreSQL script for this table containing:
1. CREATE TABLE IF NOT EXISTS {warehouse_schema}.{tname} (...) with appropriate
   column types inferred from the derivations above.
2. INSERT INTO {warehouse_schema}.{tname} (...) SELECT ... FROM the staging table(s)
   listed above (joined together if more than one, per the join guidance above),
   using the EXACT quoted references given — do not strip the quotes or change
   the case, since Postgres treats quoted identifiers as case-sensitive and an
   unquoted or re-cased reference will silently point at a different,
   nonexistent table. Apply the column derivations exactly as given, translated
   to valid PostgreSQL syntax per the rules above.
3. Use INSERT ... ON CONFLICT DO NOTHING (or an equivalent NOT EXISTS guard)
   so the script is idempotent on re-run.
4. Add a short "-- REVIEW:" comment above any column marked "unmapped" or
   "UNRESOLVED" above, flagging it for manual review (use NULL as a
   placeholder value for it) — do not silently guess business logic for
   these columns, and do not invent a staging table, lookup table, or JOIN
   condition that wasn't explicitly given to you above.

Return ONLY valid JSON: {{"sql": "-- full script here"}}"""

            try:
                ai_result = ask_ai(ai_prompt, agent_name="MigrationAgent")
                sql = ai_result.get("sql", "-- SQL generation returned no content")
            except Exception as e:
                sql = f"-- AI generation failed for {tname}: {e}"

            scripts.append({
                "name":   tname,
                "label":  _default_label(tname, ttype),
                "schema": warehouse_schema,
                "sql":    sql,
                # Extra fields kept for the UI only — execute_warehouse_scripts
                # reads name/label/schema/sql and should ignore the rest.
                "columns_mapped": mapped_count,
                "columns_total":  len(table.get("columns", [])),
                "staging_tables": [_quoted_staging_ref(staging_schema, t) for t in staging_tables_used],
            })

        return {
            "success":      True,
            "sql_scripts":  {"scripts": scripts},
            "generated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_migration_deployment(
    source_connector_config: dict,
    target_connector_config: dict,
    source_schema: str,
    staging_schema: str,
    warehouse_schema: str,
    source_tables: list,
    sql_scripts: dict,
    data_model: dict,
    pipeline_id: str,
    workspace_id: str,
) -> dict:
    """
    Dedicated Migration Agent execution flow. Runs the SAME agent classes as
    AIBridge's native build-from-scratch pipelines (ETLAgent -> QualityAgent ->
    ExecutionAgent -> RecoveryAgent -> AnalyticsAgent), so migrated warehouses
    get identical quality gating and self-healing behavior — but orchestrated
    here rather than via _run_pipeline_execution() in main.py, since that
    function's assumptions (auto-discovering source_tables from a single
    connector, no separate source/target split) don't fit a migration where
    the user explicitly supplies a legacy source connector, a staging/
    warehouse target connector, and pre-generated sql_scripts from the
    scan -> parse -> resolve-gaps -> generate-sql steps that came before this.

    This does NOT modify pipeline_executor.py, execution_agent.py, or any
    other agent file — it only imports and calls them exactly as
    OrchestratorAgent already does, via the same AgentContext contract
    (agents/base.py).

    Returns:
        {"success": bool, "stage": str (if failed early), "error": str|None,
         "staging": ctx.staging_result, "warehouse": ctx.execution_result,
         "quality": ctx.quality_result, "analytics": ctx.analytics_result,
         "log": [...], "pipeline_log": ctx.pipeline_log}
    """
    from agents.base import AgentContext
    from agents.etl_agent import ETLAgent
    from agents.quality_agent import QualityAgent
    from agents.execution_agent import ExecutionAgent
    from agents.recovery_agent import RecoveryAgent
    from agents.analytics_agent import AnalyticsAgent

    log = []

    def _log(msg):
        log.append(msg)
        print(f"[MigrationDeploy] {msg}")

    try:
        ctx = AgentContext(
            pipeline_id=pipeline_id,
            workspace_id=workspace_id,
            connector_config=source_connector_config,
            source_schema=source_schema,
            source_tables=source_tables,
            source_columns={},
            source_description="Migration Agent deployment — extracted from an existing ETL/DWH project",
            business_requirements="",
            target_config=target_connector_config,
            staging_schema=staging_schema,
            warehouse_schema=warehouse_schema,
        )
        ctx.sql_scripts = sql_scripts
        ctx.data_model = data_model
    except Exception as e:
        return {"success": False, "stage": "context_setup", "error": str(e), "log": log}

    # ── Step 1: Extract legacy source tables into staging ────────────────────
    if not source_tables:
        return {"success": False, "stage": "extract",
                "error": "No source tables provided — cannot extract without knowing which "
                         "legacy tables to pull (derive these from mapping source_table values).",
                "log": log}

    _log(f"Extracting {len(source_tables)} source table(s) into {staging_schema}: {', '.join(source_tables)}")
    etl_result = ETLAgent().run(ctx)
    if not etl_result.success:
        _log(f"✗ Extract failed: {etl_result.error}")
        return {"success": False, "stage": "extract", "error": etl_result.error,
                "staging": ctx.staging_result, "log": log, "pipeline_log": ctx.pipeline_log}

    staging_result = ctx.staging_result or {}
    _log(f"✓ Extract complete — {staging_result.get('rows', 0)} rows staged")

    # ── Step 2: Quality check (pre-load), same as native pipelines ───────────
    _log("Running QualityAgent (pre-load)...")
    QualityAgent().run(ctx)
    quality_data = ctx.quality_result or {}
    _log(f"Quality: {quality_data.get('status', 'unknown')} "
         f"({quality_data.get('score', '?')}%)"
         + (f" — {quality_data.get('total_removed', 0)} bad rows quarantined"
            if quality_data.get('total_removed') else ""))

    # ── Step 3: Load warehouse from the Migration Agent's generated SQL ──────
    _log(f"Running ExecutionAgent — loading {warehouse_schema} from generated migration SQL...")
    ExecutionAgent().run(ctx)
    exec_result = ctx.execution_result or {}

    failed_scripts = [s for s in exec_result.get("scripts", []) if not s.get("success", True)]
    if failed_scripts:
        _log(f"{len(failed_scripts)} script(s) failed — running RecoveryAgent...")
        RecoveryAgent().run(ctx)
        if ctx.recovery_result and ctx.recovery_result.get("recovered", 0) > 0:
            _log("Recovery fixed script(s) — retrying execution...")
            ExecutionAgent().run(ctx)
            exec_result = ctx.execution_result or {}

    # ── Step 4: Analytics, same as native pipelines ──────────────────────────
    AnalyticsAgent().run(ctx)

    success = exec_result.get("success", False)
    _log(("✓" if success else "✗") + " Migration deployment finished")

    return {
        "success":       success,
        "staging":       staging_result,
        "warehouse":     exec_result,
        "quality":       quality_data,
        "analytics":     ctx.analytics_result,
        "recovery":      ctx.recovery_result,
        "log":           log,
        "pipeline_log":  ctx.pipeline_log,
    }
def generate_migration_document(scan_result: dict, resolutions: dict = None, domain_override: str = None) -> bytes:
    """
    Generate a business-readable Migration Requirements & Data Lineage
    document (.docx) from a Migration Agent scan — available as soon as
    scanning completes (doesn't require SQL to have been generated yet).

    Structure (matches the approved sample):
      1. Title page — domain, source file, generated-by line
      2. Executive Summary — narrative + a quick stats table
      3. Data Model Overview — every dim/fact table, type, row count, columns
      4. Column-Level Mapping & Lineage — every column's real source,
         transformation, mapping name, and workflow name
      5. Gaps & Manual Resolutions — resolved gaps show the resolution;
         unresolved ones are visibly flagged

    `resolutions` is the same dict shape used by generate_sql_scripts() —
    gap index or "table.column" -> resolution text.

    Returns raw .docx bytes (write to a file or stream directly in a
    FastAPI response — no temp file needed).
    """
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import io

    resolutions = resolutions or {}
    tables = scan_result.get("tables", [])
    mappings = scan_result.get("mappings", [])
    gaps = scan_result.get("gaps", [])
    domain = domain_override or scan_result.get("domain", "unknown")
    ai_summary = scan_result.get("ai_summary", "")
    source_files = sorted(set(m.get("source_file") for m in mappings if m.get("source_file")))
    source_file_display = ", ".join(source_files) if source_files else "N/A"

    NAVY = RGBColor(0x2D, 0x2A, 0x6E)
    GREY = RGBColor(0x55, 0x55, 0x55)
    RED = RGBColor(0x99, 0x1B, 0x1B)
    GREEN = RGBColor(0x16, 0x65, 0x34)

    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)

    def shade_cell(cell, hex_color):
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), hex_color)
        cell._tc.get_or_add_tcPr().append(shd)

    def header_row(table, headers):
        row = table.rows[0]
        for i, h in enumerate(headers):
            cell = row.cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(h)
            run.bold = True
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            run.font.size = Pt(9)
            shade_cell(cell, "2D2A6E")

    def data_row(table, values, colors=None):
        row = table.add_row()
        for i, v in enumerate(values):
            cell = row.cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(v))
            run.font.size = Pt(9)
            if colors and colors[i]:
                run.font.color.rgb = colors[i]
                run.bold = True

    def narrative(text, size=11):
        p = doc.add_paragraph()
        run = p.add_run(text)
        run.font.size = Pt(size)
        p.paragraph_format.space_after = Pt(10)
        return p

    # ── Title page ──
    for _ in range(6):
        doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("Migration Requirements & Data Lineage")
    r.bold = True; r.font.size = Pt(28); r.font.color.rgb = NAVY

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = subtitle.add_run("AIBridge Migration Agent \u2014 Warehouse Migration Documentation")
    r.font.size = Pt(14); r.font.color.rgb = GREY

    for text, size, color, italic in [
        (f"Domain: {domain.title() if domain else 'Unknown'}", 12, None, False),
        (f"Source file(s): {source_file_display}", 10, GREY, False),
        ("Generated by AIBridge Migration Agent", 11, GREY, True),
    ]:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.italic = italic
        if color:
            run.font.color.rgb = color

    doc.add_page_break()

    # ── 1. Executive Summary ──
    doc.add_heading("1. Executive Summary", level=1)
    narrative(
        f"This document describes a data warehouse scanned by AIBridge Migration Agent"
        + (f", using the source file \"{source_file_display}\"" if source_files else "")
        + ". AIBridge automatically reconstructed how each warehouse column is populated today, "
          "based on the uploaded mapping file(s) and/or the existing warehouse structure."
    )
    if ai_summary:
        narrative(ai_summary)
    narrative(
        "The sections below summarize what was found, exactly how each column is derived, "
        "and which pieces still need a person to confirm before this migration is deployed."
    )

    dim_count = sum(1 for t in tables if t.get("type") == "dim")
    fact_count = sum(1 for t in tables if t.get("type") == "fact")
    needs_review_mappings = [m for m in mappings if m.get("needs_review")]
    total_issues = len(gaps) + len(needs_review_mappings)
    resolved_gaps = sum(1 for i, g in enumerate(gaps) if resolutions.get(str(i)) or resolutions.get(g.get("column", "")))
    resolved_review = sum(1 for m in needs_review_mappings if resolutions.get(m.get("target", "")))
    total_resolved = resolved_gaps + resolved_review

    stats_table = doc.add_table(rows=1, cols=2)
    stats_table.style = "Table Grid"
    header_row(stats_table, ["Metric", "Value"])
    data_row(stats_table, ["Tables scanned", f"{len(tables)} ({dim_count} dimension, {fact_count} fact)"])
    data_row(stats_table, ["Column mappings extracted", str(len(mappings))])
    data_row(stats_table, ["Issues identified", str(total_issues)])
    data_row(stats_table, ["Issues resolved", f"{total_resolved} of {total_issues}"])

    doc.add_page_break()

    # ── 2. Data Model Overview ──
    doc.add_heading("2. Data Model Overview", level=1)
    narrative(
        "The warehouse being migrated consists of the tables below. \u201CDimension\u201D tables "
        "describe the things being tracked; \u201CFact\u201D tables hold the actual measured events."
    )
    dm_table = doc.add_table(rows=1, cols=4)
    dm_table.style = "Table Grid"
    header_row(dm_table, ["Table", "Type", "Row Count", "Columns"])
    for t in tables:
        data_row(dm_table, [t.get("name", ""), t.get("type", "").upper(), t.get("row_count", "\u2014"), str(len(t.get("columns", [])))])

    doc.add_page_break()

    # ── 3. Column-Level Mapping & Lineage ──
    doc.add_heading("3. Column-Level Mapping & Lineage", level=1)
    narrative(
        "Every mapped column below traces back to its real source field and any transformation "
        "logic applied. The Mapping and Workflow columns show exactly which object each column's "
        "logic came from, for cross-checking against the original export if needed."
    )
    ml_table = doc.add_table(rows=1, cols=5)
    ml_table.style = "Table Grid"
    header_row(ml_table, ["Target Column", "Source", "Transformation", "Mapping", "Workflow"])
    for m in mappings:
        source_display = f"{m.get('source_table', '')}.{m.get('source', '')}" if m.get('source_table') else m.get('source', '')
        if m.get("needs_review"):
            data_row(ml_table, [
                m.get("target", ""), source_display,
                f"NEEDS REVIEW: {m.get('review_reason', 'unresolved')}",
                m.get("mapping_name") or "\u2014", m.get("workflow_name") or "\u2014"
            ], colors=[None, None, RED, None, None])
        else:
            data_row(ml_table, [
                m.get("target", ""), source_display, m.get("transformation", ""),
                m.get("mapping_name") or "\u2014", m.get("workflow_name") or "\u2014"
            ])

    doc.add_page_break()

    # ── 4. Gaps & Manual Resolutions ──
    doc.add_heading("4. Gaps & Manual Resolutions", level=1)
    narrative(
        "Not every warehouse column had a matching source mapping. The table below lists each "
        "gap, why it was flagged, and how it was resolved \u2014 or, if still unresolved, that it "
        "needs input before this migration can be safely deployed."
    )
    gp_table = doc.add_table(rows=1, cols=3)
    gp_table.style = "Table Grid"
    header_row(gp_table, ["Column", "Reason", "Resolution"])

    any_unresolved = False
    for i, g in enumerate(gaps):
        resolution = resolutions.get(str(i)) or resolutions.get(g.get("column", ""))
        if resolution:
            data_row(gp_table, [g.get("column", ""), g.get("reason", ""), resolution])
        else:
            any_unresolved = True
            data_row(gp_table, [g.get("column", ""), g.get("reason", ""), "\u26A0 UNRESOLVED \u2014 needs manual input before deployment"], colors=[None, None, RED])
    for m in needs_review_mappings:
        resolution = resolutions.get(m.get("target", ""))
        if resolution:
            data_row(gp_table, [m.get("target", ""), m.get("review_reason", ""), resolution])
        else:
            any_unresolved = True
            data_row(gp_table, [m.get("target", ""), m.get("review_reason", ""), "\u26A0 UNRESOLVED \u2014 needs manual input before deployment"], colors=[None, None, RED])

    verdict = doc.add_paragraph()
    verdict.paragraph_format.space_before = Pt(12)
    run = verdict.add_run(
        "\u26A0 This migration has unresolved gaps and should not be deployed to production until they are addressed."
        if any_unresolved else "\u2713 All identified gaps have been resolved."
    )
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RED if any_unresolved else GREEN

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _find_soffice() -> str:
    """
    Locate the LibreOffice 'soffice' executable. Checks PATH first, then
    falls back to known default install locations — PATH alone is
    unreliable here because Windows environment variable changes don't
    propagate to already-running parent processes (VSCode, an existing
    terminal session, etc.), which is a common source of "installed but
    still not found" confusion. Returns None if not found anywhere checked.
    """
    import shutil
    import os

    found = shutil.which("soffice") or shutil.which("soffice.com") or shutil.which("soffice.exe")
    if found:
        return found

    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    """
    Convert generated .docx bytes to PDF via a headless LibreOffice
    conversion. REQUIRES LibreOffice installed on the server this runs on —
    this is a real system dependency, not just a pip package. Detection
    checks PATH first, then known default install locations directly (see
    _find_soffice), since PATH alone is unreliable across Windows
    processes that were started before an install/PATH change.

    Raises RuntimeError with a clear message if LibreOffice isn't found or
    the conversion fails, rather than silently returning something broken.
    """
    import subprocess
    import tempfile
    import os

    soffice_path = _find_soffice()
    if not soffice_path:
        raise RuntimeError(
            "PDF export requires LibreOffice installed. Checked PATH and common install "
            "locations but couldn't find it. Install LibreOffice from libreoffice.org, or "
            "use the Word (.docx) export instead. If you just installed it, make sure the "
            "backend process itself was started AFTER installing (restarting the terminal "
            "isn't enough if the backend runs inside an app like VSCode that was already open)."
        )

    with tempfile.TemporaryDirectory() as tmp:
        docx_path = os.path.join(tmp, "migration_doc.docx")
        with open(docx_path, "wb") as f:
            f.write(docx_bytes)

        result = subprocess.run(
            [soffice_path, "--headless", "--convert-to", "pdf", "--outdir", tmp, docx_path],
            capture_output=True, text=True, timeout=60
        )
        pdf_path = os.path.join(tmp, "migration_doc.pdf")
        if result.returncode != 0 or not os.path.exists(pdf_path):
            raise RuntimeError(f"PDF conversion failed: {result.stderr or result.stdout}")

        with open(pdf_path, "rb") as f:
            return f.read()


# ── dbt project parsing & SQL generation ─────────────────────────────────
import re


def parse_dbt_sources_yml(yml_content: str) -> dict:
    """
    Parse a dbt sources.yml file. Returns a lookup:
        {(source_name, table_name): "schema.real_table_name"}
    honoring an `identifier:` override if present (dbt lets a source table's
    logical name differ from its actual table name via `identifier`).
    """
    import yaml
    lookup = {}
    try:
        data = yaml.safe_load(yml_content) or {}
        for src in (data.get("sources") or []):
            src_name = src.get("name", "")
            schema = src.get("schema", src_name)
            for tbl in (src.get("tables") or []):
                tbl_name = tbl.get("name", "")
                real_name = tbl.get("identifier", tbl_name)
                lookup[(src_name, tbl_name)] = f"{schema}.{real_name}"
    except Exception as e:
        print(f"[MigrationAgent] dbt sources.yml parse error: {e}")
    return lookup


def parse_dbt_schema_yml(yml_content: str) -> dict:
    """
    Parse a dbt schema.yml file (model + column descriptions). Returns:
        {model_name: {"description": str, "columns": {col_name: description}}}
    """
    import yaml
    result = {}
    try:
        data = yaml.safe_load(yml_content) or {}
        for model in (data.get("models") or []):
            name = model.get("name", "")
            cols = {c.get("name", ""): c.get("description", "") for c in (model.get("columns") or [])}
            result[name] = {"description": model.get("description", ""), "columns": cols}
    except Exception as e:
        print(f"[MigrationAgent] dbt schema.yml parse error: {e}")
    return result


_REF_PATTERN = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_SOURCE_PATTERN = re.compile(r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_CONFIG_PATTERN = re.compile(r"\{\{\s*config\([^)]*\)\s*\}\}\s*", re.DOTALL)


def parse_dbt_model_sql(model_name: str, sql_content: str) -> dict:
    """
    Parse one dbt .sql model file. Extracts:
      - ref_dependencies: list of other model names this model depends on
      - source_dependencies: list of (source_name, table_name) tuples
      - materialized: 'table', 'view', 'incremental', etc. if a config()
        block specifies it (defaults to 'table' if not found)
      - raw_sql: the model body with the {{ config(...) }} block stripped
        (ref()/source() calls left as-is, resolved separately)

    Does NOT attempt to parse individual column-level lineage from the SQL
    body — dbt SQL can be arbitrarily complex (CTEs, window functions,
    subqueries), and reliably extracting per-column source lineage would
    require a real SQL parser, not regex. Table-level dependencies (which
    models/sources feed this model) ARE reliably extracted via ref()/
    source(), since those are simple, standardized Jinja macro calls.
    """
    ref_deps = list(dict.fromkeys(_REF_PATTERN.findall(sql_content)))
    source_deps = list(dict.fromkeys(_SOURCE_PATTERN.findall(sql_content)))

    materialized = "table"
    config_match = re.search(r"config\(([^)]*)\)", sql_content)
    if config_match:
        mat_match = re.search(r"materialized\s*=\s*['\"]([^'\"]+)['\"]", config_match.group(1))
        if mat_match:
            materialized = mat_match.group(1)

    raw_sql = _CONFIG_PATTERN.sub("", sql_content).strip()

    return {
        "name": model_name,
        "ref_dependencies": ref_deps,
        "source_dependencies": source_deps,
        "materialized": materialized,
        "raw_sql": raw_sql,
    }


def resolve_dbt_model_sql(model: dict, all_models: dict, source_lookup: dict, warehouse_schema: str) -> str:
    """
    Replace every {{ ref('x') }} and {{ source('a','b') }} in a model's raw
    SQL with a real, resolved table reference, producing valid standalone
    SQL with no Jinja left in it.

    ref('x') -> "{warehouse_schema}.x" (assumes x is/will be deployed into
    the same warehouse schema as this model, since dbt's ref() always
    points at another model in the same project).

    source('a','b') -> resolved from source_lookup (from sources.yml) if
    found; otherwise falls back to "staging.stg_b" (the same source-table
    naming convention already confirmed for Informatica migrations), with
    a REVIEW comment since we couldn't confirm the real location.
    """
    sql = model["raw_sql"]

    for ref_name in model["ref_dependencies"]:
        if ref_name in all_models:
            replacement = f"{warehouse_schema}.{ref_name}"
        else:
            replacement = f"{warehouse_schema}.{ref_name} /* REVIEW: '{ref_name}' not found among parsed models */"
        sql = re.sub(
            r"\{\{\s*ref\(\s*['\"]" + re.escape(ref_name) + r"['\"]\s*\)\s*\}\}",
            replacement, sql
        )

    for src_name, tbl_name in model["source_dependencies"]:
        resolved = source_lookup.get((src_name, tbl_name))
        if resolved:
            replacement = resolved
        else:
            replacement = f"staging.stg_{tbl_name} /* REVIEW: source '{src_name}.{tbl_name}' not found in sources.yml, assumed staging convention */"
        sql = re.sub(
            r"\{\{\s*source\(\s*['\"]" + re.escape(src_name) + r"['\"]\s*,\s*['\"]" + re.escape(tbl_name) + r"['\"]\s*\)\s*\}\}",
            replacement, sql
        )

    return sql


def topological_sort_dbt_models(models: dict) -> list:
    """
    Sort dbt models so every model appears AFTER all models it depends on
    (via ref()) — critical because, unlike Informatica mappings (mostly
    independent target tables), dbt models form a real dependency DAG.
    Deploying them out of order means a downstream model's SQL would
    reference a table that doesn't exist yet.

    Uses Kahn's algorithm. Raises ValueError if a circular dependency is
    detected (shouldn't happen in a valid dbt project, but dbt itself
    would refuse to run such a project too, so surfacing it rather than
    silently picking an arbitrary order is the right behavior).

    Only considers ref() dependencies (model-to-model) — source()
    dependencies point outside the model graph entirely, not to something
    being deployed in this same run.
    """
    in_degree = {name: 0 for name in models}
    graph = {name: [] for name in models}

    for name, model in models.items():
        for dep in model["ref_dependencies"]:
            if dep in models:
                graph[dep].append(name)
                in_degree[name] += 1

    queue = sorted([name for name, deg in in_degree.items() if deg == 0])
    ordered = []

    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for downstream in sorted(graph[current]):
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                queue.append(downstream)
        queue.sort()

    if len(ordered) != len(models):
        remaining = set(models.keys()) - set(ordered)
        raise ValueError(f"Circular dependency detected among dbt models: {remaining}")

    return ordered


def parse_dbt_project(sql_files: dict, yml_files: dict) -> dict:
    """
    Parse a full dbt project upload.

    sql_files: {filename: content} for every uploaded .sql model file
               (model name = filename without .sql extension, per dbt convention)
    yml_files: {filename: content} for every uploaded .yml file (sources.yml,
               schema.yml, or any dbt-allowed filename — distinguished by
               checking for a top-level "sources:" or "models:" key, not
               filename, since dbt allows arbitrary yml filenames)

    Returns:
        {
          "success": True,
          "models": [...],              # parsed model dicts, in deployment order
          "deployment_order": [...],    # list of model names, topologically sorted
          "mappings": [...],            # table-level lineage for the Mappings UI
          "gaps": [...],                # sources referenced but not found in sources.yml
        }
    """
    source_lookup = {}
    schema_docs = {}
    for fname, content in yml_files.items():
        try:
            import yaml
            data = yaml.safe_load(content) or {}
        except Exception:
            continue
        if "sources" in data:
            source_lookup.update(parse_dbt_sources_yml(content))
        if "models" in data:
            schema_docs.update(parse_dbt_schema_yml(content))

    models = {}
    for fname, content in sql_files.items():
        if not fname.endswith(".sql"):
            continue
        model_name = fname.rsplit("/", 1)[-1][:-4]  # strip path and .sql
        models[model_name] = parse_dbt_model_sql(model_name, content)

    try:
        deployment_order = topological_sort_dbt_models(models)
    except ValueError as e:
        return {"success": False, "error": str(e), "models": [], "deployment_order": [], "mappings": [], "gaps": []}

    # Table-level lineage for the Mappings UI — one entry per model showing
    # what it depends on. Column-level lineage isn't attempted (see
    # parse_dbt_model_sql's docstring for why).
    mappings = []
    gaps = []
    for name in deployment_order:
        model = models[name]
        upstream = list(model["ref_dependencies"])
        for src_name, tbl_name in model["source_dependencies"]:
            if (src_name, tbl_name) in source_lookup:
                upstream.append(source_lookup[(src_name, tbl_name)])
            else:
                upstream.append(f"{src_name}.{tbl_name} (UNRESOLVED)")
                gaps.append({
                    "column": f"{name} (source)",
                    "table": name,
                    "reason": f"source('{src_name}', '{tbl_name}') has no matching entry in sources.yml"
                })
        mappings.append({
            "target": name,
            "source": ", ".join(upstream) if upstream else "(no dependencies — likely a seed or root source)",
            "materialized": model["materialized"],
            "description": schema_docs.get(name, {}).get("description", ""),
            # Carried through so /migration/generate-sql can regenerate SQL
            # later without needing the original .sql files re-uploaded —
            # same round-trip principle as Informatica's mappings list.
            "raw_sql": model["raw_sql"],
            "ref_dependencies": model["ref_dependencies"],
            "source_dependencies": model["source_dependencies"],
        })

    return {
        "success": True,
        "source_lookup_display": {f"{k[0]}.{k[1]}": v for k, v in source_lookup.items()},
        "models": [models[name] for name in deployment_order],
        "deployment_order": deployment_order,
        "source_lookup": source_lookup,
        "mappings": mappings,
        "gaps": gaps,
    }


def generate_sql_from_dbt_models(parsed_project: dict, warehouse_schema: str = "warehouse") -> dict:
    """
    Generate deployable SQL scripts from a parsed dbt project, in the exact
    {name, label, schema, sql} shape pipeline_executor.execute_warehouse_scripts()
    expects — same contract as generate_sql_scripts() (the Informatica path),
    so this plugs into the same approval/deploy flow with no new endpoint
    logic needed.

    Unlike the Informatica path, this does NOT ask an AI to reconstruct SQL
    from column-level derivations — dbt models already ARE real, tested SQL.
    Each script replicates dbt's own default 'table' materialization
    behavior (full refresh): DROP TABLE IF EXISTS + CREATE TABLE AS SELECT,
    using the model's actual SQL with ref()/source() resolved to real table
    references.

    Models with materialized='incremental' are flagged rather than
    full-refreshed silently — incremental models rely on dbt's
    is_incremental() Jinja macro for conditional logic that isn't safely
    resolvable without running inside dbt itself, so guessing at that logic
    would risk silently wrong behavior on a re-run.

    CRITICAL: scripts are returned in the project's topologically-sorted
    deployment order. execute_warehouse_scripts() runs scripts sequentially
    in the order given, so this order must be preserved all the way through
    to deployment — do NOT split dbt models into independent per-model
    pipelines the way Informatica migrations are, since a downstream
    model's SQL directly depends on an upstream model already existing.
    """
    if not parsed_project.get("success"):
        return {"success": False, "error": parsed_project.get("error", "dbt project parsing failed")}

    models_by_name = {m["name"]: m for m in parsed_project["models"]}
    source_lookup = parsed_project.get("source_lookup", {})
    scripts = []

    for name in parsed_project["deployment_order"]:
        model = models_by_name[name]
        resolved_sql = resolve_dbt_model_sql(model, models_by_name, source_lookup, warehouse_schema)

        if model["materialized"] == "incremental":
            sql = (
                f"-- REVIEW: this dbt model uses materialized='incremental', which relies on\n"
                f"-- dbt's is_incremental() macro for conditional logic (typically a WHERE\n"
                f"-- clause limiting to new/changed rows) that this migration could not safely\n"
                f"-- resolve automatically. Below is a FULL REFRESH equivalent as a starting\n"
                f"-- point \u2014 review and add the correct incremental filter before relying on this.\n\n"
                f"DROP TABLE IF EXISTS {warehouse_schema}.{name};\n"
                f"CREATE TABLE {warehouse_schema}.{name} AS\n{resolved_sql};"
            )
        else:
            sql = (
                f"-- Replicates dbt's default table materialization (full refresh),\n"
                f"-- matching this model's original materialized='{model['materialized']}' config.\n"
                f"DROP TABLE IF EXISTS {warehouse_schema}.{name};\n"
                f"CREATE TABLE {warehouse_schema}.{name} AS\n{resolved_sql};"
            )

        scripts.append({
            "name": name,
            "label": name.replace("_", " ").title(),
            "schema": warehouse_schema,
            "sql": sql,
            "materialized": model["materialized"],
        })

    return {"success": True, "sql_scripts": {"scripts": scripts}, "deployment_order": parsed_project["deployment_order"]}


def run_dbt_deployment(
    target_connector_config: dict,
    staging_schema: str,
    warehouse_schema: str,
    sql_scripts: dict,
    pipeline_id: str,
    workspace_id: str,
) -> dict:
    """
    Dedicated dbt deployment flow — deliberately DIFFERENT from
    run_migration_deployment() (the Informatica path). dbt's own convention
    is that source() tables already exist in the target warehouse (loaded
    there by a separate tool like Fivetran/Airbyte — dbt itself never does
    extraction). So this skips ETLAgent entirely and runs QualityAgent ->
    ExecutionAgent -> RecoveryAgent -> AnalyticsAgent directly against the
    already-resolved model SQL.

    CRITICAL: `sql_scripts["scripts"]` MUST already be in the project's
    topologically-sorted deployment order (from generate_sql_from_dbt_models)
    — this function does not re-order anything, and ExecutionAgent runs
    scripts strictly in the order given. Running dbt models out of order
    means a downstream model could reference a table that doesn't exist yet.

    If your actual migration involves moving the underlying source data to
    a NEW physical warehouse (not just porting the transformation logic to
    run against data that's already there), this assumption is wrong and
    an extraction step would be needed first — this function does not
    handle that case.

    Returns the same result shape as run_migration_deployment() minus the
    "staging" key (since no extraction happens):
        {"success": bool, "warehouse": ..., "quality": ..., "analytics": ...,
         "recovery": ..., "log": [...], "pipeline_log": [...]}
    """
    from agents.base import AgentContext
    from agents.quality_agent import QualityAgent
    from agents.execution_agent import ExecutionAgent
    from agents.recovery_agent import RecoveryAgent
    from agents.analytics_agent import AnalyticsAgent

    log = []

    def _log(msg):
        log.append(msg)
        print(f"[dbtDeploy] {msg}")

    try:
        ctx = AgentContext(
            pipeline_id=pipeline_id,
            workspace_id=workspace_id,
            connector_config=target_connector_config,
            source_schema=staging_schema,
            source_tables=[],
            source_columns={},
            source_description="dbt project deployment via Migration Agent",
            business_requirements="",
            target_config=target_connector_config,
            staging_schema=staging_schema,
            warehouse_schema=warehouse_schema,
        )
        ctx.sql_scripts = sql_scripts
        ctx.data_model = {}
    except Exception as e:
        return {"success": False, "stage": "context_setup", "error": str(e), "log": log}

    _log("Skipping extraction — dbt source() tables are assumed already loaded "
         "in the target warehouse, per dbt's own convention (dbt never extracts data itself).")

    _log("Running QualityAgent...")
    QualityAgent().run(ctx)
    quality_data = ctx.quality_result or {}
    _log(f"Quality: {quality_data.get('status', 'unknown')} ({quality_data.get('score', '?')}%)")

    n_models = len(sql_scripts.get("scripts", []))
    _log(f"Running ExecutionAgent — {n_models} dbt model(s) in dependency order...")
    ExecutionAgent().run(ctx)
    exec_result = ctx.execution_result or {}

    failed_scripts = [s for s in exec_result.get("scripts", []) if not s.get("success", True)]
    if failed_scripts:
        _log(f"{len(failed_scripts)} model(s) failed — running RecoveryAgent...")
        RecoveryAgent().run(ctx)
        if ctx.recovery_result and ctx.recovery_result.get("recovered", 0) > 0:
            _log("Recovery fixed model(s) — retrying execution...")
            ExecutionAgent().run(ctx)
            exec_result = ctx.execution_result or {}

    AnalyticsAgent().run(ctx)

    success = exec_result.get("success", False)
    _log(("✓" if success else "✗") + " dbt deployment finished")

    return {
        "success":      success,
        "warehouse":    exec_result,
        "quality":      quality_data,
        "analytics":    ctx.analytics_result,
        "recovery":     ctx.recovery_result,
        "log":          log,
        "pipeline_log": ctx.pipeline_log,
    }