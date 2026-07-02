content = '''__pycache__/
*.pyc
*.pyo
venv/
.env
*.duckdb
*.db
node_modules/
dist/
build/
*.bak
*.bak2
*.bak3
*.log
.DS_Store
Thumbs.db
'''
open('E:/AIBRIDGE_Claude/.gitignore', 'w').write(content)
print('Done')
