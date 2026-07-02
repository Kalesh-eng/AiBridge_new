"""
agents/data_model_agent.py
Designs star/snowflake schema — fact tables, dimension tables, surrogate keys.
Wraps nlm_engine.py generate_data_model().
"""

from .base import BaseAgent, AgentContext, AgentResult


class DataModelAgent(BaseAgent):
    name        = "DataModelAgent"
    description = "Designs star schema with fact tables, dimension tables, and surrogate keys"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from nlm_engine import run_phase_1_model_design

        result.log("Designing data model...")

        schema_text  = ctx.schema_result.get("schema_text", "") if ctx.schema_result else ""
        profile_text = ctx.metadata_result.get("profile", "")   if ctx.metadata_result else ""

        # Build enriched raw schema combining schema + profile
        raw_schema = schema_text
        if profile_text:
            raw_schema = f"{schema_text}\n\nDATA PROFILE:\n{profile_text}"

        # Add validation hints if relationship issues found
        validation_hints = ""
        if ctx.relationship_validation:
            warnings = ctx.relationship_validation.get("warnings", [])
            if warnings:
                validation_hints = "\n\nRELATIONSHIP WARNINGS:\n" + "\n".join(warnings)
                raw_schema += validation_hints

        plan_type = "star"
        if ctx.plan:
            plan_type = ctx.plan.get("schema_type", "star")

        result.log(f"Schema type: {plan_type}")
        result.log(f"Schema size: {len(raw_schema)} chars")

        phase1 = run_phase_1_model_design(
            source_description    = ctx.source_description,
            raw_schema            = raw_schema,
            business_requirements = ctx.business_requirements,
            connector_config      = ctx.connector_config,
            source_schema         = ctx.source_schema
        )

        data_model      = phase1.get("data_model", {})
        schema_analysis = phase1.get("schema_analysis", {})

        dim_count  = len(data_model.get("dimension_tables", []))
        fact_count = len(data_model.get("fact_tables", []))

        result.log(f"✓ Model designed: {fact_count} fact tables, {dim_count} dimension tables")

        ctx.data_model = {
            "data_model":      data_model,
            "schema_analysis": schema_analysis
        }

        return ctx.data_model
