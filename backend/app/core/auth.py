"""FastAPI Authentication and RBAC Authorization Dependencies.

Implements:
- Bearer token authentication
- In-memory rate limiting with sliding bucket
- Role hierarchy verification (VIEWER < ANALYST < DBA < ADMIN)
- Production action authorization: Only DBA and ADMIN can approve migrations or mutate config
"""

from __future__ import annotations

import collections
import time
from typing import Callable
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import ROLE_HIERARCHY, Role, TokenPayload, get_security_manager
from app.db.session import get_db
from app.models.security import User

security_scheme = HTTPBearer(auto_error=False)


class RateLimiter:
    """Sliding-window in-memory rate limiter per client IP / Token."""

    def __init__(self, requests_per_minute: int = 120) -> None:
        self.requests_per_minute = requests_per_minute
        self.history: dict[str, collections.deque[float]] = collections.defaultdict(collections.deque)

    def is_allowed(self, client_key: str) -> tuple[bool, int]:
        now = time.time()
        window_start = now - 60.0
        q = self.history[client_key]

        # Purge timestamps outside sliding window
        while q and q[0] < window_start:
            q.popleft()

        if len(q) >= self.requests_per_minute:
            retry_after = int(60.0 - (now - q[0])) + 1
            return False, max(1, retry_after)

        q.append(now)
        return True, 0


# Default global API rate limiter (120 req / min)
_API_RATE_LIMITER = RateLimiter(requests_per_minute=120)
# Strict rate limiter for auth / login attempts (20 req / min)
_AUTH_RATE_LIMITER = RateLimiter(requests_per_minute=20)


def check_rate_limit(request: Request, limiter: RateLimiter | None = None) -> None:
    """Checks rate limit based on client IP or authorized identity."""
    active_limiter = limiter or _API_RATE_LIMITER
    client_ip = request.client.host if request.client else "127.0.0.1"
    # Use Authorization header as key if present, otherwise client IP
    auth_header = request.headers.get("authorization", "")
    key = f"{client_ip}:{auth_header[:32]}" if auth_header else client_ip

    allowed, retry_after = active_limiter.is_allowed(key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security_scheme),
    db: Session = Depends(get_db),
) -> TokenPayload | None:
    """Extracts and verifies user identity from token if provided.
    
    If no token is provided, returns None (allowing public endpoints).
    If an invalid or expired token is provided, raises 401.
    """
    check_rate_limit(request)

    if not credentials or not credentials.credentials:
        request.state.current_user = None
        return None

    token = credentials.credentials
    sec_manager = get_security_manager()
    try:
        payload = sec_manager.decode_and_verify_token(token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    request.state.current_user = payload
    return payload


def get_current_user(
    payload: TokenPayload | None = Depends(get_current_user_optional),
) -> TokenPayload:
    """Enforces that an active authenticated session is present."""
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide a valid Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def require_role(min_role: Role) -> Callable[[TokenPayload], TokenPayload]:
    """Dependency factory checking that the authenticated user meets the minimum role rank."""
    min_weight = ROLE_HIERARCHY[min_role]

    def _role_checker(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        user_weight = ROLE_HIERARCHY.get(user.role, 0)
        if user_weight < min_weight:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Action requires at least {min_role.value} role (current role: {user.role.value}).",
            )
        return user

    return _role_checker


# Role-specific guards
require_viewer = require_role(Role.VIEWER)
require_analyst = require_role(Role.ANALYST)
require_dba = require_role(Role.DBA)
require_admin = require_role(Role.ADMIN)


def require_dba_or_admin(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
    """Strict guard: Only DBA and ADMIN can approve production-changing actions."""
    if user.role not in {Role.DBA, Role.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Production action forbidden. Only DBA or ADMIN roles can approve migrations or mutate catalogs (current: {user.role.value}).",
        )
    return user
