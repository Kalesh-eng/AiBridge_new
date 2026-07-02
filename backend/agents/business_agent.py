"""
agents/business_agent.py
Analyzes business requirements, defines KPIs, grain, and modeling goals.

v1.1: Safe fallback when AI is unavailable (503/429 errors)
"""

from .base import BaseAgent, AgentContext, AgentResult


class BusinessAgent(BaseAgent):
    name        = "BusinessAgent"
    description = "Analyzes business requirements, KPIs, grain definitions, and analytics goals"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from ai_provider import ask_ai

        result.log("Analyzing business requirements...")

        schema_text = ""
        if ctx.schema_result:
            schema_text = ctx.schema_result.get("schema_text", "")

        profile_text = ""
        if ctx.metadata_result:
            profile_text = ctx.metadata_result.get("profile", "")

        prompt = f"""You are a data warehouse business analyst.

SOURCE SYSTEM:
{ctx.source_description or 'Not provided'}

BUSINESS REQUIREMENTS:
{ctx.business_requirements or 'Not provided'}

SCHEMA SUMMARY:
{schema_text[:2000] if schema_text else 'Not available'}

DATA PROFILE:
{profile_text[:1000] if profile_text else 'Not available'}

Analyze the business requirements and return JSON:
{{
  "business_domain": "retail|finance|healthcare|education|manufacturing|other",
  "key_metrics": ["list of KPIs the business wants to measure"],
  "reporting_grain": "what does one row in the fact table represent",
  "time_dimension_needed": true,
  "suggested_dimensions": ["list of dimension concepts"],
  "suggested_facts": ["list of fact/metric concepts"],
  "analytics_goals": ["list of business questions to answer"],
  "complexity": "simple|medium|complex",
  "notes": "any important business rules or constraints"
}}"""

        # Safe AI call — fallback to empty defaults if AI unavailable
        try:
            ai_result = ask_ai(prompt)
        except Exception as e:
            result.log(f"AI unavailable ({type(e).__name__}) — using defaults", "warn")
            ai_result = {}

        business = {
            "business_domain":       ai_result.get("business_domain", "other"),
            "key_metrics":           ai_result.get("key_metrics", []),
            "reporting_grain":       ai_result.get("reporting_grain", ""),
            "time_dimension_needed": ai_result.get("time_dimension_needed", True),
            "suggested_dimensions":  ai_result.get("suggested_dimensions", []),
            "suggested_facts":       ai_result.get("suggested_facts", []),
            "analytics_goals":       ai_result.get("analytics_goals", []),
            "complexity":            ai_result.get("complexity", "medium"),
            "notes":                 ai_result.get("notes", "")
        }

        ctx.business_result = business
        result.log(f"Domain: {business['business_domain']}")
        result.log(f"Complexity: {business['complexity']}")
        result.log(f"KPIs: {business['key_metrics']}")
        result.log("✓ Business analysis complete")
        return business
