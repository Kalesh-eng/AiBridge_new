"""
database.py — SQLAlchemy models for local Postgres.

v2.0: Added PipelineMapping + PipelineVersion tables.
      - PipelineMapping: save ETL mappings per user with versioning
      - PipelineVersion: full version history of data model + SQL + mappings
      - run_migrations() auto-adds new columns to existing tables

v1.x: Pipeline target fields, connector source_schema, HIL mode, etc.
"""
import os
import uuid
from datetime import datetime
from sqlalchemy import (create_engine, Column, String, Boolean,
                        Text, Integer, DateTime, JSON, text)
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine       = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base         = declarative_base()


class User(Base):
    __tablename__ = "users"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email      = Column(String, unique=True, nullable=False)
    full_name  = Column(String, nullable=False)
    password   = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"
    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id   = Column(String, nullable=False)
    name       = Column(String, nullable=False)
    plan       = Column(String, default="starter")
    hil_mode   = Column(String, default="balanced")
    created_at = Column(DateTime, default=datetime.utcnow)


class Connector(Base):
    __tablename__  = "connectors"
    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id   = Column(String, nullable=False)
    name           = Column(String, nullable=False)
    connector_type = Column(String, nullable=False)
    role           = Column(String, default="both")
    host           = Column(String)
    port           = Column(Integer)
    database_name  = Column(String)
    username       = Column(String)
    password       = Column(String)
    source_schema  = Column(String, default="raw")
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime, default=datetime.utcnow)


class Pipeline(Base):
    __tablename__       = "pipelines"
    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id        = Column(String, nullable=False)
    name                = Column(String, nullable=False)
    source_desc         = Column(Text)
    raw_schema          = Column(Text)
    biz_requirements    = Column(Text)
    schedule            = Column(String, default="manual")
    schedule_config     = Column(JSON, default=dict)       # NEW — custom schedule config
    is_active           = Column(Boolean, default=True)
    artifacts           = Column(JSON, default=dict)
    connector_id        = Column(String)
    source_tables       = Column(JSON, default=list)
    source_schema       = Column(String, default="raw")
    source_columns      = Column(JSON, default=dict)
    target_connector_id = Column(String)
    staging_schema      = Column(String, default="staging")
    warehouse_schema    = Column(String, default="warehouse")
    current_version     = Column(Integer, default=1)       # NEW — active version number
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id       = Column(String, unique=True, nullable=False)
    pipeline_id  = Column(String)
    workspace_id = Column(String)
    status       = Column(String, nullable=False)
    started_at   = Column(DateTime)
    ended_at     = Column(DateTime)
    rows_loaded  = Column(Integer, default=0)
    log          = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)


class SchemaChange(Base):
    __tablename__ = "schema_changes"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String)
    table_name   = Column(String, nullable=False)
    change_type  = Column(String, nullable=False)
    column_name  = Column(String)
    details      = Column(JSON, default=dict)
    applied_at   = Column(DateTime, default=datetime.utcnow)


class RecoveryLog(Base):
    __tablename__ = "recovery_logs"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_id     = Column(String)
    pipeline_run_id = Column(String)
    workspace_id    = Column(String)
    failed_script   = Column(String)
    error_message   = Column(Text)
    error_pattern   = Column(String)
    action_taken    = Column(String)
    fix_method      = Column(String)
    fix_sql         = Column(Text)
    recovered       = Column(Boolean, default=False)
    attempts        = Column(JSON)
    summary         = Column(Text)
    started_at      = Column(DateTime)
    ended_at        = Column(DateTime)
    created_at      = Column(DateTime, default=datetime.utcnow)


class ApprovalQueue(Base):
    __tablename__ = "approval_queue"
    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id    = Column(String, nullable=False)
    pipeline_id     = Column(String)
    pipeline_run_id = Column(String)
    approval_type   = Column(String, nullable=False)
    title           = Column(String)
    description     = Column(Text)
    proposed_data   = Column(JSON)
    edited_data     = Column(JSON)
    context         = Column(JSON, default=dict)
    status          = Column(String, default="pending")
    requested_by    = Column(String)
    approved_by     = Column(String)
    comments        = Column(Text)
    risk_level      = Column(String, default="medium")
    created_at      = Column(DateTime, default=datetime.utcnow)
    decided_at      = Column(DateTime)


# ── NEW: ETL Mapping storage ──────────────────────────────────────────────────

class PipelineMapping(Base):
    """
    Saved ETL mappings per pipeline per user.
    Each mapping has a version number — old versions are kept for history.
    Only one version is active at a time (is_active=True).

    Stores column-level source→target mapping:
    {
      "mappings": [
        {
          "target_table": "warehouse.fact_transactions",
          "source_schema": "staging",
          "columns": [
            {
              "source_table": "staging.stg_transactions",
              "source_column": "amount",
              "target_column": "amount",
              "transform_rule": "direct"
            }
          ]
        }
      ]
    }
    """
    __tablename__ = "pipeline_mappings"
    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_id  = Column(String, nullable=False)
    workspace_id = Column(String, nullable=False)
    created_by   = Column(String)                          # user_id
    name         = Column(String, nullable=False)          # e.g. "Banking ETL v1"
    version      = Column(Integer, default=1)
    is_active    = Column(Boolean, default=True)           # only one active per pipeline
    mappings     = Column(JSON, default=dict)              # full ETL mapping JSON
    notes        = Column(Text)                            # what changed in this version
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow)


# ── NEW: Pipeline version history ─────────────────────────────────────────────

class PipelineVersion(Base):
    """
    Full version snapshot of a pipeline design.
    Created automatically when:
      - Pipeline design is approved (Gate 1 + Gate 2)
      - User manually saves a version with a label

    Stores complete snapshot:
      - data_model  (dim/fact table definitions)
      - sql_scripts (generated SQL)
      - etl_mappings (column mappings)
      - schema_hash (for cache lookup)

    Rollback = set this version's artifacts as pipeline.artifacts
               and update pipeline.current_version
    """
    __tablename__ = "pipeline_versions"
    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    pipeline_id   = Column(String, nullable=False)
    workspace_id  = Column(String, nullable=False)
    created_by    = Column(String)                         # user_id
    version       = Column(Integer, nullable=False)        # 1, 2, 3...
    version_label = Column(String)                         # "v1", "After adding loan dim"
    is_active     = Column(Boolean, default=False)         # currently deployed version
    data_model    = Column(JSON, default=dict)             # dim/fact model
    sql_scripts   = Column(JSON, default=dict)             # generated SQL
    etl_mappings  = Column(JSON, default=dict)             # ETL column mappings
    schema_hash   = Column(String)                         # for cache reference
    change_summary= Column(Text)                           # auto or user-written summary
    created_at    = Column(DateTime, default=datetime.utcnow)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Auto-migration ────────────────────────────────────────────────────────────

COLUMNS_TO_MIGRATE = [
    # Existing columns
    ("connectors", "source_schema",       "VARCHAR DEFAULT 'raw'"),
    ("pipelines",  "source_schema",       "VARCHAR DEFAULT 'raw'"),
    ("pipelines",  "source_tables",       "JSON DEFAULT '[]'"),
    ("pipelines",  "source_columns",      "JSON DEFAULT '{}'"),
    ("pipelines",  "target_connector_id", "VARCHAR"),
    ("pipelines",  "staging_schema",      "VARCHAR DEFAULT 'staging'"),
    ("pipelines",  "warehouse_schema",    "VARCHAR DEFAULT 'warehouse'"),
    ("workspaces", "hil_mode",            "VARCHAR DEFAULT 'balanced'"),
    # NEW columns
    ("pipelines",  "schedule_config",     "JSON DEFAULT '{}'"),
    ("pipelines",  "current_version",     "INTEGER DEFAULT 1"),
]


def run_migrations():
    """Add any missing columns to existing tables (safe, idempotent)."""
    with engine.connect() as conn:
        for table, column, definition in COLUMNS_TO_MIGRATE:
            try:
                conn.execute(text(
                    f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}'
                ))
                conn.commit()
            except Exception as e:
                print(f"  [migration] {table}.{column}: {e}")
    print("✓ Migrations applied")


def setup_database():
    try:
        Base.metadata.create_all(bind=engine)
        print("✓ All tables created successfully")
        run_migrations()
        return True
    except Exception as e:
        print(f"✗ Database setup failed: {e}")
        return False


if __name__ == "__main__":
    setup_database()
