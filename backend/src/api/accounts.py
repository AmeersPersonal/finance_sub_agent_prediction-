"""Email/password accounts: POST /signup and POST /login, the routes the frontend's
sign-up and sign-in forms call (through the dev proxy as /api/signup, /api/login).

Login starts the same session as Google sign-in (`SESSION_COOKIE`, `SessionStore`),
so `current_user`, /oauth/me, /oauth/logout, preferences and forecast quotas treat
both kinds of account alike. The session's `sub` is `password:<account id>`, which
can't collide with a provider's subject id.

A wrong email and a wrong password get the same 401 and take about as long, so the
response doesn't reveal which emails have accounts (sign-up's 409 does, as most
sign-up forms do). Attempts are rate-limited per client address.
"""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.state import RateLimiter
from database.connection import connect
from database.repository import DatabaseRepository
from oauth.passwords import DUMMY_HASH, hash_password, verify_password
from oauth.provider import OAuthSettings
from oauth.routes import SESSION_COOKIE, get_settings, get_store
from oauth.sessions import SESSION_TTL, SessionStore

router = APIRouter(tags=["accounts"])
# Per client address: sign-ups, and sign-ins per email, in any 15 minutes.
attempts = RateLimiter(limit=10, window=900)

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD, MAX_PASSWORD = 8, 256  # the cap keeps hashing cheap for absurd inputs


def _email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL.match(value):
        raise ValueError("Enter a valid email address.")
    return value


class SignupRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    first_name: str = Field(alias="firstName", min_length=1, max_length=100)
    last_name: str = Field(alias="lastName", min_length=1, max_length=100)
    email: str
    password: str = Field(min_length=MIN_PASSWORD, max_length=MAX_PASSWORD)

    @field_validator("first_name", "last_name")
    @classmethod
    def named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter your name.")
        return value.strip()

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return _email(value)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD)


def _repo(method: str, *args, **kwargs):
    with connect() as connection:
        return getattr(DatabaseRepository(connection), method)(*args, **kwargs)


def _limit(key: str) -> None:
    wait = attempts.acquire(key)
    if wait is not None:
        raise HTTPException(
            status_code=429, headers={"Retry-After": str(math.ceil(wait))},
            detail=f"Too many attempts. Try again in {math.ceil(wait / 60)} min.",
        )


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def public_user(account: dict[str, Any]) -> dict[str, Any]:
    return {"sub": f"password:{account['id']}", "email": account["email"],
            "name": f"{account['first_name']} {account['last_name']}", "provider": "password"}


@router.post("/signup", status_code=201)
async def signup(body: SignupRequest, request: Request) -> dict[str, Any]:
    _limit(f"signup:{_client(request)}")
    password_hash = await asyncio.to_thread(hash_password, body.password)
    account_id = await asyncio.to_thread(
        _repo, "create_account", email=body.email, password_hash=password_hash,
        first_name=body.first_name, last_name=body.last_name,
    )
    if account_id is None:
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    return {"user": public_user({"id": account_id, "email": body.email,
                                 "first_name": body.first_name, "last_name": body.last_name})}


@router.post("/login")
async def login(body: LoginRequest, request: Request, store: SessionStore = Depends(get_store),
                settings: OAuthSettings = Depends(get_settings)) -> JSONResponse:
    email = body.email.strip().lower()
    _limit(f"login:{_client(request)}:{email}")
    account = await asyncio.to_thread(_repo, "get_account", email) if EMAIL.match(email) else None
    valid = await asyncio.to_thread(verify_password, body.password,
                                    account["password_hash"] if account else DUMMY_HASH)
    if account is None or not valid:
        raise HTTPException(401, "Invalid email or password.")
    user = public_user(account)
    response = JSONResponse({"user": user})
    response.set_cookie(
        SESSION_COOKIE, store.create_session(user), max_age=int(SESSION_TTL.total_seconds()),
        path="/", httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
    return response
