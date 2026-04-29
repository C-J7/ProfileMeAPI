import os
import json
from datetime import datetime, timezone
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from uuid6 import uuid7

from main import User, get_db

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key-placeholder")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# APIRouter
router = APIRouter(prefix="/auth", tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/github")

def create_tokens(user_id: str):
    now = datetime.now(timezone.utc)
    access_token = jwt.encode({"sub": user_id, "exp": now.timestamp() + 180}, JWT_SECRET, algorithm="HS256") # 3 mins
    refresh_token = jwt.encode({"sub": user_id, "exp": now.timestamp() + 300}, JWT_SECRET, algorithm="HS256") # 5 mins
    return access_token, refresh_token

def get_current_user(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization")
    token = auth_header.split(" ")[1] if auth_header and auth_header.startswith("Bearer ") else request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = db.query(User).filter(User.id == payload.get("sub")).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_admin(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


# --- Auth Endpoints ---

@router.get("/github")
async def github_login(redirect_uri: str = None):
    url = f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}"
    if redirect_uri:
        url += f"&redirect_uri={redirect_uri}"
    return {"url": url}

@router.get("/github/callback")
async def github_callback(code: str, response: Response, code_verifier: Optional[str] = None, db: Session = Depends(get_db)):
    # Prepare payload, including the PKCE verifier if provided by the CLI
    data = {
        "client_id": GITHUB_CLIENT_ID, 
        "client_secret": GITHUB_CLIENT_SECRET, 
        "code": code
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data=data
        )
        gh_token = token_resp.json().get("access_token")
        if not gh_token:
            raise HTTPException(status_code=400, detail="Invalid code or verifier")

        user_resp = await client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {gh_token}"})
        gh_user = user_resp.json()

    user = db.query(User).filter(User.github_id == str(gh_user["id"])).first()
    if not user:
        user = User(
            id=str(uuid7()),
            github_id=str(gh_user["id"]),
            username=gh_user["login"],
            email=gh_user.get("email"),
            avatar_url=gh_user.get("avatar_url"),
            role="analyst" # Default role
        )
        db.add(user)
    
    user.last_login_at = datetime.now(timezone.utc)
    access_token, refresh_token = create_tokens(user.id)
    user.refresh_token = refresh_token
    db.commit()

    response.set_cookie(key="access_token", value=access_token, httponly=True, secure=True, samesite="lax", max_age=180)
    response.set_cookie(key="refresh_token", value=refresh_token, httponly=True, secure=True, samesite="lax", max_age=300)

    return {"status": "success", "access_token": access_token, "refresh_token": refresh_token}

@router.post("/refresh")
async def refresh_token(request: Request, response: Response, db: Session = Depends(get_db)):
    
    payload = {}
    try:
        body = await request.body()
        if body:
            payload = json.loads(body)
    except json.JSONDecodeError:
        pass

    token = payload.get("refresh_token") or request.cookies.get("refresh_token")
    
    if not token:
        raise HTTPException(status_code=401, detail="Refresh token required")

    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = db.query(User).filter(User.id == decoded.get("sub")).first()
        
        if not user or user.refresh_token != token:
            raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")
            
        access_token, new_refresh_token = create_tokens(user.id)
        user.refresh_token = new_refresh_token 
        db.commit()

        response.set_cookie(key="access_token", value=access_token, httponly=True, secure=True, samesite="lax", max_age=180)
        response.set_cookie(key="refresh_token", value=new_refresh_token, httponly=True, secure=True, samesite="lax", max_age=300)

        return {"status": "success", "access_token": access_token, "refresh_token": new_refresh_token}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")

# Logout Endpoint - Revokes the refresh token and clears cookies
@router.post("/logout")
async def logout(response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.refresh_token = None
    db.commit()
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    # Return JSON for CLI parsing
    return {
        "status": "success", 
        "refresh_token": refresh_token,
        "username": user.username,
        "role": user.role,
        "message": "Logged out successfully"
    }