"""
agents/base.py
Base agent protocol. Every AIBridge agent follows this contract.

Rules:
  - Stateless: no shared mutable state between runs
  - Never raises: always returns AgentResult
  - Logs every step with [HH:MM:SS] timestamps
  - Input and output are typed dataclasses
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import traceback


@dataclass
class AgentContext:
    """
    Shared context passed through the entire pipeline.
    Agents READ from context and ADD their results to it.
    OrchestratorAgent builds this and passes it to each agent.
    """
    # Identifiers
    pipeline_id:      str  = ""
    workspace_id:     str  = ""
    run_id:           str  = ""

    # Source config
    connector_config: dict = field(default_factory=dict)
    source_schema:    str  = "raw"
    source_tables:    list = field(default_factory=list)
    source_columns:   dict = field(default_factory=dict)

    # User inputs
    source_description:    str = ""
    business_requirements: str = ""

    # Target config
    target_config:    dict = field(default_factory=dict)
    staging_schema:   str  = "staging"
    warehouse_schema: str  = "warehouse"

    # Agent outputs (populated as pipeline progresses)
    schema_result:              Any = None   # SchemaAgent
    metadata_result:            Any = None   # MetadataAgent
    business_result:            Any = None   # BusinessAgent
    plan:                       Any = None   # PlannerAgent
    relationship_validation:    Any = None   # RelationshipValidationAgent
    data_model:                 Any = None   # DataModelAgent
    etl_mappings:               Any = None   # ETLAgent (mappings phase)
    staging_result:             Any = None   # ETLAgent (extract phase)
    sql_scripts:                Any = None   # SQLAgent
    sql_validation:             Any = None   # SQLValidationAgent
    governance_validation:      Any = None   # GovernanceValidationAgent
    review_result:              Any = None   # ReviewAgent
    execution_result:           Any = None   # ExecutionAgent
    recovery_result:            Any = None   # RecoveryAgent
    quality_result:             Any = None   # QualityAgent
    analytics_result:           Any = None   # AnalyticsAgent

    # FK relationships from RelationshipValidationAgent
    # Passed into AI prompts for generic bridge join generation
    fk_relationships: list = field(default_factory=list)

    # Pipeline-level log (all agents append here)
    pipeline_log: list = field(default_factory=list)

    # Control flags
    blocked:          bool = False
    blocked_reason:   str  = ""
    needs_human:      bool = False
    human_feedback:   str  = ""


@dataclass
class AgentResult:
    """Returned by every agent's run() method."""
    success:    bool          = False
    agent_name: str           = ""
    data:       Any           = None
    error:      Optional[str] = None
    logs:       list          = field(default_factory=list)
    started_at: str           = ""
    ended_at:   str           = ""
    duration_s: float         = 0.0

    def log(self, msg: str, level: str = "info"):
        ts    = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] [{level.upper()}] [{self.agent_name}] {msg}"
        self.logs.append(entry)
        print(entry)


class BaseAgent:
    """
    Base class for all AIBridge agents.

    Subclasses must set:
      name: str
      description: str

    Subclasses must implement:
      process(ctx: AgentContext, result: AgentResult) -> Any
    """
    name:        str = "BaseAgent"
    description: str = "Base agent — override in subclass"

    def run(self, ctx: AgentContext) -> AgentResult:
        result = AgentResult(
            agent_name = self.name,
            started_at = datetime.utcnow().isoformat()
        )
        start = datetime.utcnow()
        result.log(f"▶ Starting")

        try:
            data = self.process(ctx, result)
            if data is not None:
                result.data = data
            result.success = True
            result.log(f"✓ Completed successfully")
        except Exception as e:
            result.success = False
            result.error   = str(e)
            result.log(f"✗ Failed: {e}", "error")
            result.log(traceback.format_exc(), "error")

        result.ended_at   = datetime.utcnow().isoformat()
        result.duration_s = (datetime.utcnow() - start).total_seconds()
        result.log(f"Duration: {result.duration_s:.2f}s")

        ctx.pipeline_log.extend(result.logs)
        return result

    def process(self, ctx: AgentContext, result: AgentResult) -> Any:
        raise NotImplementedError(f"{self.name}.process() not implemented")
