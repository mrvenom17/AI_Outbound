# api/routes/dashboard.py
from typing import List, Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from pydantic import BaseModel
from datetime import datetime, timedelta

from db.session import get_db
from db.models import (
    Campaign, Company, Person, Lead, SentEmail, EmailBounce,
    AIDecision, SendMetric, EmailValidation, EmailCandidate
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


class CampaignOverview(BaseModel):
    campaign_id: int
    campaign_name: str
    leads_discovered: int
    emails_sent: int
    bounce_rate: float


@router.get("/campaigns/overview", response_model=List[CampaignOverview])
def campaign_overview(db: Session = Depends(get_db)):
    """
    Campaign Overview - shows active campaigns with metrics.
    """
    campaigns = db.query(Campaign).all()
    results = []
    
    for campaign in campaigns:
        # Count leads discovered (via companies -> people -> leads)
        leads_count = db.query(Lead).join(Person).join(Company).filter(
            Company.campaign_id == campaign.id
        ).count()
        
        # Count emails sent
        emails_sent = db.query(SentEmail).join(Lead).join(Person).join(Company).filter(
            Company.campaign_id == campaign.id,
            SentEmail.sent == True
        ).count()
        
        # Calculate bounce rate
        total_sent = emails_sent
        bounces = db.query(EmailBounce).join(SentEmail).join(Lead).join(Person).join(Company).filter(
            Company.campaign_id == campaign.id
        ).count()
        
        bounce_rate = float(bounces) / float(total_sent) if total_sent > 0 else 0.0
        
        results.append(CampaignOverview(
            campaign_id=campaign.id,
            campaign_name=campaign.name,
            leads_discovered=leads_count,
            emails_sent=emails_sent,
            bounce_rate=bounce_rate,
        ))
    
    return results


class LeadPipelineStats(BaseModel):
    total_leads: int
    by_status: Dict[str, int]
    by_confidence_range: Dict[str, int]
    email_patterns: Dict[str, int]


@router.get("/leads/pipeline", response_model=LeadPipelineStats)
def lead_pipeline(db: Session = Depends(get_db)):
    """
    Lead Pipeline - shows leads by validation status, confidence, patterns.
    """
    total_leads = db.query(Lead).count()
    
    # By validation status
    status_counts = db.query(
        Lead.validation_status,
        func.count(Lead.id)
    ).group_by(Lead.validation_status).all()
    by_status = {status or "unknown": count for status, count in status_counts}
    
    # By confidence range
    confidence_ranges = {
        "high": db.query(Lead).filter(Lead.confidence >= 0.8).count(),
        "medium": db.query(Lead).filter(
            and_(Lead.confidence >= 0.5, Lead.confidence < 0.8)
        ).count(),
        "low": db.query(Lead).filter(Lead.confidence < 0.5).count(),
    }
    
    # Email patterns used
    pattern_counts = db.query(
        EmailCandidate.pattern,
        func.count(EmailCandidate.id)
    ).group_by(EmailCandidate.pattern).all()
    email_patterns = {pattern or "unknown": count for pattern, count in pattern_counts}
    
    return LeadPipelineStats(
        total_leads=total_leads,
        by_status=by_status,
        by_confidence_range=confidence_ranges,
        email_patterns=email_patterns,
    )


class EmailPerformanceStats(BaseModel):
    sent_today: int
    sent_this_week: int
    bounce_rate: float
    reply_rate: float
    current_rate_limit: Dict[str, int]


@router.get("/emails/performance", response_model=EmailPerformanceStats)
def email_performance(db: Session = Depends(get_db)):
    """
    Email Performance - shows send stats, bounce rate, reply rate, rate limits.
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    
    sent_today = db.query(SentEmail).filter(
        SentEmail.sent_at >= today_start,
        SentEmail.sent == True
    ).count()
    
    sent_this_week = db.query(SentEmail).filter(
        SentEmail.sent_at >= week_start,
        SentEmail.sent == True
    ).count()
    
    # Bounce rate (last 7 days)
    total_sent_week = sent_this_week
    bounces_week = db.query(EmailBounce).join(SentEmail).filter(
        SentEmail.sent_at >= week_start
    ).count()
    bounce_rate = float(bounces_week) / float(total_sent_week) if total_sent_week > 0 else 0.0
    
    # Reply rate (placeholder - requires email_replies table which we haven't implemented yet)
    reply_rate = 0.0  # UNKNOWN - REQUIRES NEW COMPONENT (email_replies table)
    
    # Current rate limits
    latest_metric = db.query(SendMetric).order_by(SendMetric.date.desc()).first()
    current_rate_limit = {
        "emails_per_hour": latest_metric.emails_per_hour if latest_metric else 10,
        "emails_per_day": latest_metric.emails_per_day if latest_metric else 10,
    }
    
    return EmailPerformanceStats(
        sent_today=sent_today,
        sent_this_week=sent_this_week,
        bounce_rate=bounce_rate,
        reply_rate=reply_rate,
        current_rate_limit=current_rate_limit,
    )


class AIDecisionItem(BaseModel):
    id: int
    decision_type: str
    model: str
    created_at: str
    input_summary: Dict[str, Any]
    output_preview: str


@router.get("/ai/decisions", response_model=List[AIDecisionItem])
def ai_decisions(limit: int = 50, db: Session = Depends(get_db)):
    """
    AI Decision Audit - shows recent LLM decisions with evidence.
    """
    decisions = db.query(AIDecision).order_by(
        AIDecision.created_at.desc()
    ).limit(limit).all()
    
    results = []
    for decision in decisions:
        output_preview = decision.output[:200] if decision.output else ""
        if len(decision.output or "") > 200:
            output_preview += "..."
        
        results.append(AIDecisionItem(
            id=decision.id,
            decision_type=decision.decision_type,
            model=decision.model,
            created_at=decision.created_at.isoformat(),
            input_summary=decision.input_evidence or {},
            output_preview=output_preview,
        ))
    
    return results


class DeliverabilityStatus(BaseModel):
    current_send_rate: Dict[str, int]
    bounce_rate_trend: List[Dict[str, Any]]
    blocked_emails: int
    blocked_domains: int
    warmup_progress: Dict[str, Any]


@router.get("/deliverability/status", response_model=DeliverabilityStatus)
def deliverability_status(days: int = 7, db: Session = Depends(get_db)):
    """
    Deliverability Status - shows rate limits, bounce trends, blocking status.
    """
    # Current send rate
    latest_metric = db.query(SendMetric).order_by(SendMetric.date.desc()).first()
    current_send_rate = {
        "emails_per_hour": latest_metric.emails_per_hour if latest_metric else 10,
        "emails_per_day": latest_metric.emails_per_day if latest_metric else 10,
    }
    
    # Bounce rate trend (last N days)
    cutoff = datetime.utcnow() - timedelta(days=days)
    daily_bounces = db.query(
        func.date(SentEmail.sent_at).label("date"),
        func.count(EmailBounce.id).label("bounce_count"),
        func.count(SentEmail.id).label("sent_count"),
    ).join(EmailBounce, SentEmail.id == EmailBounce.sent_email_id, isouter=True).filter(
        SentEmail.sent_at >= cutoff
    ).group_by(func.date(SentEmail.sent_at)).all()
    
    bounce_rate_trend = [
        {
            "date": date.isoformat(),
            "bounce_count": bounce_count,
            "sent_count": sent_count,
            "bounce_rate": float(bounce_count) / float(sent_count) if sent_count > 0 else 0.0,
        }
        for date, bounce_count, sent_count in daily_bounces
    ]
    
    # Blocked emails/domains
    blocked_emails = db.query(Lead).filter(Lead.blocked == True).count()
    blocked_domains = db.query(func.count(func.distinct(Lead.domain))).filter(
        Lead.blocked == True
    ).scalar() or 0
    
    # Warm-up progress (days since first send, current limit)
    first_send = db.query(func.min(SentEmail.sent_at)).filter(
        SentEmail.sent == True
    ).scalar()
    
    if first_send:
        days_since_first = (datetime.utcnow() - first_send).days
    else:
        days_since_first = 0
    
    warmup_progress = {
        "days_since_first_send": days_since_first,
        "current_daily_limit": current_send_rate["emails_per_day"],
        "warmup_complete": current_send_rate["emails_per_day"] >= 100,
    }
    
    return DeliverabilityStatus(
        current_send_rate=current_send_rate,
        bounce_rate_trend=bounce_rate_trend,
        blocked_emails=blocked_emails,
        blocked_domains=blocked_domains,
        warmup_progress=warmup_progress,
    )


@router.get("/leads/{lead_id}/validation")
def lead_validation_details(lead_id: int, db: Session = Depends(get_db)):
    """
    Get validation details for a specific lead (why email was chosen).
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        return {"error": "Lead not found"}
    
    # Find email candidate and validations
    person = lead.person
    email_candidates = db.query(EmailCandidate).filter(
        EmailCandidate.person_id == person.id
    ).all()
    
    validations = []
    for candidate in email_candidates:
        if candidate.email == lead.email:
            candidate_validations = db.query(EmailValidation).filter(
                EmailValidation.email_candidate_id == candidate.id
            ).all()
            for val in candidate_validations:
                validations.append({
                    "email": candidate.email,
                    "pattern": candidate.pattern,
                    "smtp_status": val.smtp_status,
                    "smtp_confidence": val.smtp_confidence,
                    "hunter_result": val.hunter_result,
                    "hunter_score": val.hunter_score,
                    "hunter_ok": val.hunter_ok,
                })
    
    return {
        "lead_id": lead_id,
        "chosen_email": lead.email,
        "validation_status": lead.validation_status,
        "confidence": lead.confidence,
        "validations": validations,
    }