"""
auth.py — Local Postgres JWT authentication
Includes: signup, login, password reset, forgot password.
"""
import os
import uuid
import secrets
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from database import get_db, User, Workspace
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "aibridge-secret-key")
ALGORITHM  = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MINUTES", 10080))

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=4)
security = HTTPBearer()

# In-memory reset token store (use Redis in production)
_reset_tokens: dict = {}


def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)

def create_token(user_id: str, email: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=EXPIRE_MIN)
    return jwt.encode(
        {"sub": user_id, "email": email, "exp": expire},
        SECRET_KEY, algorithm=ALGORITHM
    )

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again."
        )

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    payload = decode_token(credentials.credentials)
    user    = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def signup(email: str, password: str, full_name: str, db: Session) -> dict:
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        id        = str(uuid.uuid4()),
        email     = email,
        full_name = full_name,
        password  = hash_password(password)
    )
    db.add(user)
    db.flush()
    workspace = Workspace(
        id       = str(uuid.uuid4()),
        owner_id = user.id,
        name     = f"{full_name}'s Workspace",
        plan     = "starter"
    )
    db.add(workspace)
    db.commit()
    db.refresh(user)

    # Send welcome email (non-blocking)
    try:
        from notifications import notify_signup_welcome
        notify_signup_welcome(email, full_name)
    except Exception:
        pass

    return {
        "success": True,
        "message": "Account created successfully. Please log in.",
        "user_id": str(user.id)
    }


def login(email: str, password: str, db: Session) -> dict:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token     = create_token(str(user.id), user.email)
    workspace = db.query(Workspace).filter(Workspace.owner_id == user.id).first()
    return {
        "success":      True,
        "access_token": token,
        "token_type":   "bearer",
        "user": {
            "id":        str(user.id),
            "email":     user.email,
            "full_name": user.full_name,
            "workspace": {
                "id":   str(workspace.id)   if workspace else None,
                "name": workspace.name      if workspace else None,
                "plan": workspace.plan      if workspace else None,
            }
        }
    }


def forgot_password(email: str, db: Session) -> dict:
    """Generate a password reset token and send email."""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        # Don't reveal if email exists
        return {"success": True, "message": "If that email exists, a reset link has been sent."}

    token = secrets.token_urlsafe(32)
    _reset_tokens[token] = {
        "user_id": str(user.id),
        "expires": datetime.utcnow() + timedelta(hours=1)
    }

    try:
        from notifications import notify_password_reset
        notify_password_reset(email, token)
    except Exception as e:
        print(f"Reset email failed: {e}")

    return {"success": True, "message": "If that email exists, a reset link has been sent."}


def reset_password(token: str, new_password: str, db: Session) -> dict:
    """Reset password using the token from email."""
    if token not in _reset_tokens:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    data = _reset_tokens[token]
    if datetime.utcnow() > data["expires"]:
        del _reset_tokens[token]
        raise HTTPException(status_code=400, detail="Reset token has expired")

    user = db.query(User).filter(User.id == data["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password = hash_password(new_password)
    db.commit()
    del _reset_tokens[token]

    return {"success": True, "message": "Password reset successfully. Please log in."}


def get_user_workspace(user_id: str, db: Session) -> dict:
    ws = db.query(Workspace).filter(Workspace.owner_id == user_id).first()
    if not ws:
        return {}
    return {"id": str(ws.id), "name": ws.name, "plan": ws.plan}
