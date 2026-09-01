"""
AIBridge v2 — Script Intelligence Engine
==========================================
Reads SQL, Python, Informatica XML, dbt models and extracts:
1. Business rules (filters, exclusions, validations)
2. Calculations and metric definitions
3. Data transformations
4. Column mappings and lineage
5. Implicit assumptions about data quality

These rules are stored in the Knowledge Graph and used by
Neon BI to generate correct, context-aware queries.
"""

import re
from ai_provider import ask_ai_text


# ── Rule categories ──────────────────────────────────────────────────────────

RULE_TYPES = {
    "exclusion":    "Data excluded from analysis (WHERE col != 'X')",
    "filter":       "Standard filter applied (WHERE status = 'active')",
    "calculation":  "Business metric calculation (revenue = price * qty)",
    "mapping":      "Column or value mapping (code 'B2B' = Business customer)",
    "date_logic":   "Date-based business rule (pre-2019 = legacy data)",
    "quality":      "Data quality assumption (amount > 0 = valid sale)",
    "join":         "Table relationship (orders JOIN customers ON customer_id)",
}


# ── SQL Parser ───────────────────────────────────────────────────────────────

def _extract_sql_rules(sql: str) -> list:
    """Extract business rules from SQL using pattern matching + AI."""
    rules = []

    # 1. Extract WHERE clause conditions
    where_match = re.findall(
        r'WHERE\s+([\s\S]+?)(?:GROUP BY|ORDER BY|HAVING|LIMIT|$)',
        sql, re.IGNORECASE
    )
    for where_clause in where_match:
        # Find NOT IN exclusions
        not_in = re.findall(
            r'(\w+)\s+NOT\s+IN\s*\(([^)]+)\)',
            where_clause, re.IGNORECASE
        )
        for col, vals in not_in:
            rules.append({
                "type": "exclusion",
                "column": col,
                "values": [v.strip().strip("'\"") for v in vals.split(",")],
                "description": f"Exclude {col} values: {vals.strip()}",
                "source": "sql_where",
            })

        # Find equality filters
        eq_filters = re.findall(
            r'(\w+)\s*=\s*[\'"]([^\'"]+)[\'"]',
            where_clause
        )
        for col, val in eq_filters:
            if col.lower() not in ('and', 'or', 'not', 'where'):
                rules.append({
                    "type": "filter",
                    "column": col,
                    "value": val,
                    "description": f"Filter: {col} = '{val}'",
                    "source": "sql_where",
                })

        # Find comparison filters (amount > 0, year >= 2019)
        comparisons = re.findall(
            r'(\w+)\s*(>=|<=|>|<|!=|<>)\s*([\'"]?[\w\-]+[\'"]?)',
            where_clause
        )
        for col, op, val in comparisons:
            if col.lower() not in ('and', 'or', 'not', 'where', '1'):
                rtype = "date_logic" if any(kw in col.lower() for kw in ['date', 'year', 'dt', 'time']) else "quality"
                rules.append({
                    "type": rtype,
                    "column": col,
                    "operator": op,
                    "value": val.strip("'\""),
                    "description": f"Rule: {col} {op} {val}",
                    "source": "sql_where",
                })

    # 2. Extract calculated columns
    case_calcs = re.findall(
        r'(\w+)\s*=\s*([\w\s\+\-\*\/\(\)\.]+?)(?:,|\n|FROM)',
        sql, re.IGNORECASE
    )
    for alias, expr in case_calcs:
        if any(op in expr for op in ['+', '-', '*', '/']):
            rules.append({
                "type": "calculation",
                "column": alias,
                "formula": expr.strip(),
                "description": f"Calculation: {alias} = {expr.strip()}",
                "source": "sql_select",
            })

    # 3. Extract CASE WHEN logic
    case_whens = re.findall(
        r'CASE\s+WHEN\s+([\s\S]+?)\s+END',
        sql, re.IGNORECASE
    )
    for case in case_whens:
        rules.append({
            "type": "mapping",
            "formula": f"CASE WHEN {case[:100]}",
            "description": f"Business mapping: CASE WHEN {case[:80]}...",
            "source": "sql_case",
        })

    return rules


# ── Python Parser ────────────────────────────────────────────────────────────

def _extract_python_rules(code: str) -> list:
    """Extract business rules from Python/pandas code."""
    rules = []

    # Filter operations: df[df['col'] != value]
    filters = re.findall(
        r'df\[df\[[\'"]([\w]+)[\'"]\]\s*(!=|==|>|<|>=|<=)\s*([^\]]+)\]',
        code
    )
    for col, op, val in filters:
        rtype = "exclusion" if op in ('!=', '<>') else "filter"
        rules.append({
            "type": rtype,
            "column": col,
            "operator": op,
            "value": val.strip().strip("'\""),
            "description": f"Python filter: {col} {op} {val.strip()}",
            "source": "python_filter",
        })

    # Assignment calculations: df['col'] = expression
    calcs = re.findall(
        r'df\[[\'"]([\w]+)[\'"]\]\s*=\s*(.+)',
        code
    )
    for col, expr in calcs:
        if any(op in expr for op in ['+', '-', '*', '/', 'sum', 'mean', 'avg']):
            rules.append({
                "type": "calculation",
                "column": col,
                "formula": expr.strip(),
                "description": f"Python calc: {col} = {expr.strip()[:80]}",
                "source": "python_calc",
            })

    # dropna / fillna patterns
    dropna = re.findall(r'\.dropna\(subset=\[([^\]]+)\]\)', code)
    for cols in dropna:
        rules.append({
            "type": "quality",
            "columns": cols,
            "description": f"Drop nulls in: {cols}",
            "source": "python_quality",
        })

    return rules


# ── Informatica XML Parser ───────────────────────────────────────────────────

def _extract_informatica_rules(xml: str) -> list:
    """Extract business rules from Informatica PowerCenter XML."""
    rules = []

    # Extract transformation expressions
    expr_fields = re.findall(
        r'<TRANSFORMFIELD NAME=[\'"]([^\'"]+)[\'"][^>]*EXPRESSION=[\'"]([^\'"]+)[\'"]',
        xml, re.IGNORECASE
    )
    for name, expr in expr_fields:
        if any(kw in expr.upper() for kw in ['IIF', 'DECODE', 'CASE', 'IN(']):
            rules.append({
                "type": "mapping",
                "column": name,
                "formula": expr[:200],
                "description": f"Informatica mapping: {name} = {expr[:100]}",
                "source": "informatica_xml",
            })
        elif any(op in expr for op in ['+', '-', '*', '/']):
            rules.append({
                "type": "calculation",
                "column": name,
                "formula": expr[:200],
                "description": f"Informatica calc: {name} = {expr[:100]}",
                "source": "informatica_xml",
            })

    # Extract filter conditions
    filters = re.findall(
        r'<FILTERPROPERTIES CONDITION=[\'"]([^\'"]+)[\'"]',
        xml, re.IGNORECASE
    )
    for condition in filters:
        rules.append({
            "type": "filter",
            "condition": condition,
            "description": f"Informatica filter: {condition[:100]}",
            "source": "informatica_filter",
        })

    # Extract source/target mappings
    mappings = re.findall(
        r'<CONNECTOR FROMFIELD=[\'"]([^\'"]+)[\'"] TOFIELD=[\'"]([^\'"]+)[\'"]',
        xml, re.IGNORECASE
    )
    for src, tgt in mappings[:20]:
        if src.lower() != tgt.lower():
            rules.append({
                "type": "mapping",
                "source_column": src,
                "target_column": tgt,
                "description": f"Column mapping: {src} → {tgt}",
                "source": "informatica_mapping",
            })

    return rules


# ── dbt Parser ───────────────────────────────────────────────────────────────

def _extract_dbt_rules(content: str, file_type: str = "sql") -> list:
    """Extract business rules from dbt SQL models and YAML."""
    rules = []

    if file_type == "yaml":
        # Extract column descriptions
        col_descs = re.findall(
            r'name:\s*(\w+)\s*\n\s*description:\s*[\'"]?([^\'">\n]+)',
            content
        )
        for col, desc in col_descs:
            rules.append({
                "type": "mapping",
                "column": col,
                "description": f"dbt doc: {col} = {desc.strip()}",
                "source": "dbt_yaml",
            })

        # Extract tests → quality rules
        not_null = re.findall(r'- not_null.*?name:\s*(\w+)', content, re.DOTALL)
        accepted = re.findall(
            r'accepted_values:.*?column_name:\s*(\w+).*?values:\s*\[([^\]]+)\]',
            content, re.DOTALL
        )
        for col in not_null:
            rules.append({
                "type": "quality",
                "column": col,
                "description": f"dbt test: {col} must not be null",
                "source": "dbt_test",
            })
        for col, vals in accepted:
            rules.append({
                "type": "filter",
                "column": col,
                "values": [v.strip().strip("'\"") for v in vals.split(",")],
                "description": f"dbt test: {col} accepted values = [{vals}]",
                "source": "dbt_test",
            })
    else:
        # SQL model — use SQL extractor
        rules.extend(_extract_sql_rules(content))

        # Also look for dbt ref() patterns for lineage
        refs = re.findall(r'\{\{\s*ref\([\'"](\w+)[\'"]\)\s*\}\}', content)
        for ref in refs:
            rules.append({
                "type": "join",
                "table": ref,
                "description": f"dbt dependency: references {ref}",
                "source": "dbt_ref",
            })

    return rules


# ── AI Enhancement ───────────────────────────────────────────────────────────

def _enhance_rules_with_ai(rules: list, script_content: str, script_type: str) -> dict:
    """Use AI to extract additional rules and summarize findings."""

    # Build a compact rule summary
    rule_summary = "\n".join([
        f"- {r.get('type','?')}: {r.get('description','')}"
        for r in rules[:20]
    ])

    # Send script excerpt to AI
    excerpt = script_content[:3000]

    prompt = f"""Analyze this {script_type} script and extract ALL business rules.

Script excerpt:
```
{excerpt}
```

Rules already extracted:
{rule_summary if rule_summary else "(none yet)"}

Extract additional business rules I may have missed. Focus on:
1. Data exclusions (test data, invalid records, special codes)
2. Business calculations (how metrics are computed)
3. Time-based logic (date ranges, fiscal years, cutoffs)
4. Data quality assumptions (valid ranges, non-null requirements)
5. Business entity definitions (what makes a 'customer', 'sale', 'active')

For each rule, format as:
TYPE: [exclusion/filter/calculation/date_logic/quality/mapping]
COLUMN: [column name if applicable]
RULE: [plain English description]
---"""

    try:
        ai_response = ask_ai_text(prompt, agent_name="ScriptIntelligence")

        # Parse AI response into additional rules
        ai_rules = []
        blocks = ai_response.split('---')
        for block in blocks:
            if 'TYPE:' in block and 'RULE:' in block:
                rtype = re.search(r'TYPE:\s*(\w+)', block)
                col = re.search(r'COLUMN:\s*(\w+)', block)
                rule = re.search(r'RULE:\s*(.+)', block)
                if rtype and rule:
                    ai_rules.append({
                        "type": rtype.group(1).lower(),
                        "column": col.group(1) if col else None,
                        "description": rule.group(1).strip(),
                        "source": "ai_extracted",
                    })

        return {
            "ai_summary": ai_response[:500],
            "ai_rules": ai_rules,
            "success": True,
        }
    except Exception as e:
        return {"ai_summary": "", "ai_rules": [], "success": False, "error": str(e)}


# ── Main entry point ─────────────────────────────────────────────────────────

def analyze_script(content: str, filename: str = "", use_ai: bool = True) -> dict:
    """
    Main entry point. Detects script type and extracts all business rules.

    Args:
        content: Script content as string
        filename: Original filename (used for type detection)
        use_ai: Whether to enhance with AI extraction

    Returns:
        dict with rules, summary, and metadata
    """
    # Detect script type
    fname = filename.lower()
    if fname.endswith('.xml') or '<transformation' in content.lower():
        script_type = "informatica_xml"
    elif fname.endswith('.py') or 'import pandas' in content or 'def ' in content:
        script_type = "python"
    elif fname.endswith('.yml') or fname.endswith('.yaml'):
        script_type = "dbt_yaml"
    elif 'ref(' in content and ('select' in content.lower() or 'with' in content.lower()):
        script_type = "dbt_sql"
    else:
        script_type = "sql"

    # Extract rules using appropriate parser
    if script_type == "informatica_xml":
        rules = _extract_informatica_rules(content)
    elif script_type == "python":
        rules = _extract_python_rules(content)
    elif script_type == "dbt_yaml":
        rules = _extract_dbt_rules(content, "yaml")
    elif script_type == "dbt_sql":
        rules = _extract_dbt_rules(content, "sql")
    else:
        rules = _extract_sql_rules(content)

    # Enhance with AI
    ai_result = {}
    if use_ai and content.strip():
        ai_result = _enhance_rules_with_ai(rules, content, script_type)
        if ai_result.get("ai_rules"):
            rules.extend(ai_result["ai_rules"])

    # Deduplicate rules
    seen = set()
    unique_rules = []
    for r in rules:
        key = r.get("description", "")[:80]
        if key not in seen:
            seen.add(key)
            unique_rules.append(r)

    # Count by type
    type_counts = {}
    for r in unique_rules:
        rtype = r.get("type", "unknown")
        type_counts[rtype] = type_counts.get(rtype, 0) + 1

    return {
        "success": True,
        "script_type": script_type,
        "filename": filename,
        "rules": unique_rules,
        "rule_count": len(unique_rules),
        "rule_types": type_counts,
        "ai_summary": ai_result.get("ai_summary", ""),
        "lines_analyzed": len(content.splitlines()),
    }


def analyze_multiple_scripts(scripts: list) -> dict:
    """
    Analyze multiple scripts and merge their business rules.

    Args:
        scripts: List of {"content": str, "filename": str}

    Returns:
        Merged knowledge base with all rules
    """
    all_rules = []
    summaries = []

    for script in scripts:
        result = analyze_script(
            content=script.get("content", ""),
            filename=script.get("filename", "unknown"),
        )
        all_rules.extend(result.get("rules", []))
        summaries.append({
            "filename": script.get("filename"),
            "script_type": result.get("script_type"),
            "rule_count": result.get("rule_count"),
        })

    # Deduplicate across scripts
    seen = set()
    unique_rules = []
    for r in all_rules:
        key = r.get("description", "")[:80]
        if key not in seen:
            seen.add(key)
            unique_rules.append(r)

    return {
        "success": True,
        "scripts_analyzed": len(scripts),
        "script_summaries": summaries,
        "total_rules": len(unique_rules),
        "rules": unique_rules,
    }
