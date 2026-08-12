with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    lines = f.readlines()

# Find the dedup block
for i, line in enumerate(lines):
    if 'Fix 0b-pre: Remove duplicate column definitions' in line:
        print(f"Found at line {i+1}")
        # Find the end of the block
        for j in range(i+1, min(len(lines), i+30)):
            if '# Fix 0b: SERIAL' in lines[j]:
                end = j
                print(f"Block ends at line {j+1}")
                break
        
        # Replace the entire dedup block with a correct implementation
        new_block = [
            '            # Fix 0b-pre: Remove duplicate column definitions in CREATE TABLE\n',
            '            if "CREATE TABLE" in sql.upper() and "CREATE TABLE" in sql:\n',
            '                import re as _re_dup\n',
            '                # Find the full CREATE TABLE (...) block — match from first ( to matching )\n',
            '                _ct_match = _re_dup.search(\n',
            '                    r\'CREATE\\s+TABLE\\s+[^(]+\\(\',\n',
            '                    sql, _re_dup.IGNORECASE\n',
            '                )\n',
            '                if _ct_match:\n',
            '                    # Find the matching closing paren for the CREATE TABLE block\n',
            '                    _start = _ct_match.end() - 1  # position of opening (\n',
            '                    _depth = 0\n',
            '                    _end = _start\n',
            '                    for _ci, _ch in enumerate(sql[_start:], _start):\n',
            '                        if _ch == \'(\': _depth += 1\n',
            '                        elif _ch == \')\': \n',
            '                            _depth -= 1\n',
            '                            if _depth == 0: _end = _ci; break\n',
            '                    if _end > _start:\n',
            '                        _cols_block = sql[_start+1:_end]\n',
            '                        _col_defs = [c.strip() for c in _cols_block.split(\',\') if c.strip()]\n',
            '                        _seen = set()\n',
            '                        _unique = []\n',
            '                        for _cdef in _col_defs:\n',
            '                            _words = _cdef.split()\n',
            '                            _cname = _words[0].strip(\'"\')\\.lower() if _words else ""\n',
            '                            if _cname and _cname not in _seen:\n',
            '                                _seen.add(_cname)\n',
            '                                _unique.append(_cdef)\n',
            '                            elif _cname in _seen:\n',
            '                                pass  # skip duplicate\n',
            '                            else:\n',
            '                                _unique.append(_cdef)\n',
            '                        _new_block = "(" + ",\\n    ".join(_unique) + ")"\n',
            '                        _new_sql = sql[:_start] + _new_block + sql[_end+1:]\n',
            '                        if _new_sql != sql:\n',
            '                            sql = _new_sql\n',
            '                            log(f"[SQLPatch] Deduped CREATE TABLE columns for: {script.get(\'name\')}")\n',
        ]
        lines[i:end] = new_block
        print(f"✓ Replaced dedup block with correct implementation")
        break

with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

import ast
with open('E:/AIBRIDGE_Claude/backend/pipeline_executor.py', encoding='utf-8') as f:
    src = f.read()
try:
    ast.parse(src)
    print(f"Syntax OK — {len(src.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
    src_lines = src.splitlines()
    for j in range(max(0,e.lineno-3), min(len(src_lines),e.lineno+2)):
        print(f"  {j+1}: {src_lines[j]}")
