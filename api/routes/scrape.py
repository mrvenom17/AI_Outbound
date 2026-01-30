# api/routes/scrape.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from db.session import get_db
from db.models import Campaign
from scrapers.discovery import search_companies, search_people
from utils.patterns import generate_email_candidates, verify_with_hunter
from utils.smtp_check import validate_email
from utils.writer import write_to_csv_and_db
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1", tags=["scrape"])


class ScrapeLeadsRequest(BaseModel):
    campaign_id: Optional[int] = None
    query: Optional[str] = None
    max_companies: int = 20
    max_people_per_company: int = 3
    require_valid_email: bool = True


class ScrapeLeadsResponse(BaseModel):
    campaign_id: Optional[int]
    query: str
    companies_found: int
    leads_written: int
    status: str


def _scrape_leads_worker(
    campaign_id: Optional[int],
    query: str,
    max_companies: int,
    max_people_per_company: int,
    require_valid_email: bool,
):
    """
    Worker function that does the actual scraping.
    Can be run in background task.
    """
    companies = search_companies(query) or []
    leads_written = 0
    seen_emails = set()
    
    for c in companies[:max_companies]:
        domain = c.get("domain") or ""
        company_name = c.get("company_name") or ""
        
        if not domain:
            continue
        
        people = search_people(domain) or []
        
        for p in people[:max_people_per_company]:
            name = p.get("name") or ""
            if not name:
                continue
            
            # Generate candidate emails
            candidates = generate_email_candidates(name, domain)
            if not candidates:
                continue
            
            chosen_email: Optional[str] = None
            chosen_status = "unknown"
            chosen_confidence = 0.5
            
            # Validate via SMTP (+ optional Hunter)
            for candidate in candidates:
                smtp_res = validate_email(candidate)
                
                if smtp_res["status"] == "invalid":
                    continue
                
                hunter_res = verify_with_hunter(candidate)
                if hunter_res.get("ok"):
                    chosen_email = candidate
                    chosen_status = "valid"
                    chosen_confidence = max(
                        smtp_res.get("confidence", 0.0),
                        (hunter_res.get("score") or 0) / 100.0
                    )
                    break
                
                if smtp_res["status"] in ("valid", "unknown"):
                    chosen_email = candidate
                    chosen_status = smtp_res["status"]
                    chosen_confidence = smtp_res.get("confidence", 0.5)
                    if smtp_res["status"] == "valid":
                        break
            
            if not chosen_email:
                continue
            
            if require_valid_email and chosen_status != "valid":
                continue
            
            # Build row
            row = {
                "name": name,
                "email": chosen_email,
                "company": company_name,
                "linkedin_url": p.get("linkedin_url", ""),
                "role": p.get("role", ""),
                "domain": domain,
                "confidence": chosen_confidence,
                "validation_status": chosen_status,
                "source_query": query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            if chosen_email in seen_emails:
                continue
            seen_emails.add(chosen_email)
            write_to_csv_and_db(row, campaign_id=campaign_id)
            leads_written += 1
    
    return leads_written


@router.post("/scrape", response_model=ScrapeLeadsResponse)
def scrape_leads(
    request: ScrapeLeadsRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Scrape leads (wraps scrape_leads CLI command).
    Can run synchronously or as background task.
    """
    # Get campaign if campaign_id provided
    campaign = None
    if request.campaign_id:
        campaign = db.query(Campaign).filter(Campaign.id == request.campaign_id).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        query = campaign.query
        max_companies = campaign.max_companies
        max_people_per_company = campaign.max_people_per_company
        require_valid_email = campaign.require_valid_email
    elif request.query:
        query = request.query
        max_companies = request.max_companies
        max_people_per_company = request.max_people_per_company
        require_valid_email = request.require_valid_email
    else:
        raise HTTPException(
            status_code=400,
            detail="Either campaign_id or query must be provided"
        )
    
    # Run scraping (synchronously for now - can be moved to background)
    companies = search_companies(query)
    companies_found = len(companies) if companies else 0
    
    # Start background task for actual lead generation
    background_tasks.add_task(
        _scrape_leads_worker,
        request.campaign_id,
        query,
        max_companies,
        max_people_per_company,
        require_valid_email,
    )
    
    return ScrapeLeadsResponse(
        campaign_id=request.campaign_id,
        query=query,
        companies_found=companies_found,
        leads_written=0,  # Will be updated by background task
        status="started",
    )
