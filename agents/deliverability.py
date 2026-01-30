# agents/deliverability.py
"""
Deliverability safety checks - code-enforced protections before sending.
"""
from typing import Tuple, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import func

def check_domain_throttle(domain: str, max_per_day: Optional[int] = None, db=None) -> Tuple[bool, str]:
    """
    Check if domain has exceeded daily send limit.
    Uses Settings domain_throttle_max_per_day when set; otherwise default 3.
    
    Returns:
        (allowed: bool, reason: str)
    """
    if max_per_day is None:
        try:
            from utils.settings import get_setting
            max_per_day = get_setting("domain_throttle_max_per_day", 3)
            if max_per_day is not None:
                max_per_day = int(max_per_day)
            else:
                max_per_day = 3
        except (ImportError, TypeError, ValueError):
            max_per_day = 3
    try:
        from db.session import SessionLocal
        from db.models import DomainThrottle, SentEmail, Lead
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            # Extract domain from email if needed
            if "@" in domain:
                domain = domain.split("@")[1]
            
            domain = domain.lower().strip()
            
            # Check cooldown
            throttle = db.query(DomainThrottle).filter(
                DomainThrottle.domain == domain
            ).order_by(DomainThrottle.date.desc()).first()
            
            if throttle and throttle.cooldown_until:
                if throttle.cooldown_until > datetime.utcnow():
                    return (False, f"Domain {domain} in cooldown until {throttle.cooldown_until}")
            
            # Count sends today
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Count via SentEmail table
            sends_today = db.query(SentEmail).join(Lead).filter(
                Lead.domain == domain,
                SentEmail.sent_at >= today_start,
                SentEmail.sent == True
            ).count()
            
            if sends_today >= max_per_day:
                return (False, f"Domain {domain} has reached daily limit ({max_per_day} emails/day)")
            
            return (True, None)
            
        finally:
            if should_close:
                db.close()
    except ImportError:
        # Database not available - allow (preserve existing behavior)
        return (True, None)
    except Exception:
        return (True, None)  # Fail open to preserve existing behavior


def check_lead_suppression(lead_id: Optional[int], email: str, db=None) -> Tuple[bool, str]:
    """
    Check if lead should be suppressed (blocked, bounced, etc.).
    
    Returns:
        (allowed: bool, reason: str)
    """
    try:
        from db.session import SessionLocal
        from db.models import Lead, EmailBounce, SentEmail
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            # Find lead
            if lead_id:
                lead = db.query(Lead).filter(Lead.id == lead_id).first()
            else:
                lead = db.query(Lead).filter(Lead.email == email).order_by(Lead.timestamp.desc()).first()
            
            if not lead:
                return (True, None)  # Lead not found - allow (might be new)
            
            # Check if blocked
            if lead.blocked:
                return (False, f"Lead {email} is blocked: {lead.blocked_reason or 'Unknown reason'}")
            
            # Check bounce history
            bounce_count = db.query(EmailBounce).join(SentEmail).filter(
                SentEmail.lead_id == lead.id
            ).count()
            
            if bounce_count >= 2:
                return (False, f"Lead {email} has {bounce_count} bounces - auto-suppressed")
            
            # Check for hard bounces
            hard_bounces = db.query(EmailBounce).join(SentEmail).filter(
                SentEmail.lead_id == lead.id,
                EmailBounce.bounce_type == "hard"
            ).count()
            
            if hard_bounces >= 1:
                return (False, f"Lead {email} has hard bounce - suppressed")
            
            return (True, None)
            
        finally:
            if should_close:
                db.close()
    except ImportError:
        return (True, None)
    except Exception:
        return (True, None)


def check_send_decision(
    lead_id: Optional[int],
    email: str,
    email_body: str,
    db=None
) -> Dict[str, Any]:
    """
    Comprehensive send decision check.
    Combines all safety checks.
    
    Returns:
        {
            "allowed": bool,
            "reason": str,
            "checks": {
                "domain_throttle": (bool, str),
                "lead_suppression": (bool, str),
                "rate_limit": (bool, str)
            }
        }
    """
    from agents.rate_limiter import can_send_email
    
    checks = {}
    reasons = []
    
    # Extract domain
    domain = email.split("@")[1] if "@" in email else ""
    
    # Domain throttle check
    domain_ok, domain_reason = check_domain_throttle(domain, max_per_day=None, db=db)
    checks["domain_throttle"] = (domain_ok, domain_reason)
    if not domain_ok:
        reasons.append(domain_reason)
    
    # Lead suppression check
    lead_ok, lead_reason = check_lead_suppression(lead_id, email, db=db)
    checks["lead_suppression"] = (lead_ok, lead_reason)
    if not lead_ok:
        reasons.append(lead_reason)
    
    # Rate limit check
    rate_ok, rate_reason = can_send_email()
    checks["rate_limit"] = (rate_ok, rate_reason)
    if not rate_ok:
        reasons.append(rate_reason)
    
    # Final decision
    allowed = domain_ok and lead_ok and rate_ok
    reason = "; ".join(reasons) if reasons else None
    
    return {
        "allowed": allowed,
        "reason": reason,
        "checks": checks
    }


def log_send_decision(
    lead_id: Optional[int],
    email: str,
    decision: str,
    reason: str,
    email_body: Optional[str] = None,
    db=None
) -> None:
    """
    Log send decision to database for audit trail.
    """
    try:
        from db.session import SessionLocal
        from db.models import SendDecision
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            send_decision = SendDecision(
                lead_id=lead_id,
                email=email,
                decision=decision,  # "allowed", "blocked", "throttled", "suppressed"
                reason=reason,
                email_body=email_body if decision == "blocked" else None,  # Store body if blocked for review
                checked_at=datetime.utcnow(),
            )
            db.add(send_decision)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            if should_close:
                db.close()
    except ImportError:
        pass
    except Exception:
        pass


def handle_send_error(error: Exception, domain: str, db=None) -> None:
    """
    Handle send errors and apply cooldowns.
    """
    try:
        from db.session import SessionLocal
        from db.models import DomainThrottle
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            error_msg = str(error).lower()
            
            # Check if rate limit error
            if "rate limit" in error_msg or "quota" in error_msg:
                # Apply domain cooldown
                throttle = db.query(DomainThrottle).filter(
                    DomainThrottle.domain == domain
                ).order_by(DomainThrottle.date.desc()).first()
                
                if throttle:
                    throttle.cooldown_until = datetime.utcnow() + timedelta(hours=1)
                else:
                    throttle = DomainThrottle(
                        domain=domain,
                        cooldown_until=datetime.utcnow() + timedelta(hours=1),
                    )
                    db.add(throttle)
                
                db.commit()
                
        except Exception:
            db.rollback()
        finally:
            if should_close:
                db.close()
    except ImportError:
        pass
    except Exception:
        pass
