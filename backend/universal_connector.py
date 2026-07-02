"""
universal_connector.py — AIBridge Universal Database Layer

Supports ALL databases for both source extraction and warehouse writing.
Replaces the hardcoded psycopg2 calls in pipeline_executor.py

Supported:
  ON-PREM:  PostgreSQL, MySQL, SQL Server, Oracle, SQLite
  CLOUD:    Snowflake, BigQuery, Redshift, Azure SQL
  FILES:    CSV, Excel (via DuckDB)

v1.0: Initial implementation — universal connection layer
"""

import os
import re
import pandas as pd
from datetime import datetime
from typing import Optional


# ── Connection factory ────────────────────────────────────────────────────────

def get_universal_connection(config: dict):
    """
    Returns a connection object for any supported database.
    config must have 'connector_type' key.
    """
    ct = config.get("connector_type", "postgres").lower()

    if ct in ("postgres", "postgresql"):
        return _pg_connect(config)
    elif ct == "mysql":
        return _mysql_connect(config)
    elif ct in ("sqlserver", "mssql"):
        return _sqlserver_connect(config)
    elif ct == "oracle":
        return _oracle_connect(config)
    elif ct == "sqlite":
        return _sqlite_connect(config)
    elif ct == "snowflake":
        return _snowflake_connect(config)
    elif ct in ("redshift",):
        return _pg_connect(config)  # Redshift uses PostgreSQL protocol
    elif ct in ("azuresql",):
        return _sqlserver_connect(config)  # Azure SQL uses SQL Server protocol
    elif ct == "bigquery":
        return _bigquery_connect(config)
    else:
        raise ValueError(f"Unsupported connector type: {ct}")


def get_sqlalchemy_engine(config: dict):
    """
    Returns a SQLAlchemy engine for pandas read/write operations.
    Used for cross-DB transfers and bulk loads.
    """
    from sqlalchemy import create_engine
    ct = config.get("connector_type", "postgres").lower()

    if ct in ("postgres", "postgresql", "redshift"):
        url = (f"postgresql+psycopg2://{config['username']}:{config['password']}"
               f"@{config['host']}:{config.get('port', 5432)}/{config['database']}")
        return create_engine(url)

    elif ct == "mysql":
        url = (f"mysql+mysqlconnector://{config['username']}:{config['password']}"
               f"@{config['host']}:{config.get('port', 3306)}/{config['database']}")
        return create_engine(url)

    elif ct in ("sqlserver", "mssql", "azuresql"):
        url = (f"mssql+pyodbc://{config['username']}:{config['password']}"
               f"@{config['host']}:{config.get('port', 1433)}/{config['database']}"
               f"?driver=ODBC+Driver+17+for+SQL+Server")
        return create_engine(url)

    elif ct == "oracle":
        url = (f"oracle+cx_oracle://{config['username']}:{config['password']}"
               f"@{config['host']}:{config.get('port', 1521)}/{config.get('service_name', config['database'])}")
        return create_engine(url)

    elif ct == "sqlite":
        url = f"sqlite:///{config['file_path']}"
        return create_engine(url)

    elif ct == "snowflake":
        url = (f"snowflake://{config['username']}:{config['password']}"
               f"@{config['account']}/{config['database']}/{config.get('schema', 'PUBLIC')}"
               f"?warehouse={config.get('warehouse', 'COMPUTE_WH')}")
        from sqlalchemy.dialects import registry
        registry.load('snowflake')
        return create_engine(url)

    elif ct == "bigquery":
        from google.oauth2 import service_account
        import json
        creds_dict = json.loads(config["credentials_json"])
        creds = service_account.Credentials.from_service_account_info(creds_dict)
        from sqlalchemy_bigquery import BigQueryDialect
        url = f"bigquery://{config['project_id']}/{config['dataset_id']}"
        return create_engine(url, credentials_base=creds)

    else:
        raise ValueError(f"No SQLAlchemy engine for: {ct}")


# ── Individual DB connections ─────────────────────────────────────────────────

def _pg_connect(config: dict):
    import psycopg2
    return psycopg2.connect(
        host=config.get("host", "localhost"),
        port=int(config.get("port", 5432)),
        dbname=config.get("database") or config.get("database_name"),
        user=config.get("username"),
        password=config.get("password")
    )


def _mysql_connect(config: dict):
    import mysql.connector
    return mysql.connector.connect(
        host=config.get("host", "localhost"),
        port=int(config.get("port", 3306)),
        database=config.get("database") or config.get("database_name"),
        user=config.get("username"),
        password=config.get("password"),
        connection_timeout=30
    )


def _sqlserver_connect(config: dict):
    import pyodbc
    conn_str = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={config.get('host')},{config.get('port', 1433)};"
        f"DATABASE={config.get('database') or config.get('database_name')};"
        f"UID={config.get('username')};"
        f"PWD={config.get('password')};"
        f"Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


def _oracle_connect(config: dict):
    import cx_Oracle
    dsn = cx_Oracle.makedsn(
        config.get("host"),
        int(config.get("port", 1521)),
        service_name=config.get("service_name") or config.get("database") or config.get("database_name")
    )
    return cx_Oracle.connect(
        user=config.get("username"),
        password=config.get("password"),
        dsn=dsn
    )


def _sqlite_connect(config: dict):
    import sqlite3
    return sqlite3.connect(config.get("file_path", ":memory:"))


def _snowflake_connect(config: dict):
    import snowflake.connector
    return snowflake.connector.connect(
        account=config.get("account"),
        user=config.get("username"),
        password=config.get("password"),
        database=config.get("database") or config.get("database_name"),
        schema=config.get("schema", "PUBLIC"),
        warehouse=config.get("warehouse", "COMPUTE_WH"),
        login_timeout=30
    )


def _bigquery_connect(config: dict):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    import json
    creds_dict = json.loads(config.get("credentials_json", "{}"))
    creds = service_account.Credentials.from_service_account_info(creds_dict)
    return bigquery.Client(project=config.get("project_id"), credentials=creds)


# ── Universal cursor wrapper ──────────────────────────────────────────────────

class UniversalCursor:
    """
    Wraps different DB cursors with a common interface.
    Handles dialect differences (paramstyle, quoting, etc.)
    """
    def __init__(self, conn, connector_type: str):
        self.conn           = conn
        self.connector_type = connector_type.lower()
        self._cursor        = None
        self._is_bigquery   = (self.connector_type == "bigquery")

    def __enter__(self):
        if not self._is_bigquery:
            self._cursor = self.conn.cursor()
        return self

    def __exit__(self, *args):
        if self._cursor:
            try:
                self._cursor.close()
            except Exception:
                pass

    def execute(self, sql: str, params=None):
        if self._is_bigquery:
            query = self.conn.query(sql)
            self._last_result = query.result()
            return
        if params:
            self._cursor.execute(sql, params)
        else:
            self._cursor.execute(sql)

    def fetchall(self):
        if self._is_bigquery:
            return [list(row) for row in self._last_result]
        return self._cursor.fetchall()

    def fetchone(self):
        if self._is_bigquery:
            rows = list(self._last_result)
            return rows[0] if rows else None
        return self._cursor.fetchone()

    @property
    def description(self):
        if self._is_bigquery:
            return None
        return self._cursor.description


# ── Test connection ───────────────────────────────────────────────────────────

def test_connection(config: dict) -> dict:
    """Test if a database connection works."""
    ct = config.get("connector_type", "postgres").lower()
    try:
        if ct == "bigquery":
            client = _bigquery_connect(config)
            list(client.list_datasets())
            return {"success": True, "message": f"Connected to BigQuery successfully"}

        conn = get_universal_connection(config)
        conn.close()
        db_names = {
            "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
            "mysql": "MySQL", "sqlserver": "SQL Server", "mssql": "SQL Server",
            "oracle": "Oracle", "sqlite": "SQLite", "snowflake": "Snowflake",
            "redshift": "Amazon Redshift", "azuresql": "Azure SQL",
        }
        name = db_names.get(ct, ct.title())
        return {"success": True, "message": f"Connected to {name} successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ── Schema discovery ──────────────────────────────────────────────────────────

def discover_schemas(config: dict) -> dict:
    """List all schemas/databases in the connection."""
    ct = config.get("connector_type", "postgres").lower()
    try:
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(config)
            cur  = conn.cursor()
            cur.execute("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
                  AND schema_name NOT LIKE 'pg_%'
                ORDER BY schema_name
            """)
            schemas = [r[0] for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "schemas": schemas}

        elif ct == "mysql":
            conn = _mysql_connect(config)
            cur  = conn.cursor()
            cur.execute("SHOW DATABASES")
            schemas = [r[0] for r in cur.fetchall()
                       if r[0] not in ('information_schema', 'mysql', 'performance_schema', 'sys')]
            cur.close(); conn.close()
            return {"success": True, "schemas": schemas}

        elif ct in ("sqlserver", "mssql", "azuresql"):
            conn = _sqlserver_connect(config)
            cur  = conn.cursor()
            cur.execute("SELECT name FROM sys.schemas WHERE name NOT LIKE 'db_%' ORDER BY name")
            schemas = [r[0] for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "schemas": schemas}

        elif ct == "oracle":
            conn = _oracle_connect(config)
            cur  = conn.cursor()
            cur.execute("SELECT username FROM all_users ORDER BY username")
            schemas = [r[0] for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "schemas": schemas}

        elif ct == "snowflake":
            conn = _snowflake_connect(config)
            cur  = conn.cursor()
            cur.execute("SHOW SCHEMAS")
            schemas = [r[1] for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "schemas": schemas}

        elif ct == "bigquery":
            client   = _bigquery_connect(config)
            datasets = list(client.list_datasets())
            schemas  = [d.dataset_id for d in datasets]
            return {"success": True, "schemas": schemas}

        else:
            return {"success": True, "schemas": ["default"]}

    except Exception as e:
        return {"success": False, "error": str(e), "schemas": []}


def discover_tables(config: dict, schema: str) -> dict:
    """List all tables in a schema."""
    ct = config.get("connector_type", "postgres").lower()
    try:
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(config)
            cur  = conn.cursor()
            cur.execute("""
                SELECT t.table_name,
                    pg_size_pretty(pg_total_relation_size(
                        quote_ident(t.table_schema)||'.'||quote_ident(t.table_name))) AS size,
                    (SELECT COUNT(*) FROM information_schema.columns c
                     WHERE c.table_schema = t.table_schema
                       AND c.table_name   = t.table_name) AS col_count
                FROM information_schema.tables t
                WHERE t.table_schema = %s AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_name
            """, (schema,))
            tables = [{"name": r[0], "size": r[1], "col_count": r[2]}
                      for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "tables": tables, "schema": schema}

        elif ct == "mysql":
            conn = _mysql_connect(config)
            cur  = conn.cursor()
            cur.execute(f"SHOW TABLES FROM `{schema}`")
            tables = [{"name": r[0], "size": "N/A", "col_count": 0}
                      for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "tables": tables, "schema": schema}

        elif ct in ("sqlserver", "mssql", "azuresql"):
            conn = _sqlserver_connect(config)
            cur  = conn.cursor()
            cur.execute(f"""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = '{schema}' AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
            """)
            tables = [{"name": r[0], "size": "N/A", "col_count": 0}
                      for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "tables": tables, "schema": schema}

        elif ct == "oracle":
            conn = _oracle_connect(config)
            cur  = conn.cursor()
            cur.execute(f"""
                SELECT table_name FROM all_tables
                WHERE owner = '{schema.upper()}'
                ORDER BY table_name
            """)
            tables = [{"name": r[0], "size": "N/A", "col_count": 0}
                      for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "tables": tables, "schema": schema}

        elif ct == "snowflake":
            conn = _snowflake_connect(config)
            cur  = conn.cursor()
            cur.execute(f"SHOW TABLES IN SCHEMA {schema}")
            tables = [{"name": r[1], "size": "N/A", "col_count": 0}
                      for r in cur.fetchall()]
            cur.close(); conn.close()
            return {"success": True, "tables": tables, "schema": schema}

        elif ct == "bigquery":
            client  = _bigquery_connect(config)
            dataset = client.dataset(schema)
            bq_tables = list(client.list_tables(dataset))
            tables  = [{"name": t.table_id, "size": "N/A", "col_count": 0}
                       for t in bq_tables]
            return {"success": True, "tables": tables, "schema": schema}

        else:
            return {"success": True, "tables": [], "schema": schema}

    except Exception as e:
        return {"success": False, "error": str(e), "tables": []}


def discover_columns(config: dict, schema: str, table_names: list) -> dict:
    """Discover columns for given tables."""
    ct = config.get("connector_type", "postgres").lower()
    if not table_names:
        return {"success": True, "tables": {}}

    try:
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(config)
            cur  = conn.cursor()
            cur.execute("""
                SELECT c.table_name, c.column_name, c.data_type, c.is_nullable,
                       CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 'PK'
                            WHEN tc.constraint_type = 'FOREIGN KEY' THEN 'FK'
                            ELSE NULL END AS key_type
                FROM information_schema.columns c
                LEFT JOIN information_schema.key_column_usage ku
                       ON ku.table_schema = c.table_schema
                      AND ku.table_name   = c.table_name
                      AND ku.column_name  = c.column_name
                LEFT JOIN information_schema.table_constraints tc
                       ON tc.constraint_name = ku.constraint_name
                      AND tc.table_schema    = c.table_schema
                      AND tc.constraint_type IN ('PRIMARY KEY','FOREIGN KEY')
                WHERE c.table_schema = %s AND c.table_name = ANY(%s)
                ORDER BY c.table_name, c.ordinal_position
            """, (schema, table_names))
            rows = cur.fetchall()
            cur.close(); conn.close()
            result = {}
            for table, col, dtype, nullable, key in rows:
                result.setdefault(table, []).append({
                    "name": col, "type": dtype,
                    "nullable": (nullable == "YES"), "key": key
                })
            return {"success": True, "tables": result}

        elif ct == "mysql":
            conn = _mysql_connect(config)
            cur  = conn.cursor()
            result = {}
            for table in table_names:
                cur.execute(f"DESCRIBE `{schema}`.`{table}`")
                rows = cur.fetchall()
                result[table] = [
                    {"name": r[0], "type": r[1],
                     "nullable": r[2] == 'YES',
                     "key": 'PK' if r[3] == 'PRI' else ('FK' if r[3] == 'MUL' else None)}
                    for r in rows
                ]
            cur.close(); conn.close()
            return {"success": True, "tables": result}

        elif ct in ("sqlserver", "mssql", "azuresql"):
            conn = _sqlserver_connect(config)
            cur  = conn.cursor()
            result = {}
            for table in table_names:
                cur.execute(f"""
                    SELECT c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE,
                           CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 'PK' ELSE NULL END
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    LEFT JOIN (
                        SELECT ku.COLUMN_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                            ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' AND tc.TABLE_NAME = '{table}'
                    ) pk ON pk.COLUMN_NAME = c.COLUMN_NAME
                    WHERE c.TABLE_SCHEMA = '{schema}' AND c.TABLE_NAME = '{table}'
                    ORDER BY c.ORDINAL_POSITION
                """)
                result[table] = [
                    {"name": r[0], "type": r[1],
                     "nullable": r[2] == 'YES', "key": r[3]}
                    for r in cur.fetchall()
                ]
            cur.close(); conn.close()
            return {"success": True, "tables": result}

        elif ct == "oracle":
            conn = _oracle_connect(config)
            cur  = conn.cursor()
            result = {}
            for table in table_names:
                cur.execute(f"""
                    SELECT column_name, data_type, nullable
                    FROM all_tab_columns
                    WHERE owner = '{schema.upper()}' AND table_name = '{table.upper()}'
                    ORDER BY column_id
                """)
                result[table] = [
                    {"name": r[0], "type": r[1],
                     "nullable": r[2] == 'Y', "key": None}
                    for r in cur.fetchall()
                ]
            cur.close(); conn.close()
            return {"success": True, "tables": result}

        elif ct == "snowflake":
            conn = _snowflake_connect(config)
            cur  = conn.cursor()
            result = {}
            for table in table_names:
                cur.execute(f"DESCRIBE TABLE {schema}.{table}")
                result[table] = [
                    {"name": r[0], "type": r[1], "nullable": True, "key": None}
                    for r in cur.fetchall()
                ]
            cur.close(); conn.close()
            return {"success": True, "tables": result}

        elif ct == "bigquery":
            client = _bigquery_connect(config)
            result = {}
            for table in table_names:
                tbl_ref = client.get_table(f"{config['project_id']}.{schema}.{table}")
                result[table] = [
                    {"name": f.name, "type": str(f.field_type),
                     "nullable": f.mode != 'REQUIRED', "key": None}
                    for f in tbl_ref.schema
                ]
            return {"success": True, "tables": result}

        else:
            return {"success": True, "tables": {}}

    except Exception as e:
        return {"success": False, "error": str(e), "tables": {}}


# ── Universal extract ─────────────────────────────────────────────────────────

def extract_table_universal(
    source_config: dict,
    target_config: dict,
    source_schema: str,
    table: str,
    staging_schema: str,
    selected_columns: list = None
) -> dict:
    """
    Extract one table from ANY source database into PostgreSQL staging.
    Source can be any supported DB.
    Target (staging) is always PostgreSQL.
    """
    stg = f"stg_{table}"

    try:
        src_ct  = source_config.get("connector_type", "postgres").lower()
        tgt_ct  = target_config.get("connector_type", "postgres").lower()
        same_db = _is_same_db(source_config, target_config)

        # Column selection
        if selected_columns:
            col_sql = ", ".join(f'"{c}"' for c in selected_columns)
        else:
            col_sql = "*"

        # ── Same DB PostgreSQL → fast SQL copy ────────────────────────────────
        if same_db and src_ct in ("postgres", "postgresql", "redshift"):
            import psycopg2
            conn = _pg_connect(target_config)
            conn.autocommit = False
            cur  = conn.cursor()
            cur.execute(f"""
                DROP TABLE IF EXISTS "{staging_schema}"."{stg}";
                CREATE TABLE "{staging_schema}"."{stg}" AS
                SELECT {col_sql}, CURRENT_TIMESTAMP AS _loaded_at
                FROM "{source_schema}"."{table}";
            """)
            cur.execute(f'SELECT COUNT(*) FROM "{staging_schema}"."{stg}"')
            rows = cur.fetchone()[0]
            conn.commit()
            cur.close(); conn.close()
            return {"success": True, "rows": rows, "method": "same_db_sql"}

        # ── Different DB or non-PostgreSQL source → pandas transfer ──────────
        else:
            df = _read_table_as_dataframe(source_config, source_schema, table, selected_columns)
            df["_loaded_at"] = pd.Timestamp.utcnow()

            # Write to PostgreSQL staging
            from sqlalchemy import create_engine
            tgt_url = (
                f"postgresql+psycopg2://{target_config['username']}:{target_config['password']}"
                f"@{target_config['host']}:{target_config.get('port', 5432)}/{target_config['database']}"
            )
            engine = create_engine(tgt_url)
            df.to_sql(stg, engine, schema=staging_schema,
                      if_exists="replace", index=False,
                      chunksize=10000, method="multi")
            engine.dispose()

            return {"success": True, "rows": len(df), "method": "pandas_transfer"}

    except Exception as e:
        return {"success": False, "error": str(e), "rows": 0}


def _read_table_as_dataframe(config: dict, schema: str, table: str,
                              selected_columns: list = None) -> pd.DataFrame:
    """Read any database table into a pandas DataFrame."""
    ct = config.get("connector_type", "postgres").lower()

    if selected_columns:
        col_sql = ", ".join(f'"{c}"' for c in selected_columns)
    else:
        col_sql = "*"

    if ct in ("postgres", "postgresql", "redshift"):
        conn  = _pg_connect(config)
        query = f'SELECT {col_sql} FROM "{schema}"."{table}"'
        df    = pd.read_sql(query, conn)
        conn.close()
        return df

    elif ct == "mysql":
        conn  = _mysql_connect(config)
        query = f"SELECT {col_sql} FROM `{schema}`.`{table}`"
        df    = pd.read_sql(query, conn)
        conn.close()
        return df

    elif ct in ("sqlserver", "mssql", "azuresql"):
        conn  = _sqlserver_connect(config)
        query = f"SELECT {col_sql} FROM [{schema}].[{table}]"
        df    = pd.read_sql(query, conn)
        conn.close()
        return df

    elif ct == "oracle":
        conn  = _oracle_connect(config)
        query = f'SELECT {col_sql} FROM "{schema.upper()}"."{table.upper()}"'
        df    = pd.read_sql(query, conn)
        conn.close()
        return df

    elif ct == "sqlite":
        conn  = _sqlite_connect(config)
        query = f"SELECT {col_sql} FROM [{table}]"
        df    = pd.read_sql(query, conn)
        conn.close()
        return df

    elif ct == "snowflake":
        conn  = _snowflake_connect(config)
        query = f"SELECT {col_sql} FROM {schema}.{table}"
        df    = pd.read_sql(query, conn)
        conn.close()
        return df

    elif ct == "bigquery":
        client = _bigquery_connect(config)
        query  = f"SELECT {col_sql} FROM `{config['project_id']}.{schema}.{table}`"
        df     = client.query(query).to_dataframe()
        return df

    else:
        raise ValueError(f"Cannot read from connector type: {ct}")


# ── Schema text for AI ────────────────────────────────────────────────────────

def get_schema_text_for_ai(config: dict, schema: str,
                            table_names: list = None) -> str:
    """
    Get schema as text for AI prompts.
    Works for all databases.
    """
    try:
        if not table_names:
            tables_result = discover_tables(config, schema)
            table_names   = [t["name"] for t in tables_result.get("tables", [])]

        if not table_names:
            return f"No tables found in {schema}"

        cols_result = discover_columns(config, schema, table_names)
        tables      = cols_result.get("tables", {})

        lines = []
        for table, cols in tables.items():
            col_strs = []
            for c in cols:
                cs = f"{c['name']} ({c['type']})"
                if c.get("key"):
                    cs += f" [{c['key']}]"
                col_strs.append(cs)
            lines.append(f"{table}: {', '.join(col_strs)}")

        return "\n".join(lines)

    except Exception as e:
        return f"Could not discover schema: {e}"


# ── FK discovery ──────────────────────────────────────────────────────────────

def discover_foreign_keys(config: dict, schema: str) -> list:
    """Discover foreign key relationships."""
    ct = config.get("connector_type", "postgres").lower()
    try:
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(config)
            cur  = conn.cursor()
            cur.execute("""
                SELECT
                    kcu.table_name AS from_table,
                    kcu.column_name AS from_column,
                    ccu.table_name AS to_table,
                    ccu.column_name AS to_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = %s
            """, (schema,))
            fks = [{"from_table": r[0], "from_column": r[1],
                    "to_table": r[2], "to_column": r[3]}
                   for r in cur.fetchall()]
            cur.close(); conn.close()
            return fks

        elif ct == "mysql":
            conn = _mysql_connect(config)
            cur  = conn.cursor()
            cur.execute(f"""
                SELECT TABLE_NAME, COLUMN_NAME,
                       REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = '{schema}'
                AND REFERENCED_TABLE_NAME IS NOT NULL
            """)
            fks = [{"from_table": r[0], "from_column": r[1],
                    "to_table": r[2], "to_column": r[3]}
                   for r in cur.fetchall()]
            cur.close(); conn.close()
            return fks

        elif ct in ("sqlserver", "mssql", "azuresql"):
            conn = _sqlserver_connect(config)
            cur  = conn.cursor()
            cur.execute(f"""
                SELECT
                    tp.name AS from_table, cp.name AS from_column,
                    tr.name AS to_table,   cr.name AS to_column
                FROM sys.foreign_key_columns fkc
                JOIN sys.objects tp ON fkc.parent_object_id = tp.object_id
                JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id
                    AND fkc.parent_column_id = cp.column_id
                JOIN sys.objects tr ON fkc.referenced_object_id = tr.object_id
                JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id
                    AND fkc.referenced_column_id = cr.column_id
            """)
            fks = [{"from_table": r[0], "from_column": r[1],
                    "to_table": r[2], "to_column": r[3]}
                   for r in cur.fetchall()]
            cur.close(); conn.close()
            return fks

        else:
            return []

    except Exception as e:
        print(f"[UniversalConnector] Could not discover FKs: {e}")
        return []


# ── Row count ─────────────────────────────────────────────────────────────────

def get_row_count(config: dict, schema: str, table: str) -> int:
    """Get row count for a table in any database."""
    ct = config.get("connector_type", "postgres").lower()
    try:
        if ct in ("postgres", "postgresql", "redshift"):
            conn = _pg_connect(config)
            cur  = conn.cursor()
            cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
            count = cur.fetchone()[0]
            cur.close(); conn.close()
            return count

        elif ct == "mysql":
            conn = _mysql_connect(config)
            cur  = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM `{schema}`.`{table}`")
            count = cur.fetchone()[0]
            cur.close(); conn.close()
            return count

        elif ct in ("sqlserver", "mssql", "azuresql"):
            conn = _sqlserver_connect(config)
            cur  = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}]")
            count = cur.fetchone()[0]
            cur.close(); conn.close()
            return count

        elif ct == "oracle":
            conn = _oracle_connect(config)
            cur  = conn.cursor()
            cur.execute(f'SELECT COUNT(*) FROM "{schema.upper()}"."{table.upper()}"')
            count = cur.fetchone()[0]
            cur.close(); conn.close()
            return count

        elif ct == "snowflake":
            conn = _snowflake_connect(config)
            cur  = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            count = cur.fetchone()[0]
            cur.close(); conn.close()
            return count

        elif ct == "bigquery":
            client = _bigquery_connect(config)
            query  = f"SELECT COUNT(*) as cnt FROM `{config['project_id']}.{schema}.{table}`"
            result = client.query(query).result()
            return list(result)[0][0]

        else:
            return 0

    except Exception as e:
        print(f"[UniversalConnector] Row count failed for {schema}.{table}: {e}")
        return 0


# ── Warehouse row recount ─────────────────────────────────────────────────────

def recount_warehouse_rows(target_config: dict, warehouse_schema: str) -> int:
    """Count total rows in warehouse schema (PostgreSQL target always)."""
    try:
        import psycopg2
        conn = _pg_connect(target_config)
        cur  = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(n_live_tup),0) FROM pg_stat_user_tables WHERE schemaname=%s",
            (warehouse_schema,)
        )
        rows = cur.fetchone()[0] or 0
        cur.close(); conn.close()
        return int(rows)
    except Exception as e:
        print(f"[UniversalConnector] Could not recount warehouse rows: {e}")
        return 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_same_db(src: dict, tgt: dict) -> bool:
    """Check if source and target are the same database instance."""
    return (
        src.get("host") == tgt.get("host") and
        int(src.get("port", 0)) == int(tgt.get("port", 0)) and
        (src.get("database") or src.get("database_name")) ==
        (tgt.get("database") or tgt.get("database_name"))
    )


def normalize_config(connector_db_record) -> dict:
    """
    Convert a database Connector ORM record to a config dict
    that universal_connector functions understand.
    """
    return {
        "connector_type": connector_db_record.connector_type or "postgres",
        "host":           connector_db_record.host,
        "port":           connector_db_record.port,
        "database":       connector_db_record.database_name,
        "database_name":  connector_db_record.database_name,
        "username":       connector_db_record.username,
        "password":       connector_db_record.password,
        "source_schema":  connector_db_record.source_schema or "public",
    }


# ── Required packages per connector type ─────────────────────────────────────

REQUIRED_PACKAGES = {
    "postgres":   ["psycopg2-binary"],
    "postgresql": ["psycopg2-binary"],
    "mysql":      ["mysql-connector-python"],
    "sqlserver":  ["pyodbc"],
    "mssql":      ["pyodbc"],
    "oracle":     ["cx_Oracle"],
    "sqlite":     [],  # built-in
    "snowflake":  ["snowflake-connector-python", "snowflake-sqlalchemy"],
    "bigquery":   ["google-cloud-bigquery", "sqlalchemy-bigquery"],
    "redshift":   ["psycopg2-binary"],
    "azuresql":   ["pyodbc"],
}


def check_packages(connector_type: str) -> dict:
    """Check if required packages are installed for a connector type."""
    ct       = connector_type.lower()
    required = REQUIRED_PACKAGES.get(ct, [])
    missing  = []
    for pkg in required:
        try:
            __import__(pkg.replace("-", "_").split("-")[0])
        except ImportError:
            missing.append(pkg)
    return {
        "connector_type": ct,
        "required":       required,
        "missing":        missing,
        "ready":          len(missing) == 0,
        "install_cmd":    f"pip install {' '.join(missing)}" if missing else None
    }
