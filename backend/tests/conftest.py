"""Test settings - set before any app module is imported so tests never use values from the real .env."""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["QBWC_PASSWORD"] = "secret"
os.environ["ADMIN_PASSWORD"] = "Admin@123"
os.environ["SMTP_HOST"] = ""
os.environ["STATIC_DIR"] = ""
os.environ["QBWC_RUN_EVERY_MINUTES"] = "1"
os.environ["QBWC_USERNAME"] = "qbwc"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["ATTACHMENTS_DIR"] = "./test_attachments"

if os.path.exists("test.db"):
    os.remove("test.db")
