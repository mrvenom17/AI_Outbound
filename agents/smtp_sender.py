# agents/smtp_sender.py
"""
SMTP sending with server rotation (round_robin, random, least_used).
Use send_email_dispatch() to send via SMTP (when configured) or Gmail API.
"""
import smtplib
import random
from email.mime.text import MIMEText
from datetime import datetime
from typing import Optional, Any

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


def send_email_smtp(
    server: SmtpServer,
    to: str,
    subject: str,
    body: str,
    db=None,
    update_usage: bool = True,
) -> Optional[str]:
    """
    Send one email via the given SMTP server.
    Returns a message_id-like string on success (for logging), None on failure.
    If update_usage is True, increments emails_sent and last_used_at on server.
    """
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = f"{server.from_name} <{server.from_email}>" if server.from_name else server.from_email
    msg["To"] = to

    try:
        if server.use_tls:
            smtp = smtplib.SMTP(server.host, server.port, timeout=30)
            smtp.starttls()
        else:
            smtp = smtplib.SMTP(server.host, server.port, timeout=30)
        smtp.login(server.username, server.password)
        smtp.sendmail(server.from_email, [to], msg.as_string())
        smtp.quit()
    except Exception as e:
        print(f"❌ SMTP send failed ({server.name}): {e}")
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
):
    """
    Send email using SMTP (with rotation) or Gmail API based on settings.
    - If use_smtp_servers is True and there are active SMTP servers, use SMTP rotation.
    - Otherwise use Gmail API (authenticate_gmail + send_email).
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
                msg_id = send_email_smtp(server, to, subject, body, db=db)
                if msg_id:
                    from agents.gmail_service import _store_sent_email
                    _store_sent_email(to, subject, body, msg_id)
                return msg_id
    # Fallback to Gmail
    from agents.gmail_service import authenticate_gmail, send_email
    try:
        service = authenticate_gmail()
        return send_email(service, to, subject, body, check_rate_limit=check_rate_limit, lead_id=lead_id)
    except Exception as e:
        print(f"❌ Gmail send failed: {e}")
        return None
