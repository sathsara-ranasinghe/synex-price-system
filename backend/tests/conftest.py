"""Test settings - set before any app module is imported so tests never touch the real .env database."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["QBWC_PASSWORD"] = "secret"
os.environ["ADMIN_PASSWORD"] = "Admin@123"
os.environ["SMTP_HOST"] = ""
os.environ["STATIC_DIR"] = ""
os.environ["ATTACHMENTS_DIR"] = "./test_attachments"

if os.path.exists("test.db"):
    os.remove("test.db")
