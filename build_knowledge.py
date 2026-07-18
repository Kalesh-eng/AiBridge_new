import sys
sys.path.insert(0, 'E:/AIBRIDGE_Claude/backend')
from database import SessionLocal
from warehouse_knowledge import refresh_warehouse_knowledge

db = SessionLocal()
knowledge = refresh_warehouse_knowledge(db)
db.close()

print(f"\nKnowledge graph built:")
print(f"  Pipelines: {len(knowledge.get('pipelines', {}))}")
print(f"  Tables: {len(knowledge.get('warehouse_tables', {}))}")
print(f"  Relationships: {len(knowledge.get('relationships', []))}")
print(f"\nSchema context preview:")
ctx = knowledge.get('schema_context', '')
print(ctx[:800])
