with open('E:/AIBRIDGE_Claude/backend/main.py', encoding='utf-8') as f:
    src = f.read()

src = src.replace(
    'from fastapi import FastAPI, HTTPException, Depends, UploadFile, File',
    'from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form'
)

with open('E:/AIBRIDGE_Claude/backend/main.py', 'w', encoding='utf-8') as f:
    f.write(src)

print("✓ Form import added")
