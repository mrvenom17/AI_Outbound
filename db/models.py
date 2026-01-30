# db/models.py
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class Campaign(Base):
    """Campaign entity - replaces query string parameter"""
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    query = Column(String, nullable=False)  # Perplexity query
    offer_description = Column(Text, nullable=True)  # What we're pitching (e.g. "Done-For-You email automation", "Intelpatch product")
    max_companies = Column(Integer, default=20)
    max_people_per_company = Column(Integer, default=3)
    require_valid_email = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    companies = relationship("Company", back_populates="campaign")


class Company(Base):
    """Company records from Perplexity discovery"""
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    company_name = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    linkedin = Column(String, default="")
    hq_country = Column(String, default="")
    funding_stage = Column(String, default="")
    signals = Column(String, default="")
    discovered_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    campaign = relationship("Campaign", back_populates="companies")
    people = relationship("Person", back_populates="company")


class Person(Base):
    """Person records from Perplexity discovery"""
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, default="")
    linkedin_url = Column(String, default="")
    location = Column(String, default="")
    discovered_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="people")
    email_candidates = relationship("EmailCandidate", back_populates="person")
    leads = relationship("Lead", back_populates="person")


class EmailCandidate(Base):
    """Generated email patterns before validation"""
    __tablename__ = "email_candidates"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    email = Column(String, nullable=False)
    pattern = Column(String)  # e.g., "first.last", "first_last"
    generated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    person = relationship("Person", back_populates="email_candidates")
    validations = relationship("EmailValidation", back_populates="email_candidate")


class EmailValidation(Base):
    """SMTP and Hunter validation results"""
    __tablename__ = "email_validations"

    id = Column(Integer, primary_key=True, index=True)
    email_candidate_id = Column(Integer, ForeignKey("email_candidates.id"), nullable=False)
    smtp_status = Column(String)  # "valid", "invalid", "unknown"
    smtp_confidence = Column(Float)
    hunter_result = Column(String)  # "deliverable", "undeliverable", "risky", "unknown"
    hunter_score = Column(Integer)
    hunter_ok = Column(Boolean)
    validated_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    email_candidate = relationship("EmailCandidate", back_populates="validations")


class Lead(Base):
    """Final validated leads - replaces leads.csv"""
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)
    email = Column(String, nullable=False)
    company = Column(String, nullable=False)
    linkedin_url = Column(String, default="")
    role = Column(String, default="")
    domain = Column(String, default="")
    confidence = Column(Float, default=0.5)
    validation_status = Column(String)  # "valid", "unknown", "invalid"
    source_query = Column(String, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)
    blocked = Column(Boolean, default=False)
    blocked_reason = Column(String, default="")

    # Relationships
    person = relationship("Person", back_populates="leads")
    sent_emails = relationship("SentEmail", back_populates="lead")


class SentEmail(Base):
    """Email send records - replaces sent_emails.csv"""
    __tablename__ = "sent_emails"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    thread_id = Column(String)  # Gmail thread ID
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    lead = relationship("Lead", back_populates="sent_emails")
    bounces = relationship("EmailBounce", back_populates="sent_email")


class EmailBounce(Base):
    """Bounce records from Gmail bounce detection"""
    __tablename__ = "email_bounces"

    id = Column(Integer, primary_key=True, index=True)
    sent_email_id = Column(Integer, ForeignKey("sent_emails.id"), nullable=False)
    bounce_type = Column(String)  # "hard", "soft"
    detected_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    sent_email = relationship("SentEmail", back_populates="bounces")


class AIDecision(Base):
    """LLM decision audit trail"""
    __tablename__ = "ai_decisions"

    id = Column(Integer, primary_key=True, index=True)
    decision_type = Column(String, nullable=False)  # "email_generation", "company_discovery", "people_discovery"
    input_evidence = Column(JSON)  # What was passed to LLM
    output = Column(Text)  # LLM response
    model = Column(String)  # Which model was used
    created_at = Column(DateTime, default=datetime.utcnow)


class SendMetric(Base):
    """Send rate metrics for deliverability"""
    __tablename__ = "send_metrics"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=datetime.utcnow)
    emails_sent = Column(Integer, default=0)
    emails_per_hour = Column(Integer, default=10)
    emails_per_day = Column(Integer, default=10)
    bounce_rate = Column(Float, default=0.0)


class SystemSettings(Base):
    """System-wide settings and configuration"""
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(Text)  # JSON string for complex values
    value_type = Column(String, default="string")  # "string", "int", "float", "bool", "json"
    description = Column(String, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScrapedContent(Base):
    """Raw scraped content from company/person web pages"""
    __tablename__ = "scraped_content"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=True)
    source_url = Column(String, nullable=False)
    page_type = Column(String)  # "homepage", "blog", "about", "team", "person_profile"
    raw_text = Column(Text)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    page_date = Column(DateTime, nullable=True)  # Published date if available
    content_hash = Column(String, index=True)  # SHA256 for deduplication


class EnrichmentSignal(Base):
    """Extracted signals from scraped content with source links"""
    __tablename__ = "enrichment_signals"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    signal_type = Column(String)  # "funding", "launch", "hiring", "announcement", "pain_point"
    signal_text = Column(Text)  # The extracted signal
    source_text = Column(Text)  # Original scraped text snippet
    source_url = Column(String)  # URL where signal was found
    confidence = Column(Float)  # 0.0 to 1.0
    extracted_at = Column(DateTime, default=datetime.utcnow)


class SendDecision(Base):
    """Log of send decisions (allowed/blocked) with reasons"""
    __tablename__ = "send_decisions"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    email = Column(String, nullable=False)
    decision = Column(String)  # "allowed", "blocked", "throttled", "suppressed"
    reason = Column(String)
    email_body = Column(Text, nullable=True)  # Stored if blocked for review
    checked_at = Column(DateTime, default=datetime.utcnow)


class DomainThrottle(Base):
    """Domain-level send throttling"""
    __tablename__ = "domain_throttle"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, nullable=False, index=True)
    emails_sent_today = Column(Integer, default=0)
    last_sent_at = Column(DateTime)
    date = Column(DateTime, default=datetime.utcnow)
    cooldown_until = Column(DateTime, nullable=True)  # If domain is in cooldown


class SmtpServer(Base):
    """SMTP server configuration for sending emails (rotation support)"""
    __tablename__ = "smtp_servers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Display name, e.g. "Primary SMTP", "Backup 1"
    host = Column(String, nullable=False)
    port = Column(Integer, default=587)
    username = Column(String, nullable=False)
    password = Column(Text, nullable=False)  # Stored in DB; consider env/secret in production
    use_tls = Column(Boolean, default=True)
    from_email = Column(String, nullable=False)  # Sender address
    from_name = Column(String, default="")  # Sender display name
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)  # Higher = preferred when rotating
    emails_sent = Column(Integer, default=0)  # For least_used rotation
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
