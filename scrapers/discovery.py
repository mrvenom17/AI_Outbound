import json
import os
from typing import List, Dict, Any

import dotenv
import requests

dotenv.load_dotenv()

PPLX_API_KEY = os.getenv("PPLX_API_KEY")
PPLX_URL = "https://api.perplexity.ai/chat/completions"
PPLX_MODEL = "sonar"  # good quality / cost balance


class PerplexityError(Exception):
    pass


def _log_ai_decision(decision_type: str, input_evidence: dict, output: any, model: str) -> None:
    """Log AI decision to database for audit trail. Fails silently if unavailable."""
    try:
        from db.session import SessionLocal
        from db.models import AIDecision
        from datetime import datetime
        
        db = SessionLocal()
        try:
            decision = AIDecision(
                decision_type=decision_type,
                input_evidence=input_evidence,
                output=json.dumps(output) if isinstance(output, (dict, list)) else str(output),
                model=model,
                created_at=datetime.utcnow(),
            )
            db.add(decision)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except ImportError:
        pass


def _ensure_api_key() -> None:
    if not PPLX_API_KEY:
        raise PerplexityError("PPLX_API_KEY is not set in environment variables.")

def perplexity_api_call(prompt: str, max_tokens: int = 800) -> List[Dict]:
    _ensure_api_key()

    url = "https://api.perplexity.ai/chat/completions"

    payload = {
        "model": str(PPLX_MODEL),  # force string
        "messages": [
            {"role": "system", "content": "Return ONLY JSON. No explanation, no markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {PPLX_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    if resp.status_code != 200:
        # This is the part you were missing: actually SEE the error Perplexity returns
        print("=== PERPLEXITY ERROR ===")
        print("Status:", resp.status_code)
        try:
            print("Body:", json.dumps(resp.json(), indent=2))
        except Exception:
            print("Raw body:", resp.text)
        print("========================")
        resp.raise_for_status()  # will raise HTTPError with 400 etc.

    # Normal path
    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    # We told it to return JSON, so interpret it as such
    try:
        # Try to extract JSON from markdown code blocks if present
        cleaned_content = content.strip()
        if cleaned_content.startswith("```"):
            # Remove markdown code block markers
            lines = cleaned_content.split("\n")
            # Remove first line (```json or ```)
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            # Remove last line (```)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned_content = "\n".join(lines).strip()
        
        result = json.loads(cleaned_content)
        # Log decision to database
        _log_ai_decision(
            decision_type="perplexity_api_call",
            input_evidence={"prompt": prompt, "model": PPLX_MODEL},
            output=result,
            model=PPLX_MODEL,
        )
        # Ensure we return a list: Perplexity sometimes returns {"companies": [...]} or similar
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("companies", "data", "results", "items", "list"):
                if key in result and isinstance(result[key], list):
                    return result[key]
            # Use first value that is a list of dicts
            for v in result.values():
                if isinstance(v, list) and (not v or isinstance(v[0], dict)):
                    return v
        return []
    except json.JSONDecodeError:
        # Log error decision
        _log_ai_decision(
            decision_type="perplexity_api_call_error",
            input_evidence={"prompt": prompt, "model": PPLX_MODEL},
            output=content,
            model=PPLX_MODEL,
        )
        # If it misbehaves, you’ll see the raw string in logs
        # Try to extract a JSON array from raw content (model sometimes adds text around JSON)
        import re
        match = re.search(r'\[[\s\S]*\]', content)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, list):
                    _log_ai_decision(
                        decision_type="perplexity_api_call",
                        input_evidence={"prompt": prompt, "model": PPLX_MODEL, "recovered": True},
                        output=result,
                        model=PPLX_MODEL,
                    )
                    return result
            except json.JSONDecodeError:
                pass
        print("⚠️ Could not parse JSON from Perplexity. Raw content (first 500 chars):")
        print(content[:500])
        return []


def search_companies(query: str, limit: int = 15, enrichment_level: str = "deep") -> List[Dict]:
    """
    Find companies matching the query with optional enrichment.
    Returns list of dicts with enhanced information for personalization.
    """
    if enrichment_level == "deep":
        prompt = (
            f"Find up to {limit} companies matching this description: '{query}'. "
            "For EACH company, provide:\n"
            "- Recent news or announcements (last 3-6 months)\n"
            "- Latest funding rounds, amounts, and investors\n"
            "- Recent hires or team expansions\n"
            "- Product launches or feature updates\n"
            "- Industry challenges or pain points they're facing\n"
            "- Growth metrics or milestones\n"
            "- Recent partnerships or customer wins\n\n"
            "Return ONLY a JSON array. Each element MUST be an object with keys:\n"
            "  company_name, domain, linkedin, hq_country, funding_stage, signals, "
            "recent_news, latest_funding, recent_hires, product_updates, pain_points, "
            "growth_metrics, partnerships.\n"
            "CRITICAL: 'domain' field is REQUIRED for each company (e.g., 'example.com'). "
            "If domain is unknown, try to infer it from company name or LinkedIn URL. "
            "Use empty string '' only for other optional fields. Focus on RECENT information (last 3-6 months)."
        )
    elif enrichment_level == "standard":
        prompt = (
            f"Find up to {limit} companies matching this description: '{query}'. "
            "Include recent news and funding information.\n"
            "Return ONLY a JSON array. Each element MUST be an object with keys:\n"
            "  company_name, domain, linkedin, hq_country, funding_stage, signals, "
            "recent_news, latest_funding.\n"
            "CRITICAL: 'domain' field is REQUIRED (e.g., 'example.com'). "
            "If domain is unknown, infer it from company name or LinkedIn URL. "
            "Use empty string '' only for other optional fields."
        )
    else:  # basic
        prompt = (
            f"Find up to {limit} companies matching this description: '{query}'. "
            "Return ONLY a compact JSON array. Each element MUST be an object with keys:\n"
            "  company_name, domain, linkedin, hq_country, funding_stage, signals.\n"
            "CRITICAL: 'domain' field is REQUIRED (e.g., 'example.com'). "
            "If domain is unknown, infer it from company name or LinkedIn URL. "
            "Use short values. If other fields are unknown, use an empty string ''. "
            "Do not include any extra keys."
        )

    # Request enough tokens for large limits
    max_tokens = min(4096, 400 + limit * 80)
    results = perplexity_api_call(prompt, max_tokens=max_tokens)

    # Ensure results is a list (API sometimes returns dict with wrapper key)
    if not isinstance(results, list):
        results = []

    # If we got nothing, retry once with simpler prompt for better reliability
    if not results and enrichment_level != "basic":
        simple_prompt = (
            f"Find up to {limit} companies matching: '{query}'. "
            "Return ONLY a JSON array. Each object: company_name, domain, linkedin, hq_country, funding_stage, signals. "
            "Domain is REQUIRED (e.g. example.com). Infer from company name if needed. Use '' for unknown."
        )
        results = perplexity_api_call(simple_prompt, max_tokens=max_tokens)
        if not isinstance(results, list):
            results = []

    # Log company discovery decision (additional to perplexity_api_call log)
    _log_ai_decision(
        decision_type="company_discovery",
        input_evidence={"query": query, "limit": limit, "model": PPLX_MODEL},
        output=results,
        model=PPLX_MODEL,
    )

    normalized = []
    for item in results:
        if not isinstance(item, dict):
            continue
        # Accept multiple key names for company name and domain
        company_name = str(item.get("company_name") or item.get("name") or item.get("company") or "").strip()
        domain = str(item.get("domain") or item.get("website") or item.get("url") or "").strip()
        linkedin = str(item.get("linkedin") or item.get("linkedin_url") or "").strip()
        
        # Try to extract domain if missing
        if not domain:
            # Try to extract from LinkedIn URL
            if linkedin and "linkedin.com/company/" in linkedin:
                try:
                    slug = linkedin.split("linkedin.com/company/")[-1].split("/")[0].split("?")[0]
                    if slug:
                        domain = f"{slug}.com"
                except Exception:
                    pass
            
            # Try to infer from company name
            if not domain and company_name:
                name_clean = company_name.lower().replace(" ", "").replace("-", "")
                for suffix in ("inc", "llc", "ltd", "corp", ".com", "inc.", "llc.", "ltd."):
                    if name_clean.endswith(suffix.replace(".", "")):
                        name_clean = name_clean[: -len(suffix.replace(".", ""))].strip()
                name_clean = name_clean.strip(".").strip()
                if name_clean:
                    domain = f"{name_clean}.com"
        
        # Need at least company name or domain to be useful
        if not domain and not company_name:
            continue
        if not domain:
            domain = (company_name or "unknown").lower().replace(" ", "") + ".com"
        if not company_name:
            company_name = domain.replace(".com", "").replace(".", " ").title()
        
        base_data = {
            "company_name": company_name,
            "domain": domain,
            "linkedin": linkedin,
            "hq_country": str(item.get("hq_country", "")).strip(),
            "funding_stage": str(item.get("funding_stage", "")).strip(),
            "signals": str(item.get("signals", "")).strip(),
        }
        
        # REAL SCRAPING: Scrape actual website if enrichment level is standard or deep
        if enrichment_level in ("standard", "deep"):
            try:
                from scrapers.web_scraper import scrape_company_website, store_scraped_content
                from scrapers.enrichment import extract_company_signals, store_enrichment_signals
                
                # Scrape company website
                scraped_data = scrape_company_website(domain)
                
                if scraped_data and scraped_data.get("pages"):
                    # Store scraped content (will be linked to company later)
                    pages = scraped_data["pages"]
                    # Note: company_id not available yet, will be linked when company is created
                    # For now, store without company_id
                    store_scraped_content(pages, company_id=None, db=None)
                    
                    # Extract signals from scraped text
                    scraped_texts = [
                        {
                            "source_url": p["source_url"],
                            "raw_text": p["raw_text"],
                            "page_type": p.get("page_type", "other"),
                            "page_date": p.get("page_date")
                        }
                        for p in pages
                    ]
                    
                    signals = extract_company_signals(scraped_texts, min_confidence=0.7)
                    
                    # Store signals (will be linked to company/lead later)
                    if signals:
                        store_enrichment_signals(signals, company_id=None, db=None)
                    
                    # Add signal summaries to base_data (for backward compatibility)
                    funding_signals = [s for s in signals if s.get("signal_type") == "funding_round"]
                    if funding_signals:
                        base_data["latest_funding"] = funding_signals[0].get("signal_text", "")
                    
                    news_signals = [s for s in signals if s.get("signal_type") == "company_announcement"]
                    if news_signals:
                        base_data["recent_news"] = news_signals[0].get("signal_text", "")
                    
            except Exception as e:
                # Scraping failed - continue with Perplexity data only
                print(f"⚠️  Website scraping failed for {domain}: {e}")
                # Add empty enrichment fields for backward compatibility
                if enrichment_level in ("standard", "deep"):
                    base_data["recent_news"] = ""
                    base_data["latest_funding"] = ""
        
        if enrichment_level == "deep":
            # Additional deep enrichment fields (from Perplexity or scraping)
            base_data["recent_hires"] = str(item.get("recent_hires", "")).strip()
            base_data["product_updates"] = str(item.get("product_updates", "")).strip()
            base_data["pain_points"] = str(item.get("pain_points", "")).strip()
            base_data["growth_metrics"] = str(item.get("growth_metrics", "")).strip()
            base_data["partnerships"] = str(item.get("partnerships", "")).strip()
        
        normalized.append(base_data)

    return normalized


def search_people(company_domain: str, limit: int = 5, enrichment_level: str = "deep") -> List[Dict]:
    """
    Find key decision makers for a given company domain with optional enrichment.
    Returns list of dicts with enhanced information for personalization.
    """
    if enrichment_level == "deep":
        prompt = (
            f"For the company with domain '{company_domain}', find up to {limit} key decision makers "
            "(prioritise: Founder, Co-founder, CEO, CRO, VP Sales, Head of Sales, Head of Growth). "
            "For EACH person, provide:\n"
            "- Recent LinkedIn activity or posts (last 3 months)\n"
            "- Recent company news or announcements they were involved in\n"
            "- Their specific pain points or challenges mentioned publicly\n"
            "- Recent hires or team expansions in their department\n"
            "- Funding rounds or growth milestones\n"
            "- Industry trends they've commented on\n\n"
            "Return ONLY a JSON array. Each element MUST be an object with keys:\n"
            "  name, role, linkedin_url, location, recent_activity, company_news, pain_points, "
            "recent_hires, funding_info, industry_insights.\n"
            "Use empty string '' for unknown values. Be specific and recent (last 3-6 months)."
        )
    elif enrichment_level == "standard":
        prompt = (
            f"For the company with domain '{company_domain}', find up to {limit} key decision makers "
            "(prioritise: Founder, Co-founder, CEO, CRO, VP Sales, Head of Sales, Head of Growth). "
            "For EACH person, provide recent company news and their role context.\n"
            "Return ONLY a JSON array. Each element MUST be an object with keys:\n"
            "  name, role, linkedin_url, location, recent_activity, company_news.\n"
            "Use empty string '' for unknown values."
        )
    else:  # basic
        prompt = (
            f"For the company with domain '{company_domain}', find up to {limit} key decision makers "
            "(prioritise: Founder, Co-founder, CEO, CRO, VP Sales, Head of Sales, Head of Growth). "
            "Return ONLY a JSON array. Each element MUST be an object with keys:\n"
            "  name, role, linkedin_url, location.\n"
            "If a value is unknown, use empty string ''. "
            "Do not include any extra keys."
        )

    results = perplexity_api_call(prompt)

    # Log people discovery decision
    _log_ai_decision(
        decision_type="people_discovery",
        input_evidence={"company_domain": company_domain, "limit": limit, "model": PPLX_MODEL},
        output=results,
        model=PPLX_MODEL,
    )

    normalized = []
    for item in results:
        if not isinstance(item, dict):
            continue
        
        name = str(item.get("name", "")).strip()
        linkedin_url = str(item.get("linkedin_url", "")).strip()
        
        base_data = {
            "name": name,
            "role": str(item.get("role", "")).strip(),
            "linkedin_url": linkedin_url,
            "location": str(item.get("location", "")).strip(),
        }
        
        # REAL SCRAPING: Scrape public profile if URL available and enrichment level is deep
        if enrichment_level == "deep" and linkedin_url:
            try:
                from scrapers.web_scraper import scrape_person_public_page, store_scraped_content
                from scrapers.enrichment import extract_person_signals, store_enrichment_signals
                
                # Scrape person's public page
                person_page = scrape_person_public_page(linkedin_url)
                
                if person_page:
                    # Store scraped content
                    store_scraped_content([person_page], person_id=None, db=None)
                    
                    # Extract signals
                    signals = extract_person_signals([person_page], name, min_confidence=0.7)
                    
                    # Store signals
                    if signals:
                        store_enrichment_signals(signals, lead_id=None, db=None)
                    
                    # Add to base_data for backward compatibility
                    activity_signals = [s for s in signals if s.get("signal_type") == "recent_activity"]
                    if activity_signals:
                        base_data["recent_activity"] = activity_signals[0].get("signal_text", "")
                    
            except Exception as e:
                # Scraping failed - continue with Perplexity data only
                print(f"⚠️  Profile scraping failed for {name}: {e}")
        
        # Add enrichment data from Perplexity (if available, but real scraping takes precedence)
        if enrichment_level in ("standard", "deep"):
            if "recent_activity" not in base_data:
                base_data["recent_activity"] = str(item.get("recent_activity", "")).strip()
            base_data["company_news"] = str(item.get("company_news", "")).strip()
        
        if enrichment_level == "deep":
            base_data["pain_points"] = str(item.get("pain_points", "")).strip()
            base_data["recent_hires"] = str(item.get("recent_hires", "")).strip()
            base_data["funding_info"] = str(item.get("funding_info", "")).strip()
            base_data["industry_insights"] = str(item.get("industry_insights", "")).strip()
        
        normalized.append(base_data)

    return normalized
