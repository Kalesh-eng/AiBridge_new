path = r'E:\AIBRIDGE_Claude\frontend\src\pages\Analytics.jsx'
with open(path, encoding='utf-8') as f: content = f.read()
import re
old = re.search(r\"\{ code: 'sn', name: 'Shona'.*?\},\", content)
if old:
    new = old.group() + \"\n    { code: 'ms', name: 'Malay',       flag: '\U0001f1f2\U0001f1fe', web_speech_code: 'ms-MY' },\"
    content = content[:old.start()] + new + content[old.end():]
    print('Malay added')
with open(path, 'w', encoding='utf-8') as f: f.write(content)