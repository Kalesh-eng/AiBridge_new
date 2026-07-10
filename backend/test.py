with open('E:/AIBRIDGE_Claude/backend/universal_connector.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "Write to PostgreSQL staging" comment
for i, line in enumerate(lines):
    if 'Write to PostgreSQL staging' in line:
        print(f"Found at line {i+1}: {line.rstrip()}")
        # Find the block — from this comment to engine.dispose()
        start = i
        end = None
        for j in range(i, min(len(lines), i+15)):
            if 'engine.dispose()' in lines[j]:
                end = j
                break
        if end:
            print(f"Block runs from line {start+1} to {end+1}")
            # Replace the block
            new_block = '''            # Write to target staging DB (any supported DB type)
            tgt_ct_stg = target_config.get("connector_type", "postgres").lower()
            if tgt_ct_stg in ("postgres", "postgresql", "redshift"):
                from sqlalchemy import create_engine as _ce
                port = target_config.get("port", 5432)
                tgt_url = (
                    f"postgresql+psycopg2://{target_config['username']}:{target_config['password']}"
                    f"@{target_config['host']}:{port}/{target_config['database']}"
                )
                engine = _ce(tgt_url)
                df.to_sql(stg, engine, schema=staging_schema,
                          if_exists="replace", index=False,
                          chunksize=10000, method="multi")
                engine.dispose()
            elif tgt_ct_stg == "mysql":
                from sqlalchemy import create_engine as _ce
                port = target_config.get("port", 3306)
                tgt_url = (
                    f"mysql+pymysql://{target_config['username']}:{target_config['password']}"
                    f"@{target_config['host']}:{port}/{target_config['database']}"
                )
                engine = _ce(tgt_url)
                df.to_sql(stg, engine, schema=None,
                          if_exists="replace", index=False,
                          chunksize=10000, method="multi")
                engine.dispose()
            elif tgt_ct_stg in ("sqlserver", "mssql", "azuresql"):
                from sqlalchemy import create_engine as _ce
                import urllib
                port = target_config.get("port", 1433)
                params = urllib.parse.quote_plus(
                    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                    f"SERVER={target_config['host']},{port};"
                    f"DATABASE={target_config['database']};"
                    f"UID={target_config['username']};"
                    f"PWD={target_config['password']}"
                )
                tgt_url = f"mssql+pyodbc:///?odbc_connect={params}"
                engine = _ce(tgt_url)
                df.to_sql(stg, engine, schema=staging_schema,
                          if_exists="replace", index=False,
                          chunksize=10000, method="multi")
                engine.dispose()
            elif tgt_ct_stg == "snowflake":
                from sqlalchemy import create_engine as _ce
                account  = target_config.get("account", "")
                tgt_url  = (
                    f"snowflake://{target_config['username']}:{target_config['password']}"
                    f"@{account}/{target_config['database']}/{staging_schema}"
                )
                engine = _ce(tgt_url)
                df.to_sql(stg, engine, schema=staging_schema,
                          if_exists="replace", index=False,
                          chunksize=10000, method="multi")
                engine.dispose()
            elif tgt_ct_stg == "bigquery":
                # BigQuery uses pandas-gbq or bigquery storage API
                project = target_config.get("project_id", target_config.get("database", ""))
                dataset = staging_schema
                df.to_gbq(
                    f"{dataset}.{stg}",
                    project_id=project,
                    if_exists="replace",
                    credentials=None  # uses ADC or service account from target_config
                )
            else:
                # Fallback to PostgreSQL
                from sqlalchemy import create_engine as _ce
                port = target_config.get("port", 5432)
                tgt_url = (
                    f"postgresql+psycopg2://{target_config['username']}:{target_config['password']}"
                    f"@{target_config['host']}:{port}/{target_config['database']}"
                )
                engine = _ce(tgt_url)
                df.to_sql(stg, engine, schema=staging_schema,
                          if_exists="replace", index=False,
                          chunksize=10000, method="multi")
                engine.dispose()
'''
            # Replace lines from start to end+1
            lines[start:end+1] = [new_block]
            print("✓ Replaced staging write block with universal version")
        break

# Also update the docstring
for i, line in enumerate(lines):
    if 'Target (staging) is always PostgreSQL.' in line:
        lines[i] = '    Target (staging) is any supported DB — client choice.\n'
        print("✓ Updated docstring")
        break

with open('E:/AIBRIDGE_Claude/backend/universal_connector.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/universal_connector.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")