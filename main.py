# main.py
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import typer
from rich.console import Console

from agents.email_agent import generate_email
from agents.gmail_service import authenticate_gmail, send_email
from agents.smtp_sender import get_active_smtp_servers, send_email_dispatch
from utils.settings import get_setting
from config import KEYWORD, LOCATION, OUTPUT_FILE
from scrapers.google_scraper import google_search_linkedin_companies
from scrapers.linkedin_parser import parse_linkedin_csv_or_mock
from scrapers.discovery import search_companies, search_people
from utils.helpers import get_company_domain_from_linkedin
from utils.patterns import generate_email_candidates, verify_with_hunter
from utils.smtp_check import validate_email
from utils.writer import write_to_csv_and_db

app = typer.Typer()
console = Console()

# Default query for the scraper
DEFAULT_QUERY = "Seed stage B2B SaaS startups hiring SDRs"


# ------------- EMAIL SENDER ------------- #

@app.command()
def send_emails(
    csv_path: str = typer.Option(
        "leads.csv",
        "--csv",
        help="Path to CSV with columns at least: name,email,company,linkedin_url",
    ),
    subject: str = typer.Option("Quick question", help="Email subject line"),
    campaign_id: int = typer.Option(
        None,
        "--campaign-id",
        help="Campaign ID for pitch context (emails will pitch this campaign's offer)",
    ),
):
    """
    Send personalised emails to leads in the given CSV.
    Use --campaign-id so emails pitch the right offer (e.g. Done-For-You automation vs Intelpatch).
    """
    if not csv_path:
        console.print("[red]No CSV path provided.[/red]")
        raise typer.Exit(1)

    df = pd.read_csv(csv_path)

    required_cols = {"name", "email", "company"}
    missing = required_cols - set(df.columns.str.lower())
    if missing:
        console.print(f"[red]CSV is missing required columns: {missing}[/red]")
        raise typer.Exit(1)

    # Normalise column access (case-safe)
    col_map = {c.lower(): c for c in df.columns}
    name_col = col_map.get("name")
    email_col = col_map.get("email")
    company_col = col_map.get("company")
    linkedin_col = col_map.get("linkedin_url", None)

    use_smtp = get_setting("use_smtp_servers", False)
    smtp_servers = get_active_smtp_servers() if use_smtp else []
    use_smtp_path = use_smtp and len(smtp_servers) > 0
    service = None
    if not use_smtp_path:
        service = authenticate_gmail()
    results = []

    for _, row in df.iterrows():
        name = str(row[name_col]).strip()
        email = str(row[email_col]).strip()
        company = str(row[company_col]).strip()
        linkedin = str(row[linkedin_col]).strip() if linkedin_col else ""

        if not email:
            continue

        console.print(f"✍️  Generating email for {name} ({company})...")
        
        # Get verified signals, company focus, campaign context, and enrichment from database
        verified_signals = []
        company_focus = None
        lead_id = None
        campaign_name = None
        campaign_offer = None
        company_enrichment = None
        person_enrichment = None
        
        try:
            from db.session import SessionLocal
            from db.models import Lead, EnrichmentSignal, ScrapedContent, Campaign
            from sqlalchemy.orm import joinedload
            from scrapers.enrichment import summarize_company_focus
            
            db = SessionLocal()
            try:
                lead = db.query(Lead).options(joinedload(Lead.person).joinedload("company")).filter(
                    Lead.email == email
                ).order_by(Lead.timestamp.desc()).first()
                
                if lead:
                    lead_id = lead.id
                    signals = db.query(EnrichmentSignal).filter(
                        EnrichmentSignal.lead_id == lead.id,
                        EnrichmentSignal.confidence >= 0.7
                    ).all()
                    verified_signals = [
                        {"signal_type": s.signal_type, "signal_text": s.signal_text, "source_url": s.source_url, "confidence": s.confidence}
                        for s in signals
                    ]
                    
                    if lead.person and lead.person.company:
                        company_id = lead.person.company.id
                        scraped_content = db.query(ScrapedContent).filter(ScrapedContent.company_id == company_id).all()
                        if scraped_content:
                            scraped_texts = [{"source_url": c.source_url, "raw_text": c.raw_text, "page_type": c.page_type, "page_date": c.page_date} for c in scraped_content]
                            company_focus = summarize_company_focus(scraped_texts)
                        cid = campaign_id or (lead.person.company.campaign_id if lead.person.company else None)
                        if cid:
                            camp = db.query(Campaign).filter(Campaign.id == cid).first()
                            if camp:
                                campaign_name = camp.name
                                campaign_offer = getattr(camp, "offer_description", None) or camp.name
                        co = lead.person.company
                        company_enrichment = {}
                        if co.signals:
                            company_enrichment["signals"] = co.signals
                        if co.funding_stage:
                            company_enrichment["funding_stage"] = co.funding_stage
                        if co.hq_country:
                            company_enrichment["hq_country"] = co.hq_country
                        for s in signals:
                            t, txt = s.signal_type, (s.signal_text or "").strip()
                            if t in ("funding_round", "latest_funding") and txt:
                                company_enrichment["latest_funding"] = txt
                            if t in ("company_announcement", "recent_news") and txt:
                                company_enrichment["recent_news"] = company_enrichment.get("recent_news", "") + " " + txt
                            if t in ("recent_hires", "hiring_signal") and txt:
                                company_enrichment["recent_hires"] = txt
                            if t in ("product_launch", "product_updates") and txt:
                                company_enrichment["product_updates"] = txt
                        person_enrichment = {}
                        for s in signals:
                            t, txt = s.signal_type, (s.signal_text or "").strip()
                            if t == "pain_point" and txt:
                                person_enrichment["pain_points"] = txt
                            if t in ("recent_activity", "public_statement") and txt:
                                person_enrichment["recent_activity"] = txt
                        if not company_enrichment:
                            company_enrichment = None
                        if not person_enrichment:
                            person_enrichment = None
            finally:
                db.close()
        except Exception:
            pass
        
        # Generate evidence-based email
        try:
            from agents.email_agent import generate_evidence_based_email, should_send_email
            
            # Get role from CSV if available
            role_col = col_map.get("role", None)
            role = str(row[role_col]).strip() if role_col and role_col in df.columns else ""
            
            if verified_signals or company_focus or company_enrichment or person_enrichment:
                body = generate_evidence_based_email(
                    name=name,
                    company=company,
                    role=role,
                    verified_signals=verified_signals,
                    company_focus=company_focus,
                    company_enrichment=company_enrichment,
                    person_enrichment=person_enrichment,
                    min_confidence=0.7,
                    campaign_name=campaign_name,
                    campaign_offer=campaign_offer,
                )
            else:
                body = generate_email(name, company, linkedin, campaign_name=campaign_name, campaign_offer=campaign_offer)
            
            # Mail Critic: evaluate and rewrite until pass or max_rewrites
            try:
                from utils.settings import get_setting
                from agents.mail_critic import evaluate_email, rewrite_email_with_feedback
                if get_setting("enable_mail_critic", True):
                    min_score = float(get_setting("critic_min_score", 0.7))
                    max_rewrites = int(get_setting("critic_max_rewrites", 2))
                    strictness = get_setting("critic_strictness", "medium") or "medium"
                    for attempt in range(max_rewrites + 1):
                        passed, score, feedback = evaluate_email(
                            body, name, company,
                            min_score=min_score, strictness=strictness,
                        )
                        if passed:
                            break
                        if feedback and attempt < max_rewrites:
                            console.print(f"   📝 Critic (score {score:.2f}): rewriting...")
                            body = rewrite_email_with_feedback(body, feedback, name, company)
            except (ImportError, Exception):
                pass
            
            should_send, reason = should_send_email(
                verified_signals=verified_signals,
                email_body=body,
                min_confidence=0.7,
                require_signal=False,
            )
            
            if not should_send:
                console.print(f"⏸️  Email rejected: {reason}")
                continue
        except ImportError:
            body = generate_email(name, company, linkedin, campaign_name=campaign_name, campaign_offer=campaign_offer)
        except Exception as e:
            console.print(f"⚠️  Error generating email: {e}")
            body = generate_email(name, company, linkedin, campaign_name=campaign_name, campaign_offer=campaign_offer)

        console.print(f"📤 Sending to {email}...")
        if use_smtp_path:
            from db.session import SessionLocal
            db_send = SessionLocal()
            try:
                thread_id = send_email_dispatch(email, subject, body, check_rate_limit=True, lead_id=lead_id, db=db_send)
            finally:
                db_send.close()
        else:
            thread_id = send_email(service, email, subject, body, check_rate_limit=True, lead_id=lead_id)

        results.append(
            {
                "name": name,
                "email": email,
                "company": company,
                "sent": thread_id is not None,
                "thread_id": thread_id,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )

        # Adaptive rate limiting with configurable delay
        # Rate limiter checks are done in send_email(), but we still need a small delay
        # to avoid hammering the API even if rate limit allows
        try:
            from utils.settings import get_setting
            email_delay = get_setting("email_delay_seconds", 0.5)
        except:
            email_delay = 0.5
        
        if thread_id is not None:
            time.sleep(email_delay)  # Use configurable delay from settings
        else:
            # If rate limited, wait longer before retrying next email
            time.sleep(email_delay * 4)

    pd.DataFrame(results).to_csv("sent_emails.csv", index=False)
    console.print("[green]✅ All emails sent! Check sent_emails.csv for tracking IDs.[/green]")


# ------------- SCRAPER (PERPLEXITY / LLM FLOW) ------------- #

@app.command()
def scrape_leads(
    query: str = typer.Option(
        DEFAULT_QUERY,
        "--query",
        "-q",
        help="Search query to pass into search_companies()",
    ),
    campaign_id: int = typer.Option(
        None,
        "--campaign-id",
        help="Campaign ID from database (overrides query/max_companies/max_people_per_company)",
    ),
    max_companies: int = typer.Option(20, help="Max companies to process per run"),
    max_people_per_company: int = typer.Option(3, help="Max people per company"),
    require_valid_email: bool = typer.Option(
        True, help="If True, only store leads with at least 'valid' SMTP status"
    ),
):
    """
    Scrape companies + decision makers, infer emails, validate, and append to leads.csv.
    """
    # If campaign_id provided, fetch campaign from database
    if campaign_id:
        try:
            from db.session import SessionLocal
            from db.models import Campaign
            db = SessionLocal()
            campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
            db.close()
            
            if campaign:
                query = campaign.query
                max_companies = campaign.max_companies
                max_people_per_company = campaign.max_people_per_company
                require_valid_email = campaign.require_valid_email
                console.print(f"[cyan]Using campaign: {campaign.name} (ID: {campaign_id})[/cyan]")
            else:
                console.print(f"[red]Campaign ID {campaign_id} not found, using query parameter[/red]")
        except Exception as e:
            console.print(f"[yellow]Could not load campaign from database: {e}, using query parameter[/yellow]")
    
    # Get scraping settings
    try:
        from utils.settings import get_setting
        enrichment_level = get_setting("scraping_enrichment_level", "deep")
    except:
        enrichment_level = "deep"
    
    console.print(f"[cyan]Starting lead scrape for query:[/cyan] {query!r} (enrichment: {enrichment_level})")
    companies = search_companies(query, limit=max_companies, enrichment_level=enrichment_level) or []
    console.print(f"[cyan]Found {len(companies)} companies[/cyan]")

    leads_written = 0
    companies_processed = 0
    companies_skipped = 0

    seen_emails = set()
    
    # Get existing companies from database to skip duplicates
    try:
        from db.session import SessionLocal
        from db.models import Company
        db = SessionLocal()
        
        if campaign_id:
            # Check for companies in this campaign
            existing_companies_query = db.query(Company.domain, Company.company_name).filter(
                Company.campaign_id == campaign_id
            ).all()
        else:
            # Check for all companies
            existing_companies_query = db.query(Company.domain, Company.company_name).all()
        
        existing_companies = {(c.domain.lower() if c.domain else "", c.company_name.lower() if c.company_name else "") for c in existing_companies_query}
        db.close()
    except Exception:
        # If database not available, continue without deduplication
        existing_companies = set()

        for c in companies[:max_companies]:
            domain = c.get("domain") or ""
            company_name = c.get("company_name") or ""
            linkedin = c.get("linkedin") or ""
            
            # Try to extract domain if missing (same logic as discovery.py)
            if not domain:
                # Try to extract from LinkedIn URL
                if linkedin and "linkedin.com/company/" in linkedin:
                    try:
                        slug = linkedin.split("linkedin.com/company/")[-1].split("/")[0].split("?")[0]
                        domain = f"{slug}.com"
                    except:
                        pass
                
                # Try to infer from company name
                if not domain and company_name:
                    name_clean = company_name.lower().replace(" ", "").replace("inc", "").replace("llc", "").replace("ltd", "").replace(".", "")
                    domain = f"{name_clean}.com"
            
            if not domain:
                continue
        
        # Check if company already exists (deduplication)
        domain_lower = domain.lower()
        company_name_lower = company_name.lower()
        
        if (domain_lower, company_name_lower) in existing_companies:
            companies_skipped += 1
            console.print(f"[yellow]⏭️  Skipping {company_name} ({domain}) - already exists in database[/yellow]")
            continue
        
        companies_processed += 1
        console.print(f"\n[blue]🔍 Scraping people at {company_name} ({domain})...[/blue]")
        people = search_people(domain, limit=max_people_per_company, enrichment_level=enrichment_level) or []

        for p in people[:max_people_per_company]:
            name = p.get("name") or ""
            if not name:
                continue

            # 1) Generate candidate emails
            candidates = generate_email_candidates(name, domain)
            if not candidates:
                continue

            chosen_email: Optional[str] = None
            chosen_status = "unknown"
            chosen_confidence = 0.5

            # 2) Validate via SMTP (+ optional Hunter)
            for candidate in candidates:
                smtp_res = validate_email(candidate)

                if smtp_res["status"] == "invalid":
                    continue

                # Optional Hunter check; skip if no API key configured
                hunter_res = verify_with_hunter(candidate)
                if hunter_res.get("ok"):
                    chosen_email = candidate
                    chosen_status = "valid"
                    chosen_confidence = max(
                        smtp_res.get("confidence", 0.0), (hunter_res.get("score") or 0) / 100.0
                    )
                    break

                # Fallback: SMTP says valid/unknown but Hunter not usable
                if smtp_res["status"] in ("valid", "unknown"):
                    chosen_email = candidate
                    chosen_status = smtp_res["status"]
                    chosen_confidence = smtp_res.get("confidence", 0.5)
                    # don't break immediately; you can prefer 'valid' over 'unknown'
                    if smtp_res["status"] == "valid":
                        break

            if not chosen_email:
                continue

            if require_valid_email and chosen_status != "valid":
                # Skip unknowns if we only want strong leads
                continue

            # 3) Build row compatible with send_emails()
            row = {
                "name": name,
                "email": chosen_email,
                "company": company_name,
                "linkedin_url": p.get("linkedin_url", ""),
                # Extra metadata (useful later, harmless for sender)
                "role": p.get("role", ""),
                "domain": domain,
                "confidence": chosen_confidence,
                "validation_status": chosen_status,
                "source_query": query,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            # Add enrichment data for email personalization
            import json
            company_enrichment = {}
            if c.get("recent_news"):
                company_enrichment["recent_news"] = c.get("recent_news")
            if c.get("latest_funding"):
                company_enrichment["latest_funding"] = c.get("latest_funding")
            if c.get("recent_hires"):
                company_enrichment["recent_hires"] = c.get("recent_hires")
            if c.get("product_updates"):
                company_enrichment["product_updates"] = c.get("product_updates")
            if c.get("pain_points"):
                company_enrichment["pain_points"] = c.get("pain_points")
            
            person_enrichment = {}
            if p.get("recent_activity"):
                person_enrichment["recent_activity"] = p.get("recent_activity")
            if p.get("company_news"):
                person_enrichment["company_news"] = p.get("company_news")
            if p.get("pain_points"):
                person_enrichment["pain_points"] = p.get("pain_points")
            
            if company_enrichment or person_enrichment:
                row["company_enrichment"] = json.dumps(company_enrichment) if company_enrichment else ""
                row["person_enrichment"] = json.dumps(person_enrichment) if person_enrichment else ""

            if chosen_email in seen_emails:
                continue
            seen_emails.add(chosen_email)
            # Pass campaign_id if available for database write
            db_campaign_id = campaign_id if campaign_id else None
            write_to_csv_and_db(row, campaign_id=db_campaign_id)  # Dual-write: CSV + database

            leads_written += 1
            console.print(
                f"[green]Wrote lead:[/green] {name} @ {company_name} ({domain}) → {chosen_email}"
            )

    if leads_written == 0:
        console.print("[yellow]No leads generated.[/yellow]")
    else:
        console.print(f"[green]✅ Done. {leads_written} leads appended to leads.csv[/green]")
    
    if companies_skipped > 0:
        console.print(f"[cyan]📊 Statistics: {companies_processed} companies processed, {companies_skipped} companies skipped (duplicates)[/cyan]")


# ------------- LEGACY GOOGLE/LINKEDIN SCRAPER ------------- #

def _is_valid_email_format(email: str) -> bool:
    """
    Very basic email format check to keep legacy extractor running.
    """
    import re

    if not email:
        return False
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email) is not None


@app.command()
def extract_emails():
    """
    Legacy flow: Google search → LinkedIn parser → naive email pattern.
    Kept for experimentation; primary pipeline should be scrape_leads().
    """
    print(f"🔍 Searching for '{KEYWORD}' in '{LOCATION}'...")

    company_urls = google_search_linkedin_companies(KEYWORD, LOCATION)
    print(f"✅ Found {len(company_urls)} companies")

    all_leads = []

    for url in company_urls:
        print(f"  → Processing {url}")
        domain = get_company_domain_from_linkedin(url)
        employees = parse_linkedin_csv_or_mock(url)

        for emp in employees:
            name = emp.get("Name", "")
            if not name or len(name.split()) < 2:
                continue

            first, last = name.split()[0], name.split()[-1]
            email = f"{first.lower()}.{last.lower()}@{domain}" if domain else ""

            if not _is_valid_email_format(email):
                email = ""

            lead = {
                "name": name,
                "company": emp.get("Company", ""),
                "email": email,
                "linkedin_url": emp.get("LinkedIn URL", ""),
                "role": emp.get("Role / Title", ""),
                "industry": KEYWORD,
                "location": LOCATION,
            }
            all_leads.append(lead)

    df = pd.DataFrame(all_leads)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n🎉 Done! {len(all_leads)} leads saved to {OUTPUT_FILE}")


# ------------- ENTRYPOINT ------------- #

if __name__ == "__main__":
    app()
