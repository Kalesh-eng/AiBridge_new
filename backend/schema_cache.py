"""
schema_cache.py — AIBridge Schema Cache

v1.1: Fixed UUID object not subscriptable error — all pipeline_id comparisons now use str()
v1.0: Initial implementation
"""

import hashlib
import json


def compute_schema_hash(schema_text: str, source_tables: list,
                        business_requirements: str = "") -> str:
    tables_str         = json.dumps(sorted(source_tables or []))
    schema_normalized  = _normalize_schema(schema_text or "")
    biz_normalized     = " ".join((business_requirements or "").lower().split())
    combined           = f"{tables_str}|{schema_normalized}|{biz_normalized}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _normalize_schema(schema_text: str) -> str:
    lines = []
    for line in schema_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        line = " ".join(line.split())
        lines.append(line.lower())
    return "\n".join(sorted(lines))


def get_cached_design(pipeline_id: str, schema_hash: str, db) -> dict | None:
    try:
        from database import Pipeline
        pipeline = db.query(Pipeline).filter(
            Pipeline.id == str(pipeline_id)
        ).first()

        if not pipeline:
            return None

        artifacts     = pipeline.artifacts or {}
        cached_hash   = artifacts.get("schema_hash")
        cached_design = artifacts.get("cached_design")

        if not cached_hash or not cached_design:
            print(f"[SchemaCache] No cache found for pipeline {str(pipeline_id)[:8]}")
            return None

        if cached_hash != schema_hash:
            print(f"[SchemaCache] Schema changed — cache invalidated")
            print(f"[SchemaCache]   Old hash: {cached_hash}")
            print(f"[SchemaCache]   New hash: {schema_hash}")
            return None

        print(f"[SchemaCache] ✓ Cache HIT — reusing design (hash: {schema_hash})")
        print(f"[SchemaCache] ✓ Skipping AI calls — $0 cost this run")
        return cached_design

    except Exception as e:
        print(f"[SchemaCache] Cache read error: {e}")
        return None


def save_cached_design(pipeline_id: str, schema_hash: str,
                       schema_analysis: dict, data_model: dict,
                       etl_mappings: dict, sql_scripts: dict,
                       db) -> bool:
    try:
        from database import Pipeline
        pipeline = db.query(Pipeline).filter(
            Pipeline.id == str(pipeline_id)
        ).first()

        if not pipeline:
            print(f"[SchemaCache] Pipeline {str(pipeline_id)[:8]} not found — cannot save cache")
            return False

        artifacts = dict(pipeline.artifacts or {})
        artifacts["schema_hash"]   = schema_hash
        artifacts["cached_design"] = {
            "schema_analysis": schema_analysis,
            "data_model":      data_model,
            "etl_mappings":    etl_mappings or {},
            "sql_scripts":     sql_scripts or {}
        }

        pipeline.artifacts = artifacts
        db.commit()

        print(f"[SchemaCache] ✓ Design cached (hash: {schema_hash})")
        print(f"[SchemaCache] ✓ Next run with same schema = $0 AI cost")
        return True

    except Exception as e:
        print(f"[SchemaCache] Cache save error: {e}")
        return False


def invalidate_cache(pipeline_id: str, db) -> bool:
    try:
        from database import Pipeline
        pipeline = db.query(Pipeline).filter(
            Pipeline.id == str(pipeline_id)
        ).first()

        if not pipeline:
            return False

        artifacts = dict(pipeline.artifacts or {})
        artifacts.pop("schema_hash",   None)
        artifacts.pop("cached_design", None)
        pipeline.artifacts = artifacts
        db.commit()

        print(f"[SchemaCache] Cache invalidated for pipeline {str(pipeline_id)[:8]}")
        return True

    except Exception as e:
        print(f"[SchemaCache] Cache invalidation error: {e}")
        return False


def get_cache_status(pipeline_id: str, db) -> dict:
    try:
        from database import Pipeline
        pipeline = db.query(Pipeline).filter(
            Pipeline.id == str(pipeline_id)
        ).first()

        if not pipeline:
            return {"cached": False, "hash": None}

        artifacts   = pipeline.artifacts or {}
        cached_hash = artifacts.get("schema_hash")

        return {
            "cached":     bool(cached_hash),
            "hash":       cached_hash,
            "has_design": bool(artifacts.get("cached_design"))
        }
    except Exception as e:
        return {"cached": False, "hash": None, "error": str(e)}