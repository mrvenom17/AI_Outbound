# agents/imap_inbox.py
"""
Fetch sent and received emails via IMAP for an email server (SmtpServer with imap_host set).
"""
import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Any, Optional
from datetime import datetime

from db.models import SmtpServer

# Folder names vary by provider
SENT_FOLDER_NAMES = ("Sent", "Sent Items", "Sent Mail", "[Gmail]/Sent Mail", "INBOX.Sent")
INBOX_FOLDER = "INBOX"
DEFAULT_LIMIT = 100
IMAP_TIMEOUT = 30


def _decode_mime_header(s: Optional[str]) -> str:
    if not s:
        return ""
    try:
        parts = decode_header(s)
        out = []
        for part, enc in parts:
            if isinstance(part, bytes):
                out.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(part or "")
        return " ".join(out).strip()
    except Exception:
        return str(s) if s else ""


def _get_body_preview(msg: email.message.Message, max_len: int = 200) -> str:
    """Extract plain-text body preview."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="replace").strip()
                        break
                except Exception:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="replace").strip()
        except Exception:
            pass
    if len(body) > max_len:
        body = body[:max_len] + "..."
    return body.replace("\n", " ").strip()


def _parse_email(msg: email.message.Message, uid: int) -> Dict[str, Any]:
    subject = _decode_mime_header(msg.get("Subject"))
    from_ = _decode_mime_header(msg.get("From"))
    to_ = _decode_mime_header(msg.get("To"))
    date_str = msg.get("Date")
    try:
        if date_str:
            date_tuple = email.utils.parsedate_tz(date_str)
            if date_tuple:
                from time import mktime
                ts = email.utils.mktime_tz(date_tuple)
                dt = datetime.utcfromtimestamp(ts)
            else:
                dt = datetime.utcnow()
        else:
            dt = datetime.utcnow()
    except Exception:
        dt = datetime.utcnow()
    body_preview = _get_body_preview(msg)
    return {
        "uid": uid,
        "subject": subject,
        "from_": from_,
        "to": to_,
        "date": dt,
        "date_str": date_str or "",
        "snippet": body_preview,
        "raw_message": msg,
    }


def _list_folders(imap: imaplib.IMAP4) -> List[str]:
    try:
        status, lines = imap.list()
        if status != "OK" or not lines:
            return []
        folders = []
        for line in lines:
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            # Parse "(\HasNoChildren) \"/\" \"INBOX\""
            parts = line.split('"')
            if len(parts) >= 3:
                folders.append(parts[-2].strip())
        return folders
    except Exception:
        return []


def _find_sent_folder(imap: imaplib.IMAP4) -> Optional[str]:
    folders = _list_folders(imap)
    for name in SENT_FOLDER_NAMES:
        if name in folders:
            return name
    for f in folders:
        if "sent" in f.lower():
            return f
    return None


def fetch_inbox_emails(
    server: SmtpServer,
    folder: str = INBOX_FOLDER,
    limit: int = DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """
    Fetch emails from the given IMAP folder (e.g. INBOX or Sent).
    server must have imap_host set; uses server username/password.
    Returns list of dicts: uid, subject, from_, to, date, date_str, snippet.
    """
    imap_host = getattr(server, "imap_host", None) or (server.host if "imap" in server.host.lower() else None)
    if not imap_host:
        # Try common pattern: smtp.example.com -> imap.example.com
        imap_host = server.host.replace("smtp.", "imap.", 1)
    port = getattr(server, "imap_port", None) or 993
    use_ssl = getattr(server, "imap_use_ssl", True)

    try:
        if use_ssl:
            imap = imaplib.IMAP4_SSL(imap_host, port, timeout=IMAP_TIMEOUT)
        else:
            imap = imaplib.IMAP4(imap_host, port, timeout=IMAP_TIMEOUT)
        imap.login(server.username, server.password)
    except Exception as e:
        raise RuntimeError(f"IMAP login failed ({imap_host}): {e}") from e

    result = []
    try:
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            imap.logout()
            return result
        status, data = imap.search(None, "ALL")
        if status != "OK" or not data:
            imap.logout()
            return result
        uids = data[0].split()
        uids = list(reversed(uids))[:limit]  # Newest first
        for uid_bytes in uids:
            try:
                status, msg_data = imap.fetch(uid_bytes, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                uid = int(uid_bytes.decode() if isinstance(uid_bytes, bytes) else uid_bytes)
                raw = msg_data[0]
                if isinstance(raw, tuple):
                    raw = raw[1]
                if isinstance(raw, bytes):
                    msg = email.message_from_bytes(raw)
                else:
                    msg = email.message_from_string(raw)
                result.append(_parse_email(msg, uid))
            except Exception:
                continue
    finally:
        try:
            imap.close()
            imap.logout()
        except Exception:
            pass
    return result


def fetch_received(server: SmtpServer, limit: int = DEFAULT_LIMIT) -> List[Dict[str, Any]]:
    """Fetch received emails (INBOX)."""
    return fetch_inbox_emails(server, folder=INBOX_FOLDER, limit=limit)


def fetch_sent(server: SmtpServer, limit: int = DEFAULT_LIMIT) -> List[Dict[str, Any]]:
    """Fetch sent emails. Tries common Sent folder names."""
    imap_host = getattr(server, "imap_host", None) or server.host.replace("smtp.", "imap.", 1)
    port = getattr(server, "imap_port", None) or 993
    use_ssl = getattr(server, "imap_use_ssl", True)
    try:
        if use_ssl:
            imap = imaplib.IMAP4_SSL(imap_host, port, timeout=IMAP_TIMEOUT)
        else:
            imap = imaplib.IMAP4(imap_host, port, timeout=IMAP_TIMEOUT)
        imap.login(server.username, server.password)
    except Exception as e:
        raise RuntimeError(f"IMAP login failed ({imap_host}): {e}") from e
    sent_folder = _find_sent_folder(imap)
    try:
        imap.logout()
    except Exception:
        pass
    if not sent_folder:
        return []
    return fetch_inbox_emails(server, folder=sent_folder, limit=limit)
