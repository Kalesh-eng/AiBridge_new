& e:/AIBRIDGE_Claude/venv/Scripts/python.exe -c "
import sys
sys.path.insert(0, '.')
from warehouse_knowledge import refresh_warehouse_knowledge
from database import SessionLocal
db = SessionLocal()
k = refresh_warehouse_knowledge(db)
db.close()
print('Tables:', len(k.get('warehouse_tables', {})))
print(k.get('schema_context', '')[:500])