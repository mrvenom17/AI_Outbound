# scripts/migrate_csvs.py
"""
Migration script to import existing CSV files into database.

Usage:
    python scripts/migrate_csvs.py --leads-csv leads.csv --sent-emails-csv sent_emails.csv
"""
import argparse
import pandas as pd
from datetime import datetime
from typing import Optional

def migrate_leads_csv(csv_path: str, campaign_id: Optional[int] = None) -> int:
    """
    Migrate leads.csv to database.
    Returns number of leads migrated.
    """
    try:
        from db.session import SessionLocal
        from db.models import Campaign, Company, Person, Lead
        from sqlalchemy import and_
    except ImportError:
        print("❌ Database not available. Install dependencies first.")
        return 0
    
    df = pd.read_csv(csv_path)
    print(f"📄 Reading {len(df)} leads from {csv_path}")
    
    # Check required columns
    required_cols = {"name", "email", "company"}
    missing = required_cols - set(df.columns.str.lower())
    if missing:
        print(f"❌ Missing required columns: {missing}")
        return 0
    
    col_map = {c.lower(): c for c in df.columns}
    name_col = col_map.get("name")
    email_col = col_map.get("email")
    company_col = col_map.get("company")
    linkedin_col = col_map.get("linkedin_url", None)
    role_col = col_map.get("role", None)
    domain_col = col_map.get("domain", None)
    confidence_col = col_map.get("confidence", None)
    validation_status_col = col_map.get("validation_status", None)
    source_query_col = col_map.get("source_query", None)
    timestamp_col = col_map.get("timestamp", None)
    
    db = SessionLocal()
    migrated = 0
    
    try:
        # Get or create default campaign if needed
        if campaign_id is None:
            default_campaign = db.query(Campaign).filter(Campaign.name == "Default").first()
            if not default_campaign:
                default_campaign = Campaign(
                    name="Default",
                    query="Migrated from CSV",
                    max_companies=20,
                    max_people_per_company=3,
                    require_valid_email=True,
                )
                db.add(default_campaign)
                db.flush()
            campaign_id = default_campaign.id
        
        for _, row in df.iterrows():
            name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
            email = str(row[email_col]).strip() if pd.notna(row[email_col]) else ""
            company_name = str(row[company_col]).strip() if pd.notna(row[company_col]) else ""
            
            if not name or not email or not company_name:
                continue
            
            # Get domain
            domain = ""
            if domain_col and pd.notna(row[domain_col]):
                domain = str(row[domain_col]).strip()
            else:
                # Try to extract from email
                if "@" in email:
                    domain = email.split("@")[1]
            
            if not domain:
                continue
            
            # Get or create Company
            company = db.query(Company).filter(
                and_(Company.domain == domain, Company.company_name == company_name)
            ).first()
            
            if not company:
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
            person = db.query(Person).filter(
                and_(
                    Person.company_id == company.id,
                    Person.name == name,
                )
            ).first()
            
            if not person:
                linkedin_url = ""
                if linkedin_col and pd.notna(row[linkedin_col]):
                    linkedin_url = str(row[linkedin_col]).strip()
                
                role = ""
                if role_col and pd.notna(row[role_col]):
                    role = str(row[role_col]).strip()
                
                person = Person(
                    company_id=company.id,
                    name=name,
                    role=role,
                    linkedin_url=linkedin_url,
                    location="",
                )
                db.add(person)
                db.flush()
            
            # Check if lead already exists
            existing_lead = db.query(Lead).filter(
                and_(
                    Lead.person_id == person.id,
                    Lead.email == email,
                )
            ).first()
            
            if existing_lead:
                continue  # Skip duplicates
            
            # Parse timestamp
            timestamp = datetime.utcnow()
            if timestamp_col and pd.notna(row[timestamp_col]):
                try:
                    ts_str = str(row[timestamp_col]).strip()
                    # Try parsing ISO format
                    if "T" in ts_str:
                        timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        timestamp = pd.to_datetime(ts_str).to_pydatetime()
                except (ValueError, AttributeError):
                    timestamp = datetime.utcnow()
            
            # Get other fields
            linkedin_url = ""
            if linkedin_col and pd.notna(row[linkedin_col]):
                linkedin_url = str(row[linkedin_col]).strip()
            
            role = ""
            if role_col and pd.notna(row[role_col]):
                role = str(row[role_col]).strip()
            
            confidence = 0.5
            if confidence_col and pd.notna(row[confidence_col]):
                try:
                    confidence = float(row[confidence_col])
                except (ValueError, TypeError):
                    confidence = 0.5
            
            validation_status = "unknown"
            if validation_status_col and pd.notna(row[validation_status_col]):
                validation_status = str(row[validation_status_col]).strip()
            
            source_query = ""
            if source_query_col and pd.notna(row[source_query_col]):
                source_query = str(row[source_query_col]).strip()
            
            # Create Lead
            lead = Lead(
                person_id=person.id,
                email=email,
                company=company_name,
                linkedin_url=linkedin_url,
                role=role,
                domain=domain,
                confidence=confidence,
                validation_status=validation_status,
                source_query=source_query,
                timestamp=timestamp,
            )
            db.add(lead)
            migrated += 1
        
        db.commit()
        print(f"✅ Migrated {migrated} leads to database")
        return migrated
        
    except Exception as e:
        print(f"❌ Error migrating leads: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def migrate_sent_emails_csv(csv_path: str) -> int:
    """
    Migrate sent_emails.csv to database.
    Returns number of emails migrated.
    """
    try:
        from db.session import SessionLocal
        from db.models import SentEmail, Lead
    except ImportError:
        print("❌ Database not available. Install dependencies first.")
        return 0
    
    df = pd.read_csv(csv_path)
    print(f"📄 Reading {len(df)} sent emails from {csv_path}")
    
    # Check required columns
    required_cols = {"email"}
    missing = required_cols - set(df.columns.str.lower())
    if missing:
        print(f"❌ Missing required columns: {missing}")
        return 0
    
    col_map = {c.lower(): c for c in df.columns}
    email_col = col_map.get("email")
    name_col = col_map.get("name", None)
    company_col = col_map.get("company", None)
    sent_col = col_map.get("sent", None)
    thread_id_col = col_map.get("thread_id", None)
    subject_col = col_map.get("subject", None)
    timestamp_col = col_map.get("timestamp", None)
    
    db = SessionLocal()
    migrated = 0
    
    try:
        for _, row in df.iterrows():
            email = str(row[email_col]).strip() if pd.notna(row[email_col]) else ""
            
            if not email:
                continue
            
            # Find lead by email
            lead = db.query(Lead).filter(Lead.email == email).order_by(
                Lead.timestamp.desc()
            ).first()
            
            if not lead:
                print(f"⚠️  No lead found for email {email}, skipping")
                continue
            
            # Check if sent email already exists
            existing = db.query(SentEmail).filter(
                and_(
                    SentEmail.lead_id == lead.id,
                    SentEmail.thread_id == (str(row[thread_id_col]).strip() if thread_id_col and pd.notna(row[thread_id_col]) else None)
                )
            ).first()
            
            if existing:
                continue  # Skip duplicates
            
            # Parse fields
            sent = True
            if sent_col and pd.notna(row[sent_col]):
                sent = bool(row[sent_col])
            
            thread_id = None
            if thread_id_col and pd.notna(row[thread_id_col]):
                thread_id = str(row[thread_id_col]).strip()
            
            subject = "Quick question"
            if subject_col and pd.notna(row[subject_col]):
                subject = str(row[subject_col]).strip()
            
            timestamp = datetime.utcnow()
            if timestamp_col and pd.notna(row[timestamp_col]):
                try:
                    ts_str = str(row[timestamp_col]).strip()
                    if "T" in ts_str:
                        timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    else:
                        timestamp = pd.to_datetime(ts_str).to_pydatetime()
                except (ValueError, AttributeError):
                    timestamp = datetime.utcnow()
            
            # Create SentEmail (body not available in CSV, use placeholder)
            sent_email = SentEmail(
                lead_id=lead.id,
                thread_id=thread_id,
                subject=subject,
                body="[Migrated from CSV - body not available]",
                sent=sent,
                sent_at=timestamp,
            )
            db.add(sent_email)
            migrated += 1
        
        db.commit()
        print(f"✅ Migrated {migrated} sent emails to database")
        return migrated
        
    except Exception as e:
        print(f"❌ Error migrating sent emails: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate CSV files to database")
    parser.add_argument("--leads-csv", default="leads.csv", help="Path to leads.csv")
    parser.add_argument("--sent-emails-csv", default="sent_emails.csv", help="Path to sent_emails.csv")
    parser.add_argument("--campaign-id", type=int, help="Campaign ID to associate leads with")
    
    args = parser.parse_args()
    
    print("🚀 Starting CSV migration...")
    
    leads_migrated = 0
    if args.leads_csv:
        try:
            leads_migrated = migrate_leads_csv(args.leads_csv, args.campaign_id)
        except FileNotFoundError:
            print(f"⚠️  Leads CSV not found: {args.leads_csv}")
    
    emails_migrated = 0
    if args.sent_emails_csv:
        try:
            emails_migrated = migrate_sent_emails_csv(args.sent_emails_csv)
        except FileNotFoundError:
            print(f"⚠️  Sent emails CSV not found: {args.sent_emails_csv}")
    
    print(f"\n✅ Migration complete!")
    print(f"   - Leads migrated: {leads_migrated}")
    print(f"   - Sent emails migrated: {emails_migrated}")


if __name__ == "__main__":
    main()
