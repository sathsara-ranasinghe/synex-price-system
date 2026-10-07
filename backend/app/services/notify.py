import logging
import smtplib
import threading
from email.message import EmailMessage

from ..config import get_settings

log = logging.getLogger(__name__)


def _message(to: list[str], subject: str, body: str, attachment: tuple[str, bytes, str] | None) -> EmailMessage:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, ", ".join(to), subject
    msg.set_content(body)
    if attachment:
        name, content, mime = attachment
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)
    return msg


def _deliver(msg: EmailMessage) -> None:
    s = get_settings()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


def send_email_now(to: list[str], subject: str, body: str, attachment: tuple[str, bytes, str] | None = None) -> None:
    """Send immediately; raises RuntimeError with a readable message on failure."""
    if not get_settings().smtp_host:
        raise RuntimeError("E-mail is not set up: add SMTP_HOST, SMTP_USER and SMTP_PASSWORD to the server .env")
    try:
        _deliver(_message(to, subject, body, attachment))
    except (OSError, smtplib.SMTPException) as e:
        raise RuntimeError(f"Could not send e-mail: {e}") from e


def send_email(to: list[str], subject: str, body: str) -> None:
    """Fire-and-forget notification e-mail (never raises)."""
    if not get_settings().smtp_host or not to:
        return

    def _send():
        try:
            _deliver(_message(to, subject, body, None))
        except Exception:
            log.exception("Failed to send e-mail")

    threading.Thread(target=_send, daemon=True).start()
