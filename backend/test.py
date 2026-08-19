import requests, json
login = requests.post('http://localhost:8888/auth/login', json={'email': 'kaleshvenna@gmail.com', 'password': 'Kalesh@123456'})
token = login.json().get('access_token')
r = requests.post('http://localhost:8888/chat',
    json={'message': 'top 5 brands by average price', 'pipeline_id': '67b29244-bdf1-4b0d-8b97-46eae637be45', 'history': []},
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
print(json.dumps(r.json(), indent=2))