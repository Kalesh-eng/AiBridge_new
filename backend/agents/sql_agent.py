"""
agents/sql_agent.py
Generates CREATE TABLE + INSERT warehouse SQL from the data model.
Wraps nlm_engine.py run_phase_2_sql_generation() + sanitize_generated_sql().
"""

from .base import BaseAgent, AgentContext, AgentResult


class SQLAgent(BaseAgent):
    name        = "SQLAgent"
    description = "Generates CREATE TABLE and INSERT SQL scripts for the warehouse"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from nlm_engine import run_phase_2_sql_generation

        if not ctx.data_model:
            raise ValueError("DataModelAgent must run before SQLAgent")

        data_model      = ctx.data_model.get("data_model", {})
        schema_analysis = ctx.data_model.get("schema_analysis", {})

        result.log(f"Generating SQL for {len(data_model.get('fact_tables', []))} facts "
                   f"and {len(data_model.get('dimension_tables', []))} dimensions")
        result.log(f"Target: {ctx.warehouse_schema} schema")

        raw_schema = ""
        if ctx.schema_result:
            raw_schema = ctx.schema_result.get("schema_text", "")

        phase2 = run_phase_2_sql_generation(
            schema_analysis  = schema_analysis,
            data_model       = data_model,
            staging_schema   = ctx.staging_schema,
            warehouse_schema = ctx.warehouse_schema,
            raw_schema       = raw_schema,
        )

        sql_scripts = phase2.get("sql_scripts", {})
        etl_mappings = phase2.get("etl_mappings", {})
        scripts = sql_scripts.get("scripts", [])

        result.log(f"✓ Generated {len(scripts)} SQL scripts")
        for s in scripts:
            result.log(f"  → {s.get('name')} ({s.get('label', '')})")

        ctx.sql_scripts  = sql_scripts
        ctx.etl_mappings = etl_mappings

        return {
            "sql_scripts":  sql_scripts,
            "etl_mappings": etl_mappings,
            "script_count": len(scripts)
        }
