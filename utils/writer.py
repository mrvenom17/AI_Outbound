# utils/writer.py
from __future__ import annotations

import csv
import os
from typing import Dict, Any, Optional
from datetime import datetime

DEFAULT_CSV = "leads.csv"

# Final unified schema for your system:
# - Compatible with send_emails()
# - Supports extra metadata for later use
FIELDNAMES = [
    "name",             # person name
    "email",            # chosen email
    "company",          # company name
    "linkedin_url",     # person's LinkedIn
    "role",             # title / role
    "domain",           # company domain
    "confidence",       # numeric confidence
    "validation_status",# 'valid' / 'unknown' / 'invalid'
    "source_query",     # which search query produced this
    "timestamp",        # ISO timestamp
]


def write_to_csv(data: Dict[str, Any], filename: str = DEFAULT_CSV) -> None:
    """
    Append a single lead dict to the CSV file.

    - Creates the file with header if missing.
    - Uses a fixed schema FIELDNAMES.
    - Ignores any extra keys in `data`.
    """
    file_exists = os.path.isfile(filename)

    # Make sure directory exists (if writing somewhere nested later)
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)

    with open(filename, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=FIELDNAMES,
            extrasaction="ignore",  # ignore keys not in FIELDNAMES
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)


def write_to_database(data: Dict[str, Any], campaign_id: Optional[int] = None) -> Optional[int]:
    """
    Write lead data to database (dual-write pattern).
    
    Creates Company and Person records if needed, then creates Lead.
    Returns lead_id if successful, None if database unavailable.
    
    Preserves CSV write behavior - this is additive only.
    """
    try:
        from db.session import SessionLocal
        from db.models import Company, Person, Lead
        from sqlalchemy import and_
    except ImportError:
        # Database not available - silently fail (CSV still works)
        return None
    
    db = SessionLocal()
    try:
        # Parse timestamp if string
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                timestamp = datetime.utcnow()
        elif timestamp is None:
            timestamp = datetime.utcnow()
        
        # Get or create Company
        domain = data.get("domain", "").strip()
        company_name = data.get("company", "").strip()
        
        if not domain or not company_name:
            return None
        
        company = db.query(Company).filter(
            and_(Company.domain == domain, Company.company_name == company_name)
        ).first()
        
        if not company:
            # Create company - need campaign_id
            if campaign_id is None:
                # Try to find default campaign or create one
                from db.models import Campaign
                default_campaign = db.query(Campaign).filter(
                    Campaign.name == "Default"
                ).first()
                if not default_campaign:
                    default_campaign = Campaign(
                        name="Default",
                        query=data.get("source_query", ""),
                        max_companies=20,
                        max_people_per_company=3,
                        require_valid_email=True,
                    )
                    db.add(default_campaign)
                    db.flush()
                campaign_id = default_campaign.id
            
            company = Company(
                campaign_id=campaign_id,
                company_name=company_name,
                domain=domain,
                linkedin="",
                hq_country="",
                funding_stage="",
                signals="",
            )
            db.add(company)
            db.flush()
        
        # Get or create Person
        person_name = data.get("name", "").strip()
        linkedin_url = data.get("linkedin_url", "").strip()
        role = data.get("role", "").strip()
        
        if not person_name:
            return None
        
        person = db.query(Person).filter(
            and_(
                Person.company_id == company.id,
                Person.name == person_name,
            )
        ).first()
        
        if not person:
            person = Person(
                company_id=company.id,
                name=person_name,
                role=role,
                linkedin_url=linkedin_url,
                location="",
            )
            db.add(person)
            db.flush()
        
        # Check if lead already exists (deduplication)
        existing_lead = db.query(Lead).filter(
            and_(
                Lead.person_id == person.id,
                Lead.email == data.get("email", "").strip(),
            )
        ).first()
        
        if existing_lead:
            # Update existing lead
            existing_lead.confidence = data.get("confidence", 0.5)
            existing_lead.validation_status = data.get("validation_status", "unknown")
            existing_lead.timestamp = timestamp
            db.commit()
            return existing_lead.id
        
        # Create Lead
        lead = Lead(
            person_id=person.id,
            email=data.get("email", "").strip(),
            company=company_name,
            linkedin_url=linkedin_url,
            role=role,
            domain=domain,
            confidence=data.get("confidence", 0.5),
            validation_status=data.get("validation_status", "unknown"),
            source_query=data.get("source_query", ""),
            timestamp=timestamp,
        )
        db.add(lead)
        db.flush()  # Flush to get lead.id
        
        # Link scraped content and enrichment signals to company/lead
        try:
            from db.models import ScrapedContent, EnrichmentSignal
            
            # Link scraped content to company
            db.query(ScrapedContent).filter(
                ScrapedContent.company_id.is_(None),
                ScrapedContent.source_url.contains(domain)
            ).update({"company_id": company.id}, synchronize_session=False)
            
            # Link enrichment signals to company and lead
            db.query(EnrichmentSignal).filter(
                EnrichmentSignal.company_id.is_(None),
                EnrichmentSignal.source_url.contains(domain)
            ).update({"company_id": company.id, "lead_id": lead.id}, synchronize_session=False)
            
        except Exception:
            # If linking fails, continue (non-critical)
            pass
        
        db.commit()
        return lead.id
        
    except Exception as e:
        # Log error but don't fail - CSV write already succeeded
        import logging
        logging.getLogger(__name__).warning(f"Database write failed: {e}")
        db.rollback()
        return None
    finally:
        db.close()


def write_to_csv_and_db(
    data: Dict[str, Any], 
    filename: str = DEFAULT_CSV, 
    campaign_id: Optional[int] = None
) -> None:
    """
    Dual-write: Write to both CSV (preserved) and database (new).
    
    CSV write always happens. Database write is best-effort.
    """
    # Always write to CSV (preserves existing behavior)
    write_to_csv(data, filename)
    
    # Also write to database (best-effort, fails silently if unavailable)
    write_to_database(data, campaign_id)
