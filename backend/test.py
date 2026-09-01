import requests, json
login = requests.post('http://localhost:8888/auth/login', json={'email': 'kaleshvenna@gmail.com', 'password': 'Kalesh@123456'})
token = login.json().get('access_token')
r = requests.post('http://localhost:8888/dwh/introspect',
    json={'connector_id': '9754ff6d-63d2-45ca-b1ea-1a6946bbf9b1', 'schemas': ['bank']},
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
print('Status:', r.status_code)
print(json.dumps(r.json(), indent=2)[:500])