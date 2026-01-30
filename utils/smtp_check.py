import dns.resolver
import smtplib
import socket
from typing import Dict

def validate_email(email: str) -> Dict[str, any]:
    if not email or "@" not in email:
        return {"status": "invalid", "confidence": 0.0}

    local, domain = email.split("@", 1)

    # STEP 1 — MX Lookup
    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_record = answers[0]                          # <- concrete record
        mx_host = mx_record.exchange.to_text().rstrip(".")  # Pylance-clean way
    except Exception:
        return {"status": "unknown", "confidence": 0.5}

    # STEP 2 — SMTP handshake
    try:
        server = smtplib.SMTP(mx_host, 25, timeout=10)
        server.ehlo_or_helo_if_needed()

        if server.has_extn("STARTTLS"):
            server.starttls()
            server.ehlo()

        server.mail("verify@lead-scraper.dev")
        code, _ = server.rcpt(email)
        server.quit()

        if code in (250, 251, 252):
            return {"status": "valid", "confidence": 0.9}
        if code >= 500:
            return {"status": "invalid", "confidence": 0.0}

        return {"status": "unknown", "confidence": 0.5}

    except smtplib.SMTPRecipientsRefused:
        return {"status": "invalid", "confidence": 0.0}
    except (smtplib.SMTPConnectError, socket.timeout, OSError, ConnectionResetError):
        return {"status": "unknown", "confidence": 0.5}
    except Exception:
        return {"status": "unknown", "confidence": 0.5}
