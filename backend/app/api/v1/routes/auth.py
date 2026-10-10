"""Authentication, Token Issuance, and RBAC Endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth import (
    RateLimiter,
    check_rate_limit,
    get_current_user,
    get_current_user_optional,
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
from app.models.security import SecurityAuditEvent, User
from app.services.audit.recorder import AuditEventCategory, audit_from_request

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=2, max_length=128)
    password: str = Field(..., min_length=4)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in_seconds: int
    user: dict[str, Any]


class RegisterUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    email: str = Field(..., pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    password: str = Field(..., min_length=8)
    role: Role = Role.VIEWER


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str
    last_login_at: str | None = None


def _serialize_user(u: User) -> UserResponse:
    return UserResponse(
        id=u.id,
        username=u.username,
        email=u.email,
        role=u.role,
        is_active=u.is_active,
        created_at=u.created_at.isoformat() if u.created_at else "",
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    response: Response,
    credentials: LoginRequest,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Authenticates credentials (username or email), verifies password hash, and issues HMAC token + HttpOnly cookie."""
    check_rate_limit(request, _AUTH_RATE_LIMITER)

    ident = credentials.username.strip()
    user = (
        db.query(User)
        .filter((User.username == ident) | (User.email == ident))
        .first()
    )
    if not user or not user.is_active:
        audit_from_request(
            request,
            db,
            event_category=AuditEventCategory.AUTH,
            action="login_failure",
            target_entity="User",
            target_id=ident,
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

    response.set_cookie(
        key="dbzenith_session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=sec_mgr.token_ttl_seconds,
        path="/",
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


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    current_user: TokenPayload | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Terminates the operator session and clears HttpOnly session cookies."""
    response.delete_cookie(key="dbzenith_session", path="/")
    if current_user:
        audit_from_request(
            request,
            db,
            event_category=AuditEventCategory.AUTH,
            action="logout",
            target_entity="User",
            target_id=str(current_user.user_id),
            status="SUCCESS",
            details={"username": current_user.username, "role": current_user.role.value},
        )
    return {"status": "logged_out"}


@router.get("/me")
def get_current_user_profile(
    current_user: TokenPayload = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Returns the authenticated operator profile."""
    email = f"{current_user.username}@dbzenith.local"
    if str(current_user.user_id).isdigit():
        u = db.get(User, int(current_user.user_id))
        if u and u.email:
            email = u.email
    return {
        "user_id": current_user.user_id,
        "username": current_user.username,
        "email": email,
        "role": current_user.role.value,
        "issued_at": current_user.issued_at,
        "expires_at": current_user.expires_at,
    }


@router.get("/users", response_model=list[UserResponse])
def list_users(
    current_admin: TokenPayload = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    """Lists all operator accounts (Admin only). Never exposes password hashes or salts."""
    users = db.query(User).order_by(User.id.asc()).all()
    return [_serialize_user(u) for u in users]


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
    try:
        db.add(new_user)
        db.flush()
        db.add(
            SecurityAuditEvent(
                event_category=AuditEventCategory.AUTH,
                action="user_created",
                actor_id=str(current_admin.user_id),
                actor_username=current_admin.username,
                actor_role=current_admin.role.value,
                target_entity="User",
                target_id=str(new_user.id),
                status="SUCCESS",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                details_json=json.dumps({"created_username": new_user.username, "assigned_role": new_user.role}),
            )
        )
        db.commit()
        db.refresh(new_user)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="user_creation_transaction_failed") from exc

    return _serialize_user(new_user)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    request: Request,
    payload: UpdateUserRequest,
    current_admin: TokenPayload = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Updates an operator's role or active status (Admin only). Prevents self-lockout/self-demotion."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    is_self = str(target.id) == str(current_admin.user_id) or target.username == current_admin.username
    if is_self:
        if payload.is_active is False:
            raise HTTPException(status_code=400, detail="Administrators cannot deactivate their own account.")
        if payload.role is not None and payload.role != Role.ADMIN:
            raise HTTPException(status_code=400, detail="Administrators cannot demote their own ADMIN role.")

    prev_role = target.role
    prev_active = target.is_active

    if payload.role is not None:
        target.role = payload.role.value
    if payload.is_active is not None:
        target.is_active = payload.is_active

    try:
        db.add(
            SecurityAuditEvent(
                event_category=AuditEventCategory.AUTH,
                action="user_updated",
                actor_id=str(current_admin.user_id),
                actor_username=current_admin.username,
                actor_role=current_admin.role.value,
                target_entity="User",
                target_id=str(target.id),
                status="SUCCESS",
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                details_json=json.dumps({
                    "username": target.username,
                    "previous_role": prev_role,
                    "new_role": target.role,
                    "previous_active": prev_active,
                    "new_active": target.is_active,
                }),
            )
        )
        db.commit()
        db.refresh(target)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="user_update_transaction_failed") from exc

    return _serialize_user(target)

