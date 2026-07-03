with open('E:/AIBRIDGE_Claude/backend/agents/quality_agent.py', encoding='utf-8') as f:
    src = f.read()

old = """    business_required = [
        col.split(".")[-1]
        for col, is_req in required_columns.items()
        if is_req and col.split(".")[-1] in col_names
    ]"""

new = """    # Case-insensitive match — required cols may be lowercase, staging cols may be mixed case
    col_names_lower = {c.lower(): c for c in col_names}
    business_required = [
        col_names_lower[col.split(".")[-1].lower()]
        for col, is_req in required_columns.items()
        if is_req and col.split(".")[-1].lower() in col_names_lower
    ]"""

if old in src:
    src = src.replace(old, new)
    with open('E:/AIBRIDGE_Claude/backend/agents/quality_agent.py', 'w', encoding='utf-8') as f:
        f.write(src)
    print("Fixed: case-insensitive column matching")
else:
    print("ERROR: not found")