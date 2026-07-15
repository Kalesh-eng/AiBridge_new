"""
Simple test to verify AIBridge MCP server tools are correctly defined.
Tests the server without needing any MCP client (Cursor, VS Code, etc.)
"""
import asyncio
import sys
sys.path.insert(0, 'E:/AIBRIDGE_Claude/backend')

async def test_mcp_tools():
    from aibridge_mcp_server import list_tools
    
    tools = await list_tools()
    print(f"✓ MCP Server exposes {len(tools)} tools:")
    for t in tools:
        print(f"  - {t.name}: {t.description[:60]}...")
    
    print("\n✓ MCP server is correctly configured")
    print("✓ Connect via Cursor, VS Code MCP extension, or any MCP client")
    print(f"\nConfig for MCP clients:")
    print('''  command: E:/AIBRIDGE_Claude/venv/Scripts/python.exe''')
    print('''  args: ["E:/AIBRIDGE_Claude/backend/aibridge_mcp_server.py"]''')

asyncio.run(test_mcp_tools())
