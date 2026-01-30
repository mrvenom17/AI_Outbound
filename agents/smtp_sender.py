# agents/smtp_sender.py
"""
SMTP sending with server rotation (round_robin, random, least_used).
Use send_email_dispatch() to send via SMTP (when configured) or Gmail API.
"""
import smtplib
import random
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from typing import Optional, Any, List, Tuple

from db.models import SmtpServer


def get_active_smtp_servers(db=None):
    """Return list of active SMTP servers, ordered by priority desc then id."""
    if db is None:
        try:
            from db.session import SessionLocal
            db = SessionLocal()
            try:
                servers = (
                    db.query(SmtpServer)
                    .filter(SmtpServer.is_active == True)
                    .order_by(SmtpServer.priority.desc(), SmtpServer.id)
                    .all()
                )
                return servers
            finally:
                db.close()
        except Exception:
            return []
    servers = (
        db.query(SmtpServer)
        .filter(SmtpServer.is_active == True)
        .order_by(SmtpServer.priority.desc(), SmtpServer.id)
        .all()
    )
    return servers


def get_next_smtp_server(db=None, strategy: str = "round_robin"):
    """
    Pick next SMTP server based on rotation strategy.
    Strategies: round_robin, random, least_used.
    Returns SmtpServer or None if no active servers.
    """
    servers = get_active_smtp_servers(db)
    if not servers:
        return None
    if strategy == "random":
        return random.choice(servers)
    if strategy == "least_used":
        return min(servers, key=lambda s: (s.emails_sent or 0, (s.last_used_at or datetime.min).isoformat()))
    # round_robin: use server with oldest last_used_at (or any if never used)
    return min(servers, key=lambda s: (s.last_used_at or datetime.min).isoformat())


# Connection timeout (seconds); increase for slow/hosted SMTP
SMTP_TIMEOUT = 60
SMTP_MAX_RETRIES = 2


def send_email_smtp(
    server: SmtpServer,
    to: str,
    subject: str,
    body: str,
    db=None,
    update_usage: bool = True,
    timeout: int = SMTP_TIMEOUT,
    attachments: Optional[List[Tuple[str, bytes]]] = None,
) -> Optional[str]:
    """
    Send one email via the given SMTP server.
    attachments: optional list of (filename, raw_bytes) for any file type.
    Returns a message_id-like string on success (for logging), None on failure.
    """
    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(body, "plain"))
        for filename, data in attachments:
            ctype, _ = mimetypes.guess_type(filename) or ("application", "octet-stream")
            maintype, subtype = ctype.split("/", 1) if "/" in ctype else ("application", "octet-stream")
            part = MIMEBase(maintype, subtype)
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
    else:
        msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = f"{server.from_name} <{server.from_email}>" if server.from_name else server.from_email
    msg["To"] = to

    port = server.port or 587
    use_ssl = getattr(server, "use_ssl", None) or (port == 465)
    last_error = None
    for attempt in range(SMTP_MAX_RETRIES):
        try:
            if use_ssl or port == 465:
                smtp = smtplib.SMTP_SSL(server.host, port, timeout=timeout)
            else:
                smtp = smtplib.SMTP(server.host, port, timeout=timeout)
                if getattr(server, "use_tls", True):
                    smtp.starttls()
            smtp.login(server.username, server.password)
            smtp.sendmail(server.from_email, [to], msg.as_string())
            smtp.quit()
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt < SMTP_MAX_RETRIES - 1:
                import time
                time.sleep(2)
                continue
            # Raise so callers (UI / CLI) can show the actual error to the user
            raise RuntimeError(f"SMTP send failed ({server.host}:{port}): {last_error}") from last_error

    if last_error is not None:
        return None

    # Update usage in DB
    if update_usage and db is not None:
        try:
            s = db.query(SmtpServer).filter(SmtpServer.id == server.id).first()
            if s:
                s.emails_sent = (s.emails_sent or 0) + 1
                s.last_used_at = datetime.utcnow()
                db.commit()
        except Exception:
            if db:
                db.rollback()

    return f"smtp-{server.id}-{datetime.utcnow().isoformat()}"


def send_email_dispatch(
    to: str,
    subject: str,
    body: str,
    check_rate_limit: bool = True,
    lead_id: Optional[int] = None,
    db=None,
    attachments: Optional[List[Tuple[str, bytes]]] = None,
):
    """
    Send email using SMTP (with rotation) or Gmail API based on settings.
    attachments: optional list of (filename, raw_bytes) for any file type.
    Returns thread_id or message_id string on success, None on failure.
    """
    from utils.settings import get_setting

    use_smtp = get_setting("use_smtp_servers", False, db=db)
    if use_smtp:
        servers = get_active_smtp_servers(db)
        if servers:
            strategy = get_setting("smtp_rotation_strategy", "round_robin", db=db) or "round_robin"
            server = get_next_smtp_server(db=db, strategy=strategy)
            if server:
                # Deliverability checks (same as Gmail path)
                try:
                    from agents.deliverability import check_send_decision, log_send_decision
                    decision = check_send_decision(lead_id, to, body, db=db)
                    if not decision["allowed"]:
                        log_send_decision(lead_id, to, "blocked", decision["reason"], email_body=body, db=db)
                        return None
                    log_send_decision(lead_id, to, "allowed", None, db=db)
                except ImportError:
                    pass
                if check_rate_limit:
                    from agents.rate_limiter import can_send_email
                    can_send, reason = can_send_email()
                    if not can_send:
                        return None
                msg_id = send_email_smtp(server, to, subject, body, db=db, attachments=attachments)
                if msg_id:
                    from agents.gmail_service import _store_sent_email
                    _store_sent_email(to, subject, body, msg_id)
                return msg_id
    # Fallback to Gmail
    from agents.gmail_service import authenticate_gmail, send_email
    try:
        service = authenticate_gmail()
        return send_email(service, to, subject, body, check_rate_limit=check_rate_limit, lead_id=lead_id, attachments=attachments)
    except Exception as e:
        print(f"❌ Gmail send failed: {e}")
        return None
