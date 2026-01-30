# api/routes/send.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from db.session import get_db
from agents.gmail_service import authenticate_gmail, send_email
from agents.email_agent import generate_email
from sqlalchemy.orm import joinedload
import pandas as pd

router = APIRouter(prefix="/api/v1", tags=["send"])


class SendEmailRequest(BaseModel):
    name: str
    email: str
    company: str
    linkedin_url: Optional[str] = ""
    subject: str = "Quick question"


class SendEmailResponse(BaseModel):
    name: str
    email: str
    sent: bool
    thread_id: Optional[str]
    timestamp: str


@router.post("/send", response_model=SendEmailResponse)
def send_single_email(request: SendEmailRequest, db: Session = Depends(get_db)):
    """
    Send a single email (wraps send_emails CLI command logic).
    """
    try:
        service = authenticate_gmail()
        
        # Generate email body
        body = generate_email(request.name, request.company, request.linkedin_url or "")
        
        # Send email
        thread_id = send_email(service, request.email, request.subject, body, check_rate_limit=True)
        
        from datetime import datetime
        return SendEmailResponse(
            name=request.name,
            email=request.email,
            sent=thread_id is not None,
            thread_id=thread_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


class SendBatchRequest(BaseModel):
    csv_path: Optional[str] = None
    leads: Optional[List[SendEmailRequest]] = None
    subject: str = "Quick question"


class SendBatchResponse(BaseModel):
    total: int
    sent: int
    failed: int
    results: List[SendEmailResponse]


@router.post("/send/batch", response_model=SendBatchResponse)
def send_batch_emails(request: SendBatchRequest, db: Session = Depends(get_db)):
    """
    Send emails in batch (wraps send_emails CLI command).
    Either provide csv_path or leads list.
    """
    try:
        service = authenticate_gmail()
        results = []
        
        if request.csv_path:
            # Read from CSV
            df = pd.read_csv(request.csv_path)
            required_cols = {"name", "email", "company"}
            missing = required_cols - set(df.columns.str.lower())
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"CSV is missing required columns: {missing}"
                )
            
            col_map = {c.lower(): c for c in df.columns}
            name_col = col_map.get("name")
            email_col = col_map.get("email")
            company_col = col_map.get("company")
            linkedin_col = col_map.get("linkedin_url", None)
            
            for _, row in df.iterrows():
                name = str(row[name_col]).strip()
                email = str(row[email_col]).strip()
                company = str(row[company_col]).strip()
                linkedin = str(row[linkedin_col]).strip() if linkedin_col else ""
                
                if not email:
                    continue
                
                # Try to find lead in database first
                from db.models import Lead
                lead = db.query(Lead).options(joinedload(Lead.person)).filter(Lead.email == email).first()
                if lead and lead.person:
                    name = lead.person.name
                    company = lead.company
                    linkedin = lead.linkedin_url or linkedin
                
                body = generate_email(name, company, linkedin)
                thread_id = send_email(service, email, request.subject, body, check_rate_limit=True)
                
                from datetime import datetime
                results.append(SendEmailResponse(
                    name=name,
                    email=email,
                    sent=thread_id is not None,
                    thread_id=thread_id,
                    timestamp=datetime.utcnow().isoformat() + "Z",
                ))
        elif request.leads:
            # Use provided leads list
            for lead in request.leads:
                lead_name = lead.person.name if lead.person else "Unknown"
                body = generate_email(lead_name, lead.company, lead.linkedin_url or "")
                thread_id = send_email(service, lead.email, lead.subject, body, check_rate_limit=True)
                
                from datetime import datetime
                results.append(SendEmailResponse(
                    name=lead_name,
                    email=lead.email,
                    sent=thread_id is not None,
                    thread_id=thread_id,
                    timestamp=datetime.utcnow().isoformat() + "Z",
                ))
        else:
            raise HTTPException(
                status_code=400,
                detail="Either csv_path or leads must be provided"
            )
        
        sent_count = sum(1 for r in results if r.sent)
        return SendBatchResponse(
            total=len(results),
            sent=sent_count,
            failed=len(results) - sent_count,
            results=results,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send batch: {str(e)}")
