"""
agents/planner_agent.py
Decides the execution plan based on schema + business analysis.
Chooses: Star Schema / Snowflake / ETL Only / KPI SQL / Metadata Only

v1.1: Safe fallback to star_schema when AI is unavailable (503/429 errors)
"""

from .base import BaseAgent, AgentContext, AgentResult


class PlannerAgent(BaseAgent):
    name        = "PlannerAgent"
    description = "Decides warehouse type and which agents to run based on requirements"

    PLANS = {
        "star_schema": [
            "RelationshipValidationAgent", "DataModelAgent", "ETLAgent",
            "SQLAgent", "SQLValidationAgent", "GovernanceValidationAgent",
            "ReviewAgent", "ExecutionAgent"
        ],
        "snowflake": [
            "RelationshipValidationAgent", "DataModelAgent", "ETLAgent",
            "SQLAgent", "SQLValidationAgent", "GovernanceValidationAgent",
            "ReviewAgent", "ExecutionAgent"
        ],
        "etl_only": [
            "ETLAgent", "ExecutionAgent"
        ],
        "kpi_sql": [
            "SQLAgent", "SQLValidationAgent", "GovernanceValidationAgent",
            "ReviewAgent", "ExecutionAgent"
        ],
        "metadata_only": [
            "MetadataAgent", "AnalyticsAgent"
        ]
    }

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from ai_provider import ask_ai

        result.log("Deciding execution plan...")

        schema_summary = ""
        if ctx.schema_result:
            tables = ctx.schema_result.get("source_tables", [])
            schema_summary = f"{len(tables)} tables: {tables}"

        business_summary = ""
        if ctx.business_result:
            business_summary = (
                f"Domain: {ctx.business_result.get('business_domain')}, "
                f"Complexity: {ctx.business_result.get('complexity')}, "
                f"KPIs: {ctx.business_result.get('key_metrics', [])}"
            )

        prompt = f"""You are a data warehouse architect.

SOURCE: {ctx.source_description or 'Not provided'}
REQUIREMENTS: {ctx.business_requirements or 'Not provided'}
SCHEMA: {schema_summary}
BUSINESS: {business_summary}

Choose the best execution plan:
- star_schema: Full Kimball star schema with fact + dimension tables (most common)
- snowflake: Normalized snowflake schema (hierarchical dimensions)
- etl_only: Just copy data source → staging → warehouse as-is (no modeling)
- kpi_sql: Generate SQL views/queries only (data already in warehouse)
- metadata_only: Profile and analyze data quality only (no warehouse build)

Return JSON:
{{
  "plan": "star_schema",
  "schema_type": "star",
  "reason": "why this plan was chosen",
  "needs_modeling": true,
  "needs_etl": true,
  "needs_sql_generation": true,
  "estimated_dimensions": 4,
  "estimated_facts": 1
}}"""

        # Safe AI call — fallback to star_schema if AI unavailable
        try:
            ai_result = ask_ai(prompt)
            plan_name = ai_result.get("plan", "star_schema")
        except Exception as e:
            result.log(f"AI unavailable ({type(e).__name__}) — defaulting to star_schema", "warn")
            ai_result = {}
            plan_name = "star_schema"

        if plan_name not in self.PLANS:
            result.log(f"Unknown plan '{plan_name}' — defaulting to star_schema", "warn")
            plan_name = "star_schema"

        plan = {
            "plan":                   plan_name,
            "schema_type":            ai_result.get("schema_type", "star"),
            "reason":                 ai_result.get("reason", "Defaulted to star schema"),
            "needs_modeling":         ai_result.get("needs_modeling", True),
            "needs_etl":              ai_result.get("needs_etl", True),
            "needs_sql_generation":   ai_result.get("needs_sql_generation", True),
            "estimated_dimensions":   ai_result.get("estimated_dimensions", 0),
            "estimated_facts":        ai_result.get("estimated_facts", 0),
            "agents":                 self.PLANS[plan_name]
        }

        ctx.plan = plan
        result.log(f"Plan selected: {plan_name}")
        result.log(f"Reason: {plan['reason']}")
        result.log(f"Agents to run: {plan['agents']}")
        return plan
