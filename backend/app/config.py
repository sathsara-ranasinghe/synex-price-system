from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Synex QB Portal"
    database_url: str = "postgresql+psycopg://synex:synex@localhost:5432/synex_prices"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # security
    require_2fa: str = "approvers"  # off | approvers (admins, approvers, direct writers) | all
    login_max_failures: int = 10  # wrong passwords per account before a 15-minute lock
    login_max_failures_ip: int = 30  # wrong passwords from one address before a 15-minute lock
    enable_api_docs: bool = False  # /api/docs; keep off on the internet

    # Initial admin created on first start
    admin_username: str = "admin"
    admin_password: str = "Admin@123"
    admin_email: str = "admin@synex.local"

    # QuickBooks Web Connector (QBWC). These create the FIRST company; more companies are added in the app.
    default_company_name: str = "Synex"
    qbwc_username: str = "qbwc"
    qbwc_password: str = "change-me-qbwc"
    qbwc_public_url: str = "https://prices.synex.local/qbwc"
    qbwc_company_file: str = ""  # empty = use the company file currently open in QB
    qbwc_run_every_minutes: int = 1  # incremental syncs are batched, so every poll can sync
    qbwc_max_returned: int = 500  # iterator page size
    qbwc_history_days: int = 365  # how far back to read POs/Bills on first sync
    qbxml_version: str = "16.0"  # QuickBooks Desktop 2024 supports qbXML 16.0

    cors_origins: str = "http://localhost:4200"
    static_dir: str = ""
    attachments_dir: str = "./data/attachments"
    max_attachment_mb: int = 20  # built Angular app to serve (Windows deployment without Nginx)

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "prices@synex.local"

    # daily summary e-mail (users with "receive alerts" on); hour of day in DIGEST_TZ, -1 = off
    digest_hour: int = 7
    digest_tz: str = "Asia/Colombo"


@lru_cache
def get_settings() -> Settings:
    return Settings()
