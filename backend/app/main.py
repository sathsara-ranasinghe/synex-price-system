import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from . import migrate, models  # noqa: F401  (registers tables)
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import Role, User
from .permissions import ROLE_PERMISSIONS
from .qbwc import soap
from .routers import auth, changes, companies, files, imports, insights, portal, system
from .security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("synex")

# Trigram indexes make ILIKE '%text%' searches fast on large company files.
SEARCH_INDEXES = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS ix_qb_records_name_trgm ON qb_records USING gin (name gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_qb_records_party_trgm ON qb_records USING gin (party_name gin_trgm_ops)",
]


def init_db() -> None:
    migrate.before_create_all(engine)
    Base.metadata.create_all(engine)
    migrate.after_create_all(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            for sql in SEARCH_INDEXES:
                conn.execute(text(sql))
    s = get_settings()
    with SessionLocal() as db:
        for name, perms in ROLE_PERMISSIONS.items():
            role = db.query(Role).filter_by(role_name=name).first()
            if role is None:  # seed once; afterwards roles are edited in the app
                db.add(Role(role_name=name, permissions=perms))
            elif name == "admin":  # admin always has every permission, including new modules
                role.permissions = perms
        db.flush()
        migrate.ensure_default_company(db)
        if not db.query(User).first():
            admin_role = db.query(Role).filter_by(role_name="admin").one()
            db.add(User(username=s.admin_username, full_name="Administrator", email=s.admin_email,
                        password_hash=hash_password(s.admin_password), role_id=admin_role.role_id))
            log.warning("Created initial admin user '%s' - change the password after first login", s.admin_username)
        db.commit()


def _send_digests() -> int:
    with SessionLocal() as db:
        return insights.send_daily_digests(db)


async def daily_summary_loop() -> None:
    """Send the daily summary e-mail once a day after DIGEST_HOUR (server local time)."""
    import asyncio
    from datetime import datetime

    while True:
        await asyncio.sleep(600)
        s = get_settings()
        try:
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(s.digest_tz))
        except Exception:  # no time-zone data on this machine: use its local clock
            now = datetime.now()
        if s.digest_hour < 0 or not s.smtp_host or now.hour < s.digest_hour:
            continue
        try:
            n = await asyncio.to_thread(_send_digests)
            if n:
                log.info("Sent %d daily summary e-mails", n)
        except Exception:  # never let the loop die
            log.exception("Daily summary failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    init_db()
    task = asyncio.create_task(daily_summary_loop())
    yield
    task.cancel()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan,
              docs_url="/api/docs" if settings.enable_api_docs else None,
              redoc_url=None, openapi_url="/api/openapi.json" if settings.enable_api_docs else None)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; img-src 'self' data: blob:; connect-src 'self'; "
       "frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if not request.url.path.startswith("/qbwc"):
        h.setdefault("Content-Security-Policy", CSP)
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    return response
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])

for r in (auth.router, companies.router, files.router, imports.router, insights.router, portal.roles_router, portal.router,
          changes.router, system.router,
          soap.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Windows/no-Docker deployments: serve the built Angular app from this process (STATIC_DIR=...\browser).
if settings.static_dir and os.path.isdir(settings.static_dir):
    _static_root = os.path.realpath(settings.static_dir)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "qbwc/")):  # unknown API address: a real 404, not the web page
            raise HTTPException(404, "Not found")
        file = os.path.realpath(os.path.join(_static_root, path))
        if path and file.startswith(_static_root) and os.path.isfile(file):
            return FileResponse(file)
        return FileResponse(os.path.join(_static_root, "index.html"))
