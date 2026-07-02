"""
agents/execution_agent.py
Runs the approved SQL scripts against the warehouse.
Wraps pipeline_executor.py execute_warehouse_scripts().
"""

from .base import BaseAgent, AgentContext, AgentResult


class ExecutionAgent(BaseAgent):
    name        = "ExecutionAgent"
    description = "Executes approved SQL scripts against the warehouse database"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from pipeline_executor import execute_warehouse_scripts

        if not ctx.sql_scripts:
            raise ValueError("No SQL scripts to execute")

        scripts = ctx.sql_scripts.get("scripts", [])
        if not scripts:
            raise ValueError("SQL scripts list is empty")

        result.log(f"Executing {len(scripts)} warehouse scripts...")
        result.log(f"Warehouse schema: {ctx.warehouse_schema}")

        target_config = ctx.target_config if ctx.target_config else ctx.connector_config

        # Get a DB session for logging
        from database import SessionLocal
        db = SessionLocal()

        try:
            exec_result = execute_warehouse_scripts(
                pipeline_id      = ctx.pipeline_id,
                pipeline_name    = f"Pipeline {ctx.pipeline_id}",
                sql_scripts      = scripts,
                target_config    = target_config,
                workspace_id     = ctx.workspace_id,
                db_session       = db,
                warehouse_schema = ctx.warehouse_schema,
                staging_schema   = ctx.staging_schema,
                should_stop_fn   = getattr(ctx, 'should_stop_fn', None),
                source_connector_type = getattr(ctx, "source_connector_type", None)
            )
        finally:
            db.close()

        # NOTE: execute_warehouse_scripts returns rows under the key "rows",
        # not "total_rows" — the original code below read "total_rows" and
        # was silently always falling back to 0. Fixed as part of this
        # patch (kept the old key as a fallback in case that ever changes).
        total_rows = exec_result.get("total_rows", exec_result.get("rows", 0))
        success    = exec_result.get("success", False)
        stopped    = exec_result.get("stopped", False)

        # A Stop request mid-warehouse-load is not a failure — do not log
        # it as "Execution partial" (which would misleadingly suggest
        # script errors rather than a clean user-requested stop).
        if stopped:
            result.log(f"🛑 Execution stopped early — {total_rows} rows loaded before stop")
        elif success:
            result.log(f"✓ Execution complete — {total_rows} total rows loaded")
        else:
            failed = [s for s in exec_result.get("scripts", []) if not s.get("success")]
            result.log(f"✗ Execution partial — {len(failed)} scripts failed", "error")
            for f in failed:
                result.log(f"  → {f.get('name')}: {f.get('error', '')[:100]}", "error")

        ctx.execution_result = exec_result
        return exec_result
