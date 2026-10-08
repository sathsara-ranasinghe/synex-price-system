"""Small in-place upgrades for databases created by earlier versions (no Alembic yet).

v2 -> v3: multi-company. Adds company_id to QuickBooks tables, creates the first company from the
QBWC settings in .env and assigns all existing data to it.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Company, QBRecord, QBReport, QBWrite, SyncLog, SyncRequest
from .security import hash_password

log = logging.getLogger("synex.migrate")

COMPANY_TABLES = ["qb_records", "qb_writes", "qb_reports", "sync_logs", "sync_requests"]


def before_create_all(engine: Engine) -> None:
    insp = inspect(engine)
    tables = insp.get_table_names()
    # sync_checkpoints changed its primary key; checkpoints are only an optimisation, so recreate it.
    if "sync_checkpoints" in tables and "company_id" not in {c["name"] for c in insp.get_columns("sync_checkpoints")}:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE sync_checkpoints"))
        log.warning("Recreated sync_checkpoints for multi-company; the next sync of each company is a full sync")


def after_create_all(engine: Engine) -> None:
    insp = inspect(engine)
    tables = insp.get_table_names()
    with engine.begin() as conn:
        for t in COMPANY_TABLES:
            if t in tables and "company_id" not in {c["name"] for c in insp.get_columns(t)}:
                conn.execute(text(f"ALTER TABLE {t} ADD COLUMN company_id INTEGER REFERENCES companies(company_id)"))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{t}_company_id ON {t} (company_id)"))
                log.warning("Added company_id to %s", t)
        if "companies" in tables:
            cols = {c["name"] for c in insp.get_columns("companies")}
            if "disabled_entities" not in cols:
                conn.execute(text("ALTER TABLE companies ADD COLUMN disabled_entities JSON"))
            if "qbwc_url" not in cols:
                conn.execute(text("ALTER TABLE companies ADD COLUMN qbwc_url VARCHAR(300)"))
            if "preferences" not in cols:
                conn.execute(text("ALTER TABLE companies ADD COLUMN preferences JSON"))
        if "users" in tables:
            ucols = {c["name"] for c in insp.get_columns("users")}
            for col, ddl in (("totp_secret", "VARCHAR(300)"), ("totp_enabled", "BOOLEAN DEFAULT FALSE"),
                             ("recovery_codes", "JSON")):
                if col not in ucols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
        if engine.dialect.name == "postgresql":
            conn.execute(text("ALTER TABLE qb_records DROP CONSTRAINT IF EXISTS uq_qb_record"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_qb_record_company ON qb_records (company_id, entity, qb_id)"))


def ensure_default_company(db: Session) -> Company:
    """The first company (from .env QBWC_* settings). Existing rows without a company belong to it."""
    company = db.query(Company).order_by(Company.company_id).first()
    if company is None:
        s = get_settings()
        last = db.query(SyncLog).filter(SyncLog.qb_company_file.isnot(None)).order_by(SyncLog.sync_id.desc()).first()
        company = Company(name=s.default_company_name, qbwc_username=s.qbwc_username,
                          qbwc_password_hash=hash_password(s.qbwc_password),
                          app_name="Synex Price Management",  # name already registered in Web Connector
                          company_file=last.qb_company_file if last else None)
        db.add(company)
        db.flush()
        log.warning("Created company '%s' (Web Connector user '%s')", company.name, company.qbwc_username)
    for model in (QBRecord, QBWrite, QBReport, SyncLog, SyncRequest):
        db.query(model).filter(model.company_id.is_(None)).update({model.company_id: company.company_id},
                                                                  synchronize_session=False)
    return company
