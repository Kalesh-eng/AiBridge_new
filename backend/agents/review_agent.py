"""
agents/review_agent.py
Human-in-the-Loop (HIL) gateway.
Manages Gate 1 (model review) and Gate 2 (SQL review).
Wraps the existing ApprovalQueue pattern from main.py.
"""

from .base import BaseAgent, AgentContext, AgentResult


class ReviewAgent(BaseAgent):
    name        = "ReviewAgent"
    description = "Human-in-the-Loop gateway — presents model and SQL for human approval"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from database import get_db, ApprovalQueue
        from datetime import datetime

        result.log("Preparing HIL review...")

        # Determine what needs review
        needs_model_review = ctx.data_model is not None
        needs_sql_review   = ctx.sql_scripts is not None

        review_items = []

        if needs_model_review:
            review_items.append("data_model")
            result.log("Gate 1: Data model ready for human review")

        if needs_sql_review:
            scripts = ctx.sql_scripts.get("scripts", [])
            review_items.append("sql_scripts")
            result.log(f"Gate 2: {len(scripts)} SQL scripts ready for human review")

        # Check governance warnings to surface to human
        gov_warnings = []
        if ctx.governance_validation:
            gov_warnings = ctx.governance_validation.get("warnings", [])
            if gov_warnings:
                result.log(f"⚠ Surfacing {len(gov_warnings)} governance warnings to human")

        ctx.needs_human = True
        review = {
            "status":         "pending",
            "review_items":   review_items,
            "gov_warnings":   gov_warnings,
            "data_model":     ctx.data_model,
            "sql_scripts":    ctx.sql_scripts,
            "submitted_at":   datetime.utcnow().isoformat()
        }

        ctx.review_result = review
        result.log(f"✓ Review prepared — {len(review_items)} items pending human approval")
        result.log("⏸ Waiting for human approval via /pipeline/approve-model and /pipeline/approve-sql")

        return review
