from .base import BaseAgent, AgentContext, AgentResult


class RecoveryAgent(BaseAgent):
    name        = "RecoveryAgent"
    description = "Detects execution failures, auto-fixes SQL using AI, and retries"

    def process(self, ctx: AgentContext, result: AgentResult) -> dict:
        import recovery_agent as ra

        if not ctx.execution_result:
            raise ValueError("ExecutionAgent must run before RecoveryAgent")

        exec_result    = ctx.execution_result
        scripts        = ctx.sql_scripts.get("scripts", []) if ctx.sql_scripts else []
        failed_scripts = [s for s in exec_result.get("scripts", []) if not s.get("success", True)]

        if not failed_scripts:
            result.log("No failed scripts - nothing to recover")
            ctx.recovery_result = {"recovered": 0, "failed": 0, "actions": []}
            return ctx.recovery_result

        result.log(f"Attempting recovery for {len(failed_scripts)} failed scripts...")
        target_config = ctx.target_config if ctx.target_config else ctx.connector_config
        recovered     = 0
        actions       = []

        for failed in failed_scripts:
            script_name = failed.get("name", "unknown")
            error_msg   = failed.get("error", "")
            result.log(f"Recovering: {script_name}")
            try:
                recovery = ra.recover_pipeline(
                    failed_script = script_name,
                    error_message = error_msg,
                    all_scripts   = scripts,
                    conn_config   = target_config,
                    pipeline_id   = ctx.pipeline_id,
                    workspace_id  = ctx.workspace_id,
                    run_id        = ctx.run_id
                )
                if recovery.get("recovered"):
                    recovered += 1
                    result.log(f"Recovered: {script_name} via {recovery.get('fix_method')}")
                    actions.append({"script": script_name, "recovered": True,
                                    "fix_method": recovery.get("fix_method"),
                                    "action": recovery.get("action_taken")})
                else:
                    result.log(f"Could not recover: {script_name}", "warn")
                    actions.append({"script": script_name, "recovered": False,
                                    "reason": recovery.get("summary", "")})
            except Exception as e:
                result.log(f"Recovery exception: {e}", "error")
                actions.append({"script": script_name, "recovered": False, "reason": str(e)})

        unrecovered = len(failed_scripts) - recovered
        ctx.recovery_result = {
            "recovered": recovered, "failed": unrecovered,
            "total_attempted": len(failed_scripts), "actions": actions,
            "needs_escalation": unrecovered > 0
        }
        result.log(f"Recovery complete: {recovered}/{len(failed_scripts)} scripts fixed")
        if unrecovered > 0:
            result.log(f"{unrecovered} scripts need human escalation", "warn")
        return ctx.recovery_result
