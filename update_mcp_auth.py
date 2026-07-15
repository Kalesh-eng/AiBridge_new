with open('E:/AIBRIDGE_Claude/backend/aibridge_mcp_server.py', encoding='utf-8') as f:
    content = f.read()

# Add auto-login after the imports block
old = '# --- HTTP helper -----------------------------------------------------------\ndef _headers():'

new = '''# --- Auth -----------------------------------------------------------------
_token_cache = {"token": os.environ.get("AIBRIDGE_TOKEN", "")}

async def _ensure_token():
    """Auto-login if no token set. Uses AIBRIDGE_EMAIL / AIBRIDGE_PASSWORD env vars."""
    if _token_cache["token"]:
        return
    email    = os.environ.get("AIBRIDGE_EMAIL", "")
    password = os.environ.get("AIBRIDGE_PASSWORD", "")
    if not email or not password:
        return  # No credentials — caller will get 401
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{AIBRIDGE_BASE_URL}/auth/login",
                         json={"email": email, "password": password})
        if r.status_code == 200:
            _token_cache["token"] = r.json().get("access_token", "")

# --- HTTP helper -----------------------------------------------------------
def _headers():
    h = {"Content-Type": "application/json"}
    if _token_cache["token"]:
        h["Authorization"] = f"Bearer {_token_cache['token']}"
    return h'''

content = content.replace(old, new, 1)

# Update _get and _post to call _ensure_token
old_get = '''async def _get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:'''
new_get = '''async def _get(path: str) -> dict:
    await _ensure_token()
    async with httpx.AsyncClient(timeout=60) as c:'''

old_post = '''async def _post(path: str, body: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=120) as c:'''
new_post = '''async def _post(path: str, body: dict = None) -> dict:
    await _ensure_token()
    async with httpx.AsyncClient(timeout=120) as c:'''

content = content.replace(old_get, new_get, 1)
content = content.replace(old_post, new_post, 1)

# Update _headers to use _token_cache
old_h = '''def _headers():
    h = {"Content-Type": "application/json"}
    if AIBRIDGE_TOKEN:
        h["Authorization"] = f"Bearer {AIBRIDGE_TOKEN}"
    return h'''
new_h = '''def _headers():
    h = {"Content-Type": "application/json"}
    if _token_cache["token"]:
        h["Authorization"] = f"Bearer {_token_cache['token']}"
    return h'''
content = content.replace(old_h, new_h, 1)

with open('E:/AIBRIDGE_Claude/backend/aibridge_mcp_server.py', 'w', encoding='utf-8') as f:
    f.write(content)

import ast
try:
    ast.parse(content)
    print(f"Syntax OK — {len(content.splitlines())} lines")
except SyntaxError as e:
    print(f"ERROR at line {e.lineno}: {e.msg}")
