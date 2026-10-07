import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from . import migrate, models  # noqa: F401  (registers tables)
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import Role, User
from .permissions import ROLE_PERMISSIONS
from .qbwc import soap
from .routers import auth, changes, companies, files, portal, system
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition"])

for r in (auth.router, companies.router, files.router, portal.roles_router, portal.router, changes.router, system.router,
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
        file = os.path.realpath(os.path.join(_static_root, path))
        if path and file.startswith(_static_root) and os.path.isfile(file):
            return FileResponse(file)
        return FileResponse(os.path.join(_static_root, "index.html"))
