"""
warehouse_knowledge.py
=======================
Consolidated warehouse knowledge graph for AIBridge Chat.
Scans all pipeline data models and builds a unified schema context.
Auto-refreshes on pipeline execution completion.
"""

import json
import os
import threading
from datetime import datetime

KNOWLEDGE_FILE = os.path.join(os.path.dirname(__file__), "warehouse_knowledge.json")
_refresh_lock  = threading.Lock()

def refresh_warehouse_knowledge(db) -> dict:
    """
    Scan all pipelines, extract data models and warehouse schema,
    build consolidated knowledge graph. Thread-safe.
    """
    with _refresh_lock:
        try:
            from database import Pipeline
            import sqlalchemy as sa
            from database import engine

            knowledge = {
                "last_updated": datetime.utcnow().isoformat(),
                "pipelines": {},
                "warehouse_tables": {},
                "relationships": [],
                "schema_context": ""
            }

            # 1. Scan all pipeline data models
            pipelines = db.query(Pipeline).all()
            for p in pipelines:
                artifacts = p.artifacts or {}
                data_model = artifacts.get("data_model") or {}
                if not data_model:
                    continue

                pipeline_info = {
                    "name": p.name,
                    "id": str(p.id),
                    "fact_tables": [],
                    "dimension_tables": []
                }

                # Extract fact tables
                for fact in data_model.get("fact_tables", []):
                    fname = fact.get("name", "")
                    if not fname:
                        continue
                    fact_info = {
                        "name": fname,
                        "pipeline": p.name,
                        "grain": fact.get("grain", ""),
                        "measures": [
                            m if isinstance(m, str) else m.get("name", "")
                            for m in fact.get("measures", [])
                        ],
                        "foreign_keys": []
                    }
                    for fk in fact.get("foreign_keys", []):
                        fk_str = fk if isinstance(fk, str) else fk.get("column", "")
                        fact_info["foreign_keys"].append(fk_str)
                        # Add to relationships
                        if "_key" in fk_str.lower():
                            dim_name = fk_str.replace("_key", "").replace("dim_", "")
                            knowledge["relationships"].append({
                                "from": f"{fname}.{fk_str}",
                                "to": f"dim_{dim_name}.{fk_str}"
                            })
                    pipeline_info["fact_tables"].append(fact_info)
                    knowledge["warehouse_tables"][fname] = fact_info

                # Extract dimension tables
                for dim in data_model.get("dimension_tables", []):
                    dname = dim.get("name", "")
                    if not dname:
                        continue
                    dim_info = {
                        "name": dname,
                        "pipeline": p.name,
                        "scd_type": dim.get("scd_type", "1"),
                        "natural_key": dim.get("natural_key_column", ""),
                        "attributes": [
                            a if isinstance(a, str) else a.get("name", "")
                            for a in dim.get("attributes", [])
                        ]
                    }
                    pipeline_info["dimension_tables"].append(dim_info)
                    knowledge["warehouse_tables"][dname] = dim_info

                knowledge["pipelines"][str(p.id)] = pipeline_info

            # 2. Also scan actual warehouse schema from DB
            try:
                with engine.connect() as conn:
                    r = conn.execute(sa.text("""
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = 'warehouse'
                        ORDER BY table_name, ordinal_position
                    """))
                    rows = r.fetchall()
                    db_tables = {}
                    for tbl, col, dtype in rows:
                        db_tables.setdefault(tbl, []).append(f"{col} ({dtype})")

                    # Enrich knowledge with actual DB columns
                    for tbl, cols in db_tables.items():
                        if tbl not in knowledge["warehouse_tables"]:
                            knowledge["warehouse_tables"][tbl] = {"name": tbl, "pipeline": "unknown"}
                        knowledge["warehouse_tables"][tbl]["columns"] = cols
            except Exception as e:
                print(f"[Knowledge] DB schema scan warning: {e}")

            # 3. Build human-readable schema context
            lines = ["=== AIBridge Warehouse Knowledge Graph ===\n"]

            # Group by pipeline
            for pid, pinfo in knowledge["pipelines"].items():
                lines.append(f"\nPipeline: {pinfo['name']}")
                for fact in pinfo["fact_tables"]:
                    tbl = knowledge["warehouse_tables"].get(fact["name"], {})
                    cols = tbl.get("columns", [])
                    lines.append(f"  FACT: {fact['name']}")
                    lines.append(f"    Grain: {fact.get('grain', 'unknown')}")
                    lines.append(f"    Measures: {', '.join(fact.get('measures', []))}")
                    lines.append(f"    FK keys: {', '.join(fact.get('foreign_keys', []))}")
                    if cols:
                        lines.append(f"    Columns: {', '.join(cols[:10])}")
                for dim in pinfo["dimension_tables"]:
                    tbl = knowledge["warehouse_tables"].get(dim["name"], {})
                    cols = tbl.get("columns", [])
                    lines.append(f"  DIM: {dim['name']} (SCD Type {dim.get('scd_type', '1')})")
                    lines.append(f"    Attributes: {', '.join(dim.get('attributes', [])[:8])}")
                    if cols:
                        lines.append(f"    Columns: {', '.join(cols[:8])}")

            # Relationships
            if knowledge["relationships"]:
                lines.append("\nRelationships (FK joins):")
                for rel in knowledge["relationships"]:
                    lines.append(f"  {rel['from']} → {rel['to']}")

            knowledge["schema_context"] = "\n".join(lines)

            # Save to file
            with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
                json.dump(knowledge, f, indent=2)

            print(f"[Knowledge] ✓ Warehouse knowledge refreshed — {len(knowledge['warehouse_tables'])} tables, {len(knowledge['pipelines'])} pipelines")
            return knowledge

        except Exception as e:
            print(f"[Knowledge] ✗ Refresh failed: {e}")
            return {}


def get_warehouse_knowledge(db=None) -> dict:
    """
    Get cached warehouse knowledge. Refreshes if:
    - Cache file doesn't exist
    - Cache is older than 1 hour
    - db session provided (forces check)
    """
    try:
        if os.path.exists(KNOWLEDGE_FILE):
            mtime = os.path.getmtime(KNOWLEDGE_FILE)
            age_minutes = (datetime.utcnow().timestamp() - mtime) / 60
            if age_minutes < 60:  # use cache if < 1 hour old
                with open(KNOWLEDGE_FILE, encoding="utf-8") as f:
                    return json.load(f)
        # Refresh if db provided
        if db:
            return refresh_warehouse_knowledge(db)
    except Exception as e:
        print(f"[Knowledge] Cache read error: {e}")
    return {}


def get_schema_context_for_chat(db=None) -> str:
    """Get the schema context string for use in chat prompts."""
    knowledge = get_warehouse_knowledge(db)
    return knowledge.get("schema_context", "")
