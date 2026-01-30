# scrapers/enrichment.py
"""
Evidence-based enrichment extraction from scraped text.
LLMs extract facts ONLY - no invention, no inference without evidence.
"""
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import os
from dotenv import load_dotenv

load_dotenv()

def extract_company_signals(scraped_texts: List[Dict[str, Any]], min_confidence: float = 0.7) -> List[Dict[str, Any]]:
    """
    Extract verifiable signals from scraped company content.
    
    Args:
        scraped_texts: List of dicts with keys: source_url, raw_text, page_type, page_date
        min_confidence: Minimum confidence threshold (default 0.7)
    
    Returns:
        List of signal dicts with source links and confidence scores
    """
    if not scraped_texts:
        return []
    
    model_name = "meta-llama/llama-3.1-8b-instruct"
    llm = ChatOpenAI(
        model=model_name,
        temperature=0.1,  # Low temperature for factual extraction
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    
    all_signals = []
    cutoff_date = datetime.utcnow() - timedelta(days=90)
    
    for scraped in scraped_texts:
        source_url = scraped.get("source_url", "")
        raw_text = scraped.get("raw_text", "")
        page_date = scraped.get("page_date")
        
        # Skip if text too short
        if len(raw_text) < 100:
            continue
        
        # Skip if page is too old (for recent signals)
        if page_date and page_date < cutoff_date:
            continue  # Still extract, but mark as not recent
        
        prompt_template = """
You are a fact extraction system. Extract ONLY verifiable facts from the provided scraped web content.

RULES (STRICT):
1. Extract ONLY facts that are explicitly stated in the text
2. Do NOT infer, assume, or invent anything
3. If a fact is unclear or missing, mark confidence as 0.0
4. For each signal, provide the EXACT source text snippet (50-100 characters)
5. If text says "might", "could", "possibly" → confidence must be < 0.5
6. If text says "announced", "launched", "raised" → confidence can be 1.0 (direct statement)

Input text from {source_url}:
{raw_text}

Extract the following signal types (ONLY if explicitly mentioned):
- funding_round: Recent funding announcements (amount, date, investors) - must have specific numbers
- product_launch: New product or feature launches (product name, date) - must have product name
- hiring_signal: Hiring announcements or job postings (role, department, date) - must have role mentioned
- company_announcement: Press releases or major announcements (topic, date) - must have specific topic
- pain_point: Explicitly stated challenges or problems (problem description) - must be direct quote

For each signal found, return:
{{
    "signal_type": "funding_round",
    "signal_text": "Exact quote or summary from text",
    "source_snippet": "Exact text snippet from source (50-100 chars)",
    "confidence": 0.9,
    "date_mentioned": "2024-01-15" or null
}}

Return JSON array. If no signals found, return empty array [].
Do NOT include any signals with confidence < {min_confidence}.
"""
        
        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | llm
        
        try:
            response = chain.invoke({
                "source_url": source_url,
                "raw_text": raw_text[:5000],  # Limit text length
                "min_confidence": min_confidence
            })
            
            content = response.content.strip()
            
            # Try to parse JSON
            try:
                # Remove markdown code blocks if present
                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
                
                signals = json.loads(content)
                
                if isinstance(signals, list):
                    for signal in signals:
                        # Validate signal
                        if not isinstance(signal, dict):
                            continue
                        
                        # Require source_snippet
                        if not signal.get("source_snippet"):
                            continue
                        
                        # Check confidence threshold
                        confidence = float(signal.get("confidence", 0.0))
                        if confidence < min_confidence:
                            continue
                        
                        # Check for inference words (reduce confidence)
                        signal_text_lower = signal.get("signal_text", "").lower()
                        if any(word in signal_text_lower for word in ["might", "could", "possibly", "seems", "appears"]):
                            confidence = max(0.0, confidence - 0.3)
                            if confidence < min_confidence:
                                continue
                        
                        # Add source URL
                        signal["source_url"] = source_url
                        signal["confidence"] = confidence
                        all_signals.append(signal)
                        
            except json.JSONDecodeError:
                # LLM didn't return valid JSON - skip this page
                continue
                
        except Exception as e:
            # Log error but continue
            print(f"⚠️  Error extracting signals from {source_url}: {e}")
            continue
    
    return all_signals


def extract_person_signals(scraped_texts: List[Dict[str, Any]], person_name: str, min_confidence: float = 0.7) -> List[Dict[str, Any]]:
    """
    Extract verifiable signals about a person from scraped content.
    """
    if not scraped_texts:
        return []
    
    model_name = "meta-llama/llama-3.1-8b-instruct"
    llm = ChatOpenAI(
        model=model_name,
        temperature=0.1,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    
    all_signals = []
    
    for scraped in scraped_texts:
        source_url = scraped.get("source_url", "")
        raw_text = scraped.get("raw_text", "")
        
        if len(raw_text) < 50:
            continue
        
        prompt_template = """
Extract verifiable facts about {person_name} from scraped content.

RULES (STRICT):
1. Extract ONLY facts explicitly stated
2. Link each fact to source text snippet
3. Do NOT infer intent or opinions
4. If fact is unclear, confidence must be < 0.5

Signal types:
- recent_activity: Recent posts, comments, or public activity (must have date or "recent")
- role_change: Promotions, role changes, new positions (must have specific role)
- public_statement: Quotes, interviews, or public statements (must be direct quote)
- industry_commentary: Comments on industry trends (must be direct quote)

For each signal:
{{
    "signal_type": "recent_activity",
    "signal_text": "Exact quote or summary",
    "source_snippet": "Exact text snippet (50-100 chars)",
    "confidence": 0.9,
    "date_mentioned": "2024-01-15" or null
}}

Return JSON array. If no signals found, return [].
Do NOT include signals with confidence < {min_confidence}.
"""
        
        prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = prompt | llm
        
        try:
            response = chain.invoke({
                "person_name": person_name,
                "raw_text": raw_text[:3000],
                "min_confidence": min_confidence
            })
            
            content = response.content.strip()
            
            try:
                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
                
                signals = json.loads(content)
                
                if isinstance(signals, list):
                    for signal in signals:
                        if not isinstance(signal, dict) or not signal.get("source_snippet"):
                            continue
                        
                        confidence = float(signal.get("confidence", 0.0))
                        if confidence < min_confidence:
                            continue
                        
                        signal["source_url"] = source_url
                        signal["confidence"] = confidence
                        all_signals.append(signal)
                        
            except json.JSONDecodeError:
                continue
                
        except Exception:
            continue
    
    return all_signals


def summarize_company_focus(scraped_texts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract company focus/industry from scraped text.
    Returns dict with industry, product, target_customer, source_snippets, confidence.
    """
    if not scraped_texts:
        return {
            "industry": "NOT FOUND",
            "product": "NOT FOUND",
            "target_customer": "NOT FOUND",
            "source_snippets": {},
            "confidence": 0.0
        }
    
    # Combine all text (prioritize homepage and about pages)
    combined_text = ""
    for scraped in scraped_texts:
        page_type = scraped.get("page_type", "")
        if page_type in ("homepage", "about"):
            combined_text += scraped.get("raw_text", "") + "\n\n"
    
    if not combined_text:
        # Fallback to all text
        combined_text = "\n\n".join(s.get("raw_text", "") for s in scraped_texts)
    
    if len(combined_text) < 100:
        return {
            "industry": "NOT FOUND",
            "product": "NOT FOUND",
            "target_customer": "NOT FOUND",
            "source_snippets": {},
            "confidence": 0.0
        }
    
    model_name = "meta-llama/llama-3.1-8b-instruct"
    llm = ChatOpenAI(
        model=model_name,
        temperature=0.1,
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    
    prompt_template = """
From the scraped company website content, extract:
1. Primary industry or vertical
2. Main product or service offering
3. Target customer segment

RULES (STRICT):
- Use ONLY information explicitly stated on website
- If unclear, mark as "NOT FOUND"
- Provide source text snippet for each claim (50-100 chars)
- Confidence: 1.0 if direct quote, 0.5-0.8 if clearly stated, < 0.5 if inferred

Content:
{combined_text}

Return JSON:
{{
    "industry": "B2B SaaS" or "NOT FOUND",
    "product": "CRM software" or "NOT FOUND",
    "target_customer": "SMBs" or "NOT FOUND",
    "source_snippets": {{
        "industry": "exact text from website",
        "product": "exact text from website",
        "target_customer": "exact text from website"
    }},
    "confidence": 0.0 to 1.0
}}
"""
    
    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm
    
    try:
        response = chain.invoke({
            "combined_text": combined_text[:5000]
        })
        
        content = response.content.strip()
        
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()
        
        result = json.loads(content)
        
        # Validate
        if not isinstance(result, dict):
            return {
                "industry": "NOT FOUND",
                "product": "NOT FOUND",
                "target_customer": "NOT FOUND",
                "source_snippets": {},
                "confidence": 0.0
            }
        
        # Ensure all fields present
        result.setdefault("industry", "NOT FOUND")
        result.setdefault("product", "NOT FOUND")
        result.setdefault("target_customer", "NOT FOUND")
        result.setdefault("source_snippets", {})
        result.setdefault("confidence", 0.0)
        
        return result
        
    except Exception:
        return {
            "industry": "NOT FOUND",
            "product": "NOT FOUND",
            "target_customer": "NOT FOUND",
            "source_snippets": {},
            "confidence": 0.0
        }


def store_enrichment_signals(
    signals: List[Dict[str, Any]],
    company_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    db=None
) -> int:
    """
    Store enrichment signals in database.
    Returns number of signals stored.
    """
    try:
        from db.session import SessionLocal
        from db.models import EnrichmentSignal
        from datetime import datetime
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            stored_count = 0
            
            for signal in signals:
                # Parse date if present
                date_mentioned = None
                if signal.get("date_mentioned"):
                    try:
                        from dateutil import parser
                        date_mentioned = parser.parse(signal["date_mentioned"])
                    except:
                        pass
                
                enrichment_signal = EnrichmentSignal(
                    lead_id=lead_id,
                    company_id=company_id,
                    signal_type=signal.get("signal_type", ""),
                    signal_text=signal.get("signal_text", ""),
                    source_text=signal.get("source_snippet", ""),
                    source_url=signal.get("source_url", ""),
                    confidence=float(signal.get("confidence", 0.0)),
                    extracted_at=datetime.utcnow(),
                )
                db.add(enrichment_signal)
                stored_count += 1
            
            db.commit()
            return stored_count
        except Exception:
            db.rollback()
            return 0
        finally:
            if should_close:
                db.close()
    except ImportError:
        return 0
    except Exception:
        return 0
