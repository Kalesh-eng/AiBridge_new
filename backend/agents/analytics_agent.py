"""
agents/analytics_agent.py
Pipeline metrics, warehouse stats, BI queries, run history.
Wraps /nl/to-sql logic and pipeline metrics.
"""

from .base import BaseAgent, AgentContext, AgentResult


class AnalyticsAgent(BaseAgent):
    name        = "AnalyticsAgent"
    description = "Computes pipeline metrics, warehouse stats, and enables BI queries"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        result.log("Computing pipeline analytics...")

        metrics = {
            "pipeline_id":   ctx.pipeline_id,
            "run_id":        ctx.run_id,
            "stages":        {},
            "warehouse":     {},
            "bi_ready":      False
        }

        # ── Stage timing metrics ──────────────────────────────────────────────
        stage_map = [
            ("schema",       ctx.schema_result),
            ("metadata",     ctx.metadata_result),
            ("business",     ctx.business_result),
            ("plan",         ctx.plan),
            ("data_model",   ctx.data_model),
            ("staging",      ctx.staging_result),
            ("sql",          ctx.sql_scripts),
            ("execution",    ctx.execution_result),
            ("recovery",     ctx.recovery_result),
        ]

        for stage_name, stage_result in stage_map:
            if stage_result:
                metrics["stages"][stage_name] = "completed"
            else:
                metrics["stages"][stage_name] = "skipped"

        # ── Warehouse metrics ─────────────────────────────────────────────────
        if ctx.execution_result:
            exec_r = ctx.execution_result
            metrics["warehouse"] = {
                "total_rows":      exec_r.get("total_rows", 0),
                "scripts_run":     len(exec_r.get("scripts", [])),
                "scripts_success": len([s for s in exec_r.get("scripts", []) if s.get("success")]),
                "scripts_failed":  len([s for s in exec_r.get("scripts", []) if not s.get("success")]),
                "success":         exec_r.get("success", False)
            }
            metrics["bi_ready"] = exec_r.get("success", False)

        # ── Staging metrics ───────────────────────────────────────────────────
        if ctx.staging_result:
            metrics["staging"] = {
                "rows_extracted":    ctx.staging_result.get("rows", 0),
                "tables_extracted":  ctx.staging_result.get("tables_extracted", 0)
            }

        # ── Recovery metrics ──────────────────────────────────────────────────
        if ctx.recovery_result:
            metrics["recovery"] = {
                "recovered":  ctx.recovery_result.get("recovered", 0),
                "failed":     ctx.recovery_result.get("failed", 0)
            }

        # ── Log summary ───────────────────────────────────────────────────────
        wh = metrics.get("warehouse", {})
        result.log(f"Pipeline: {len(metrics['stages'])} stages executed")
        if wh:
            result.log(f"Warehouse: {wh.get('total_rows', 0)} rows, "
                       f"{wh.get('scripts_success', 0)}/{wh.get('scripts_run', 0)} scripts")
        result.log(f"BI ready: {metrics['bi_ready']}")

        ctx.analytics_result = metrics
        return metrics

    def ask_warehouse(self, question: str, ctx: AgentContext) -> dict:
        """
        Answer a business question from the warehouse.
        Called independently from the BI tab.
        """
        from ai_provider import ask_ai
        from pipeline_executor import get_full_schema_for_ai

        schema_text = get_full_schema_for_ai(
            ctx.connector_config,
            source_schema=ctx.warehouse_schema
        )

        prompt = f"""You are a SQL expert. Generate a valid PostgreSQL SELECT query.

WAREHOUSE SCHEMA:
{schema_text}

RULES:
1. Return ONLY valid JSON: {{"sql": "SELECT ..."}}
2. Use ONLY columns that exist in the schema above
3. Always prefix tables with schema: warehouse.fact_*, warehouse.dim_*
4. Use proper JOINs between fact and dimension tables via surrogate keys
5. Add LIMIT 100
6. ONLY SELECT statements — no modifications

QUESTION: {question}"""

        result = ask_ai(prompt)
        return {"sql": result.get("sql", ""), "question": question}
