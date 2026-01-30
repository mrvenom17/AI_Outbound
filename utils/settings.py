# utils/settings.py
"""
Settings management utility - reads/writes settings from database
"""
from typing import Any, Optional
import json

def get_setting(key: str, default: Any = None, db=None) -> Any:
    """
    Get a setting value from database.
    If db is None, creates a new session.
    """
    try:
        from db.session import SessionLocal
        from db.models import SystemSettings
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
            
            if setting:
                value_type = setting.value_type or "string"
                
                if value_type == "int":
                    return int(setting.value) if setting.value else default
                elif value_type == "float":
                    return float(setting.value) if setting.value else default
                elif value_type == "bool":
                    return setting.value.lower() in ("true", "1", "yes") if setting.value else default
                elif value_type == "json":
                    return json.loads(setting.value) if setting.value else default
                else:
                    return setting.value if setting.value else default
            else:
                return default
        finally:
            if should_close:
                db.close()
    except ImportError:
        return default
    except Exception:
        return default


def set_setting(key: str, value: Any, value_type: str = "string", description: str = "", db=None) -> bool:
    """
    Set a setting value in database.
    Returns True if successful, False otherwise.
    """
    try:
        from db.session import SessionLocal
        from db.models import SystemSettings
        from datetime import datetime
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            # Convert value to string based on type
            if value_type == "json":
                value_str = json.dumps(value)
            else:
                value_str = str(value)
            
            setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
            
            if setting:
                setting.value = value_str
                setting.value_type = value_type
                if description:
                    setting.description = description
                setting.updated_at = datetime.utcnow()
            else:
                setting = SystemSettings(
                    key=key,
                    value=value_str,
                    value_type=value_type,
                    description=description,
                )
                db.add(setting)
            
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            return False
        finally:
            if should_close:
                db.close()
    except ImportError:
        return False
    except Exception:
        return False


# Default settings
DEFAULT_SETTINGS = {
    "email_delay_seconds": {"value": 0.5, "type": "float", "description": "Delay between emails (seconds)"},
    "rate_limit_emails_per_hour": {"value": 10, "type": "int", "description": "Maximum emails per hour"},
    "rate_limit_emails_per_day": {"value": 10, "type": "int", "description": "Maximum emails per day"},
    "domain_throttle_max_per_day": {"value": 3, "type": "int", "description": "Maximum emails per domain per day"},
    "require_valid_email": {"value": True, "type": "bool", "description": "Only send to validated emails"},
    "enable_rate_limiting": {"value": True, "type": "bool", "description": "Enable rate limiting"},
    "enable_bounce_checking": {"value": True, "type": "bool", "description": "Enable automatic bounce checking"},
    "bounce_check_interval_hours": {"value": 24, "type": "int", "description": "Bounce check interval (hours)"},
    "max_companies_per_scrape": {"value": 20, "type": "int", "description": "Maximum companies to scrape per run"},
    "max_people_per_company": {"value": 3, "type": "int", "description": "Maximum people per company"},
    "scraping_enrichment_level": {"value": "deep", "type": "string", "description": "Scraping enrichment level: basic, standard, deep"},
    "email_personalization_level": {"value": "high", "type": "string", "description": "Email personalization level: low, medium, high"},
    "include_company_news": {"value": True, "type": "bool", "description": "Include recent company news in email personalization"},
    "include_funding_info": {"value": True, "type": "bool", "description": "Include funding information in personalization"},
    "include_recent_hires": {"value": True, "type": "bool", "description": "Include recent hires/updates in personalization"},
    # Mail Critic (pre-send quality check)
    "enable_mail_critic": {"value": True, "type": "bool", "description": "Enable critic to check emails before send; rewrite if not up to mark"},
    "critic_min_score": {"value": 0.7, "type": "float", "description": "Minimum score (0-1) for email to pass critic without rewrite"},
    "critic_max_rewrites": {"value": 2, "type": "int", "description": "Maximum rewrite attempts if critic rejects the email"},
    "critic_strictness": {"value": "medium", "type": "string", "description": "Critic strictness: low, medium, high"},
    # SMTP rotation
    "use_smtp_servers": {"value": False, "type": "bool", "description": "Use SMTP servers (from SMTP Servers page) instead of Gmail to send emails"},
    "smtp_rotation_strategy": {"value": "round_robin", "type": "string", "description": "SMTP rotation: round_robin, random, least_used"},
}


def initialize_default_settings(db=None):
    """Initialize default settings if they don't exist"""
    for key, config in DEFAULT_SETTINGS.items():
        current = get_setting(key, db=db)
        if current is None:
            set_setting(
                key,
                config["value"],
                config["type"],
                config["description"],
                db=db
            )
