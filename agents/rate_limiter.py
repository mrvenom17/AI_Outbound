# agents/rate_limiter.py
from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy import func

def get_current_rate_limit() -> tuple[int, int]:
    """
    Get current rate limits (emails_per_hour, emails_per_day).
    Uses SystemSettings (Settings page) when set; otherwise SendMetric or defaults.
    
    Fails silently and returns defaults if database unavailable.
    """
    # Prefer user-configured limits from Settings page
    try:
        from utils.settings import get_setting
        hour = get_setting("rate_limit_emails_per_hour", None)
        day = get_setting("rate_limit_emails_per_day", None)
        if hour is not None and day is not None:
            try:
                return (int(hour), int(day))
            except (TypeError, ValueError):
                pass
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: SendMetric (adaptive/warm-up) or defaults
    try:
        from db.session import SessionLocal
        from db.models import SendMetric
        
        db = SessionLocal()
        try:
            latest = db.query(SendMetric).order_by(SendMetric.date.desc()).first()
            if latest:
                return (latest.emails_per_hour, latest.emails_per_day)
            return (10, 10)
        finally:
            db.close()
    except ImportError:
        return (10, 10)
    except Exception:
        return (10, 10)


def check_rate_limit() -> bool:
    """
    Check if we can send an email now based on rate limits.
    Returns True if allowed, False if rate limited.
    
    This is a simple check - actual enforcement happens in can_send_email().
    """
    hourly_limit, daily_limit = get_current_rate_limit()
    
    try:
        from db.session import SessionLocal
        from db.models import SentEmail
        
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            one_hour_ago = now - timedelta(hours=1)
            one_day_ago = now - timedelta(days=1)
            
            # Count emails sent in last hour
            hourly_count = db.query(SentEmail).filter(
                SentEmail.sent_at >= one_hour_ago,
                SentEmail.sent == True
            ).count()
            
            # Count emails sent in last day
            daily_count = db.query(SentEmail).filter(
                SentEmail.sent_at >= one_day_ago,
                SentEmail.sent == True
            ).count()
            
            return hourly_count < hourly_limit and daily_count < daily_limit
        finally:
            db.close()
    except ImportError:
        # Database not available - allow sending (fallback to CSV-only mode)
        return True


def can_send_email() -> tuple[bool, Optional[str]]:
    """
    Check if email can be sent now.
    Returns (can_send: bool, reason: Optional[str]).
    Respects Settings: enable_rate_limiting and rate_limit_emails_per_hour/day.
    """
    try:
        from utils.settings import get_setting
        if not get_setting("enable_rate_limiting", True):
            return (True, None)  # Rate limiting disabled in Settings
    except ImportError:
        pass
    except Exception:
        pass

    if not check_rate_limit():
        hourly_limit, daily_limit = get_current_rate_limit()
        return (False, f"Rate limit exceeded: {hourly_limit}/hour, {daily_limit}/day")
    
    return (True, None)


def update_rate_limits(bounce_rate: float) -> None:
    """
    Update rate limits based on bounce rate.
    Implements warm-up logic and adaptive rate limiting.
    
    Fails silently if database unavailable.
    """
    try:
        from db.session import SessionLocal
        from db.models import SendMetric
        from datetime import datetime
        
        db = SessionLocal()
        try:
            latest = db.query(SendMetric).order_by(SendMetric.date.desc()).first()
            
            if not latest:
                # First metric - start warm-up
                new_metric = SendMetric(
                    date=datetime.utcnow(),
                    emails_sent=0,
                    emails_per_hour=10,
                    emails_per_day=10,
                    bounce_rate=0.0,
                )
                db.add(new_metric)
            else:
                # Calculate new limits based on bounce rate
                new_hourly = latest.emails_per_hour
                new_daily = latest.emails_per_day
                
                if bounce_rate > 0.05:  # 5% bounce rate threshold
                    # Decrease by 50%
                    new_hourly = max(5, int(new_hourly * 0.5))
                    new_daily = max(5, int(new_daily * 0.5))
                else:
                    # Warm-up: increase by 5 per day (max 100/day)
                    new_daily = min(100, new_daily + 5)
                    # Hourly limit is 1/8 of daily (assuming 8-hour workday)
                    new_hourly = min(12, int(new_daily / 8))
                
                new_metric = SendMetric(
                    date=datetime.utcnow(),
                    emails_sent=0,
                    emails_per_hour=new_hourly,
                    emails_per_day=new_daily,
                    bounce_rate=bounce_rate,
                )
                db.add(new_metric)
            
            db.commit()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to update rate limits: {e}")
            db.rollback()
        finally:
            db.close()
    except ImportError:
        # Database not available - silently fail
        pass
