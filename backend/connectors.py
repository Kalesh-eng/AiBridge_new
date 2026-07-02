"""
connectors.py
Universal database connector supporting:
ON-PREM:  PostgreSQL, MySQL, SQL Server, Oracle, SQLite
CLOUD:    BigQuery, Snowflake, Redshift, Azure SQL
FILES:    CSV, Excel
"""

import os
import json
import pandas as pd
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ── Connector registry ────────────────────────────────────────────────────────

CONNECTOR_TYPES = {
    # On-Prem
    "postgres":   { "label": "PostgreSQL",      "category": "onprem", "default_port": 5432,  "icon": "🐘" },
    "mysql":      { "label": "MySQL",            "category": "onprem", "default_port": 3306,  "icon": "🐬" },
    "sqlserver":  { "label": "SQL Server",       "category": "onprem", "default_port": 1433,  "icon": "🪟" },
    "oracle":     { "label": "Oracle",           "category": "onprem", "default_port": 1521,  "icon": "🔴" },
    "sqlite":     { "label": "SQLite",           "category": "onprem", "default_port": None,  "icon": "📁" },
    # Cloud
    "bigquery":   { "label": "BigQuery",         "category": "cloud",  "default_port": None,  "icon": "☁️" },
    "snowflake":  { "label": "Snowflake",        "category": "cloud",  "default_port": 443,   "icon": "❄️" },
    "redshift":   { "label": "Redshift",         "category": "cloud",  "default_port": 5439,  "icon": "🔴" },
    "azuresql":   { "label": "Azure SQL",        "category": "cloud",  "default_port": 1433,  "icon": "🔷" },
    # Files
    "csv":        { "label": "CSV File",         "category": "file",   "default_port": None,  "icon": "📄" },
    "excel":      { "label": "Excel File",       "category": "file",   "default_port": None,  "icon": "📊" },
}


def get_connector_types():
    """Return all supported connector types for the UI."""
    return CONNECTOR_TYPES


# ── Base connector ────────────────────────────────────────────────────────────

class BaseConnector:
    def __init__(self, config: dict):
        self.config = config

    def connect(self) -> dict:
        raise NotImplementedError

    def get_schema(self) -> dict:
        raise NotImplementedError

    def format_schema_for_nlm(self) -> str:
        result = self.get_schema()
        if not result.get("success"):
            return ""
        lines = []
        for table, info in result.get("schema", {}).items():
            cols = ", ".join(
                f"{c['name']} ({c['type']})" for c in info["columns"]
            )
            lines.append(f"{table}: {cols}")
        return "\n".join(lines)

    def extract_table(self, table_name: str, target_conn, target_schema: str = "staging") -> dict:
        raise NotImplementedError


# ── PostgreSQL ────────────────────────────────────────────────────────────────

class PostgresConnector(BaseConnector):
    def __init__(self, host, port, database, username, password):
        super().__init__({
            "host": host, "port": port, "database": database,
            "username": username, "password": password
        })

    def _get_conn(self):
        import psycopg2
        return psycopg2.connect(
            host=self.config["host"],
            port=self.config["port"],
            dbname=self.config["database"],
            user=self.config["username"],
            password=self.config["password"]
        )

    def connect(self) -> dict:
        try:
            conn = self._get_conn()
            conn.close()
            return {"success": True, "message": "Connected to PostgreSQL successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_schema(self) -> dict:
        try:
            conn = self._get_conn()
            cur  = conn.cursor()
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [r[0] for r in cur.fetchall()]
            schema = {}
            for table in tables:
                cur.execute("""
                    SELECT column_name, data_type,
                           CASE WHEN column_name IN (
                               SELECT ku.column_name FROM information_schema.table_constraints tc
                               JOIN information_schema.key_column_usage ku ON tc.constraint_name = ku.constraint_name
                               WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_name = %s
                           ) THEN 'YES' ELSE 'NO' END AS is_pk
                    FROM information_schema.columns
                    WHERE table_name = %s ORDER BY ordinal_position
                """, (table, table))
                cols = [{"name": r[0], "type": r[1], "is_pk": r[2] == 'YES'} for r in cur.fetchall()]
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                schema[table] = {"columns": cols, "row_count": cur.fetchone()[0]}
            cur.close(); conn.close()
            return {"success": True, "schema": schema, "table_count": len(tables)}
        except Exception as e:
            return {"success": False, "message": str(e), "schema": {}}


# ── MySQL ─────────────────────────────────────────────────────────────────────

class MySQLConnector(BaseConnector):
    def __init__(self, host, port, database, username, password):
        super().__init__({
            "host": host, "port": port, "database": database,
            "username": username, "password": password
        })

    def _get_conn(self):
        import mysql.connector
        return mysql.connector.connect(
            host=self.config["host"],
            port=self.config["port"],
            database=self.config["database"],
            user=self.config["username"],
            password=self.config["password"]
        )

    def connect(self) -> dict:
        try:
            conn = self._get_conn(); conn.close()
            return {"success": True, "message": "Connected to MySQL successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_schema(self) -> dict:
        try:
            conn = self._get_conn()
            cur  = conn.cursor()
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]
            schema = {}
            for table in tables:
                cur.execute(f"DESCRIBE {table}")
                cols = [{"name": r[0], "type": r[1], "is_pk": r[3] == 'PRI'} for r in cur.fetchall()]
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                schema[table] = {"columns": cols, "row_count": cur.fetchone()[0]}
            cur.close(); conn.close()
            return {"success": True, "schema": schema, "table_count": len(tables)}
        except Exception as e:
            return {"success": False, "message": str(e), "schema": {}}


# ── SQL Server ────────────────────────────────────────────────────────────────

class SQLServerConnector(BaseConnector):
    def __init__(self, host, port, database, username, password):
        super().__init__({
            "host": host, "port": port, "database": database,
            "username": username, "password": password
        })

    def _get_conn(self):
        import pyodbc
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={self.config['host']},{self.config['port']};"
            f"DATABASE={self.config['database']};"
            f"UID={self.config['username']};"
            f"PWD={self.config['password']}"
        )
        return pyodbc.connect(conn_str)

    def connect(self) -> dict:
        try:
            conn = self._get_conn(); conn.close()
            return {"success": True, "message": "Connected to SQL Server successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_schema(self) -> dict:
        try:
            conn = self._get_conn()
            cur  = conn.cursor()
            cur.execute("""
                SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME
            """)
            tables = [r[0] for r in cur.fetchall()]
            schema = {}
            for table in tables:
                cur.execute(f"""
                    SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_NAME = '{table}' ORDER BY ORDINAL_POSITION
                """)
                cols = [{"name": r[0], "type": r[1], "is_pk": False} for r in cur.fetchall()]
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                schema[table] = {"columns": cols, "row_count": cur.fetchone()[0]}
            cur.close(); conn.close()
            return {"success": True, "schema": schema, "table_count": len(tables)}
        except Exception as e:
            return {"success": False, "message": str(e), "schema": {}}


# ── Snowflake ─────────────────────────────────────────────────────────────────

class SnowflakeConnector(BaseConnector):
    def __init__(self, account, username, password, database, schema="PUBLIC", warehouse="COMPUTE_WH"):
        super().__init__({
            "account": account, "username": username, "password": password,
            "database": database, "schema": schema, "warehouse": warehouse
        })

    def _get_conn(self):
        import snowflake.connector
        return snowflake.connector.connect(
            account=self.config["account"],
            user=self.config["username"],
            password=self.config["password"],
            database=self.config["database"],
            schema=self.config["schema"],
            warehouse=self.config["warehouse"]
        )

    def connect(self) -> dict:
        try:
            conn = self._get_conn(); conn.close()
            return {"success": True, "message": "Connected to Snowflake successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_schema(self) -> dict:
        try:
            conn = self._get_conn()
            cur  = conn.cursor()
            cur.execute("SHOW TABLES")
            tables = [r[1] for r in cur.fetchall()]
            schema = {}
            for table in tables:
                cur.execute(f"DESCRIBE TABLE {table}")
                cols = [{"name": r[0], "type": r[1], "is_pk": False} for r in cur.fetchall()]
                schema[table] = {"columns": cols, "row_count": 0}
            cur.close(); conn.close()
            return {"success": True, "schema": schema, "table_count": len(tables)}
        except Exception as e:
            return {"success": False, "message": str(e), "schema": {}}


# ── BigQuery ──────────────────────────────────────────────────────────────────

class BigQueryConnector(BaseConnector):
    def __init__(self, project_id, dataset_id, credentials_json: str):
        super().__init__({
            "project_id": project_id,
            "dataset_id": dataset_id,
            "credentials_json": credentials_json
        })

    def _get_client(self):
        from google.cloud import bigquery
        from google.oauth2 import service_account
        import json
        creds_dict = json.loads(self.config["credentials_json"])
        creds  = service_account.Credentials.from_service_account_info(creds_dict)
        return bigquery.Client(project=self.config["project_id"], credentials=creds)

    def connect(self) -> dict:
        try:
            client = self._get_client()
            list(client.list_datasets())
            return {"success": True, "message": "Connected to BigQuery successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_schema(self) -> dict:
        try:
            client  = self._get_client()
            dataset = client.dataset(self.config["dataset_id"])
            tables  = list(client.list_tables(dataset))
            schema  = {}
            for t in tables:
                tbl  = client.get_table(t)
                cols = [{"name": f.name, "type": str(f.field_type), "is_pk": False}
                        for f in tbl.schema]
                schema[t.table_id] = {"columns": cols, "row_count": tbl.num_rows or 0}
            return {"success": True, "schema": schema, "table_count": len(tables)}
        except Exception as e:
            return {"success": False, "message": str(e), "schema": {}}


# ── Redshift ──────────────────────────────────────────────────────────────────

class RedshiftConnector(PostgresConnector):
    """Redshift uses same protocol as Postgres."""
    def connect(self) -> dict:
        result = super().connect()
        if result["success"]:
            result["message"] = "Connected to Amazon Redshift successfully"
        return result


# ── Azure SQL ─────────────────────────────────────────────────────────────────

class AzureSQLConnector(SQLServerConnector):
    """Azure SQL uses same protocol as SQL Server."""
    def connect(self) -> dict:
        result = super().connect()
        if result["success"]:
            result["message"] = "Connected to Azure SQL successfully"
        return result


# ── SQLite ────────────────────────────────────────────────────────────────────

class SQLiteConnector(BaseConnector):
    def __init__(self, file_path: str):
        super().__init__({"file_path": file_path})

    def connect(self) -> dict:
        try:
            import sqlite3
            conn = sqlite3.connect(self.config["file_path"])
            conn.close()
            return {"success": True, "message": "Connected to SQLite successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def get_schema(self) -> dict:
        try:
            import sqlite3
            conn   = sqlite3.connect(self.config["file_path"])
            cur    = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            schema = {}
            for table in tables:
                cur.execute(f"PRAGMA table_info({table})")
                cols = [{"name": r[1], "type": r[2], "is_pk": bool(r[5])} for r in cur.fetchall()]
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                schema[table] = {"columns": cols, "row_count": cur.fetchone()[0]}
            cur.close(); conn.close()
            return {"success": True, "schema": schema, "table_count": len(tables)}
        except Exception as e:
            return {"success": False, "message": str(e), "schema": {}}


# ── File connectors ───────────────────────────────────────────────────────────

class FileConnector:
    def __init__(self, duckdb_path: str):
        self.duckdb_path = duckdb_path

    def load_csv(self, file_path: str, table_name: str) -> dict:
        try:
            import duckdb
            df     = pd.read_csv(file_path)
            target = f"raw_{table_name}"
            con    = duckdb.connect(self.duckdb_path)
            con.execute(f"DROP TABLE IF EXISTS {target}")
            con.execute(f"CREATE TABLE {target} AS SELECT * FROM df")
            con.close()
            return {"success": True, "table": target, "rows": len(df), "columns": list(df.columns)}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def load_excel(self, file_path: str, table_name: str, sheet_name=0) -> dict:
        try:
            import duckdb
            df     = pd.read_excel(file_path, sheet_name=sheet_name)
            target = f"raw_{table_name}"
            con    = duckdb.connect(self.duckdb_path)
            con.execute(f"DROP TABLE IF EXISTS {target}")
            con.execute(f"CREATE TABLE {target} AS SELECT * FROM df")
            con.close()
            return {"success": True, "table": target, "rows": len(df), "columns": list(df.columns)}
        except Exception as e:
            return {"success": False, "message": str(e)}


# ── Factory ───────────────────────────────────────────────────────────────────

def create_connector(connector_type: str, config: dict) -> BaseConnector:
    """
    Factory function — create the right connector from type string.
    config keys depend on connector type.
    """
    ct = connector_type.lower()
    if ct == "postgres":
        return PostgresConnector(
            config["host"], config.get("port", 5432),
            config["database_name"], config["username"], config["password"]
        )
    elif ct == "mysql":
        return MySQLConnector(
            config["host"], config.get("port", 3306),
            config["database_name"], config["username"], config["password"]
        )
    elif ct == "sqlserver":
        return SQLServerConnector(
            config["host"], config.get("port", 1433),
            config["database_name"], config["username"], config["password"]
        )
    elif ct == "snowflake":
        return SnowflakeConnector(
            config["account"], config["username"], config["password"],
            config["database_name"],
            config.get("schema", "PUBLIC"), config.get("warehouse", "COMPUTE_WH")
        )
    elif ct == "bigquery":
        return BigQueryConnector(
            config["project_id"], config["dataset_id"], config["credentials_json"]
        )
    elif ct in ("redshift", "azuresql"):
        return PostgresConnector(
            config["host"], config.get("port", 5439 if ct == "redshift" else 1433),
            config["database_name"], config["username"], config["password"]
        )
    elif ct == "sqlite":
        return SQLiteConnector(config["file_path"])
    else:
        raise ValueError(f"Unsupported connector type: {connector_type}")
