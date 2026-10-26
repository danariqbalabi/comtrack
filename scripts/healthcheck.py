import base64
import json
import os
import urllib.request

username, password = os.getenv('ACCESS_USERNAME', ''), os.getenv('ACCESS_PASSWORD', '')
request = urllib.request.Request('http://127.0.0.1:8000/api/health')
if username and password:
    request.add_header('Authorization', 'Basic ' + base64.b64encode(f'{username}:{password}'.encode()).decode())
with urllib.request.urlopen(request, timeout=5) as response:
    result = json.load(response)
    assert result['status'] == 'ok' and result['database'] == 'ok'
