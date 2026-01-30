from googleapiclient.discovery import build
from typing import List, Dict
from datetime import datetime, timedelta
import base64
import re


def classify_bounce_type(bounce_body: str) -> str:
    """
    Classify bounce as 'hard' or 'soft' based on bounce message.
    Returns 'hard' for permanent failures, 'soft' for temporary.
    """
    hard_indicators = [
        "user unknown",
        "mailbox not found",
        "no such user",
        "address rejected",
        "invalid recipient",
        "permanent failure",
        "550",
        "551",
    ]
    
    soft_indicators = [
        "mailbox full",
        "quota exceeded",
        "temporary failure",
        "try again later",
        "451",
        "452",
    ]
    
    body_lower = bounce_body.lower()
    
    for indicator in hard_indicators:
        if indicator in body_lower:
            return "hard"
    
    for indicator in soft_indicators:
        if indicator in body_lower:
            return "soft"
    
    # Default to hard if unclear (safer)
    return "hard"


def get_bounced_emails(service, days=1) -> List[Dict[str, str]]:
    """
    Find bounced emails in last `days` days.
    Returns list of dicts with 'email' and 'bounce_type'.
    """
    query = f"subject:('Delivery Status Notification' OR 'Mail Delivery Subsystem') newer_than:{days}d"
    results = service.users().messages().list(userId='me', q=query).execute()
    messages = results.get('messages', [])

    bounced_emails = []
    for msg in messages:
        # Fetch full message
        txt = service.users().messages().get(userId='me', id=msg['id']).execute()
        # Extract bounced email (simplified — you can parse headers/body)
        # In real use: parse "Final-Recipient" from body
        # For MVP: just log message ID or use regex
        payload = txt.get('payload', {})
        bounce_body = ""
        
        for part in payload.get('parts', [payload]):
            body = part.get('body', {}).get('data', '')
            if body:
                decoded = base64.urlsafe_b64decode(body).decode('utf-8', errors='ignore')
                bounce_body += decoded
                # Look for pattern: "Final-Recipient: rfc822;user@domain.com"
                match = re.search(r'Final-Recipient: rfc822;([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', decoded)
                if match:
                    email = match.group(1).lower()
                    bounce_type = classify_bounce_type(bounce_body)
                    bounced_emails.append({
                        "email": email,
                        "bounce_type": bounce_type,
                        "message_id": msg['id'],
                    })
    
    return bounced_emails


def process_bounces(service, days=1) -> int:
    """
    Process bounces: detect, store in database, and update blocking status.
    Returns number of bounces processed.
    """
    bounced_emails = get_bounced_emails(service, days)
    
    if not bounced_emails:
        return 0
    
    try:
        from db.session import SessionLocal
        from db.models import EmailBounce, SentEmail, Lead
        from sqlalchemy import and_
        
        db = SessionLocal()
        try:
            processed_count = 0
            
            for bounce_info in bounced_emails:
                email = bounce_info["email"]
                bounce_type = bounce_info["bounce_type"]
                
                # Find sent email by recipient email
                sent_email = db.query(SentEmail).join(Lead).filter(
                    Lead.email == email
                ).order_by(SentEmail.sent_at.desc()).first()
                
                if sent_email:
                    # Check if bounce already recorded
                    existing = db.query(EmailBounce).filter(
                        EmailBounce.sent_email_id == sent_email.id
                    ).first()
                    
                    if not existing:
                        # Record bounce
                        bounce = EmailBounce(
                            sent_email_id=sent_email.id,
                            bounce_type=bounce_type,
                            detected_at=datetime.utcnow(),
                        )
                        db.add(bounce)
                        processed_count += 1
                        
                        # Auto-block if hard bounce or multiple bounces
                        lead = sent_email.lead
                        bounce_count = db.query(EmailBounce).join(SentEmail).filter(
                            SentEmail.lead_id == lead.id
                        ).count()
                        
                        if bounce_type == "hard" or bounce_count >= 2:
                            lead.blocked = True
                            lead.blocked_reason = f"{bounce_type} bounce (count: {bounce_count})"
                            
                            # Also suppress domain if multiple bounces
                            if bounce_count >= 3:
                                from db.models import DomainThrottle
                                domain = lead.domain
                                if domain:
                                    throttle = db.query(DomainThrottle).filter(
                                        DomainThrottle.domain == domain
                                    ).order_by(DomainThrottle.date.desc()).first()
                                    
                                    if throttle:
                                        throttle.cooldown_until = datetime.utcnow() + timedelta(days=7)
                                    else:
                                        throttle = DomainThrottle(
                                            domain=domain,
                                            cooldown_until=datetime.utcnow() + timedelta(days=7),
                                        )
                                        db.add(throttle)
            
            db.commit()
            return processed_count
            
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to process bounces: {e}")
            db.rollback()
            return 0
        finally:
            db.close()
    except ImportError:
        # Database not available - return count but don't store
        return len(bounced_emails)


def get_bounce_rate(days=7) -> float:
    """
    Calculate bounce rate for last N days.
    Returns bounce rate as float (0.0 to 1.0).
    """
    try:
        from db.session import SessionLocal
        from db.models import SentEmail, EmailBounce
        from datetime import datetime, timedelta
        
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            total_sent = db.query(SentEmail).filter(
                SentEmail.sent_at >= cutoff,
                SentEmail.sent == True
            ).count()
            
            if total_sent == 0:
                return 0.0
            
            total_bounces = db.query(EmailBounce).join(SentEmail).filter(
                SentEmail.sent_at >= cutoff
            ).count()
            
            return float(total_bounces) / float(total_sent)
        finally:
            db.close()
    except ImportError:
        return 0.0