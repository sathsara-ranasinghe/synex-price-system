from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Table, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(Base):
    __tablename__ = "roles"
    role_id: Mapped[int] = mapped_column(primary_key=True)
    role_name: Mapped[str] = mapped_column(String(50), unique=True)
    permissions: Mapped[list] = mapped_column(JSON, default=list)


class Company(Base):
    """One QuickBooks company file. Each company has its own Web Connector login and its own data."""

    __tablename__ = "companies"
    company_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    qbwc_username: Mapped[str] = mapped_column(String(100), unique=True)
    qbwc_password_hash: Mapped[str] = mapped_column(String(200))
    app_name: Mapped[str] = mapped_column(String(100))  # AppName in the .qwc; must be unique in Web Connector
    # AppURL Web Connector calls for this company (None = QBWC_PUBLIC_URL from .env)
    qbwc_url: Mapped[str | None] = mapped_column(String(300))
    # Path of the .qbw this company syncs with. Learned on the first sync, then enforced so a different
    # company file can never be synced into this company by mistake.
    company_file: Mapped[str | None] = mapped_column(String(500))
    # entity keys QuickBooks reported as not enabled / not available for this company file (hidden in the UI)
    disabled_entities: Mapped[list | None] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


user_companies = Table(
    "user_companies", Base.metadata,
    Column("user_id", ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
    Column("company_id", ForeignKey("companies.company_id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    receive_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    role: Mapped[Role] = relationship(lazy="joined")
    companies: Mapped[list[Company]] = relationship(secondary=user_companies, lazy="selectin")


class SyncLog(Base):
    __tablename__ = "sync_logs"
    sync_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.company_id"), index=True)
    ticket: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    prices_changed: Mapped[int] = mapped_column(Integer, default=0)  # unused, kept for existing databases
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | success | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(20), default="schedule")  # schedule | manual
    qb_company_file: Mapped[str | None] = mapped_column(String(500))
    # internal QBWC state machine: queue of pending steps + iterator ids
    state: Mapped[dict] = mapped_column(JSON, default=dict)


class SyncCheckpoint(Base):
    """Last successful sync time per QB entity, used for incremental (FromModifiedDate) queries."""

    __tablename__ = "sync_checkpoints"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), primary_key=True)
    entity: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SyncRequest(Base):
    """A manual sync request from the UI; picked up the next time the Web Connector polls."""

    __tablename__ = "sync_requests"
    request_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.company_id"), index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    full_resync: Mapped[bool] = mapped_column(Boolean, default=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    audit_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    entity: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(30))
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    user: Mapped[User | None] = relationship(lazy="joined")


class Notification(Base):
    __tablename__ = "notifications"
    notification_id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QBWrite(Base):
    """Outbox of changes (and report requests) for QuickBooks, sent on the next Web Connector poll.

    kind: qb_add | qb_mod | qb_delete | qb_void | report
    status: pending (awaiting approval) -> approved -> sent -> done | failed ; or rejected
    """

    __tablename__ = "qb_writes"
    write_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.company_id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    entity_id: Mapped[int] = mapped_column(Integer)  # qb_records.record_id (edits) / qb_reports.report_id
    summary: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    qb_ref: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)

    requester: Mapped[User | None] = relationship(foreign_keys=[requested_by], lazy="joined")


class QBRecord(Base):
    """A copy of any QuickBooks list record or transaction. `data` is the full Ret as JSON."""

    __tablename__ = "qb_records"
    __table_args__ = (UniqueConstraint("company_id", "entity", "qb_id", name="uq_qb_record_company"),)
    record_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.company_id"), index=True)
    entity: Mapped[str] = mapped_column(String(40), index=True)
    qb_id: Mapped[str] = mapped_column(String(50))
    edit_sequence: Mapped[str | None] = mapped_column(String(50))
    name: Mapped[str | None] = mapped_column(String(400), index=True)
    party_id: Mapped[str | None] = mapped_column(String(50), index=True)
    party_name: Mapped[str | None] = mapped_column(String(400))
    txn_date: Mapped[date | None] = mapped_column(Date, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    time_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class QBReport(Base):
    __tablename__ = "qb_reports"
    report_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.company_id"), index=True)
    report_type: Mapped[str] = mapped_column(String(60))
    from_date: Mapped[date | None] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | done | failed
    result: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Attachment(Base):
    """A file attached to a QuickBooks record in the portal (stored on the portal server, not in QuickBooks)."""

    __tablename__ = "attachments"
    attachment_id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.company_id"), index=True)
    entity: Mapped[str] = mapped_column(String(40))
    qb_id: Mapped[str] = mapped_column(String(50), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    stored_as: Mapped[str] = mapped_column(String(300))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    uploader: Mapped[User | None] = relationship(lazy="joined")
