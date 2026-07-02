"""
agents/etl_agent.py
Handles source → staging data movement.
Wraps pipeline_executor.py extract_to_staging().
"""

from .base import BaseAgent, AgentContext, AgentResult


class ETLAgent(BaseAgent):
    name        = "ETLAgent"
    description = "Extracts data from source tables and loads into staging schema"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from pipeline_executor import extract_to_staging

        source_tables = ctx.source_tables
        if not source_tables and ctx.schema_result:
            source_tables = ctx.schema_result.get("source_tables", [])

        if not source_tables:
            raise ValueError("No source tables specified for extraction")

        result.log(f"Extracting {len(source_tables)} tables: {source_tables}")
        result.log(f"Source schema: {ctx.source_schema}")
        result.log(f"Staging schema: {ctx.staging_schema}")

        # Use target_config if provided, otherwise use source_config
        target_config = ctx.target_config if ctx.target_config else ctx.connector_config

        
        staging_result = extract_to_staging(
            source_tables  = source_tables,
            source_config  = ctx.connector_config,
            target_config  = target_config,
            source_schema  = ctx.source_schema,
            staging_schema = ctx.staging_schema,
            source_columns = ctx.source_columns or {},
        )

        # A Stop request during extraction is not a failure — ETLAgent must
        # NOT raise here, or the pipeline would be logged/reported as a
        # crash instead of a clean user-requested stop. Return whatever
        # was extracted before the stop took effect and let main.py's own
        # stop checkpoint (which runs immediately after this agent) decide
        # how to report it.
        if staging_result.get("stopped"):
            result.log(f"🛑 Extract stopped early — {staging_result.get('rows', 0)} rows "
                       f"across {staging_result.get('tables_extracted', 0)} tables before stop.")
            ctx.staging_result = staging_result
            return staging_result

        if not staging_result.get("success"):
            raise ValueError(f"Extract failed: {staging_result.get('error', 'unknown')}")

        rows  = staging_result.get("rows", 0)
        tbls  = staging_result.get("tables_extracted", 0)
        result.log(f"✓ Extract complete — {rows} rows across {tbls} tables")

        ctx.staging_result = staging_result
        return staging_result
