"""Authentication, Token Issuance, and RBAC Endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import (
    RateLimiter,
    check_rate_limit,
    get_current_user,
    require_admin,
    _AUTH_RATE_LIMITER,
)
from app.core.security import (
    Role,
    TokenPayload,
    get_security_manager,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.security import User
from app.services.audit.recorder import AuditEventCategory, audit_from_request

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=4)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in_seconds: int
    user: dict[str, Any]


class RegisterUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    email: str = Field(..., pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    password: str = Field(..., min_length=8)
    role: Role = Role.VIEWER


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Authenticates credentials, verifies cryptographic password hash, and issues HMAC token."""
    check_rate_limit(request, _AUTH_RATE_LIMITER)

    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not user.is_active:
        audit_from_request(
            request,
            db,
            event_category=AuditEventCategory.AUTH,
            action="login_failure",
            target_entity="User",
            target_id=credentials.username,
            status="FAILURE",
            details={"reason": "user_not_found_or_inactive"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    if not verify_password(credentials.password, user.salt, user.password_hash):
        audit_from_request(
            request,
            db,
            event_category=AuditEventCategory.AUTH,
            action="login_failure",
            target_entity="User",
            target_id=str(user.id),
            status="FAILURE",
            details={"username": user.username, "reason": "bad_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    sec_mgr = get_security_manager()
    token = sec_mgr.create_token(
        user_id=str(user.id),
        username=user.username,
        role=user.role,
        ttl_seconds=sec_mgr.token_ttl_seconds,
    )

    audit_from_request(
        request,
        db,
        event_category=AuditEventCategory.AUTH,
        action="login_success",
        target_entity="User",
        target_id=str(user.id),
        status="SUCCESS",
        details={"username": user.username, "role": user.role},
    )

    return LoginResponse(
        access_token=token,
        expires_in_seconds=sec_mgr.token_ttl_seconds,
        user={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
        },
    )


@router.get("/me")
def get_current_user_profile(
    current_user: TokenPayload = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Returns the authenticated operator profile."""
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "role": current_user.role.value,
        "issued_at": current_user.issued_at,
        "expires_at": current_user.expires_at,
    }


@router.post("/users", response_model=UserResponse)
def create_user(
    request: Request,
    user_data: RegisterUserRequest,
    current_admin: TokenPayload = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Creates a new operator with assigned RBAC role (Admin only)."""
    existing = db.query(User).filter((User.username == user_data.username) | (User.email == user_data.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered.")

    pwd_hash, salt = hash_password(user_data.password)
    new_user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=pwd_hash,
        salt=salt,
        role=user_data.role.value,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    audit_from_request(
        request,
        db,
        event_category=AuditEventCategory.AUTH,
        action="user_created",
        target_entity="User",
        target_id=str(new_user.id),
        status="SUCCESS",
        details={"created_username": new_user.username, "assigned_role": new_user.role},
    )

    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        role=new_user.role,
        is_active=new_user.is_active,
        created_at=new_user.created_at.isoformat() if new_user.created_at else "",
    )
