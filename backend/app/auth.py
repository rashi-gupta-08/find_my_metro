"""Database-backed authentication. No passwords or session tokens enter logs."""
import hashlib
import hmac
import secrets
import uuid
import ipaddress
import threading
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import Session, engine, iso, parse, transaction, utcnow
from .models import AuthSession, PasswordReset, Device, RateBucket, SecurityAudit, User, Observation, Evidence

router = APIRouter(prefix="/api/v1/auth", tags=["Accounts"])
hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
dummy_hash = hasher.hash(secrets.token_urlsafe(32))
hash_slots = threading.BoundedSemaphore(4)
COOKIE = "__Host-metro_session" if settings.secure_cookies else "metro_session"


def hash_password(password):
    if not hash_slots.acquire(blocking=False):
        raise HTTPException(429, "Sign-in service is busy. Try again shortly.", headers={"Retry-After":"2"})
    try:
        return hasher.hash(password)
    finally:
        hash_slots.release()


def verify_password(encoded, password):
    if not hash_slots.acquire(blocking=False):
        raise HTTPException(429, "Sign-in service is busy. Try again shortly.", headers={"Retry-After":"2"})
    try:
        return hasher.verify(encoded, password)
    finally:
        hash_slots.release()


def client_identity(request):
    direct = request.client.host
    try:
        trusted = [ipaddress.ip_network(value.strip()) for value in settings.trusted_proxy_cidrs.split(",") if value.strip()]
        if any(ipaddress.ip_address(direct) in network for network in trusted):
            forwarded = request.headers.get("x-forwarded-for", "").strip()
            # The trusted last hop must replace this header with one address, not append untrusted input.
            return str(ipaddress.ip_address(forwarded))
    except ValueError:
        pass
    return direct


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token):
    return hmac.new(settings.auth_secret.encode(), ("csrf:"+token).encode(), hashlib.sha256).hexdigest()


def limit(identity, category, maximum, seconds=60):
    """Atomic fixed-window counters shared by API processes, including failed attempts."""
    now = utcnow()
    window = int(now.timestamp()) // seconds
    key = hmac.new(settings.auth_secret.encode(), f"{category}:{identity}:{window}".encode(), hashlib.sha256).hexdigest()
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(RateBucket).values(key=key, count=1, expires_at=iso(now+timedelta(seconds=seconds)))
    statement = statement.on_conflict_do_update(index_elements=[RateBucket.key], set_={"count": RateBucket.count+1}).returning(RateBucket.count)
    with transaction() as session:
        count = session.scalar(statement)
    if count > maximum:
        raise HTTPException(429, "Too many requests. Try again shortly.", headers={"Retry-After": str(seconds)})


def origin_check(request):
    if request.headers.get("origin") not in [x.strip() for x in settings.cors_origins.split(",")]:
        raise HTTPException(403, "Request origin is not permitted")
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise HTTPException(415, "Use application/json")


def identity(request: Request, *, mutation=False, admin=False):
    token = request.cookies.get(COOKIE, "")
    with Session() as session:
        login = session.get(AuthSession, digest(token)) if token else None
        user = session.get(User, login.user_id) if login and parse(login.expires_at) > utcnow() else None
        if not user or user.disabled:
            raise HTTPException(401, "Sign in to continue")
        if admin and user.role != "admin":
            raise HTTPException(403, "Administrator access required")
        if mutation:
            origin_check(request)
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_for(token)):
                raise HTTPException(403, "Refresh the page and try again")
        return user


def public_user(user):
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role,
            "verified_contributor": user.verified_contributor}


def issue_session(session, user, response, previous=None):
    if previous:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(previous)))
    # Bound each account's active session count.
    existing = session.scalars(select(AuthSession).where(AuthSession.user_id == user.id).order_by(AuthSession.expires_at.desc())).all()
    for old in existing[4:]:
        session.delete(old)
    token = secrets.token_urlsafe(48)
    session.add(AuthSession(token_hash=digest(token), user_id=user.id, expires_at=iso(utcnow()+timedelta(hours=settings.session_hours))))
    response.set_cookie(COOKIE, token, max_age=settings.session_hours*3600, secure=settings.secure_cookies,
                        httponly=True, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"user": public_user(user), "csrf_token": csrf_for(token)}


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(pattern=r"^[a-zA-Z0-9_]{3,32}$")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class Registration(Credentials):
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)


@router.post("/register", status_code=201)
def register(body: Registration, request: Request, response: Response):
    origin_check(request)
    limit(client_identity(request), "register", 5, 3600)
    password_hash = hash_password(body.password)
    user = User(id=str(uuid.uuid4()), username=body.username, display_name=body.display_name.strip() or body.username,
                password_hash=password_hash, role="passenger", disabled=False, created_at=iso(utcnow()))
    try:
        with transaction() as session:
            session.add(user)
            session.flush()
            result = issue_session(session, user, response, request.cookies.get(COOKIE))
            session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id, action="account_registered"))
        return result
    except IntegrityError:
        raise HTTPException(409, "This username is unavailable") from None


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    origin_check(request)
    limit(client_identity(request), "login_ip", 30)
    limit(body.username, "login_account", 10)
    with transaction() as session:
        user = session.scalar(select(User).where(User.username == body.username).with_for_update())
        try:
            verify_password(user.password_hash if user else dummy_hash, body.password)
            valid = user is not None and not user.disabled
        except (VerificationError, InvalidHashError):
            valid = False
        session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id if user else None, action="login_succeeded" if valid else "login_failed"))
        if valid:
            if hasher.check_needs_rehash(user.password_hash):
                user.password_hash = hash_password(body.password)
            result = issue_session(session, user, response, request.cookies.get(COOKIE))
    if not valid:
        raise HTTPException(401, "Incorrect username or password")
    return result


@router.get("/me")
def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        user = identity(request)
        return {"user": public_user(user), "csrf_token": csrf_for(request.cookies[COOKIE])}
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return {"user": None, "csrf_token": None}


@router.post("/logout")
def logout(request: Request, response: Response):
    user = identity(request, mutation=True)
    with transaction() as session:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(request.cookies[COOKIE])))
        session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id, action="session_revoked"))
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")
    return {"ok": True}


def create_password_reset(session, user_id):
    """Called by local administration only; no public grant-issuance endpoint."""
    user = session.get(User, user_id, with_for_update=True)
    if not user or user.disabled:
        raise ValueError("Recovery requires an enabled account")
    token = secrets.token_urlsafe(32)
    expires_at = iso(utcnow()+timedelta(minutes=30))
    session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    session.add(PasswordReset(token_hash=digest(token), user_id=user.id, expires_at=expires_at))
    session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id, action="password_reset_issued"))
    return token, expires_at


class PasswordRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/password/reset")
def recover_password(body: PasswordRecovery, request: Request, response: Response):
    origin_check(request)
    limit(client_identity(request), "password_reset", 10)
    with transaction() as session:
        grant = session.get(PasswordReset, digest(body.token))
        # Lock the user before the grant, matching grant issuance and password changes.
        user = session.get(User, grant.user_id, with_for_update=True) if grant else None
        grant = session.scalar(select(PasswordReset).where(PasswordReset.token_hash == digest(body.token))
                               .with_for_update().execution_options(populate_existing=True))
        if not grant or not user or user.disabled or parse(grant.expires_at) <= utcnow():
            raise HTTPException(400, "Recovery link is invalid or expired. Ask for a new link.")
        user.password_hash = hash_password(body.new_password)
        session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
        session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id, action="password_reset_sessions_revoked"))
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/password")
def change_password(body: PasswordChange, request: Request, response: Response):
    user = identity(request, mutation=True)
    limit(user.id, "password_change", 5, 3600)
    with transaction() as session:
        stored = session.get(User, user.id, with_for_update=True)
        try:
            verify_password(stored.password_hash, body.current_password)
        except VerificationError:
            raise HTTPException(401, "Current password is incorrect") from None
        stored.password_hash = hash_password(body.new_password)
        session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        session.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
        session.add(SecurityAudit(at=iso(utcnow()), actor_id=user.id, action="password_changed_sessions_revoked"))
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")
    return {"ok": True}


def authenticate_device(session, token, node_id):
    device = session.get(Device, node_id) if isinstance(node_id, str) else None
    if not token or not device or device.disabled or not hmac.compare_digest(digest(token), device.key_hash):
        raise HTTPException(401, "Invalid device credential")


class AccountDeletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)


@router.post("/account/delete")
def delete_account(body: AccountDeletion, request: Request, response: Response):
    user = identity(request, mutation=True)
    limit(user.id, "account_deletion", 5, 3600)
    with transaction() as session:
        stored = session.get(User, user.id, with_for_update=True)
        try:
            verify_password(stored.password_hash, body.current_password)
        except VerificationError:
            raise HTTPException(401, "Current password is incorrect") from None
        session.execute(delete(Observation).where(Observation.source == "crowd", Observation.payload["authenticated_contributor"].as_string() == user.id))
        session.execute(delete(Observation).where(Observation.source == "surface_crowd", Observation.payload["contributor_id"].as_string() == user.id))
        session.execute(delete(Evidence).where(Evidence.source == "crowd", Evidence.contributor == user.id))
        session.execute(update(SecurityAudit).where(SecurityAudit.actor_id == user.id).values(actor_id=None))
        session.delete(stored)
        session.add(SecurityAudit(at=iso(utcnow()), actor_id=None, action="account_deleted"))
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")
    return {"ok": True}
