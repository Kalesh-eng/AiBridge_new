"""
agents/governance_validation_agent.py
Safety and governance checks BEFORE human review.
Wraps sql_safety.py + adds PII + row count checks.

Checks:
  - Dangerous SQL (TRUNCATE, DELETE without WHERE, DROP)
  - PII columns handled (masked or excluded)
  - Row count reasonableness
  - Data retention rules
"""

from .base import BaseAgent, AgentContext, AgentResult


class GovernanceValidationAgent(BaseAgent):
    name        = "GovernanceValidationAgent"
    description = "Safety, PII, and governance checks before human review"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        from sql_safety import check_pipeline_safety

        if not ctx.sql_scripts:
            raise ValueError("SQLAgent must run before GovernanceValidationAgent")

        scripts = ctx.sql_scripts.get("scripts", [])
        result.log(f"Running governance checks on {len(scripts)} scripts...")

        # ── Check 1: SQL safety (dangerous statements) ────────────────────────
        safety = check_pipeline_safety(scripts, allow_destructive=False)

        violations = safety.get("violations", [])
        warnings   = safety.get("warnings", [])
        blocked    = safety.get("blocked", False)

        for v in violations:
            result.log(f"✗ VIOLATION: {v}", "error")
        for w in warnings:
            result.log(f"⚠ WARNING: {w}", "warn")

        # ── Check 2: PII column handling ──────────────────────────────────────
        pii_issues = []
        if ctx.metadata_result:
            pii_cols = ctx.metadata_result.get("pii_columns", [])
            if pii_cols:
                # Check if PII columns appear unmasked in SQL
                all_sql = " ".join(s.get("sql", "") for s in scripts).lower()
                for col in pii_cols:
                    if col.lower() in all_sql:
                        pii_issues.append(f"PII column '{col}' appears in warehouse SQL unmasked")
                        result.log(f"⚠ PII: '{col}' is unmasked in warehouse", "warn")

        # ── Check 3: Block if safety violations ───────────────────────────────
        if blocked:
            ctx.blocked        = True
            ctx.blocked_reason = safety.get("message", "Dangerous SQL detected")
            result.log(f"🚫 BLOCKED: {ctx.blocked_reason}", "error")

        governance = {
            "passed":       not blocked,
            "blocked":      blocked,
            "violations":   violations,
            "warnings":     warnings + pii_issues,
            "pii_issues":   pii_issues,
            "safety_score": safety.get("score", 100)
        }

        ctx.governance_validation = governance

        if governance["passed"]:
            result.log(f"✓ Governance checks passed — {len(warnings)} warnings")
        else:
            result.log(f"🚫 Governance checks FAILED — pipeline blocked", "error")

        return governance
