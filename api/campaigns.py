# api/campaigns.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from db.session import get_db
from db.models import Campaign

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    query: str
    offer_description: Optional[str] = None
    max_companies: int = 20
    max_people_per_company: int = 3
    require_valid_email: bool = True


class CampaignResponse(BaseModel):
    id: int
    name: str
    query: str
    offer_description: Optional[str] = None
    max_companies: int
    max_people_per_company: int
    require_valid_email: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post("/", response_model=CampaignResponse)
def create_campaign(campaign: CampaignCreate, db: Session = Depends(get_db)):
    """Create a new campaign"""
    db_campaign = Campaign(
        name=campaign.name,
        query=campaign.query,
        offer_description=campaign.offer_description,
        max_companies=campaign.max_companies,
        max_people_per_company=campaign.max_people_per_company,
        require_valid_email=campaign.require_valid_email,
    )
    db.add(db_campaign)
    db.commit()
    db.refresh(db_campaign)
    return CampaignResponse(
        id=db_campaign.id,
        name=db_campaign.name,
        query=db_campaign.query,
        offer_description=getattr(db_campaign, "offer_description", None),
        max_companies=db_campaign.max_companies,
        max_people_per_company=db_campaign.max_people_per_company,
        require_valid_email=db_campaign.require_valid_email,
        created_at=db_campaign.created_at.isoformat(),
        updated_at=db_campaign.updated_at.isoformat(),
    )


@router.get("/", response_model=List[CampaignResponse])
def list_campaigns(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """List all campaigns"""
    campaigns = db.query(Campaign).offset(skip).limit(limit).all()
    return [
        CampaignResponse(
            id=c.id,
            name=c.name,
            query=c.query,
            offer_description=getattr(c, "offer_description", None),
            max_companies=c.max_companies,
            max_people_per_company=c.max_people_per_company,
            require_valid_email=c.require_valid_email,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )
        for c in campaigns
    ]


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    """Get a specific campaign"""
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        query=campaign.query,
        offer_description=getattr(campaign, "offer_description", None),
        max_companies=campaign.max_companies,
        max_people_per_company=campaign.max_people_per_company,
        require_valid_email=campaign.require_valid_email,
        created_at=campaign.created_at.isoformat(),
        updated_at=campaign.updated_at.isoformat(),
    )
