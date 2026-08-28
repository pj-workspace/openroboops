from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .config import Settings
from .database import get_db
from .models import LoginSession, RuntimeSetting, User, as_utc

SESSION_COOKIE = "openroboops_session"
CSRF_COOKIE = "openroboops_csrf"
BOOTSTRAP_HASH_KEY = "bootstrap_token_hash"

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


async def ensure_bootstrap_token(db: AsyncSession) -> str | None:
    if (await db.scalar(select(User.id).limit(1))) is not None:
        return None
    setting = await db.get(RuntimeSetting, BOOTSTRAP_HASH_KEY)
    if setting is not None:
        return None
    token = secrets.token_urlsafe(24)
    db.add(RuntimeSetting(key=BOOTSTRAP_HASH_KEY, value=hash_secret(token)))
    await db.commit()
    return token


async def create_login_session(db: AsyncSession, user: User, response: Response, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.session_hours)
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=hash_secret(token),
            csrf_hash=hash_secret(csrf),
            expires_at=expires_at,
        )
    )
    await db.commit()
    max_age = settings.session_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        max_age=max_age,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        max_age=max_age,
    )
    return csrf


async def get_current_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    query = (
        select(LoginSession)
        .options(selectinload(LoginSession.user))
        .where(LoginSession.token_hash == hash_secret(session_token))
    )
    login_session = await db.scalar(query)
    now = datetime.now(UTC)
    if login_session is None or as_utc(login_session.expires_at) < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired")
    return login_session.user


async def require_csrf(
    request: Request,
    user: User = Depends(get_current_user),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return user
    if not session_token or not csrf_cookie or not csrf_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="missing CSRF token")
    login_session = await db.scalar(select(LoginSession).where(LoginSession.token_hash == hash_secret(session_token)))
    if login_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session expired")
    valid = hmac.compare_digest(csrf_cookie, csrf_header) and hmac.compare_digest(
        login_session.csrf_hash, hash_secret(csrf_header)
    )
    if not valid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid CSRF token")
    return user


async def revoke_login_session(db: AsyncSession, response: Response, token: str | None) -> None:
    if token:
        await db.execute(delete(LoginSession).where(LoginSession.token_hash == hash_secret(token)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
