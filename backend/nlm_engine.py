"""
nlm_engine.py — Universal AI ETL.

v2.6: Full flat file / no-natural-key support.
      - Data model JSON has has_natural_key + join_on_source_col fields
      - _build_table_instructions handles dims with no ID columns
      - SCD Type 1/2 without natural key → DISTINCT insert, no ON CONFLICT
      - Fact JOINs use actual attribute columns when no ID exists
      - Domain mismatch validation (v2.5)
      - No invented ID columns rules in both prompts
v2.5: Domain mismatch validation — generic guardrail.
v2.4: Corrected MEASURES vs ATTRIBUTES rule.
v2.3: Single source table rule — generic intermediate staging.
v2.2: Removed balance exception.
v2.1: MEASURES vs ATTRIBUTES rule.
v2.0: Generic FK-driven bridge joins.
"""

import json
import re
from ai_provider import ask_ai


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — Schema analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_schema(source_description: str, raw_schema: str,
                   data_profile_text: str = "") -> dict:
    profile_section = ""
    if data_profile_text:
        profile_section = f"""

ACTUAL DATABASE PROFILE (use as source of truth):
{data_profile_text}
"""

    prompt = f"""You are a data architect AI. Analyze this source schema.
Return ONLY valid JSON:
{{
  "entities": [
    {{
      "name": "table_name",
      "type": "transaction or master or reference",
      "columns": ["col1", "col2"],
      "primary_key": "col_name",
      "row_estimate": "10K"
    }}
  ],
  "relationships": [
    {{
      "from_table": "orders",
      "to_table": "customers",
      "join_key": "customer_id",
      "cardinality": "many-to-one",
      "confidence": "high"
    }}
  ],
  "notes": "one line summary"
}}

Source system: {source_description}
Schema (source tables):
{raw_schema}
{profile_section}"""
    return ask_ai(prompt)


def generate_data_model(schema_analysis: dict, business_requirements: str,
                        data_profile_text: str = "",
                        source_tables: list = None,
                        fk_relationships: list = None) -> dict:
    profile_section = ""
    if data_profile_text:
        profile_section = f"""

DATABASE PROFILE (use real column types, cardinality, sample values):
{data_profile_text}
"""

    # Build the actual source tables list for anti-hallucination rule
    actual_tables = source_tables or []
    if not actual_tables:
        actual_tables = [e.get("name", "") for e in schema_analysis.get("entities", []) if e.get("name")]

    actual_tables_str  = ", ".join(actual_tables) if actual_tables else "unknown"
    staging_tables_str = ", ".join([f"stg_{t}" for t in actual_tables]) if actual_tables else "unknown"

    # Build actual column list from schema_analysis entities
    # This is critical for flat file sources — AI must use EXACT column names
    actual_columns_section = ""
    entities = schema_analysis.get("entities", [])
    if entities:
        col_lines = []
        for entity in entities:
            cols = entity.get("columns", [])
            if cols:
                col_lines.append(f"  Table: {entity.get('name', 'unknown')}")
                for col in cols:
                    if isinstance(col, dict):
                        col_lines.append(f"    - {col.get('name', '')} ({col.get('type', 'text')})")
                    else:
                        col_lines.append(f"    - {col}")
        if col_lines:
            actual_columns_section = f"""
╔══════════════════════════════════════════════════════════════════════╗
║ ACTUAL SOURCE COLUMNS — USE THESE EXACT NAMES IN SQL                 ║
╠══════════════════════════════════════════════════════════════════════╣
║ NEVER invent column names not in this list!                          ║
║ Use exact case as shown below (wrap in double quotes in SQL)         ║
╚══════════════════════════════════════════════════════════════════════╝
{chr(10).join(col_lines)}
"""

    # Build FK relationship text for generic bridge join detection
    fk_relationships = fk_relationships or []
    if fk_relationships:
        fk_lines = []
        for fk in fk_relationships:
            fk_lines.append(
                f"  {fk.get('from_table')}.{fk.get('from_column')} "
                f"→ {fk.get('to_table')}.{fk.get('to_column')}"
            )
        fk_section = "DISCOVERED FK RELATIONSHIPS:\n" + "\n".join(fk_lines)
    else:
        # Fall back to schema_analysis relationships
        rels = schema_analysis.get("relationships", [])
        if rels:
            fk_lines = [
                f"  {r.get('from_table')}.{r.get('join_key')} → {r.get('to_table')}"
                for r in rels
            ]
            fk_section = "DISCOVERED FK RELATIONSHIPS:\n" + "\n".join(fk_lines)
        else:
            fk_section = "DISCOVERED FK RELATIONSHIPS: none detected"

    prompt = f"""You are a DWH architect AI. Design a star schema for the warehouse schema.
Return ONLY valid JSON:
{{
  "fact_tables": [
    {{
      "name": "fact_<noun>",
      "grain": "one row per <unit>",
      "surrogate_key": "<noun>_key",
      "source_business_key_column": "<id_or_null>",
      "source_business_key_from": "<source_column_or_null>",
      "has_natural_key": true,
      "measures": [
        {{"column": "measure_name", "type": "NUMERIC(10,2)", "source": "raw_table.raw_column", "rule": "sum or direct"}}
      ],
      "foreign_keys": [
        {{
          "column": "<dim_noun>_key",
          "references_table": "dim_<dim_noun>",
          "references_column": "<dim_noun>_key",
          "join_source": "raw_table.raw_column = staging table column on dim",
          "join_on_source_col": "<actual_source_col>",
          "join_on_dim_col": "<actual_dim_attr>"
        }}
      ]
    }}
  ],
  "dimension_tables": [
    {{
      "name": "dim_<noun>",
      "source_table": "<staging_table>",
      "surrogate_key": "<noun>_key",
      "natural_key_column": "<actual_source_col_or_null>",
      "natural_key_from": "<source_column_or_null>",
      "has_natural_key": true,
      "attributes": [
        {{"column": "attr_name", "type": "VARCHAR(100)", "source": "raw_column"}}
      ],
      "scd_type": "1 or 2",
      "scd2_tracked_attributes": ["column1", "column2"]
    }}
  ],
  "modeling_decisions": ["Decision 1", "Decision 2"],
  "source_has_id_columns": true
}}

╔══════════════════════════════════════════════════════════════════════╗
║ FLAT FILE vs DATABASE SOURCE — CRITICAL DISTINCTION                  ║
╠══════════════════════════════════════════════════════════════════════╣
║ DATABASE SOURCE (multiple tables with _id columns):                  ║
║   has_natural_key: true                                              ║
║   natural_key_column: "customer_id" (REAL column in source)         ║
║   source_has_id_columns: true                                        ║
║   Fact JOIN: ON dim.customer_id = src.customer_id                   ║
║                                                                      ║
║ FLAT FILE SOURCE (single CSV/Excel, NO _id columns):                 ║
║   has_natural_key: false                                             ║
║   natural_key_column: null                                           ║
║   source_has_id_columns: false                                       ║
║   Surrogate key = SERIAL only (auto-generated)                       ║
║   Fact JOIN: ON dim.brand = src."Brand"                              ║
║              AND dim.model = src."Model" (use actual attrs!)         ║
║                                                                      ║
║ NEVER invent _id columns that don't exist in the source:             ║
║   ✗ car_id, seller_id, location_id → if not in source → WRONG!     ║
║   ✓ Use actual column names: "Brand", "City", "Owner_Type"          ║
╚══════════════════════════════════════════════════════════════════════╝

Schema analysis: {json.dumps(schema_analysis)}
Business requirements: {business_requirements}
{profile_section}
{actual_columns_section}
ACTUAL SOURCE TABLES (ONLY these exist — do NOT invent others):
  Source tables: {actual_tables_str}
  Staging tables: {staging_tables_str}

{fk_section}

╔══════════════════════════════════════════════════════════════════════╗
║ GENERIC BRIDGE JOIN RULE — works for ANY domain                      ║
╠══════════════════════════════════════════════════════════════════════╣
║ Use the FK relationships above to detect bridge joins.               ║
║                                                                      ║
║ STEP 1 — For each fact table, find its direct FKs.                  ║
║ STEP 2 — For each FK target table, check if it has further FKs.     ║
║ STEP 3 — Add those secondary FKs as dimension keys in fact table.   ║
║                                                                      ║
║ Example (any domain, derived from FK map above):                     ║
║   transactions.account_id → accounts       (direct FK)              ║
║   accounts.customer_id    → customers      (secondary FK — bridge!) ║
║   accounts.branch_id      → branches       (secondary FK — bridge!) ║
║                                                                      ║
║   Therefore fact_transactions foreign_keys must include:             ║
║     account_key  (from dim_account, direct)                          ║
║     customer_key (from dim_customer, via accounts bridge)            ║
║     branch_key   (from dim_branch, via accounts bridge)              ║
║                                                                      ║
║ This is generic — apply to ANY domain using the FK map above.        ║
║ Do NOT hardcode table names — derive from FK relationships.          ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ FK COLUMNS IN DIMENSIONS — ALWAYS INCLUDE                            ║
╠══════════════════════════════════════════════════════════════════════╣
║ For dimension tables, always include ALL FK (_id) columns from the   ║
║ source table as attributes. These are needed for fact table JOINs.  ║
║ Do NOT exclude any _id column from dimension attributes.             ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ SCD TYPE 2 RULE — PRIMARY TABLE ONLY                                 ║
╠══════════════════════════════════════════════════════════════════════╣
║ SCD Type 2 change tracking ONLY applies to columns from the PRIMARY  ║
║ staging table — NEVER from JOINed/enrichment tables.                ║
║                                                                      ║
║ ✓ Track: dim_account.balance (from stg_accounts — primary table)    ║
║ ✗ Track: dim_account.customer_segment (from stg_customers — JOIN)   ║
║          → customer_segment belongs to dim_customer SCD Type 2      ║
║                                                                      ║
║ Each entity tracks its own slowly changing attributes in its own dim.║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ MEASURES vs ATTRIBUTES — CORRECT DEFINITION                          ║
╠══════════════════════════════════════════════════════════════════════╣
║ FACT table = BUSINESS EVENT MEASURES (transaction quantities):       ║
║   ✅ price, amount, revenue, cost, salary, fee, tax                  ║
║   ✅ quantity, count, units_sold, order_count                        ║
║   ✅ km_driven (usage per event/transaction)                         ║
║   ✅ duration_mins, hours_worked, bill_amount                        ║
║   ✅ loan_amount, payment_amount, outstanding                        ║
║                                                                      ║
║ DIMENSION table = ENTITY CHARACTERISTICS (descriptive properties):   ║
║   ✅ engine_cc, horsepower, mileage_kmpl (vehicle specs)             ║
║   ✅ seats, doors, weight, capacity (physical attributes)            ║
║   ✅ registration_age, age, tenure (entity age/duration)             ║
║   ✅ credit_score, rating, grade (entity ratings)                    ║
║   ✅ year, size, floor_area (entity properties)                      ║
║   ✅ name, type, status, category, region, color (descriptive)       ║
║   ✅ is_active, has_insurance, tax_paid (boolean flags)              ║
║                                                                      ║
║ KEY QUESTION to classify any column:                                 ║
║   "Is this a BUSINESS TRANSACTION VALUE                              ║
║    or an ENTITY PROPERTY / CHARACTERISTIC?"                          ║
║                                                                      ║
║   Transaction value  → FACT table                                    ║
║   Entity property    → DIMENSION table                               ║
║                                                                      ║
║ EXAMPLES:                                                            ║
║   price        → FACT   (what was paid in this transaction)          ║
║   engine_cc    → DIM    (property of the car entity)                 ║
║   km_driven    → FACT   (usage measure per listing event)            ║
║   horsepower   → DIM    (specification of the car entity)            ║
║   bill_amount  → FACT   (transaction value)                          ║
║   credit_score → DIM    (property of the customer entity)            ║
║   seats        → DIM    (physical attribute of car entity)           ║
║   quantity     → FACT   (event measure)                              ║
║                                                                      ║
║ NEVER put entity characteristics in fact tables.                     ║
║ NEVER put transaction values in dimension tables.                    ║
╚══════════════════════════════════════════════════════════════════════╝

CRITICAL RULES — use names that fit THIS domain, not generic examples:
- Banking → fact_transactions, dim_account, dim_customer, dim_branch
- Hospital → fact_visits, dim_patient, dim_doctor, dim_diagnosis
- School → fact_enrollments, dim_student, dim_course, dim_teacher
- Manufacturing → fact_production, dim_machine, dim_product, dim_shift
- The surrogate_key follows the table name: dim_patient → patient_key, dim_branch → branch_key

ALWAYS include dim_date (for time-series). Other dims depend on the domain.
Use SCD Type 2 ONLY for slowly-changing attributes (city, segment, status of customer/patient/account).
Use SCD Type 1 for everything else.
Every fact table MUST list ALL its foreign_keys, each with column/references_table/references_column.

CRITICAL — source_table for dimensions MUST start with "stg_" prefix:
  ✓ source_table: "stg_students"
  ✗ source_table: "students"
  ✗ source_table: "school.students"
The staging tables are always named stg_<original_table_name>.

╔══════════════════════════════════════════════════════════════════════╗
║ FK COLUMNS RULE — ALWAYS INCLUDE                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║ For dimension tables, ALWAYS include ALL foreign key (_id) columns   ║
║ from the source table as attributes — do NOT exclude customer_id,    ║
║ branch_id, or any _id columns. These are needed for fact table JOINs.║
║ Example: dim_account MUST include customer_id and branch_id          ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ MULTI-SOURCE DIMENSIONS — KIMBALL METHODOLOGY                        ║
╠══════════════════════════════════════════════════════════════════════╣
║ When a source table has FK columns pointing to other tables,         ║
║ enrich the dimension with attributes from those referenced tables.   ║
║                                                                      ║
║ Example (banking):                                                   ║
║   accounts.customer_id → stg_customers → add customer_name, segment ║
║   accounts.branch_id   → stg_branches  → add branch_name, region    ║
║                                                                      ║
║   dim_account attributes should include:                             ║
║     account_id, account_type, balance (from stg_accounts)           ║
║     customer_id, customer_name, segment (from stg_customers JOIN)   ║
║     branch_id, branch_name, region (from stg_branches JOIN)         ║
║                                                                      ║
║ The source_table field still lists the PRIMARY staging table.        ║
║ The SQL generator will add JOINs for enrichment tables.              ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ FLAT FILE / SINGLE TABLE SOURCE RULE — NO INVENTED ID COLUMNS        ║
╠══════════════════════════════════════════════════════════════════════╣
║ When source has only ONE staging table (flat CSV/Excel file):        ║
║                                                                      ║
║ DO NOT invent ID columns that don't exist in the source:             ║
║   ✗ car_id        → not in CSV, do NOT use as natural_key           ║
║   ✗ seller_id     → not in CSV, do NOT use as natural_key           ║
║   ✗ location_id   → not in CSV, do NOT use as natural_key           ║
║                                                                      ║
║ INSTEAD — use actual source columns as natural keys:                 ║
║   ✓ Brand + Model + Year → natural key for dim_car                  ║
║   ✓ City               → natural key for dim_location               ║
║   ✓ Owner_Type          → natural key for dim_seller                 ║
║                                                                      ║
║ Set natural_key_column to an ACTUAL column from the source.          ║
║ The SQL generator will use SERIAL PRIMARY KEY for surrogate keys.    ║
║ NEVER set natural_key_column to a column that doesn't exist!         ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ ANTI-HALLUCINATION RULE — STRICTLY ENFORCED                          ║
╠══════════════════════════════════════════════════════════════════════╣
║ ONLY create dimension tables for source tables that ACTUALLY EXIST.  ║
║                                                                      ║
║ Available staging tables: {staging_tables_str:<40s}║
║                                                                      ║
║ NEVER invent dimensions for tables not in the list above.            ║
║ Example: if stg_term is NOT in the list → do NOT create dim_term     ║
║ Example: if stg_product is NOT in the list → do NOT create dim_product║
║                                                                      ║
║ COLUMN GROUPING RULE — for single staging table sources:          ║
║ When only ONE staging table exists, you MAY create multiple    ║
║ dimension tables by grouping related columns into entities.    ║
║ Example: Brand+Model+Year → dim_car (vehicle attributes)        ║
║         City → dim_location, Owner_Type → dim_seller           ║
║                                                                ║
║ When MULTIPLE staging tables exist:                            ║
║ Do NOT create dims from column values that are not entities.   ║
║ Example: enrollments.term → NOT dim_term (just a column value) ║
║ Example: orders.status   → NOT dim_status (just a column value)║
║                                                                ║
║ dim_date is always allowed (generated from date series)        ║
╚══════════════════════════════════════════════════════════════════════╝"""
    return ask_ai(prompt)


def generate_etl_mapping(schema_analysis: dict, data_model: dict) -> dict:
    prompt = f"""You are an ETL mapping AI. Create column-level mappings.
Source tables are in the staging schema (stg_*). Target tables are in the 'warehouse' schema.
Return ONLY valid JSON:
{{
  "mappings": [
    {{
      "target_table": "warehouse.<table>",
      "source_schema": "staging",
      "columns": [
        {{
          "source_table": "staging.stg_<table>",
          "source_column": "<col>",
          "target_column": "<col>",
          "transform_rule": "direct or COALESCE or CAST"
        }}
      ]
    }}
  ]
}}

Schema: {json.dumps(schema_analysis)}
Model:  {json.dumps(data_model)}

CRITICAL: All source_table values MUST be "staging.stg_<name>" — NEVER "staging.<name>" without the stg_ prefix."""
    return ask_ai(prompt)


# ─────────────────────────────────────────────────────────────────────────────
# Helper — build per-table specs
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_stg_prefix(table_name: str) -> str:
    if not table_name:
        return table_name
    if table_name.startswith("stg_"):
        return table_name
    return f"stg_{table_name}"


def _build_table_instructions(data_model: dict) -> str:
    lines = []

    # ── Dimensions ───────────────────────────────────────────────────────
    for dim in data_model.get("dimension_tables", []):
        name      = dim.get("name", "")
        sur_key   = dim.get("surrogate_key", f"{name.replace('dim_', '')}_key")
        has_nat   = dim.get("has_natural_key", True)
        nat_key   = re.sub(r'^source_', '', dim.get("natural_key_column", "id") or "id")
        # If no natural key (flat file source) — use first attribute as nat_key placeholder
        if not has_nat or nat_key in ("id", "null", "none", "") or nat_key is None:
            has_nat = False
            nat_key = None
        scd_type  = str(dim.get("scd_type", "1"))
        src_table = _ensure_stg_prefix(dim.get("source_table", ""))
        attrs     = dim.get("attributes", [])
        tracked   = dim.get("scd2_tracked_attributes", [])

        attr_specs = []
        for a in attrs:
            if isinstance(a, dict):
                attr_specs.append(f"{a.get('column')} {a.get('type', 'VARCHAR(100)')}")
            else:
                attr_specs.append(f"{a} VARCHAR(100)")
        attrs_sql = ", ".join(attr_specs) if attr_specs else "name VARCHAR(100)"

        attr_cols_only = [a.get('column') if isinstance(a, dict) else a for a in attrs]
        attr_cols_csv  = ", ".join(attr_cols_only)
        attr_src_csv   = ", ".join(
            f's."{a.get("source", a.get("column"))}"' if isinstance(a, dict)
            else f's."{a}"'
            for a in attrs
        )

        # Build explicit column mapping hint for AI
        col_mapping_lines = []
        for a in attrs:
            if isinstance(a, dict):
                dim_col = a.get('column', '')
                src_col = a.get('source', dim_col)
                col_mapping_lines.append(f"    {dim_col} ← s.\"{src_col}\"")
            else:
                col_mapping_lines.append(f"    {a} ← s.\"{a}\"")
        col_mapping_hint = "\n".join(col_mapping_lines)

        if name == "dim_date" or "date" in name.lower():
            spec = f"""
TABLE: warehouse.{name}  (date dimension — idempotent insert)
  CREATE TABLE IF NOT EXISTS warehouse.{name} (
    {sur_key} SERIAL PRIMARY KEY,
    full_date DATE UNIQUE NOT NULL,
    year INTEGER, quarter INTEGER, month INTEGER, day INTEGER,
    day_of_week INTEGER, month_name VARCHAR(20)
  );
  CREATE INDEX IF NOT EXISTS idx_{name}_full_date ON warehouse.{name}(full_date);
  CREATE INDEX IF NOT EXISTS idx_{name}_year ON warehouse.{name}(year);
  -- IMPORTANT: range covers 1990-2035, NOT just a recent window.
  -- Source data (e.g. manufacturing year, birth year, founding year) often
  -- spans far further back than typical transaction-date dimensions.
  -- Using too narrow a range (e.g. 2020-2030 only) silently DROPS every
  -- fact row whose year falls outside it when joined via INNER JOIN —
  -- this caused a real bug where 80% of rows vanished with no error.
  INSERT INTO warehouse.{name} (full_date, year, quarter, month, day, day_of_week, month_name)
    SELECT d::DATE, EXTRACT(YEAR FROM d)::INT, EXTRACT(QUARTER FROM d)::INT,
           EXTRACT(MONTH FROM d)::INT, EXTRACT(DAY FROM d)::INT,
           EXTRACT(DOW FROM d)::INT, TO_CHAR(d, 'Month')
    FROM generate_series('1990-01-01'::DATE, '2035-12-31'::DATE, '1 day'::INTERVAL) d
    ON CONFLICT (full_date) DO NOTHING;"""

        elif scd_type == "2":
            if has_nat and nat_key:
                change_conditions = " OR ".join([f"d.{c} != s.{c}" for c in tracked]) \
                                    if tracked else "FALSE"
                spec = f"""
TABLE: warehouse.{name}  (SCD Type 2 — expire + insert)
  -- Source: staging.{src_table}  (must start with stg_)
  CREATE TABLE IF NOT EXISTS warehouse.{name} (
    {sur_key} SERIAL PRIMARY KEY,
    {nat_key} INTEGER NOT NULL,
    {attrs_sql},
    is_current BOOLEAN DEFAULT TRUE,
    valid_from DATE DEFAULT CURRENT_DATE,
    valid_to DATE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_{name}_natkey ON warehouse.{name}({nat_key});
  CREATE INDEX IF NOT EXISTS idx_{name}_current ON warehouse.{name}({nat_key}, is_current);

  UPDATE warehouse.{name}
    SET is_current = FALSE, valid_to = CURRENT_DATE
    WHERE is_current = TRUE
      AND {nat_key} IN (
        SELECT s.{nat_key} FROM staging.{src_table} s
        JOIN warehouse.{name} d
          ON d.{nat_key} = s.{nat_key} AND d.is_current = TRUE
        WHERE {change_conditions}
      );

  INSERT INTO warehouse.{name} ({nat_key}, {attr_cols_csv}, is_current, valid_from)
    SELECT s.{nat_key}, {attr_src_csv}, TRUE, CURRENT_DATE
    FROM staging.{src_table} s
    WHERE NOT EXISTS (
      SELECT 1 FROM warehouse.{name} d
      WHERE d.{nat_key} = s.{nat_key} AND d.is_current = TRUE
    );"""
            else:
                # Flat file — no natural key, use DISTINCT insert
                first_two = " AND ".join(
                    [f'd."{a.get("column") if isinstance(a, dict) else a}" = s."{a.get("source", a.get("column")) if isinstance(a, dict) else a}"'
                     for a in attrs[:2]]
                ) if attrs else "1=0"
                spec = f"""
TABLE: warehouse.{name}  (SCD Type 1 — flat file source, no natural key)
  -- Source: staging.{src_table}  (no ID columns in CSV — surrogate key only)
  -- COLUMN MAPPING (use EXACTLY these source column names):
{col_mapping_hint}
  CREATE TABLE IF NOT EXISTS warehouse.{name} (
    {sur_key} SERIAL PRIMARY KEY,
    {attrs_sql},
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

  INSERT INTO warehouse.{name} ({attr_cols_csv}, updated_at)
    SELECT DISTINCT {attr_src_csv}, CURRENT_TIMESTAMP
    FROM staging.{src_table} s
    WHERE NOT EXISTS (
      SELECT 1 FROM warehouse.{name} d WHERE {first_two}
    );"""

        else:  # SCD Type 1 — UPSERT
            if has_nat and nat_key:
                update_sets = ", ".join([f"{c} = EXCLUDED.{c}" for c in attr_cols_only])
                spec = f"""
TABLE: warehouse.{name}  (SCD Type 1 — UPSERT)
  -- Source: staging.{src_table}  (must start with stg_)
  -- COLUMN MAPPING (use EXACTLY these source column names):
{col_mapping_hint}
  CREATE TABLE IF NOT EXISTS warehouse.{name} (
    {sur_key} SERIAL PRIMARY KEY,
    {nat_key} INTEGER UNIQUE NOT NULL,
    {attrs_sql},
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  CREATE INDEX IF NOT EXISTS idx_{name}_natkey ON warehouse.{name}({nat_key});

  INSERT INTO warehouse.{name} ({nat_key}, {attr_cols_csv}, updated_at)
    SELECT s.{nat_key}, {attr_src_csv}, CURRENT_TIMESTAMP
    FROM staging.{src_table} s
    ON CONFLICT ({nat_key}) DO UPDATE SET
      {update_sets},
      updated_at = CURRENT_TIMESTAMP;"""
            else:
                # Flat file — no natural key
                first_two = " AND ".join(
                    [f'd."{a.get("column") if isinstance(a, dict) else a}" = s."{a.get("source", a.get("column")) if isinstance(a, dict) else a}"'
                     for a in attrs[:2]]
                ) if attrs else "1=0"
                spec = f"""
TABLE: warehouse.{name}  (SCD Type 1 — flat file source, no natural key)
  -- Source: staging.{src_table}  (no ID columns in CSV — surrogate key only)
  -- COLUMN MAPPING (use EXACTLY these source column names):
{col_mapping_hint}
  CREATE TABLE IF NOT EXISTS warehouse.{name} (
    {sur_key} SERIAL PRIMARY KEY,
    {attrs_sql},
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );

  INSERT INTO warehouse.{name} ({attr_cols_csv}, updated_at)
    SELECT DISTINCT {attr_src_csv}, CURRENT_TIMESTAMP
    FROM staging.{src_table} s
    WHERE NOT EXISTS (
      SELECT 1 FROM warehouse.{name} d WHERE {first_two}
    );"""

        lines.append(spec)

    # ── Facts ────────────────────────────────────────────────────────────
    for fact in data_model.get("fact_tables", []):
        name         = fact.get("name", "")
        sur_key      = fact.get("surrogate_key", f"{name.replace('fact_', '')}_key")
        has_nat_key  = fact.get("has_natural_key", True)
        business_key = re.sub(r'^source_', '', fact.get("source_business_key_column", "business_key") or "business_key")
        business_src = fact.get("source_business_key_from", "id")

        # For flat file sources (no natural key) — don't use business_key
        if not has_nat_key or business_key in ("business_key", "null", "none", "") \
                or business_src in ("null", "none", "", "id"):
            has_nat_key  = False
            business_key = None
            business_src = None
        measures     = fact.get("measures", [])
        fks          = fact.get("foreign_keys", [])

        # Build a lookup of dim_name -> (has_natural_key, attributes) from dimension_tables
        # This lets us build FULL composite JOINs for dims with no natural key
        # (joining on only 1-2 attrs causes row multiplication / cartesian explosion!)
        dim_lookup = {}
        for dim in data_model.get("dimension_tables", []):
            dim_lookup[dim.get("name", "")] = {
                "has_natural_key": dim.get("has_natural_key", True),
                "natural_key_column": dim.get("natural_key_column"),
                "attributes": dim.get("attributes", [])
            }

        fk_cols = []; fk_indexes = []; fk_joins = []; fk_col_csv_parts = []

        for fk in fks:
            if isinstance(fk, dict):
                col             = fk.get("column")
                ref_tbl         = fk.get("references_table")
                ref_col         = fk.get("references_column", col)
                join_src        = fk.get("join_source", "")
                join_on_src     = fk.get("join_on_source_col", "")   # actual source col
                join_on_dim     = fk.get("join_on_dim_col", "")      # actual dim attr
                fk_cols.append(f"{col} INTEGER REFERENCES warehouse.{ref_tbl}({ref_col})")
                fk_indexes.append(f"CREATE INDEX IF NOT EXISTS idx_{name}_{col} ON warehouse.{name}({col});")
                fk_col_csv_parts.append(col)

                ref_dim_info = dim_lookup.get(ref_tbl, {})
                ref_has_nat  = ref_dim_info.get("has_natural_key", True)

                if ref_has_nat and join_on_src and join_on_dim:
                    # Has natural key — single column JOIN is safe (unique per natural key)
                    fk_joins.append(
                        f"  -- {col}: JOIN warehouse.{ref_tbl} d ON d.{join_on_dim} = src.\"{join_on_src}\""
                    )
                elif not ref_has_nat:
                    # NO natural key — MUST join on ALL attributes to avoid row multiplication!
                    # Joining on only 1-2 attrs when dim has duplicates on those attrs
                    # (different engine_cc/seats but same brand/model/year) causes
                    # cartesian-style row explosion in the fact table.
                    attrs = ref_dim_info.get("attributes", [])
                    join_conditions = []
                    for attr in attrs:
                        attr_col = attr.get("column", attr) if isinstance(attr, dict) else attr
                        attr_src = attr.get("source", attr_col) if isinstance(attr, dict) else attr_col
                        if attr_col and not attr_col.endswith("_key"):
                            join_conditions.append(
                                f'd.{attr_col} = src."{attr_src}"'
                            )
                    if join_conditions:
                        join_cond_str = " AND ".join(join_conditions)
                        fk_joins.append(
                            f"  -- {col}: JOIN warehouse.{ref_tbl} d ON {join_cond_str}\n"
                            f"  -- ⚠ MUST match ALL {ref_tbl} attributes (no natural key) "
                            f"to avoid row multiplication!"
                        )
                    else:
                        fk_joins.append(f"  -- {col} comes from joining {ref_tbl} via {join_src}")
                else:
                    fk_joins.append(f"  -- {col} comes from joining {ref_tbl} via {join_src}")

        measure_specs = []; measure_src = []; measure_cols = []
        for m in measures:
            if isinstance(m, dict):
                measure_specs.append(f"{m.get('column')} {m.get('type', 'NUMERIC(10,2)')}")
                measure_src.append(m.get('source', m.get('column')))
                measure_cols.append(m.get('column'))
            else:
                measure_specs.append(f"{m} NUMERIC(10,2)")
                measure_src.append(m)
                measure_cols.append(m)

        fk_cols_sql      = ",\n    ".join(fk_cols) if fk_cols else ""
        measure_cols_sql = ", ".join(measure_specs) if measure_specs else "amount NUMERIC(10,2)"
        # Only include business_key if natural key exists
        if has_nat_key and business_key:
            all_insert_cols = ", ".join([business_key] + fk_col_csv_parts + measure_cols)
            all_select_cols = ", ".join(
                [f"src.{business_src}"] +
                [f"<lookup_{c}>" for c in fk_col_csv_parts] +
                [f'src."{m}"' for m in measure_src]
            )
        else:
            all_insert_cols = ", ".join(fk_col_csv_parts + measure_cols)
            all_select_cols = ", ".join(
                [f"<lookup_{c}>" for c in fk_col_csv_parts] +
                [f'src."{m}"' for m in measure_src]
            )
        join_hints = "\n  ".join(fk_joins) if fk_joins else "  -- no FK joins"

        if has_nat_key and business_key:
            bk_col_def     = f"\n    {business_key} INTEGER UNIQUE NOT NULL,"
            on_conflict    = f"\n    ON CONFLICT ({business_key}) DO NOTHING;"
        else:
            bk_col_def     = ""   # no business_key column for flat file sources
            on_conflict    = ";"  # no ON CONFLICT for flat file sources

        spec = f"""
TABLE: warehouse.{name}  (fact table — append only)
  -- {'No natural key — flat file source, surrogate key only' if not has_nat_key else 'Natural key: ' + str(business_key)}
  CREATE TABLE IF NOT EXISTS warehouse.{name} (
    {sur_key} SERIAL PRIMARY KEY,{bk_col_def}
    {fk_cols_sql},
    {measure_cols_sql},
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
{chr(10).join('  ' + idx for idx in fk_indexes)}

  -- INSERT — JOIN staging with each dim to get surrogate keys
{join_hints}
  INSERT INTO warehouse.{name} ({all_insert_cols})
    SELECT {all_select_cols}
    FROM staging.stg_<source_fact_table> src
    -- JOIN each dim on actual attribute columns (no invented IDs!){on_conflict}"""

        lines.append(spec)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-FIX SAFETY NET
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_generated_sql(scripts: list, data_model: dict) -> tuple:
    if not scripts:
        return scripts, []

    source_tables = set()
    for dim in data_model.get("dimension_tables", []):
        st = dim.get("source_table", "")
        if st.startswith("stg_"):
            source_tables.add(st[4:])
        else:
            source_tables.add(st)

    corrections = []

    for script in scripts:
        sql      = script.get("sql", "")
        name     = script.get("name", "<unknown>")
        original = sql

        # Fix 1: missing stg_ prefix
        for src in source_tables:
            if not src:
                continue
            pattern = rf'\bstaging\.{re.escape(src)}\b(?!_)'
            new_sql = re.sub(pattern, f"staging.stg_{src}", sql)
            if new_sql != sql:
                corrections.append(f"  [{name}] Added missing stg_ prefix: staging.{src} → staging.stg_{src}")
                sql = new_sql

        # Fix 4: staging.stg_<schema>.<table> → staging.stg_<table>
        # Happens when source schema name gets embedded: stg_bank.accounts → stg_accounts
        # Pattern: staging.stg_WORD.WORD  (three-part ref with stg_ prefix on middle part)
        bad_schema_ref = re.compile(r'\bstaging\.stg_\w+\.(\w+)\b', re.IGNORECASE)
        def fix_schema_ref(m):
            table = m.group(1)
            corrections.append(f"  [{name}] Fixed embedded schema ref → staging.stg_{table}")
            return f"staging.stg_{table}"
        new_sql = bad_schema_ref.sub(fix_schema_ref, sql)
        if new_sql != sql:
            sql = new_sql

        # Fix 4b: staging.stg_staging.stg_<table> → staging.stg_<table>
        # Double-prefix bug: stg_staging.stg_patients
        bad_double_ref = re.compile(r'\bstaging\.stg_staging\.(stg_\w+)\b', re.IGNORECASE)
        def fix_double_ref(m):
            table = m.group(1)
            corrections.append(f"  [{name}] Fixed double-prefix ref → staging.{table}")
            return f"staging.{table}"
        new_sql = bad_double_ref.sub(fix_double_ref, sql)
        if new_sql != sql:
            sql = new_sql

        # Fix 2: invalid FK syntax
        bad_fk_pattern = re.compile(r'REFERENCES\s+warehouse\.(\w+)\.(\w+)\s*\([^)]+\)', re.IGNORECASE)
        def fix_fk(m):
            tbl = m.group(1); col = m.group(2)
            if not (tbl.startswith("dim_") or tbl.startswith("fact_")):
                guess_singular = tbl.rstrip("s")
                candidate      = f"dim_{guess_singular}"
                model_dims     = {d.get("name") for d in data_model.get("dimension_tables", [])}
                if candidate in model_dims:
                    fixed_col = f"{guess_singular}_key"
                    corrections.append(f"  [{name}] Fixed FK → REFERENCES warehouse.{candidate}({fixed_col})")
                    return f"REFERENCES warehouse.{candidate}({fixed_col})"
            corrections.append(f"  [{name}] Removed invalid FK trailing args")
            return f"REFERENCES warehouse.{tbl}({col})"
        sql = bad_fk_pattern.sub(fix_fk, sql)

        # Fix 3: warehouse.<source_name> → warehouse.dim_<name>
        for src in source_tables:
            if not src:
                continue
            singular  = src.rstrip("s")
            pattern   = rf'\bwarehouse\.{re.escape(src)}\b(?!_)'
            candidate = f"dim_{singular}"
            model_dims = {d.get("name") for d in data_model.get("dimension_tables", [])}
            if candidate in model_dims:
                new_sql = re.sub(pattern, f"warehouse.{candidate}", sql)
                if new_sql != sql:
                    corrections.append(f"  [{name}] Fixed warehouse reference: warehouse.{src} → warehouse.{candidate}")
                    sql = new_sql

        if sql != original:
            script["sql"] = sql

    return scripts, corrections


# ─────────────────────────────────────────────────────────────────────────────
# Main SQL generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_sql(data_model: dict, etl_mapping: dict,
                 fk_relationships: list = None,
                 actual_staging_tables: list = None,
                 raw_schema: str = "") -> dict:
    dim_names        = [d.get("name", "") for d in data_model.get("dimension_tables", [])]
    fact_names       = [f.get("name", "") for f in data_model.get("fact_tables", [])]
    required_scripts = [n for n in dim_names + fact_names if n]
    required_list    = "\n".join(f"  - {name}" for name in required_scripts)
    table_instructions = _build_table_instructions(data_model)

    # Build actual column list from raw_schema for SQL generation
    # This prevents AI from inventing column names like "Accident_History"
    actual_cols_hint = ""
    if raw_schema:
        actual_cols_hint = f"""
╔══════════════════════════════════════════════════════════════════════╗
║ ACTUAL SOURCE COLUMNS — USE ONLY THESE EXACT NAMES IN SQL           ║
╠══════════════════════════════════════════════════════════════════════╣
║ NEVER invent column names! Only use columns listed below.           ║
║ Wrap column names in double quotes: s."Brand", s."Accidents"        ║
╚══════════════════════════════════════════════════════════════════════╝
{raw_schema}
"""

    # Tell AI exactly which staging tables were actually extracted
    actual_staging_tables = actual_staging_tables or []
    if actual_staging_tables:
        staging_available = (
            "ACTUALLY EXTRACTED STAGING TABLES (these are the ONLY staging tables that exist):\n" +
            "\n".join(f"  ✓ staging.{t if t.startswith('stg_') else 'stg_' + t}"
                      for t in actual_staging_tables) +
            "\n\nAny other staging table MUST be created in the SQL script itself (Step 1)."
        )
    else:
        staging_available = "EXTRACTED STAGING TABLES: unknown — derive from source tables in data model"

    # Build FK map text for bridge join hints
    fk_relationships = fk_relationships or []
    if fk_relationships:
        fk_lines = [
            f"  {fk.get('from_table')}.{fk.get('from_column')} "
            f"→ {fk.get('to_table')}.{fk.get('to_column')}"
            for fk in fk_relationships
        ]
        fk_map_text = "DISCOVERED FK RELATIONSHIPS (use for bridge joins):\n" + "\n".join(fk_lines)
    else:
        fk_map_text = "DISCOVERED FK RELATIONSHIPS: none"

    example_dim = None
    for d in data_model.get("dimension_tables", []):
        if d.get("name") != "dim_date" and "date" not in d.get("name", "").lower():
            example_dim = d
            break

    worked_example = ""
    if example_dim:
        ex_name = example_dim.get("name", "dim_student")
        ex_key  = example_dim.get("surrogate_key", "student_key")
        ex_nat  = example_dim.get("natural_key_column", "student_id")
        ex_src  = _ensure_stg_prefix(example_dim.get("source_table", "stg_students"))
        worked_example = f"""

═══════════════════════════════════════════════════════════════════════
WORKED EXAMPLE — copy this pattern exactly:
═══════════════════════════════════════════════════════════════════════
CORRECT (✓):
  CREATE TABLE IF NOT EXISTS warehouse.{ex_name} (
    {ex_key} SERIAL PRIMARY KEY,
    {ex_nat} INTEGER UNIQUE NOT NULL,
    name VARCHAR(100), updated_at TIMESTAMP
  );
  INSERT INTO warehouse.{ex_name} ({ex_nat}, name, updated_at)
    SELECT s.{ex_nat}, s.name, CURRENT_TIMESTAMP
    FROM staging.{ex_src} s
    ON CONFLICT ({ex_nat}) DO NOTHING;

WRONG (✗):
  FROM staging.{ex_src.replace('stg_', '')} s    ← missing stg_ prefix
  FROM school.{ex_src.replace('stg_', '')} s     ← source schema (wrong!)
  REFERENCES warehouse.students.student_id(...)  ← invalid FK syntax
═══════════════════════════════════════════════════════════════════════"""

    prompt = f"""You are a SQL generation AI for a production-grade ETL pipeline.

╔══════════════════════════════════════════════════════════════════════╗
║ ABSOLUTE NAMING RULES — VIOLATING THESE BREAKS THE PIPELINE          ║
╠══════════════════════════════════════════════════════════════════════╣
║ 1. STAGING tables ALWAYS have stg_ prefix:                           ║
║    ✓ FROM staging.stg_students                                       ║
║    ✗ FROM staging.students         ← BROKEN                          ║
║    ✗ FROM school.students          ← BROKEN (source schema)          ║
║                                                                      ║
║ 2. WAREHOUSE tables ALWAYS have dim_/fact_ prefix:                   ║
║    ✓ warehouse.dim_student, warehouse.fact_enrollments               ║
║    ✗ warehouse.students            ← BROKEN                          ║
║                                                                      ║
║ 3. FOREIGN KEY syntax — surrogate keys only:                         ║
║    ✓ REFERENCES warehouse.dim_student(student_key)                   ║
║    ✗ REFERENCES warehouse.students.student_id(...)  ← BROKEN         ║
║                                                                      ║
║ 4. Data flow: source.<x> → staging.stg_<x> → warehouse.dim_<x>       ║
║    NEVER read from source schema in warehouse SQL                    ║
║    ALWAYS read from staging.stg_<x>                                  ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ MULTI-SOURCE DIMENSION RULE — KIMBALL DENORMALIZED DIMS              ║
╠══════════════════════════════════════════════════════════════════════╣
║ If a dimension's source table has FK columns (_id) pointing to other ║
║ staging tables, JOIN those tables to enrich the dimension.           ║
║ Use LEFT JOIN so missing FK values do NOT drop rows.                 ║
║                                                                      ║
║ Generic pattern (derive from FK map below — NOT hardcoded):          ║
║   INSERT INTO warehouse.dim_X (nat_key, attr1, fk_id, fk_attr)      ║
║   SELECT a.nat_key, a.attr1, b.fk_id, b.fk_attr                    ║
║   FROM staging.stg_X a                                              ║
║   LEFT JOIN staging.stg_Y b ON a.fk_id = b.fk_id                   ║
║                                                                      ║
║ SCD Type 2 change tracking ONLY on primary table columns:            ║
║   ✓ WHERE d.primary_col != s.primary_col  (from stg_X — primary)    ║
║   ✗ WHERE d.joined_col  != s.joined_col   (from stg_Y — JOIN table) ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ GENERIC BRIDGE JOIN FOR FACT TABLES                                  ║
╠══════════════════════════════════════════════════════════════════════╣
║ {fk_map_text:<68s}║
║                                                                      ║
║ Use FK map to find bridge joins for fact tables:                     ║
║   Step 1: fact FK → dim_A (direct)                                  ║
║   Step 2: dim_A source has FK → dim_B (secondary/bridge)            ║
║   Step 3: JOIN staging.stg_A to get dim_B key via bridge            ║
║                                                                      ║
║ Pattern (generic):                                                   ║
║   FROM staging.stg_<fact_src> src                                    ║
║   JOIN warehouse.dim_A dA ON dA.<A_key> = src.<A_fk>                ║
║   JOIN staging.stg_A   sA ON sA.<A_nat> = src.<A_fk>  ← bridge     ║
║   JOIN warehouse.dim_B dB ON dB.<B_key> = sA.<B_fk>   ← via bridge ║
║   JOIN warehouse.dim_date dd ON dd.full_date = src.<date_col>        ║
║                                                                      ║
║ Add ALL discovered dimension keys to fact INSERT column list.        ║
╚══════════════════════════════════════════════════════════════════════╝
{worked_example}

╔══════════════════════════════════════════════════════════════════════╗
║ SINGLE SOURCE TABLE RULE — CRITICAL FOR FLAT FILE / CSV PIPELINES    ║
╠══════════════════════════════════════════════════════════════════════╣
║ When ALL dimension source_tables reference staging tables that do    ║
║ NOT match any actual extracted staging table, it means the source    ║
║ is a SINGLE FLAT TABLE (e.g. a CSV file).                            ║
║                                                                      ║
║ In this case, the SQL MUST:                                          ║
║                                                                      ║
║ STEP 1 — Create intermediate staging tables from the raw staging     ║
║ table using SELECT DISTINCT (generic, no hardcoding):                ║
║                                                                      ║
║   CREATE TABLE IF NOT EXISTS staging.stg_<entity> AS                ║
║   SELECT DISTINCT <entity_columns>                                   ║
║   FROM staging.stg_<raw_source_table>;                               ║
║                                                                      ║
║ STEP 2 — Load dims FROM the intermediate staging tables              ║
║ STEP 3 — Load fact FROM the raw staging table directly               ║
║          joining dims for surrogate keys                             ║
║                                                                      ║
║ GENERIC PATTERN (derive table/column names from data model):         ║
║   Raw staging table = the stg_ table that was actually extracted     ║
║   Intermediate table = stg_<entity> derived from dim name            ║
║                                                                      ║
║ EXAMPLE (generic — adapt names from actual data model):              ║
║   -- Step 1: Create intermediate staging                             ║
║   CREATE TABLE IF NOT EXISTS staging.stg_<entity> AS                ║
║   SELECT DISTINCT <col1>, <col2>                                     ║
║   FROM staging.stg_<raw_table>;                                      ║
║                                                                      ║
║   -- Step 2: Load dim from intermediate staging                      ║
║   INSERT INTO warehouse.dim_<entity> (<cols>)                        ║
║   SELECT s.<col1>, s.<col2>                                          ║
║   FROM staging.stg_<entity> s                                        ║
║   ON CONFLICT DO NOTHING;                                            ║
║                                                                      ║
║   -- Step 3: Load fact from raw staging table                        ║
║   INSERT INTO warehouse.fact_<name> (<cols>)                         ║
║   SELECT src.<measure1>, src.<measure2>,                             ║
║          d.<surrogate_key>                                           ║
║   FROM staging.stg_<raw_table> src                                   ║
║   JOIN warehouse.dim_<entity> d ON d.<nat_key> = src.<nat_key>;      ║
║                                                                      ║
║ NEVER reference a staging table that was not created in this script  ║
║ or was not extracted from the source!                                ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ DIM_DATE JOIN RULE — ADAPT TO AVAILABLE DATE COLUMN                  ║
╠══════════════════════════════════════════════════════════════════════╣
║ Check what date/time columns actually exist in the source:           ║
║                                                                      ║
║ Full date column exists (e.g. transaction_date, order_date):         ║
║   JOIN warehouse.dim_date dd ON dd.full_date = src."date_col"::DATE ║
║                                                                      ║
║ Only year column exists (e.g. Year, manufacturing_year):             ║
║   JOIN warehouse.dim_date dd ON dd.year = src."Year"                 ║
║                                                                      ║
║ No date or year column exists:                                       ║
║   OMIT dim_date FK — do not join dim_date at all                     ║
║                                                                      ║
║ NEVER invent date columns that don't exist in source!                ║
║   ✗ src."listing_date"    → doesn't exist in CSV!                   ║
║   ✗ src."transaction_date" → doesn't exist if not in column list!   ║
║   ✓ src."Year"            → use year join when only year exists      ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ CRITICAL: COMPOSITE JOIN RULE — PREVENTS ROW MULTIPLICATION          ║
╠══════════════════════════════════════════════════════════════════════╣
║ When joining fact to a dimension that has NO natural key:            ║
║                                                                      ║
║ ✗ WRONG — joining on only 2-3 attributes:                           ║
║   JOIN dim_car dc ON dc.brand = src."Brand"                         ║
║     AND dc.model = src."Model" AND dc.year = src."Year"             ║
║   → If dim_car has multiple rows with same brand+model+year          ║
║     (different engine_cc/seats/mileage = genuinely different cars)   ║
║   → EACH source row matches MULTIPLE dim rows                        ║
║   → Fact table EXPLODES: 10,000 source rows → 7,800,000 fact rows!  ║
║                                                                      ║
║ ✓ CORRECT — join on ALL dim attributes (the full composite key):    ║
║   JOIN dim_car dc ON dc.brand = src."Brand"                         ║
║     AND dc.model = src."Model" AND dc.year = src."Year"             ║
║     AND dc.fuel_type = src."Fuel_Type"                              ║
║     AND dc.transmission = src."Transmission"                        ║
║     AND dc.engine_cc = src."Engine_CC"                              ║
║     AND dc.mileage_kmpl = src."Mileage_kmpl"                        ║
║     AND dc.seats = src."Seats"                                       ║
║     AND dc.owner_type = src."Owner_Type"                             ║
║   → Each combination is now unique → exactly 1 match per source row ║
║                                                                      ║
║ RULE: For ANY dimension without a natural key, the fact JOIN MUST   ║
║ include EVERY attribute column of that dimension in the ON clause.   ║
║ Never join on a subset — verify row count after design:              ║
║   fact row count MUST equal source row count (for 1:1 grain facts)   ║
║                                                                ║
║ FLOAT/NUMERIC COLUMN EXCEPTION — CRITICAL:                    ║
║ NEVER join on float or decimal columns (NUMERIC, FLOAT,        ║
║ DOUBLE, REAL, DECIMAL) — float precision mismatches cause     ║
║ 0 rows to match even when values look identical.               ║
║                                                                ║
║ ✓ JOIN on: text, varchar, integer, boolean columns            ║
║ ✗ NEVER JOIN on: engine_cc (float), mileage_kmpl (float),    ║
║                    price (decimal), amount (numeric)           ║
║                                                                ║
║ If removing float columns makes the join non-unique, add more  ║
║ TEXT columns to the JOIN until each combination is unique.     ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════════╗
║ NO INVENTED ID COLUMNS — FOR FLAT FILE SOURCES                       ║
╠══════════════════════════════════════════════════════════════════════╣
║ If the staging table has NO _id columns (flat CSV/Excel source):     ║
║                                                                      ║
║ DO NOT reference non-existent ID columns in SQL:                     ║
║   ✗ s.car_id      → column doesn't exist in CSV!                    ║
║   ✗ s.seller_id   → column doesn't exist in CSV!                    ║
║   ✗ s.location_id → column doesn't exist in CSV!                    ║
║                                                                      ║
║ INSTEAD — use ACTUAL columns from the staging table:                 ║
║   ✓ s."Brand"     → actual column in CSV                            ║
║   ✓ s."City"      → actual column in CSV                            ║
║   ✓ s."Owner_Type" → actual column in CSV                           ║
║                                                                      ║
║ For SCD Type 2 dim with no natural key:                              ║
║   Use surrogate key (SERIAL) only — no natural key JOIN              ║
║   INSERT SELECT DISTINCT actual_columns FROM staging.stg_<entity>   ║
║   ON CONFLICT DO NOTHING                                             ║
║                                                                      ║
║ For fact table JOINs with dims that have no natural key:             ║
║   JOIN warehouse.dim_<entity> d ON d.<attr> = src."<ActualCol>"     ║
║   where <attr> and <ActualCol> are REAL columns, not invented IDs   ║
╚══════════════════════════════════════════════════════════════════════╝



═══════════════════════════════════════════════════════════════════════
{staging_available}
═══════════════════════════════════════════════════════════════════════

{actual_cols_hint}

═══════════════════════════════════════════════════════════════════════
PER-TABLE SQL SPECIFICATIONS (follow these EXACTLY)
═══════════════════════════════════════════════════════════════════════
{table_instructions}
═══════════════════════════════════════════════════════════════════════

YOUR TASK:
1. For each table above, output a script that follows the spec exactly
2. Use the EXACT column names shown in the spec
3. Use the EXACT FK references (REFERENCES warehouse.dim_X(X_key))
4. For fact INSERTs:
   - If dim has natural key → JOIN on natural key column
   - If dim has NO natural key (flat file) → JOIN on actual attribute columns
     e.g. JOIN warehouse.dim_car dc ON dc.brand = src."Brand" AND dc.model = src."Model"
5. ALL staging.<table> references MUST use stg_ prefix
6. ALL warehouse.<table> references MUST be dim_<x>, fact_<x>, or dim_date
7. NEVER reference a column that doesn't exist in the staging table
8. If source has no ID columns → use SERIAL surrogate key only, no natural key in INSERT

Return ONLY valid JSON in this format:
{{
  "scripts": [
    {{
      "name": "<table_name>",
      "label": "<short description>",
      "schema": "warehouse",
      "sql": "<full SQL with all statements separated by ;>"
    }}
  ]
}}

Data model:
{json.dumps(data_model, indent=2)}

ETL mappings:
{json.dumps(etl_mapping, indent=2)}"""

    return ask_ai(prompt)


def generate_schema_evolution(table_name, existing_columns,
                              new_column, column_type, user_instruction) -> dict:
    prompt = f"""You are a schema evolution AI. Generate SQL to safely add a column.
Return ONLY valid JSON:
{{
  "impact_analysis": {{
    "table_affected": "warehouse.{table_name}",
    "operation": "ADD COLUMN",
    "risk_level": "low",
    "downstream_affected": ["ETL load scripts", "BI queries"],
    "backfill_needed": true,
    "notes": "explanation"
  }},
  "scripts": [
    {{
      "name": "alter_table",
      "label": "ALTER TABLE",
      "sql": "ALTER TABLE warehouse.{table_name} ADD COLUMN {new_column} {column_type} DEFAULT NULL;"
    }}
  ]
}}

Table: warehouse.{table_name}
Existing columns: {existing_columns}
New column: {new_column} ({column_type})
Instruction: {user_instruction}"""
    return ask_ai(prompt)


# ── Domain mismatch validation ────────────────────────────────────────────────

# Domain keyword map — each domain has source column keywords and requirement keywords
_DOMAIN_KEYWORDS = {
    "automotive": {
        "source":       ["brand", "model", "fuel_type", "transmission", "mileage",
                         "engine_cc", "horsepower", "km_driven", "owner_type",
                         "car", "vehicle", "seats", "doors", "color"],
        "requirements": ["brand", "model", "fuel", "transmission", "mileage",
                         "engine", "horsepower", "km", "owner", "car", "vehicle",
                         "price", "listing", "automotive"],
    },
    "banking": {
        "source":       ["account_id", "transaction_id", "loan_id", "branch_id",
                         "balance", "interest_rate", "loan_amount", "emi",
                         "npa", "ifsc", "swift", "debit", "credit"],
        "requirements": ["loan", "npa", "branch", "account", "transaction",
                         "interest", "emi", "balance", "banking", "revenue",
                         "debit", "credit", "mortgage", "portfolio"],
    },
    "healthcare": {
        "source":       ["patient_id", "doctor_id", "diagnosis", "icd",
                         "prescription", "ward", "admit", "discharge",
                         "medication", "symptom", "blood_type"],
        "requirements": ["patient", "doctor", "diagnosis", "prescription",
                         "hospital", "clinic", "medication", "treatment",
                         "healthcare", "medical", "admission"],
    },
    "retail": {
        "source":       ["order_id", "product_id", "sku", "category",
                         "inventory", "cart", "shipment", "warehouse",
                         "discount", "coupon", "refund"],
        "requirements": ["order", "product", "sku", "inventory", "sales",
                         "revenue", "discount", "shipping", "retail",
                         "ecommerce", "basket"],
    },
    "hr": {
        "source":       ["employee_id", "department_id", "salary", "payroll",
                         "leave", "attendance", "designation", "appraisal",
                         "hire_date", "termination"],
        "requirements": ["employee", "salary", "payroll", "department",
                         "leave", "attendance", "headcount", "hr",
                         "workforce", "hiring", "attrition"],
    },
}


def _detect_domain(text: str, keyword_list: list) -> int:
    """Count how many domain keywords appear in text (case-insensitive)."""
    text_lower = text.lower()
    return sum(1 for kw in keyword_list if kw.lower() in text_lower)


def _validate_domain_match(raw_schema: str, business_requirements: str,
                            schema_analysis: dict) -> str | None:
    """
    Detect domain from source schema columns, then check if business
    requirements match that domain. Returns error message if mismatch,
    None if everything is fine.

    Generic — works for ANY domain combination.
    No hardcoding of specific table or column names.
    """
    # Build combined source text from schema + analysis
    source_text = raw_schema or ""
    for entity in schema_analysis.get("entities", []):
        source_text += " " + entity.get("name", "")
        source_text += " " + " ".join(entity.get("columns", []))
    source_text = source_text.lower()

    req_text = (business_requirements or "").lower()

    # Score each domain against source schema
    source_scores = {
        domain: _detect_domain(source_text, info["source"])
        for domain, info in _DOMAIN_KEYWORDS.items()
    }

    # Score each domain against requirements
    req_scores = {
        domain: _detect_domain(req_text, info["requirements"])
        for domain, info in _DOMAIN_KEYWORDS.items()
    }

    # Find best matching domain for source
    best_source_domain = max(source_scores, key=source_scores.get)
    best_source_score  = source_scores[best_source_domain]

    # Find best matching domain for requirements
    best_req_domain    = max(req_scores, key=req_scores.get)
    best_req_score     = req_scores[best_req_domain]

    # Only validate if we have confident domain detection (score >= 2)
    if best_source_score < 2 or best_req_score < 2:
        return None  # Not enough signal — skip validation

    # Mismatch: source domain ≠ requirements domain
    if best_source_domain != best_req_domain:
        source_cols = schema_analysis.get("entities", [{}])[0].get("columns", [])[:5]
        return (
            f"Source data appears to be '{best_source_domain}' domain "
            f"(detected columns: {source_cols}) "
            f"but requirements describe '{best_req_domain}' domain. "
            f"Please provide {best_source_domain}-related requirements, "
            f"or connect to a {best_req_domain} data source."
        )

    return None  # No mismatch


# ── PHASE 1 ──────────────────────────────────────────────────────────────────

def _fix_source_column_names(data_model: dict, raw_schema: str) -> dict:
    """
    Post-process data model to correct source column names using actual schema.
    
    AI may invent column names like "Accident_History" when the actual column
    is "Accidents". This function corrects source column mappings by fuzzy-
    matching attribute names to actual column names from raw_schema.
    
    Generic — works for any domain, any column names.
    """
    import re

    # Parse actual column names AND their data types from raw_schema text
    # Format: "  column_name (data_type)" e.g. "Engine_CC (numeric(20,6))"
    actual_cols = {}       # lowercase_no_underscore → actual_name
    actual_col_types = {}  # actual_name → data_type string (as reported by DB)
    for line in raw_schema.split("\n"):
        line = line.strip()
        m = re.match(r'(\w+)\s*\(([^)]*)\)', line)
        if m:
            col, dtype = m.group(1), m.group(2).strip()
            actual_cols[col.lower().replace("_", "")] = col
            actual_cols[col.lower()] = col
            actual_col_types[col] = dtype
        else:
            # Fallback: column name with no type in parens
            m2 = re.match(r'(\w+)', line)
            if m2:
                col = m2.group(1)
                actual_cols[col.lower().replace("_", "")] = col
                actual_cols[col.lower()] = col

    if not actual_cols:
        return data_model

    def best_match(attr_name: str) -> str | None:
        """Find best matching actual column for an attribute name."""
        key = attr_name.lower().replace("_", "")
        # Direct match
        if key in actual_cols:
            return actual_cols[key]
        # Underscore match
        if attr_name.lower() in actual_cols:
            return actual_cols[attr_name.lower()]
        # Partial match — find actual col that contains this attr or vice versa
        for actual_key, actual_name in actual_cols.items():
            if key in actual_key or actual_key in key:
                return actual_name
        # Fuzzy fallback — catches cases like "accident_history" vs "Accidents"
        # where neither is a substring of the other but they're clearly the
        # same concept. A pure substring check misses these; this previously
        # caused dim_car to be built with an attribute that has NO matching
        # source column at all, leading to a failed/dropped JOIN condition
        # and silent row under-matching in the fact table.
        import difflib
        best_score = 0.0
        best_col   = None
        for actual_key, actual_name in actual_cols.items():
            score = difflib.SequenceMatcher(None, key, actual_key).ratio()
            if score > best_score:
                best_score = score
                best_col   = actual_name
        if best_score >= 0.55:
            return best_col
        return None

    def sql_type_for_source(actual_col: str, fallback: str) -> str:
        """
        Map a source column's reported DB type to an exact SQL DDL type,
        preserving full precision so dimension tables match the source
        exactly (avoids float/numeric precision mismatches at JOIN time,
        and avoids truncating string columns that need full width).
        """
        dtype = (actual_col_types.get(actual_col) or "").lower()
        if not dtype:
            return fallback
        if "numeric" in dtype or "decimal" in dtype:
            # e.g. "numeric(20,6)" → keep exact precision/scale
            m = re.search(r'\((\d+)\s*,\s*(\d+)\)', dtype)
            if m:
                return f"NUMERIC({m.group(1)},{m.group(2)})"
            return "NUMERIC"
        if "bigint" in dtype or "int8" in dtype:
            return "BIGINT"
        if dtype in ("integer", "int4", "int"):
            return "INTEGER"
        if "smallint" in dtype:
            return "SMALLINT"
        if "double" in dtype or "float8" in dtype:
            return "DOUBLE PRECISION"
        if "real" in dtype or "float4" in dtype:
            return "REAL"
        if "boolean" in dtype or dtype == "bool":
            return "BOOLEAN"
        if "timestamp" in dtype:
            return "TIMESTAMP"
        if "date" in dtype:
            return "DATE"
        if "varchar" in dtype or "character varying" in dtype:
            return "VARCHAR(255)"
        if "text" in dtype or "char" in dtype:
            return "TEXT"
        return fallback

    # Fix dimension table attribute sources AND match types to source precision
    for dim in data_model.get("dimension_tables", []):
        fixed_attrs = []
        for attr in dim.get("attributes", []):
            if isinstance(attr, dict):
                col = attr.get("column", "")
                src = attr.get("source", col)
                # Try to find actual column that matches this attribute
                matched = best_match(col) or best_match(src)
                if matched and matched != src:
                    print(f"[ModelFix] {dim.get('name')}.{col}: source '{src}' → '{matched}'")
                    attr = {**attr, "source": matched}
                # Override declared type to match source's actual precision —
                # critical for numeric/decimal columns used in fact-to-dim JOINs,
                # since a mismatched precision (e.g. dim NUMERIC(10,2) vs source
                # NUMERIC(20,6)) causes silent equality-match failures.
                final_src = attr.get("source", col)
                exact_type = sql_type_for_source(final_src, attr.get("type", "VARCHAR(100)"))
                if exact_type != attr.get("type"):
                    print(f"[ModelFix] {dim.get('name')}.{col}: type "
                          f"'{attr.get('type')}' → '{exact_type}' (matches source precision)")
                    attr = {**attr, "type": exact_type}
            fixed_attrs.append(attr)
        dim["attributes"] = fixed_attrs

    # Fix fact table measure sources and date FK joins
    for fact in data_model.get("fact_tables", []):
        fixed_measures = []
        for m in fact.get("measures", []):
            if isinstance(m, dict):
                col = m.get("column", "")
                src = m.get("source", col)
                matched = best_match(col) or best_match(src)
                if matched and matched != src:
                    print(f"[ModelFix] {fact.get('name')}.{col}: source '{src}' → '{matched}'")
                    m = {**m, "source": matched}
            fixed_measures.append(m)
        fact["measures"] = fixed_measures

        # Fix dim_date FK — if source has no date col but has Year → use year join
        fixed_fks = []
        for fk in fact.get("foreign_keys", []):
            if isinstance(fk, dict):
                ref_tbl = fk.get("references_table", "")
                if ref_tbl == "dim_date":
                    join_src = fk.get("join_on_source_col", "")
                    # Check if join source col exists in actual columns
                    if join_src and join_src not in actual_cols and join_src.lower() not in actual_cols:
                        # Try to find a year column
                        year_col = actual_cols.get("year") or actual_cols.get("Year") or \
                                   next((v for k, v in actual_cols.items() if "year" in k.lower()), None)
                        if year_col:
                            print(f"[ModelFix] dim_date join: '{join_src}' → year join on '{year_col}'")
                            fk = {**fk, "join_on_source_col": year_col, "join_on_dim_col": "year"}
            fixed_fks.append(fk)
        fact["foreign_keys"] = fixed_fks

    return data_model


def run_phase_1_model_design(source_description, raw_schema,
                             business_requirements,
                             connector_config: dict = None,
                             source_schema: str = "raw",
                             fk_relationships: list = None) -> dict:
    profile_text  = ""
    source_tables = []

    if connector_config:
        try:
            from data_profiler import build_full_profile, format_profile_for_ai
            print(f"\n[ETL Agent] Smart mode ENABLED — profiling schema '{source_schema}'...")
            profile_result = build_full_profile(
                connector_config, schema=source_schema,
                sample_rows=5, enable_overlap_detection=True
            )
            if profile_result.get("success"):
                profile_text  = format_profile_for_ai(profile_result["profile"])
                raw_tables    = list(profile_result["profile"].get("tables", {}).keys())

                # ── CROSS-PIPELINE CONTAMINATION FIX ──────────────────────────
                # The profiler may return tables from ALL schemas (staging, warehouse,
                # raw, other source schemas). We must filter to ONLY the current
                # source schema tables — bare table names, no schema prefix.
                source_tables = [
                    t for t in raw_tables
                    if not t.startswith("staging.")
                    and not t.startswith("warehouse.")
                    and not t.startswith("raw.")
                    and not t.startswith(f"{source_schema}.")
                    and "." not in t   # bare table names only
                ]

                # If all had schema prefix (e.g. "bank.accounts"), strip the prefix
                if not source_tables:
                    source_tables = [
                        t.split(".", 1)[1] if "." in t else t
                        for t in raw_tables
                        if not t.startswith("staging.")
                        and not t.startswith("warehouse.")
                        and not t.startswith("raw.")
                    ]

            print(f"[ETL Agent] ✓ Profile built ({len(profile_text)} chars)")
            print(f"[ETL Agent] ✓ Source tables: {source_tables}")
        except Exception as e:
            print(f"[ETL Agent] ⚠ Profiling skipped: {e}")

    print("[Phase 1 — Step 1/2] Analyzing schema...")
    schema = analyze_schema(source_description, raw_schema, profile_text)

    # Extract source tables from schema analysis if not from profiler
    if not source_tables:
        source_tables = [e.get("name", "") for e in schema.get("entities", []) if e.get("name")]

    # Final safety filter — remove any schema-prefixed or system tables
    source_tables = [
        t.split(".")[-1] if "." in t else t
        for t in source_tables
        if not any(t.startswith(p) for p in ("staging.", "warehouse.", "raw."))
    ]
    # Deduplicate while preserving order
    seen = set()
    source_tables = [t for t in source_tables if not (t in seen or seen.add(t))]

    print(f"[ETL Agent] ✓ Source tables: {source_tables}")

    # ── Domain mismatch validation ────────────────────────────────────────────
    mismatch = _validate_domain_match(raw_schema, business_requirements, schema)
    if mismatch:
        print(f"[ETL Agent] ✗ Domain mismatch detected: {mismatch}")
        raise ValueError(f"Domain mismatch: {mismatch}")
    # ─────────────────────────────────────────────────────────────────────────

    print("[Phase 1 — Step 2/2] Generating data model...")
    model = generate_data_model(
        schema, business_requirements, profile_text,
        source_tables, fk_relationships=fk_relationships
    )

    # ── Fix source column names using actual raw_schema ───────────────────────
    # AI sometimes invents source column names (e.g. Accident_History vs Accidents)
    # Post-process data model to correct source column names from actual schema
    if raw_schema:
        model = _fix_source_column_names(model, raw_schema)
    # ─────────────────────────────────────────────────────────────────────────

    print("[ETL Agent] ✓ Phase 1 complete — awaiting user approval")

    return {
        "phase":            "model_design",
        "schema_analysis":  schema,
        "data_model":       model,
        "profile_text":     profile_text,
        "used_profile":     bool(profile_text),
        "source_tables":    source_tables
    }


# ── PHASE 2 ──────────────────────────────────────────────────────────────────



def validate_and_fix_sql_columns(scripts: list, actual_columns: list,
                                  data_model: dict) -> tuple:
    """
    Post-generation validation — scan every src."column" reference in
    generated SQL and remove/fix any that don't exist in the actual
    source schema. Also removes dim_date JOINs if no date/year column
    exists in the source.

    This is the permanent fix for AI hallucinating columns like
    listing_date, transaction_date, business_key etc.

    Allowed system columns that are always OK even if not in source:
    - SCD Type 2: valid_from, valid_to, is_current
    - Audit: loaded_at, created_at, updated_at, inserted_at, etl_batch_id
    - Surrogate keys: *_key (handled by SERIAL, not from source)
    - period_id (added by pipeline_executor.py patching)
    """
    import re

    if not scripts or not actual_columns:
        return scripts, []

    # Build lookup of actual column names (case-insensitive)
    actual_col_set   = {c.lower() for c in actual_columns}
    actual_col_exact = {c.lower(): c for c in actual_columns}

    # Check if source has any date or year column
    has_date_col = any(
        any(kw in c.lower() for kw in ("date", "time", "timestamp", "datetime"))
        for c in actual_columns
    )
    has_year_col = any("year" in c.lower() for c in actual_columns)
    has_any_date = has_date_col or has_year_col

    # Find the exact year column name
    year_col = next(
        (c for c in actual_columns if "year" in c.lower()), None
    )
    # Find the exact date column name
    date_col = next(
        (c for c in actual_columns
         if any(kw in c.lower() for kw in ("date", "timestamp", "datetime"))
         and "year" not in c.lower()), None
    )

    corrections = []

    for script in scripts:
        sql  = script.get("sql", "")
        name = script.get("name", "")
        original = sql

        # Fix 1: Handle dim_date JOIN based on what date columns actually exist
        if "dim_date" in sql.lower() and name.startswith("fact_"):
            # Find any src."<invented_date_col>" in the dim_date JOIN
            dim_date_join = re.search(
                r'JOIN\s+warehouse\.dim_date\s+(\w+)\s+ON\s+([^\n;]+)',
                sql, flags=re.IGNORECASE
            )
            if dim_date_join:
                alias_dd = dim_date_join.group(1)
                condition = dim_date_join.group(2)

                if not has_any_date:
                    # No date or year column at all — remove dim_date JOIN entirely
                    sql = re.sub(
                        r'JOIN\s+warehouse\.dim_date\s+\w+\s+ON\s+[^\n;]+',
                        "", sql, flags=re.IGNORECASE
                    )
                    sql = re.sub(r',?\s*date_key', "", sql, flags=re.IGNORECASE)
                    sql = re.sub(r',?\s*\w+\.date_key', "", sql, flags=re.IGNORECASE)
                    corrections.append(
                        f"  [{name}] Removed dim_date JOIN (no date/year column in source)"
                    )
                elif has_year_col and not has_date_col:
                    # Only year column exists — fix the JOIN to use year
                    # Constrain to Jan 1st to avoid row multiplication
                    # (365 rows per year in dim_date, need exactly 1 match)
                    correct_join = (
                        f'JOIN warehouse.dim_date {alias_dd} ON '
                        f'{alias_dd}.year = src."{year_col}" '
                        f'AND {alias_dd}.month = 1 AND {alias_dd}.day = 1'
                    )
                    sql = re.sub(
                        r'JOIN\s+warehouse\.dim_date\s+\w+\s+ON\s+[^\n;]+',
                        correct_join, sql, flags=re.IGNORECASE
                    )
                    corrections.append(
                        f'  [{name}] Fixed dim_date JOIN: year-only source '
                        f'→ {alias_dd}.year = src."{year_col}" AND month=1 AND day=1'
                    )
                elif has_date_col and date_col:
                    # Full date column exists — fix to use it if AI used wrong column
                    # Only fix if the current join references a non-existent column
                    invented_col = re.search(
                        r'src\."(\w+)"', condition, re.IGNORECASE
                    )
                    if invented_col:
                        col_used = invented_col.group(1)
                        if col_used.lower() not in actual_col_set:
                            correct_join = (
                                f'JOIN warehouse.dim_date {alias_dd} ON '
                                f'{alias_dd}.full_date = src."{date_col}"::DATE'
                            )
                            sql = re.sub(
                                r'JOIN\s+warehouse\.dim_date\s+\w+\s+ON\s+[^\n;]+',
                                correct_join, sql, flags=re.IGNORECASE
                            )
                            corrections.append(
                                f'  [{name}] Fixed dim_date JOIN: '
                                f'"{col_used}" → "{date_col}"'
                            )

        # Fix 2: Remove any src."col" or s."col" references to non-existent columns
        def fix_src_col(m):
            alias  = m.group(1)  # src or s
            col    = m.group(2)  # column name
            col_lc = col.lower()

            # Always allow system/SCD columns
            system_cols = {
                "valid_from", "valid_to", "is_current", "loaded_at",
                "created_at", "updated_at", "inserted_at", "etl_batch_id",
                "period_id", "current_timestamp"
            }
            if col_lc in system_cols:
                return m.group(0)

            # Check if column exists in actual source
            if col_lc in actual_col_set:
                # Return with exact case from actual schema
                exact = actual_col_exact.get(col_lc, col)
                if exact != col:
                    corrections.append(
                    corrections.append("  [" + name + "] Column case fix: " + col + " -> " + exact)
                    )
                    return alias + '."'  + exact + '"'
                return m.group(0)

            # Column not in source — remove it
            corrections.append(
            corrections.append("  [" + name + "] Removed non-existent column: " + col + " (not in source)")
            )
            return ""  # Remove the reference

        sql_fixed = re.sub(r'(src|s)\."(\w+)"', fix_src_col, sql)

        # Fix 3: If we removed columns, clean up dangling commas and empty SELECTs
        if sql_fixed != sql:
            # Clean up multiple commas: ,  , → ,
            sql_fixed = re.sub(r',\s*,', ',', sql_fixed)
            # Clean up SELECT followed by comma: SELECT , → SELECT
            sql_fixed = re.sub(r'SELECT\s*,', 'SELECT ', sql_fixed, flags=re.IGNORECASE)
            # Clean up trailing commas before FROM/WHERE/JOIN
            sql_fixed = re.sub(r',\s*(FROM|WHERE|JOIN|ON)\b', r' \1', sql_fixed, flags=re.IGNORECASE)
            # Clean up comma before closing paren
            sql_fixed = re.sub(r',\s*\)', ')', sql_fixed)
            sql = sql_fixed

        if sql != original:
            script["sql"] = sql

    return scripts, corrections



def run_phase_2_sql_generation(schema_analysis: dict,
                               data_model: dict,
                               staging_schema: str = "staging",
                               warehouse_schema: str = "warehouse",
                               fk_relationships: list = None,
                               actual_staging_tables: list = None,
                               raw_schema: str = "") -> dict:
    print("[Phase 2 — Step 1/2] Generating ETL mappings...")
    mappings = generate_etl_mapping(schema_analysis, data_model)

    # Derive actual staging table names from source tables in data model
    if not actual_staging_tables:
        src_tables = schema_analysis.get("source_tables", [])
        actual_staging_tables = [
            f"stg_{t}" if not t.startswith("stg_") else t
            for t in src_tables
        ]

    print(f"[Phase 2] Actual staging tables available: {actual_staging_tables}")
    print("[Phase 2 — Step 2/2] Generating SQL (with hardened prompt + auto-fix)...")
    sql = generate_sql(data_model, mappings,
                       fk_relationships=fk_relationships,
                       actual_staging_tables=actual_staging_tables,
                       raw_schema=raw_schema)

    dim_names  = [d.get("name", "") for d in data_model.get("dimension_tables", [])]
    fact_names = [f.get("name", "") for f in data_model.get("fact_tables", [])]
    required   = set(n for n in dim_names + fact_names if n)
    generated  = set(s.get("name", "") for s in sql.get("scripts", []))
    missing    = required - generated

    if missing:
        print(f"[ETL Agent] ⚠ AI missed {len(missing)} scripts: {missing}")
        print(f"[ETL Agent] Retrying SQL generation...")
        sql = generate_sql(data_model, mappings,
                           actual_staging_tables=actual_staging_tables,
                           raw_schema=raw_schema)

    scripts, corrections = sanitize_generated_sql(sql.get("scripts", []), data_model)
    sql["scripts"] = scripts
# Extract actual column names — try raw_schema first, fall back to schema_analysis
    import re as _re
    actual_cols = []
    if raw_schema:
        col_pattern = _re.compile(r'^\s*[-\*]?\s*(\w+)\s*\(', _re.MULTILINE)
        actual_cols = col_pattern.findall(raw_schema)
        if not actual_cols:
            col_pattern2 = _re.compile(r'^\s*(\w+)\s*:', _re.MULTILINE)
            actual_cols = col_pattern2.findall(raw_schema)

    # Fallback: extract columns from schema_analysis entities
    # This always works for DuckDB sources where raw_schema may be empty
    if not actual_cols and schema_analysis:
        for entity in schema_analysis.get("entities", []):
            cols = entity.get("columns", [])
            if cols:
                actual_cols.extend(cols)
                print(f"[ETL Agent] Using schema_analysis columns: {cols[:5]}...")
                break

    if actual_cols:
        scripts, col_corrections = validate_and_fix_sql_columns(
            scripts, actual_cols, data_model
        )
        sql["scripts"] = scripts
        if col_corrections:
            print(f"[ETL Agent] 🔧 Column validation fixed {len(col_corrections)} issues:")
            for c in col_corrections:
                print(c)
            corrections.extend(col_corrections)

    if corrections:
        print(f"[ETL Agent] 🔧 Auto-fixed {len(corrections)} SQL issues:")
        for c in corrections:
            print(c)
    else:
        print(f"[ETL Agent] ✓ Generated SQL passed sanity check — no auto-fixes needed")

    if warehouse_schema != "warehouse" or staging_schema != "staging":
        for script in sql.get("scripts", []):
            s = script.get("sql", "")
            if warehouse_schema != "warehouse":
                s = s.replace("warehouse.", f'{warehouse_schema}.')
            if staging_schema != "staging":
                s = s.replace("staging.", f'{staging_schema}.')
            script["sql"] = s
        print(f"[ETL Agent] ✓ Rewrote SQL to use schemas: {staging_schema}, {warehouse_schema}")

    print(f"[ETL Agent] ✓ Phase 2 complete ({len(sql.get('scripts', []))} scripts)")

    return {
        "phase":        "sql_generation",
        "etl_mappings": mappings,
        "sql_scripts":  sql
    }


def run_full_pipeline(source_description, raw_schema, business_requirements,
                      connector_config: dict = None,
                      source_schema: str = "raw",
                      staging_schema: str = "staging",
                      warehouse_schema: str = "warehouse") -> dict:
    p1 = run_phase_1_model_design(source_description, raw_schema,
                                  business_requirements, connector_config,
                                  source_schema)
    p2 = run_phase_2_sql_generation(p1["schema_analysis"], p1["data_model"],
                                    staging_schema, warehouse_schema)
    return {
        "schema_analysis": p1["schema_analysis"],
        "data_model":      p1["data_model"],
        "etl_mappings":    p2["etl_mappings"],
        "sql_scripts":     p2["sql_scripts"],
        "used_profile":    p1.get("used_profile", False)
    }
