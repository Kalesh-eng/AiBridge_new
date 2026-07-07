"""
agents/metadata_agent.py
Data profiling ΓÇö statistics, quality, PII detection, null patterns.
Uses standalone functions from data_profiler.py (no DataProfiler class).
"""

from .base import BaseAgent, AgentContext, AgentResult


class MetadataAgent(BaseAgent):
    name        = "MetadataAgent"
    description = "Profiles data quality, statistics, null patterns, and detects PII columns"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from data_profiler import build_full_profile, format_profile_for_ai

        cfg = ctx.connector_config
        if not cfg or not cfg.get("host"):
            result.log("No connector config ΓÇö skipping metadata profiling", "warn")
            ctx.metadata_result = {"profile": "", "pii_columns": [], "quality_issues": []}
            return ctx.metadata_result

        tables = ctx.source_tables or []
        if not tables and ctx.schema_result:
            tables = ctx.schema_result.get("source_tables", [])

        if not tables:
            result.log("No tables to profile ΓÇö skipping", "warn")
            ctx.metadata_result = {"profile": "", "pii_columns": [], "quality_issues": []}
            return ctx.metadata_result

        result.log(f"Profiling {len(tables)} tables: {tables}")

        try:
            # build_full_profile takes conn_config dict + schema
            profile_data = build_full_profile(
                conn_config              = cfg,
                schema                   = ctx.source_schema,
                sample_rows              = 5,
                enable_overlap_detection = False
            )
            profile_text = format_profile_for_ai(profile_data)
            result.log(f"Γ£ô Profile built ({len(profile_text)} chars)")
        except Exception as e:
            result.log(f"Profiling failed: {e} ΓÇö skipping", "warn")
            profile_text = ""

        # Detect PII columns from schema text
        pii_keywords = ["email", "phone", "mobile", "ssn", "aadhaar", "pan",
                        "passport", "credit_card", "dob", "date_of_birth",
                        "address", "salary", "income", "password", "secret"]
        pii_columns  = []

        schema_text = ctx.schema_result.get("schema_text", "").lower() if ctx.schema_result else ""
        for kw in pii_keywords:
            if kw in schema_text:
                pii_columns.append(kw)

        if pii_columns:
            result.log(f"ΓÜá PII detected: {pii_columns}", "warn")
        else:
            result.log("No PII columns detected")

        metadata = {
            "profile":         profile_text,
            "pii_columns":     pii_columns,
            "tables_profiled": len(tables),
            "quality_issues":  []
        }

        ctx.metadata_result = metadata
        result.log("Γ£ô Metadata complete")
        return metadata
