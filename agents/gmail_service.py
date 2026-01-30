# agents/gmail_service.py
import os
import pickle
from typing import Optional, List, Tuple
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.modify']

def authenticate_gmail():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                # If refresh fails, delete token and re-authenticate
                print(f"⚠️ Token refresh failed: {e}. Re-authenticating...")
                if os.path.exists('token.pickle'):
                    os.remove('token.pickle')
                creds = None
        
        if not creds or not creds.valid:
            if not os.path.exists('client_secret1.json'):
                raise FileNotFoundError(
                    "❌ client_secret1.json not found. "
                    "Please download OAuth credentials from Google Cloud Console and place in project root."
                )
            try:
                flow = InstalledAppFlow.from_client_secrets_file('client_secret1.json', SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                error_msg = str(e)
                if 'invalid_client' in error_msg or 'Unauthorized' in error_msg:
                    raise ValueError(
                        "❌ Gmail OAuth authentication failed: Invalid client credentials.\n"
                        "   This usually means:\n"
                        "   1. Your client_secret1.json file is invalid or expired\n"
                        "   2. The OAuth credentials were revoked\n"
                        "   3. The project credentials don't match\n\n"
                        "   Solution:\n"
                        "   1. Go to Google Cloud Console\n"
                        "   2. Create new OAuth 2.0 credentials\n"
                        "   3. Download and replace client_secret1.json\n"
                        "   4. Delete token.pickle to force re-authentication"
                    )
                raise
        
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('gmail', 'v1', credentials=creds)

# Add to agents/gmail_service.py
import base64
import mimetypes
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from agents.rate_limiter import can_send_email
import time
def send_email(service, to: str, subject: str, body: str, check_rate_limit: bool = True, lead_id: Optional[int] = None, attachments: Optional[List[Tuple[str, bytes]]] = None):
    """
    Send email via Gmail API with rate limiting and deliverability checks.
    attachments: optional list of (filename, raw_bytes) for any file type.
    Returns thread_id if successful, None if failed or rate limited.
    """
    # Deliverability safety checks
    try:
        from agents.deliverability import check_send_decision, log_send_decision, handle_send_error
        
        decision = check_send_decision(lead_id, to, body, db=None)
        
        if not decision["allowed"]:
            # Log blocked decision
            log_send_decision(lead_id, to, "blocked", decision["reason"], email_body=body, db=None)
            print(f"⏸️  Send blocked: {decision['reason']}")
            return None
        
        # Log allowed decision
        log_send_decision(lead_id, to, "allowed", None, db=None)
        
    except ImportError:
        # Deliverability module not available - continue with rate limit only
        pass
    
    # Check rate limit if enabled
    if check_rate_limit:
        can_send, reason = can_send_email()
        if not can_send:
            print(f"⏸️  Rate limited: {reason}")
            return None
    
    if attachments:
        message = MIMEMultipart("mixed")
        message.attach(MIMEText(body, "plain"))
        for filename, data in attachments:
            ctype, _ = mimetypes.guess_type(filename) or ("application/octet-stream", None)
            parts = ctype.split("/", 1) if ctype and "/" in ctype else ["application", "octet-stream"]
            maintype, subtype = parts[0], parts[1] if len(parts) > 1 else "octet-stream"
            part = MIMEBase(maintype, subtype)
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            message.attach(part)
    else:
        message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    create_message = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
    
    try:
        sent = service.users().messages().send(userId="me", body=create_message).execute()
        thread_id = sent['threadId']  # Critical for reply tracking!
        
        # Store in database if available
        _store_sent_email(to, subject, body, thread_id)
        
        return thread_id
    except Exception as e:
        print(f"❌ Failed to send to {to}: {e}")
        
        # Handle error and apply cooldown if needed
        try:
            from agents.deliverability import handle_send_error
            domain = to.split("@")[1] if "@" in to else ""
            handle_send_error(e, domain, db=None)
        except:
            pass
        
        return None


def _store_sent_email(to: str, subject: str, body: str, thread_id: str) -> None:
    """Store sent email in database. Fails silently if unavailable."""
    try:
        from db.session import SessionLocal
        from db.models import SentEmail, Lead
        from datetime import datetime
        
        db = SessionLocal()
        try:
            # Find lead by email
            lead = db.query(Lead).filter(Lead.email == to).order_by(Lead.timestamp.desc()).first()
            
            if lead:
                sent_email = SentEmail(
                    lead_id=lead.id,
                    thread_id=thread_id,
                    subject=subject,
                    body=body,
                    sent=True,
                    sent_at=datetime.utcnow(),
                )
                db.add(sent_email)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except ImportError:
        # Database not available - silently fail (CSV still works)
        pass