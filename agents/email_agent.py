# agents/email_agent.py
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate 
import os
import json
from typing import Dict, Any, Optional, List, Tuple
from dotenv import load_dotenv

load_dotenv()

def _log_ai_decision(
    decision_type: str,
    input_evidence: Dict[str, Any],
    output: str,
    model: str
) -> None:
    """
    Log AI decision to database for audit trail.
    Fails silently if database unavailable (preserves existing behavior).
    """
    try:
        from db.session import SessionLocal
        from db.models import AIDecision
        from datetime import datetime
        
        db = SessionLocal()
        try:
            decision = AIDecision(
                decision_type=decision_type,
                input_evidence=input_evidence,
                output=output,
                model=model,
                created_at=datetime.utcnow(),
            )
            db.add(decision)
            db.commit()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to log AI decision: {e}")
            db.rollback()
        finally:
            db.close()
    except ImportError:
        # Database not available - silently fail
        pass


def generate_email(
    name: str, 
    company: str, 
    linkedin_info: str = "",
    company_enrichment: Optional[Dict[str, Any]] = None,
    person_enrichment: Optional[Dict[str, Any]] = None,
    personalization_level: str = "high",
    campaign_name: Optional[str] = None,
    campaign_offer: Optional[str] = None,
) -> str:
    """
    Generate personalized email using LLM with optional enrichment data.
    Logs decision to ai_decisions table for audit trail.
    
    Args:
        name: Recipient name
        company: Company name
        linkedin_info: LinkedIn URL or info
        company_enrichment: Dict with company enrichment (news, funding, etc.)
        person_enrichment: Dict with person enrichment (activity, insights, etc.)
        personalization_level: "low", "medium", or "high"
        campaign_name: Campaign name (for context)
        campaign_offer: What we're pitching in this campaign (e.g. "Done-For-You email automation", "Intelpatch")
    """
    model_name = "meta-llama/llama-3.1-8b-instruct"
    
    # Use OpenRouter
    llm = ChatOpenAI(
        model=model_name,  # OpenRouter uses provider/model naming
        temperature=0.5,
        api_key=os.getenv("OPENROUTER_API_KEY"),  # ← your OpenRouter key
        base_url="https://openrouter.ai/api/v1"
    )
    
    # Build enrichment context based on personalization level
    enrichment_context = ""
    if personalization_level == "high" and (company_enrichment or person_enrichment):
        enrichment_context = "\n\nENRICHMENT CONTEXT (USE THIS FOR PERSONALIZATION):\n"
        
        if company_enrichment:
            if company_enrichment.get("recent_news"):
                enrichment_context += f"Company News: {company_enrichment.get('recent_news')}\n"
            if company_enrichment.get("latest_funding"):
                enrichment_context += f"Latest Funding: {company_enrichment.get('latest_funding')}\n"
            if company_enrichment.get("recent_hires"):
                enrichment_context += f"Recent Hires: {company_enrichment.get('recent_hires')}\n"
            if company_enrichment.get("product_updates"):
                enrichment_context += f"Product Updates: {company_enrichment.get('product_updates')}\n"
            if company_enrichment.get("pain_points"):
                enrichment_context += f"Pain Points: {company_enrichment.get('pain_points')}\n"
            if company_enrichment.get("growth_metrics"):
                enrichment_context += f"Growth Metrics: {company_enrichment.get('growth_metrics')}\n"
        
        if person_enrichment:
            if person_enrichment.get("recent_activity"):
                enrichment_context += f"Person's Recent Activity: {person_enrichment.get('recent_activity')}\n"
            if person_enrichment.get("company_news"):
                enrichment_context += f"Person's Company News: {person_enrichment.get('company_news')}\n"
            if person_enrichment.get("pain_points"):
                enrichment_context += f"Person's Pain Points: {person_enrichment.get('pain_points')}\n"
            if person_enrichment.get("industry_insights"):
                enrichment_context += f"Industry Insights: {person_enrichment.get('industry_insights')}\n"
    
    # Campaign-specific pitch: what we're offering in this campaign
    campaign_section = ""
    if campaign_offer or campaign_name:
        campaign_section = "\nCAMPAIGN / WHAT YOU ARE PITCHING (tailor the solution sentence to this):\n"
        if campaign_offer:
            campaign_section += f"- Offer: {campaign_offer}\n"
        if campaign_name:
            campaign_section += f"- Campaign name: {campaign_name}\n"
        campaign_section += "The second sentence MUST pitch this specific offer, not a generic AI outbound message.\n"
    
    prompt_template = """
You are a direct-response outbound writer.

Task:
You are a B2B outbound specialist. 
Write a **short, outcome-driven cold email** to {name} at {company}.
{enrichment_context}
{campaign_section}
STRUCTURE (STRICT):
1) First sentence → Personalised hook using *specific* observations from the enrichment context above.
   Use as much relevant detail as you have: recent news, funding, hires, pain points. Be specific.
2) Second sentence → Solution pitch for THIS campaign's offer (see CAMPAIGN section above).
   If no campaign is specified, use: AI outbound automation that writes, sends, validates, and books calls.
3) Third sentence → Risk-free CTA: e.g. "Let's run a 7-day pilot. If you don't see results, you walk away. Deal?"

WRITING RULES:
- No preamble — only the email body.
- 55–75 words. Use ALL relevant enrichment — do not skip details.
- Zero praise, zero compliments — only relevance → pain → outcome.
- Strong verbs. No intros, no fluff.
- USE the enrichment context fully. Reference multiple data points if available.

SIGN-OFF:  
Alay
    """
    
    prompt = ChatPromptTemplate.from_template(prompt_template)
    
    # Prepare input evidence for logging
    input_evidence = {
        "name": name,
        "company": company,
        "linkedin_info": linkedin_info or "No extra info",
        "company_enrichment": company_enrichment,
        "person_enrichment": person_enrichment,
        "personalization_level": personalization_level,
        "campaign_name": campaign_name,
        "campaign_offer": campaign_offer,
        "model": model_name,
        "temperature": 0.5,
    }
    
    chain = prompt | llm
    response = chain.invoke({
        "name": name,
        "company": company,
        "linkedin_info": linkedin_info or "No extra info",
        "enrichment_context": enrichment_context or "No additional context available.",
        "campaign_section": campaign_section or "",
    })
    
    email_body = response.content.strip()
    
    # Log decision to database
    _log_ai_decision(
        decision_type="email_generation",
        input_evidence=input_evidence,
        output=email_body,
        model=model_name,
    )
    
    return email_body


def should_send_email(
    verified_signals: List[Dict[str, Any]],
    email_body: str,
    min_confidence: float = 0.7,
    require_signal: bool = False
) -> Tuple[bool, str]:
    """
    Decision logic for whether email should be sent.
    
    Args:
        verified_signals: List of signals from enrichment_signals table
        email_body: Generated email body
        min_confidence: Minimum confidence threshold
        require_signal: If True, require at least one verified signal
    
    Returns:
        (should_send: bool, reason: str)
    """
    # Check if email has any verified signals
    has_verified_signal = any(s.get("confidence", 0.0) >= min_confidence for s in verified_signals)
    
    if require_signal and not has_verified_signal:
        return (False, "No verified signals meet confidence threshold")
    
    # Check email quality
    word_count = len(email_body.split())
    if word_count < 30:
        return (False, f"Email too short ({word_count} words, minimum 30)")
    
    if word_count > 100:
        return (False, f"Email too long ({word_count} words, maximum 100)")
    
    # Check sentence count
    sentences = email_body.split('.')
    sentence_count = len([s for s in sentences if s.strip()])
    if sentence_count < 3:
        return (False, f"Email has too few sentences ({sentence_count}, minimum 3)")
    if sentence_count > 5:
        return (False, f"Email has too many sentences ({sentence_count}, maximum 5)")
    
    # Check for forbidden marketing language
    forbidden_words = ["amazing", "incredible", "guaranteed", "best", "top", "perfect", "revolutionary"]
    email_lower = email_body.lower()
    found_forbidden = [word for word in forbidden_words if word in email_lower]
    if found_forbidden:
        return (False, f"Email contains forbidden marketing language: {', '.join(found_forbidden)}")
    
    # Check for links
    if "http://" in email_body or "https://" in email_body or "www." in email_body:
        return (False, "Email contains links (not allowed)")
    
    # Check for emojis (basic check)
    # Allow common punctuation but flag obvious emojis
    if any(ord(char) > 127 and char not in email_body.encode('ascii', 'ignore').decode('ascii') for char in email_body):
        # More sophisticated emoji detection could be added
        pass  # Allow for now but could be enhanced
    
    return (True, "Email approved")


def generate_evidence_based_email(
    name: str,
    company: str,
    role: str,
    verified_signals: List[Dict[str, Any]],
    company_focus: Optional[Dict[str, Any]] = None,
    company_enrichment: Optional[Dict[str, Any]] = None,
    person_enrichment: Optional[Dict[str, Any]] = None,
    min_confidence: float = 0.7,
    campaign_name: Optional[str] = None,
    campaign_offer: Optional[str] = None,
) -> str:
    """
    Generate email using ALL verified signals and enrichment from scraped content.
    Campaign-aware: tailors the pitch to campaign_offer (e.g. "Done-For-You email automation", "Intelpatch").
    
    Args:
        name: Recipient name
        company: Company name
        role: Person's role
        verified_signals: List of signals from enrichment_signals table
        company_focus: Company focus dict from summarize_company_focus()
        company_enrichment: Optional dict (recent_news, latest_funding, etc.) from scraping/Perplexity
        person_enrichment: Optional dict (recent_activity, pain_points, etc.)
        min_confidence: Minimum confidence to use signal
        campaign_name: Campaign name (for context)
        campaign_offer: What we're pitching in this campaign
    
    Returns:
        Email body text
    """
    model_name = "meta-llama/llama-3.1-8b-instruct"
    
    llm = ChatOpenAI(
        model=model_name,
        temperature=0.3,  # Lower temperature for factual content
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )
    
    # Filter signals by confidence — use ALL usable signals (up to 15)
    usable_signals = [s for s in verified_signals if s.get("confidence", 0.0) >= min_confidence][:15]
    
    # Format ALL verified signals for the prompt
    signals_text = ""
    if usable_signals:
        signals_text = "VERIFIED SIGNALS FROM SCRAPED CONTENT (use as many as relevant for personalization):\n"
        for i, s in enumerate(usable_signals, 1):
            signals_text += f"{i}. [{s.get('signal_type', 'unknown')}] {s.get('signal_text', '')} (confidence: {s.get('confidence', 0):.2f})\n"
        signals_text += "Reference specific details from the above. You may use multiple signals if they fit naturally.\n"
    else:
        signals_text = "No verified signals available - write generic email without specific references."
    
    # Format company focus
    focus_text = ""
    if company_focus:
        focus_text = """
COMPANY FOCUS (from scraped website):
- Industry: {industry}
- Product: {product}
- Target: {target}
""".format(
            industry=company_focus.get('industry', 'NOT FOUND'),
            product=company_focus.get('product', 'NOT FOUND'),
            target=company_focus.get('target_customer', 'NOT FOUND'),
        )
    
    # Additional enrichment (from Perplexity/scraping stored on Company/Lead)
    extra_enrichment = ""
    if company_enrichment:
        extra_enrichment += "\nADDITIONAL COMPANY CONTEXT:\n"
        for k, v in company_enrichment.items():
            if v and str(v).strip():
                extra_enrichment += f"- {k}: {v}\n"
    if person_enrichment:
        extra_enrichment += "\nADDITIONAL PERSON CONTEXT:\n"
        for k, v in person_enrichment.items():
            if v and str(v).strip():
                extra_enrichment += f"- {k}: {v}\n"
    
    # Campaign-specific pitch
    campaign_section = ""
    if campaign_offer or campaign_name:
        campaign_section = "\nCAMPAIGN / WHAT YOU ARE PITCHING (tailor the solution sentence to this):\n"
        if campaign_offer:
            campaign_section += f"- Offer: {campaign_offer}\n"
        if campaign_name:
            campaign_section += f"- Campaign name: {campaign_name}\n"
        campaign_section += "The second sentence MUST pitch this specific offer, not a generic message.\n"
    
    prompt_template = """
You are a direct-response outbound writer. Write a short, evidence-based cold email.

RULES:
1. Use the verified signals and company/person context below. Utilize as much relevant detail as possible — do not ignore data.
2. Reference specific facts with neutral, factual language. NO hype or flattery. Do NOT invent facts.
3. Maximum 3-5 sentences, 50-85 words total. Plain text only. NO links, NO emojis.
4. NO marketing language (no "amazing", "incredible", "best", "guaranteed"). Neutral, professional tone.

{signals_text}

{focus_text}
{extra_enrichment}
{campaign_section}

PERSON:
Name: {name}
Role: {role}
Company: {company}

EMAIL STRUCTURE:
1. One or two sentences: personalised hook using specific details from the signals/context above. Use multiple data points if relevant.
2. One sentence: pitch THIS campaign's offer (see CAMPAIGN section). If no campaign, use AI outbound automation.
3. One sentence: low-friction CTA (e.g. 7-day pilot, walk away if no results).

Do NOT mention source URLs in the email. Return ONLY the email body. No preamble.
"""
    
    prompt = ChatPromptTemplate.from_template(prompt_template)
    
    input_evidence = {
        "name": name,
        "company": company,
        "role": role,
        "verified_signals": verified_signals,
        "company_focus": company_focus,
        "company_enrichment": company_enrichment,
        "person_enrichment": person_enrichment,
        "min_confidence": min_confidence,
        "campaign_name": campaign_name,
        "campaign_offer": campaign_offer,
        "model": model_name,
    }
    
    chain = prompt | llm
    response = chain.invoke({
        "name": name,
        "company": company,
        "role": role,
        "signals_text": signals_text,
        "focus_text": focus_text,
        "extra_enrichment": extra_enrichment,
        "campaign_section": campaign_section,
    })
    
    email_body = response.content.strip()
    
    # Log decision
    _log_ai_decision(
        decision_type="email_generation_evidence_based",
        input_evidence=input_evidence,
        output=email_body,
        model=model_name,
    )
    
    return email_body

