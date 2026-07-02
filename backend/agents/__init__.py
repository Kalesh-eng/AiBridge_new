"""
agents/__init__.py
AIBridge Multi-Agent System — 17 specialized agents

Flow:
  OrchestratorAgent coordinates:
    Phase 1 (parallel): SchemaAgent + MetadataAgent + BusinessAgent
    Phase 2: PlannerAgent
    Phase 3: RelationshipValidationAgent → DataModelAgent
    Phase 4: ETLAgent → SQLAgent → SQLValidationAgent → GovernanceValidationAgent
    Phase 5: ReviewAgent (HIL ⏸)
    Phase 6: ExecutionAgent → RecoveryAgent (conditional)
    Phase 7: QualityAgent  ← NEW
    Phase 8: AnalyticsAgent
"""

from .base                          import BaseAgent, AgentContext, AgentResult
from .orchestrator_agent            import OrchestratorAgent
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
from .quality_agent                 import QualityAgent
from .analytics_agent               import AnalyticsAgent

__all__ = [
    "BaseAgent", "AgentContext", "AgentResult",
    "OrchestratorAgent",
    "SchemaAgent", "MetadataAgent", "BusinessAgent",
    "PlannerAgent",
    "RelationshipValidationAgent",
    "DataModelAgent",
    "ETLAgent",
    "SQLAgent", "SQLValidationAgent", "GovernanceValidationAgent",
    "ReviewAgent",
    "ExecutionAgent",
    "RecoveryAgent",
    "QualityAgent",
    "AnalyticsAgent",
]