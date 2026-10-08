from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------- auth / users

class Token(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None  # when mfa_required: send it with the authenticator code to /auth/login/verify


class Me(ORM):
    user_id: int
    username: str
    full_name: str | None
    email: str
    role: str
    permissions: list[str]
    totp_enabled: bool = False
    must_setup_2fa: bool = False


class UserOut(ORM):
    user_id: int
    username: str
    full_name: str | None
    email: str
    role_name: str
    is_active: bool
    receive_alerts: bool
    created_at: datetime
    company_ids: list[int] = []
    totp_enabled: bool = False


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    full_name: str | None = None
    email: EmailStr
    password: str = Field(min_length=8)
    role_name: str
    receive_alerts: bool = True
    company_ids: list[int] = []


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8)
    role_name: str | None = None
    is_active: bool | None = None
    receive_alerts: bool | None = None
    company_ids: list[int] | None = None
    reset_2fa: bool = False  # admin: turn off two-factor for a user who lost their phone


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


# ---------------------------------------------------------------- sync / notifications / audit

class SyncLogOut(ORM):
    sync_id: int
    started_at: datetime
    finished_at: datetime | None
    records_inserted: int
    records_updated: int
    status: str
    error_message: str | None
    triggered_by: str
    qb_company_file: str | None
    progress: int = 0


class SyncStatus(BaseModel):
    last_success: SyncLogOut | None
    running: SyncLogOut | None
    pending_request: bool
    pending_writes: int
    run_every_minutes: int
    qbwc_url: str


class SyncRequestIn(BaseModel):
    full_resync: bool = False


class NotificationOut(ORM):
    notification_id: int
    type: str
    message: str
    link: str | None
    is_read: bool
    created_at: datetime


class AuditOut(ORM):
    audit_id: int
    username: str | None
    entity: str
    entity_id: str | None
    action: str
    old_value: dict | None
    new_value: dict | None
    created_at: datetime
