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


def parse_informatica_xml(xml_content: str) -> list:
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
                    "mapped":         True
                }
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
                match = table_mappings.get(full)
                if match and match.get("needs_review"):
                    # Traced to an unresolvable transformation (e.g. a Lookup
                    # with no discoverable table) — don't treat this as mapped;
                    # surface it plainly rather than referencing a fake table.
                    col_lines.append(
                        f"  {cname} <- UNRESOLVED: {match.get('review_reason', 'source could not be traced to a real table')}"
                    )
                elif match:
                    mapped_count += 1
                    expr = match["source"] if match.get("transformation") == "direct" else match["transformation"]
                    stg_note = ""
                    if match.get("source_table"):
                        stg_ref = _quoted_staging_ref(staging_schema, _staging_table_name(match['source_table']))
                        stg_note = f" (from {stg_ref})"
                    col_lines.append(f"  {cname} <- {expr}{stg_note}")
                elif full in gap_lookup:
                    mapped_count += 1
                    col_lines.append(f"  {cname} <- {gap_lookup[full]}  (user-resolved)")
                else:
                    col_lines.append(f"  {cname} <- (unmapped — leave NULL / apply default)")

            if staging_tables_used:
                quoted_refs = [_quoted_staging_ref(staging_schema, t) for t in staging_tables_used]
                staging_list_text = ", ".join(quoted_refs)
                staging_instruction = (
                    f"Source staging table(s) — use these EXACT references, quotes included, "
                    f"in your FROM/JOIN clauses (they are case-sensitive; do not lowercase or "
                    f"re-derive them): {staging_list_text}\n"
                    f"If more than one staging table is listed, JOIN them on whatever key "
                    f"relates them (commonly a shared code/id column) — each column derivation "
                    f"below notes which staging table it actually comes from."
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
Column derivations (each notes which staging table it comes from, unless marked user-resolved):
{chr(10).join(col_lines)}

Write ONE complete, runnable PostgreSQL script for this table containing:
1. CREATE TABLE IF NOT EXISTS {warehouse_schema}.{tname} (...) with appropriate
   column types inferred from the derivations above.
2. INSERT INTO {warehouse_schema}.{tname} (...) SELECT ... FROM the staging table(s)
   listed above (joined together if more than one), using the EXACT quoted
   references given — do not strip the quotes or change the case, since
   Postgres treats quoted identifiers as case-sensitive and an unquoted or
   re-cased reference will silently point at a different, nonexistent table.
   Apply the column derivations exactly as given (use provided
   expressions/resolutions verbatim where present).
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