"""
agents/schema_agent.py
Discovers tables, columns, PKs, FKs and relationships from source DB.
Wraps existing pipeline_executor.py functions.
"""

from .base import BaseAgent, AgentContext, AgentResult


class SchemaAgent(BaseAgent):
    name        = "SchemaAgent"
    description = "Discovers tables, columns, PKs, FKs, and relationships from source database"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from pipeline_executor import get_full_schema_for_ai, list_all_tables_by_schema

        cfg = ctx.connector_config
        if not cfg or not cfg.get("host"):
            result.log("No connector config — skipping schema discovery", "warn")
            ctx.schema_result = {"schema_text": "", "source_tables": [], "table_count": 0, "schemas": {}}
            return ctx.schema_result

        result.log(f"Connecting to source: {cfg.get('database', '?')}")
        result.log(f"Source schema: {ctx.source_schema}")

        # Get full schema text for AI
        try:
            schema_text = get_full_schema_for_ai(cfg, source_schema=ctx.source_schema)
        except Exception as e:
            result.log(f"Schema text failed: {e} — continuing with empty", "warn")
            schema_text = ""

        # Get structured table list — only from source schema
        source_tables = []
        schemas       = {}
        try:
            tables_result = list_all_tables_by_schema(cfg, source_schema=ctx.source_schema)
            schemas       = tables_result.get("schemas", {})
            # Only take tables from the source schema — ignore staging, warehouse, system tables
            target_tables = schemas.get(ctx.source_schema, [])
            for t in target_tables:
                source_tables.append(t.get("name", ""))
        except Exception as e:
            result.log(f"Table list failed: {e} — continuing with empty", "warn")

        result.log(f"Discovered {len(source_tables)} tables: {source_tables}")

        # Filter to selected tables if specified
        if ctx.source_tables:
            source_tables = [t for t in source_tables if t in ctx.source_tables]
            result.log(f"Filtered to {len(source_tables)} selected tables")

        schema_data = {
            "schema_text":   schema_text,
            "source_tables": source_tables,
            "table_count":   len(source_tables),
            "schemas":       schemas
        }

        ctx.schema_result = schema_data
        result.log(f"✓ Schema discovery complete — {len(source_tables)} tables, {len(schema_text)} chars")
        return schema_data