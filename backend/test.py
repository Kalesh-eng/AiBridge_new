import sys
sys.path.insert(0,'E:/AIBRIDGE_Claude/backend')
from ai_provider import ask_ai_text
result = ask_ai_text('Say hello', agent_name='Test')
print('Result:', result[:100])