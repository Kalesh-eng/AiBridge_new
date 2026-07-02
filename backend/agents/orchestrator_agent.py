"""
agents/orchestrator_agent.py
Central coordinator. Runs agents in the correct order per the architecture.

Flow:
  Phase 1 (parallel): SchemaAgent + MetadataAgent + BusinessAgent
  Phase 2 (sequential): PlannerAgent
  Phase 3 (conditional): RelationshipValidationAgent → DataModelAgent
  Phase 4: ETLAgent → SQLAgent → SQLValidationAgent → GovernanceValidationAgent
  Phase 5: ReviewAgent (HIL)
  Phase 6: ExecutionAgent → RecoveryAgent (if needed)
  Phase 7: AnalyticsAgent
"""

from .base import BaseAgent, AgentContext, AgentResult
from .schema_agent                  import SchemaAgent
from .metadata_agent                import MetadataAgent
from .business_agent                import BusinessAgent
from .planner_agent                 import PlannerAgent
from .relationship_validation_agent import RelationshipValidationAgent
from .data_model_agent              import DataModelAgent
from .etl_agent                     import ETLAgent
from .sql_agent                     import SQLAgent
from .sql_validation_agent          import SQLValidationAgent
from .governance_validation_agent   import GovernanceValidationAgent
from .review_agent                  import ReviewAgent
from .execution_agent               import ExecutionAgent
from .recovery_agent                import RecoveryAgent
from .analytics_agent               import AnalyticsAgent

import concurrent.futures


class OrchestratorAgent(BaseAgent):
    name        = "OrchestratorAgent"
    description = "Coordinates all agents in the correct order for the pipeline"

    # Max retries for validation loops
    MAX_VALIDATION_RETRIES = 2
    MAX_SQL_RETRIES        = 2

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        result.log("=" * 60)
        result.log("AIBridge Multi-Agent Pipeline Starting")
        result.log("=" * 60)

        # ── PHASE 1: Parallel discovery ───────────────────────────────────────
        result.log("Phase 1: Parallel discovery (Schema + Metadata + Business)")
        self._run_parallel_phase1(ctx, result)

        # ── PHASE 2: Plan ─────────────────────────────────────────────────────
        result.log("Phase 2: Planning")
        plan_result = PlannerAgent().run(ctx)
        if not plan_result.success:
            result.log("PlannerAgent failed — defaulting to star_schema", "warn")

        # ── PHASE 3: Relationship validation + Data model ─────────────────────
        if ctx.plan and ctx.plan.get("needs_modeling", True):
            result.log("Phase 3: Relationship validation + Data model design")

            for attempt in range(self.MAX_VALIDATION_RETRIES + 1):
                rel_result = RelationshipValidationAgent().run(ctx)

                if rel_result.success and ctx.relationship_validation.get("passed", True):
                    result.log("✓ Relationship validation passed")
                    break
                else:
                    issues = ctx.relationship_validation.get("issues", [])
                    result.log(f"Relationship validation attempt {attempt+1} — issues: {issues}", "warn")
                    if attempt >= self.MAX_VALIDATION_RETRIES:
                        result.log("Max validation retries reached — proceeding with warnings", "warn")

            # Design data model
            dm_result = DataModelAgent().run(ctx)
            if not dm_result.success:
                raise ValueError(f"DataModelAgent failed: {dm_result.error}")

        # ── PHASE 4: ETL → SQL → Validation ──────────────────────────────────
        result.log("Phase 4: ETL + SQL generation + Validation")

        # ETL: source → staging
        if ctx.plan and ctx.plan.get("needs_etl", True):
            etl_result = ETLAgent().run(ctx)
            if not etl_result.success:
                raise ValueError(f"ETLAgent failed: {etl_result.error}")

        # SQL generation with retry loop
        if ctx.plan and ctx.plan.get("needs_sql_generation", True):
            for sql_attempt in range(self.MAX_SQL_RETRIES + 1):
                sql_result = SQLAgent().run(ctx)
                if not sql_result.success:
                    raise ValueError(f"SQLAgent failed: {sql_result.error}")

                # SQL Validation
                sv_result = SQLValidationAgent().run(ctx)

                if sv_result.success and ctx.sql_validation.get("passed", True):
                    result.log("✓ SQL validation passed")
                    break
                else:
                    issues = ctx.sql_validation.get("issues", [])
                    error_issues = [i for i in issues if i.get("severity") == "error"]
                    if error_issues and sql_attempt < self.MAX_SQL_RETRIES:
                        result.log(f"SQL validation failed — regenerating (attempt {sql_attempt+2})", "warn")
                        # Pass fix hints back to SQLAgent via context
                        ctx.data_model["_sql_fix_hints"] = [i["detail"] for i in error_issues]
                    else:
                        result.log("Proceeding with validation warnings", "warn")
                        break

            # Governance validation
            gv_result = GovernanceValidationAgent().run(ctx)
            if ctx.blocked:
                result.log(f"🚫 Pipeline BLOCKED by governance: {ctx.blocked_reason}", "error")
                return self._build_summary(ctx, "blocked")

        # ── PHASE 5: Human Review (HIL) ───────────────────────────────────────
        result.log("Phase 5: Human review (HIL)")
        rv_result = ReviewAgent().run(ctx)
        result.log("⏸ Pipeline paused — awaiting human approval")

        # Return here — execution resumes after human approves via API
        return self._build_summary(ctx, "awaiting_approval")

    def run_phase_execution(self, ctx: AgentContext) -> dict:
        """
        Called AFTER human approves via ReviewAgent.
        Runs ExecutionAgent → RecoveryAgent → AnalyticsAgent.
        """
        result = AgentResult(agent_name=self.name)
        result.log("Phase 6: Execution")

        exec_result = ExecutionAgent().run(ctx)

        # Recovery if execution had failures
        if not exec_result.success or (
            ctx.execution_result and
            any(not s.get("success") for s in ctx.execution_result.get("scripts", []))
        ):
            result.log("Phase 6b: Recovery")
            RecoveryAgent().run(ctx)

            # If recovery fixed scripts, retry execution
            if ctx.recovery_result and ctx.recovery_result.get("recovered", 0) > 0:
                result.log("Re-running execution after recovery fixes...")
                ExecutionAgent().run(ctx)

        # Analytics
        result.log("Phase 7: Analytics")
        AnalyticsAgent().run(ctx)

        return self._build_summary(ctx, "complete")

    def _run_parallel_phase1(self, ctx: AgentContext, result: AgentResult):
        """Run SchemaAgent, MetadataAgent, BusinessAgent in parallel."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(SchemaAgent().run,   ctx): "SchemaAgent",
                executor.submit(MetadataAgent().run, ctx): "MetadataAgent",
                executor.submit(BusinessAgent().run, ctx): "BusinessAgent",
            }
            for future in concurrent.futures.as_completed(futures):
                agent_name = futures[future]
                try:
                    agent_result = future.result()
                    status = "✓" if agent_result.success else "✗"
                    result.log(f"{status} {agent_name} complete ({agent_result.duration_s:.1f}s)")
                except Exception as e:
                    result.log(f"✗ {agent_name} failed: {e}", "error")

    def _build_summary(self, ctx: AgentContext, status: str) -> dict:
        """Build final pipeline summary."""
        return {
            "status":          status,
            "pipeline_id":     ctx.pipeline_id,
            "plan":            ctx.plan.get("plan") if ctx.plan else "unknown",
            "schema_tables":   ctx.schema_result.get("source_tables", []) if ctx.schema_result else [],
            "data_model":      ctx.data_model,
            "sql_scripts":     ctx.sql_scripts,
            "staging_rows":    ctx.staging_result.get("rows", 0) if ctx.staging_result else 0,
            "warehouse_rows":  ctx.execution_result.get("total_rows", 0) if ctx.execution_result else 0,
            "blocked":         ctx.blocked,
            "blocked_reason":  ctx.blocked_reason,
            "needs_human":     ctx.needs_human,
            "pipeline_log":    ctx.pipeline_log
        }

    @staticmethod
    def build_context(
        pipeline_id:           str,
        workspace_id:          str,
        connector_config:      dict,
        source_schema:         str,
        source_tables:         list,
        source_columns:        dict,
        source_description:    str,
        business_requirements: str,
        target_config:         dict = None,
        staging_schema:        str  = "staging",
        warehouse_schema:      str  = "warehouse",
        run_id:                str  = ""
    ) -> AgentContext:
        """Helper to build AgentContext from pipeline parameters."""
        return AgentContext(
            pipeline_id           = pipeline_id,
            workspace_id          = workspace_id,
            run_id                = run_id,
            connector_config      = connector_config,
            source_schema         = source_schema,
            source_tables         = source_tables,
            source_columns        = source_columns,
            source_description    = source_description,
            business_requirements = business_requirements,
            target_config         = target_config or connector_config,
            staging_schema        = staging_schema,
            warehouse_schema      = warehouse_schema
        )
