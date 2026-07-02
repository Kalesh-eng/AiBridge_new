"""
data_profiler.py
4-layer database profiling for accurate AI model generation.

Layer 1: Read FK constraints from information_schema (100% accurate)
Layer 2: Compute statistics (row count, distinct count, null %)
Layer 3: Detect hidden FKs via value overlap (the smart bit)
Layer 4: Sample 5 rows per table with PII masking

Privacy: relationship detection happens INSIDE the customer's database
via SQL aggregates. Only NUMBERS and 5 sample values leave.
"""

import psycopg2
import psycopg2.extras
import re


PII_PATTERNS = [
    re.compile(r'.*email.*',           re.I),
    re.compile(r'.*phone.*',           re.I),
    re.compile(r'.*mobile.*',          re.I),
    re.compile(r'.*ssn.*',             re.I),
    re.compile(r'.*aadhaar.*',         re.I),
    re.compile(r'.*pan.*',             re.I),
    re.compile(r'.*passport.*',        re.I),
    re.compile(r'.*credit.*card.*',    re.I),
    re.compile(r'.*card.*number.*',    re.I),
    re.compile(r'.*password.*',        re.I),
    re.compile(r'.*account.*number.*', re.I),
    re.compile(r'.*ifsc.*',            re.I),
]


def mask_pii(column_name: str, value):
    """Mask sensitive values before sending to AI."""
    if value is None:
        return None
    for pattern in PII_PATTERNS:
        if pattern.match(column_name):
            s = str(value)
            if len(s) > 4:
                return s[:2] + '*' * (len(s) - 4) + s[-2:]
            return '***'
    return value


def get_connection(host, port, database, username, password):
    return psycopg2.connect(
        host=host, port=port, dbname=database,
        user=username, password=password
    )


# ── LAYER 1 — Real FKs from information_schema ───────────────────────────────

def get_real_foreign_keys(conn_config: dict, schema: str = "raw") -> list:
    """Read declared FK constraints (100% accurate)."""
    try:
        conn = get_connection(**conn_config)
        cur  = conn.cursor()
        cur.execute("""
            SELECT
                tc.table_name           AS from_table,
                kcu.column_name         AS from_column,
                ccu.table_name          AS to_table,
                ccu.column_name         AS to_column,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema    = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema    = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema    = %s
            ORDER BY tc.table_name
        """, (schema,))
        fks = [
            {
                "from_table":  r[0],
                "from_column": r[1],
                "to_table":    r[2],
                "to_column":   r[3],
                "source":      "database_constraint",
                "confidence":  "100%"
            }
            for r in cur.fetchall()
        ]
        cur.close()
        conn.close()
        print(f"[Profiler] Layer 1: Found {len(fks)} declared FK constraints")
        return fks
    except Exception as e:
        print(f"[Profiler] Layer 1 failed: {e}")
        return []


# ── LAYER 2 — Statistics per column ──────────────────────────────────────────

def profile_column(conn_config: dict, schema: str, table: str,
                   column: str, data_type: str) -> dict:
    """Compute statistics: total, distinct, nulls, cardinality, range."""
    try:
        conn = get_connection(**conn_config)
        cur  = conn.cursor()

        cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
        total = cur.fetchone()[0]
        if total == 0:
            cur.close(); conn.close()
            return {"total": 0, "distinct": 0, "nulls": 0}

        cur.execute(f"""
            SELECT COUNT(DISTINCT "{column}"),
                   SUM(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END)
            FROM "{schema}"."{table}"
        """)
        distinct, nulls = cur.fetchone()
        nulls = nulls or 0

        result = {
            "total":        total,
            "distinct":     distinct,
            "nulls":        nulls,
            "null_pct":     round((nulls / total) * 100, 1) if total > 0 else 0,
            "is_likely_pk": (distinct == total and nulls == 0),
            "cardinality": (
                "high"   if distinct >= total * 0.9 else
                "medium" if distinct >= total * 0.1 else
                "low"
            )
        }

        if any(t in data_type.lower() for t in ["int","numeric","decimal","real","double"]):
            try:
                cur.execute(f'SELECT MIN("{column}"), MAX("{column}"), AVG("{column}") FROM "{schema}"."{table}"')
                mn, mx, avg = cur.fetchone()
                result["min"] = float(mn)  if mn  is not None else None
                result["max"] = float(mx)  if mx  is not None else None
                result["avg"] = round(float(avg), 2) if avg is not None else None
            except Exception:
                pass

        cur.close()
        conn.close()
        return result
    except Exception as e:
        return {"error": str(e), "total": 0, "distinct": 0, "nulls": 0}


# ── LAYER 3 — Detect hidden FKs via value overlap ────────────────────────────

def detect_hidden_fks(conn_config: dict, schema: str, tables: list,
                      threshold: int = 80) -> list:
    """The smart layer — detect FKs by comparing values across tables."""
    hidden_fks = []
    seen_pairs = set()

    try:
        conn = get_connection(**conn_config)
        cur  = conn.cursor()

        cur.execute("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name   = ANY(%s)
              AND (data_type IN ('integer','bigint','smallint','uuid')
                   OR (data_type LIKE '%character%' AND character_maximum_length <= 50))
            ORDER BY table_name, ordinal_position
        """, (schema, tables))
        candidates = cur.fetchall()

        print(f"[Profiler] Layer 3: Checking {len(candidates)} ID-like columns across {len(tables)} tables...")

        for from_tbl, from_col, _ in candidates:
            for to_tbl, to_col, _ in candidates:
                if from_tbl == to_tbl:
                    continue
                pair_key = f"{from_tbl}.{from_col}→{to_tbl}.{to_col}"
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                try:
                    cur.execute(f"""
                        WITH src AS (
                            SELECT DISTINCT "{from_col}" AS val
                            FROM "{schema}"."{from_tbl}"
                            WHERE "{from_col}" IS NOT NULL
                            LIMIT 1000
                        )
                        SELECT COUNT(*) FILTER (
                            WHERE val IN (
                                SELECT "{to_col}" FROM "{schema}"."{to_tbl}"
                            )
                        ) * 100.0 / NULLIF(COUNT(*), 0) AS overlap_pct
                        FROM src
                    """)
                    row = cur.fetchone()
                    overlap = row[0] if row else None

                    if overlap and overlap >= threshold:
                        hidden_fks.append({
                            "from_table":  from_tbl,
                            "from_column": from_col,
                            "to_table":    to_tbl,
                            "to_column":   to_col,
                            "overlap_pct": round(float(overlap), 1),
                            "source":      "value_overlap_detection",
                            "confidence":  f"{int(overlap)}%"
                        })
                        print(f"[Profiler] Detected: {pair_key} ({int(overlap)}% overlap)")
                except Exception:
                    continue

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Profiler] Layer 3 failed: {e}")

    print(f"[Profiler] Layer 3: Found {len(hidden_fks)} hidden FKs via value overlap")
    return hidden_fks


# ── LAYER 4 — Sample 5 rows with PII masking ─────────────────────────────────

def sample_table(conn_config: dict, schema: str, table: str,
                 limit: int = 5) -> dict:
    """Get 5 sample rows with PII masked."""
    try:
        conn = get_connection(**conn_config)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f'SELECT * FROM "{schema}"."{table}" LIMIT {limit}')
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return {"columns": [], "samples": {}}

        columns = list(rows[0].keys())
        samples = {}
        for col in columns:
            vals = [mask_pii(col, r[col]) for r in rows]
            samples[col] = [
                str(v) if v is not None and not isinstance(v, (int, float, bool, str))
                else v for v in vals
            ]
        return {"columns": columns, "samples": samples}
    except Exception as e:
        return {"columns": [], "samples": {}, "error": str(e)}


# ── MAIN — Build complete profile ─────────────────────────────────────────────

def build_full_profile(conn_config: dict, schema: str = "raw",
                       sample_rows: int = 5,
                       enable_overlap_detection: bool = True) -> dict:
    """Build complete profile combining all 4 layers."""
    try:
        conn = get_connection(**conn_config)
        cur  = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = %s AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, (schema,))
        tables = [r[0] for r in cur.fetchall()]
        cur.close()
        conn.close()

        if not tables:
            return {"success": False, "error": f"No tables in {schema} schema"}

        print(f"[Profiler] Found {len(tables)} tables in {schema} schema")

        profile = {
            "schema":       schema,
            "table_count":  len(tables),
            "tables":       {},
            "foreign_keys": [],
            "hidden_fks":   []
        }

        # Layer 1 — Real FKs
        profile["foreign_keys"] = get_real_foreign_keys(conn_config, schema)

        # Layers 2 + 4 — Statistics and sampling
        for table in tables:
            print(f"[Profiler] Profiling {schema}.{table}...")
            conn = get_connection(**conn_config)
            cur  = conn.cursor()
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))
            columns = cur.fetchall()
            cur.close()
            conn.close()

            sample      = sample_table(conn_config, schema, table, sample_rows)
            col_profile = []
            for col_name, dtype in columns:
                stats = profile_column(conn_config, schema, table, col_name, dtype)
                col_profile.append({
                    "name":    col_name,
                    "type":    dtype,
                    "samples": sample["samples"].get(col_name, [])[:3],
                    **stats
                })

            profile["tables"][table] = {
                "columns":   col_profile,
                "row_count": col_profile[0].get("total", 0) if col_profile else 0
            }

        # Layer 3 — Hidden FK detection
        if enable_overlap_detection and len(tables) > 1:
            if len(profile["foreign_keys"]) == 0:
                print("[Profiler] No declared FKs found — running value overlap detection...")
                profile["hidden_fks"] = detect_hidden_fks(conn_config, schema, tables)
            else:
                print(f"[Profiler] Skipping overlap detection ({len(profile['foreign_keys'])} declared FKs found)")

        print(f"[Profiler] ✓ Profile complete: "
              f"{len(profile['foreign_keys'])} real FKs, "
              f"{len(profile['hidden_fks'])} detected FKs")

        return {"success": True, "profile": profile}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Format profile as text for AI ─────────────────────────────────────────────

def format_profile_for_ai(profile: dict) -> str:
    """Convert profile to text the AI can use."""
    if not profile or not profile.get("tables"):
        return ""

    lines = []
    lines.append("=" * 60)
    lines.append("DATABASE PROFILE (real data, sampled + aggregated)")
    lines.append("=" * 60)

    for table_name, table_info in profile["tables"].items():
        lines.append(f"\nTable: {profile['schema']}.{table_name}")
        lines.append(f"Row count: {table_info.get('row_count', 0):,}")
        lines.append("Columns:")
        for col in table_info["columns"]:
            samples = col.get("samples", [])
            sample_str = ", ".join(str(s) for s in samples[:3]) if samples else "(empty)"
            pk_tag = " [PRIMARY KEY]" if col.get("is_likely_pk") else ""
            null_info = f", {col.get('null_pct', 0)}% null" if col.get("null_pct", 0) > 0 else ""
            cardinality = col.get("cardinality", "?")
            distinct_count = col.get("distinct", 0)

            line = f"  - {col['name']} ({col['type']}, {distinct_count} distinct, {cardinality} cardinality{null_info}){pk_tag}"
            line += f"\n    sample values: {sample_str}"
            if "min" in col and col.get("min") is not None:
                line += f"\n    range: {col.get('min')} to {col.get('max')}, avg: {col.get('avg')}"
            lines.append(line)

    if profile["foreign_keys"]:
        lines.append("\n" + "=" * 60)
        lines.append("FOREIGN KEY CONSTRAINTS (declared in database)")
        lines.append("=" * 60)
        for fk in profile["foreign_keys"]:
            lines.append(f"  {fk['from_table']}.{fk['from_column']} → "
                          f"{fk['to_table']}.{fk['to_column']} [CONFIRMED]")

    if profile["hidden_fks"]:
        lines.append("\n" + "=" * 60)
        lines.append("DETECTED RELATIONSHIPS (via data value overlap)")
        lines.append("=" * 60)
        for fk in profile["hidden_fks"]:
            lines.append(f"  {fk['from_table']}.{fk['from_column']} → "
                          f"{fk['to_table']}.{fk['to_column']} "
                          f"({fk['confidence']} value overlap)")

    return "\n".join(lines)
