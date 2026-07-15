import asyncio, httpx, os, sys, json
sys.path.insert(0, 'E:/AIBRIDGE_Claude/backend')

async def test_live():
    async with httpx.AsyncClient() as c:
        r = await c.post("http://localhost:8888/auth/login", json={
            "email": "kaleshvenna@gmail.com",
            "password": "Kalesh@123456"
        })
        print(f"Login status: {r.status_code}")
        print(f"Response: {r.text[:200]}")
        if r.status_code == 200:
            token = r.json().get("access_token")
            os.environ["AIBRIDGE_TOKEN"] = token
            print(f"✓ Token: {token[:30]}...")
            
            import aibridge_mcp_server as mcp
            import importlib; importlib.reload(mcp)
            
            result = await mcp.call_tool("list_pipelines", {})
            pipelines = json.loads(result[0].text)
            print(f"\n✓ Pipelines: {len(pipelines)}")
            for p in pipelines[:3]:
                print(f"  {p.get('name')} — {p.get('id','')[:8]}")

asyncio.run(test_live())