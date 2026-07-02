src = open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8').read()
src = src.replace('SELECT id, pipeline_id, run_id, table_name, column_name,\n                   issue_type, reason, check_type, check_date', 'SELECT audit_id, pipeline_id, run_id, table_name, column_name,\n                   issue_type, reason, check_type, check_date, created_at')
open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8').write(src)
print('Fixed')