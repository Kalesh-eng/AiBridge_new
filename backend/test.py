import requests, json
login = requests.post('http://localhost:8888/auth/login', json={'email': 'kaleshvenna@gmail.com', 'password': 'Kalesh@123456'})
token = login.json().get('access_token')
r = requests.post('http://localhost:8888/chat',
    json={'message': 'total transactions by channel', 'connector_id': '9754ff6d-63d2-45ca-b1ea-1a6946bbf9b1', 'history': []},
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
data = r.json()
print('sql_result:', json.dumps(data.get('sql_result'), indent=2))
print('schema_available:', data.get('schema_available'))