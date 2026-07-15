"""
AIBridge MCP Server
====================
A Claude/Anthropic-agnostic MCP server that wraps AIBridge's FastAPI
endpoints as MCP tools. Works with any MCP-compatible client:
Cursor, VS Code, Claude Desktop, or any future AI assistant.

Usage:
  python aibridge_mcp_server.py

Transport: stdio (default for MCP clients)
"""

import asyncio
import json
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# AIBridge API base URL — configurable via env var
import os
AIBRIDGE_BASE_URL = os.environ.get("AIBRIDGE_URL", "http://localhost:8888")
AIBRIDGE_TOKEN    = os.environ.get("AIBRIDGE_TOKEN", "")

# --- HTTP helper -----------------------------------------------------------
def _headers():
    h = {"Content-Type": "application/json"}
    if AIBRIDGE_TOKEN:
        h["Authorization"] = f"Bearer {AIBRIDGE_TOKEN}"
    return h

async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{AIBRIDGE_BASE_URL}{path}", headers=_headers())
        r.raise_for_status()
        return r.json()

async def _post(path: str, body: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{AIBRIDGE_BASE_URL}{path}",
                         headers=_headers(),
                         json=body or {})
        r.raise_for_status()
        return r.json()

# --- MCP Server -----------------------------------------------------------
server = Server("aibridge")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_pipelines",
            description="List all AIBridge ETL pipelines with their status and row counts.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="run_pipeline",
            description="Execute an existing AIBridge pipeline by ID. Returns run_id for status polling.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string", "description": "Pipeline UUID"}
                },
                "required": ["pipeline_id"]
            }
        ),
        types.Tool(
            name="get_pipeline_status",
            description="Get the execution status and row counts of a pipeline run.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"},
                    "run_id":      {"type": "string", "description": "Run ID returned by run_pipeline"}
                },
                "required": ["pipeline_id", "run_id"]
            }
        ),
        types.Tool(
            name="list_connectors",
            description="List all configured data source/target connectors in AIBridge.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
        types.Tool(
            name="get_quality_report",
            description="Get the data quality audit report for a pipeline (null checks, duplicates, business rules).",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"}
                },
                "required": ["pipeline_id"]
            }
        ),
        types.Tool(
            name="get_warehouse_stats",
            description="Get row counts for all warehouse tables loaded by a pipeline.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pipeline_id": {"type": "string"}
                },
                "required": ["pipeline_id"]
            }
        ),
        types.Tool(
            name="scan_migration",
            description="Reverse-engineer an existing database schema for migration to a target warehouse.",
            inputSchema={
                "type": "object",
                "properties": {
                    "connector_id": {"type": "string", "description": "Source connector UUID to scan"},
                    "schema_name":  {"type": "string", "description": "Database schema to scan (e.g. public)"}
                },
                "required": ["connector_id"]
            }
        ),
        types.Tool(
            name="deploy_migration",
            description="Deploy a scanned migration — generates and executes DDL on the target warehouse.",
            inputSchema={
                "type": "object",
                "properties": {
                    "migration_id":       {"type": "string"},
                    "target_connector_id": {"type": "string"}
                },
                "required": ["migration_id", "target_connector_id"]
            }
        ),
        types.Tool(
            name="list_migrations",
            description="List all migration jobs in AIBridge.",
            inputSchema={"type": "object", "properties": {}, "required": []}
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "list_pipelines":
            data = await _get("/pipeline/list")
            pipelines = data if isinstance(data, list) else data.get("pipelines", [])
            result = []
            for p in pipelines:
                result.append({
                    "id":     p.get("id"),
                    "name":   p.get("name"),
                    "status": p.get("status"),
                    "rows":   p.get("total_rows", 0),
                    "created": p.get("created_at", "")
                })
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "run_pipeline":
            pid = arguments["pipeline_id"]
            data = await _post(f"/pipeline/execute-async/{pid}")
            return [types.TextContent(type="text", text=json.dumps({
                "run_id":      data.get("run_id"),
                "pipeline_id": pid,
                "message":     "Pipeline started. Use get_pipeline_status to poll for completion."
            }, indent=2))]

        elif name == "get_pipeline_status":
            pid    = arguments["pipeline_id"]
            run_id = arguments["run_id"]
            data   = await _get(f"/pipeline/execute-async/{run_id}/status")
            return [types.TextContent(type="text", text=json.dumps(data, indent=2))]

        elif name == "list_connectors":
            data = await _get("/connector/list")
            connectors = data if isinstance(data, list) else data.get("connectors", [])
            result = []
            for c in connectors:
                result.append({
                    "id":   c.get("id"),
                    "name": c.get("name"),
                    "type": c.get("connector_type"),
                    "host": c.get("host"),
                    "db":   c.get("database_name")
                })
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "get_quality_report":
            pid  = arguments["pipeline_id"]
            data = await _get(f"/pipeline/{pid}/quality-audit")
            return [types.TextContent(type="text", text=json.dumps(data, indent=2))]

        elif name == "get_warehouse_stats":
            pid  = arguments["pipeline_id"]
            data = await _get(f"/pipeline/{pid}/stats")
            return [types.TextContent(type="text", text=json.dumps(data, indent=2))]

        elif name == "scan_migration":
            body = {"connector_id": arguments["connector_id"]}
            if "schema_name" in arguments:
                body["schema_name"] = arguments["schema_name"]
            data = await _post("/migration/scan", body)
            return [types.TextContent(type="text", text=json.dumps(data, indent=2))]

        elif name == "deploy_migration":
            data = await _post("/migration/deploy", {
                "migration_id":        arguments["migration_id"],
                "target_connector_id": arguments["target_connector_id"]
            })
            return [types.TextContent(type="text", text=json.dumps(data, indent=2))]

        elif name == "list_migrations":
            data = await _get("/migration/list")
            return [types.TextContent(type="text", text=json.dumps(data, indent=2))]

        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

    except httpx.HTTPStatusError as e:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"AIBridge API error {e.response.status_code}",
            "detail": e.response.text
        }))]
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())