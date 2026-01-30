# Evidence-Based Scraping & Enrichment Design

## TASK 1 — SCRAPING PIPELINE DESIGN

### Current State Analysis

**Existing Code:**
- `scrapers/google_scraper.py` (lines 5-32): Playwright-based Google search for LinkedIn companies
- `scrapers/discovery.py` (lines 125-203, 206-281): Perplexity API calls for company/people discovery
- `scrapers/linkedin_parser.py` (lines 5-40): CSV parser/mock (not real scraping)

**Integration Points:**
- `main.py:147-163`: Calls `search_companies()` from discovery.py
- `main.py:162`: Calls `search_people()` from discovery.py
- `scrapers/discovery.py:125-203`: `search_companies()` uses Perplexity (NOT real scraping)
- `scrapers/discovery.py:206-281`: `search_people()` uses Perplexity (NOT real scraping)

### New Scraping Pipeline Design

#### Module: `scrapers/web_scraper.py` (NEW)

**Purpose:** Real web scraping of company websites and public pages

**Functions:**
1. `scrape_company_website(domain: str) -> Dict[str, Any]`
   - Input: Company domain (e.g., "example.com")
   - Scrapes: homepage, /about, /team, /blog, /news, /press
   - Returns: Dict with raw text, URLs, page types, timestamps
   - Uses: Requests + BeautifulSoup (fast) OR Playwright (if JS required)

2. `scrape_company_blog(domain: str, max_posts: int = 10) -> List[Dict]`
   - Scrapes blog/news pages
   - Extracts: post titles, dates, content snippets
   - Filters: Last 90 days only
   - Returns: List of post dicts with source URLs

3. `scrape_about_page(domain: str) -> Dict[str, Any]`
   - Scrapes /about, /team, /company pages
   - Extracts: company description, team info, mission
   - Returns: Raw text with source URL

4. `scrape_person_public_page(person_url: str) -> Dict[str, Any]`
   - Input: Public profile URL (LinkedIn public, company bio, etc.)
   - Scrapes: Public profile information
   - Returns: Raw text, role, bio, recent activity (if public)

**Storage Schema:**
```python
# New table: scraped_content
{
    "id": int,
    "company_id": int (FK),
    "person_id": int (FK, nullable),
    "source_url": str,
    "page_type": str,  # "homepage", "blog", "about", "team", "person_profile"
    "raw_text": Text,
    "scraped_at": DateTime,
    "page_date": DateTime (nullable),  # If page has published date
    "content_hash": str  # For deduplication
}
```

**Playwright vs Requests Decision:**
- **Requests + BeautifulSoup**: Default for static HTML (faster, lower resource)
- **Playwright**: Fallback if:
  - Requests fails (403, timeout)
  - Page requires JavaScript rendering
  - Dynamic content detected
- **Detection Logic**: Try Requests first, fallback to Playwright on failure

#### Module: `scrapers/url_discovery.py` (NEW)

**Purpose:** Discover URLs to scrape from company domain

**Functions:**
1. `discover_company_urls(domain: str) -> List[str]`
   - Tries common paths: /about, /team, /blog, /news, /press, /careers
   - Checks robots.txt for allowed paths
   - Returns: List of valid URLs to scrape

2. `discover_blog_urls(domain: str) -> List[str]`
   - Finds blog index page
   - Discovers recent post URLs
   - Returns: List of blog post URLs

**Integration:**
- Called by `scrape_company_website()` before scraping
- Reuses existing `scrapers/google_scraper.py` Playwright setup if needed

### Integration with Current Code

**File: `scrapers/discovery.py`**
- **KEEP**: `perplexity_api_call()` function (lines 23-122) - still used for initial discovery
- **MODIFY**: `search_companies()` (lines 125-203)
  - Current: Uses Perplexity as PRIMARY source
  - New: Uses Perplexity for INITIAL discovery only, then scrapes real websites
  - Flow: Perplexity → get domains → scrape websites → return enriched data

- **MODIFY**: `search_people()` (lines 206-281)
  - Current: Uses Perplexity as PRIMARY source
  - New: Uses Perplexity for names/roles, then scrapes public pages if available
  - Flow: Perplexity → get names → scrape public profiles → return enriched data

**File: `main.py`**
- **NO CHANGES** to function signatures
- Scraping happens inside `search_companies()` and `search_people()`
- Existing flow preserved: `scrape_leads()` → `search_companies()` → `search_people()`

**File: `scrapers/google_scraper.py`**
- **REUSE**: Playwright setup (lines 11-30)
- **EXTEND**: Add website scraping functions using same Playwright instance

### New Database Tables

**Table: `scraped_content`**
```python
class ScrapedContent(Base):
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=True)
    source_url = Column(String, nullable=False)
    page_type = Column(String)  # "homepage", "blog", "about", "team", "person_profile"
    raw_text = Column(Text)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    page_date = Column(DateTime, nullable=True)  # Published date if available
    content_hash = Column(String)  # SHA256 for deduplication
```

**Table: `enrichment_signals`**
```python
class EnrichmentSignal(Base):
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    signal_type = Column(String)  # "funding", "launch", "hiring", "announcement", "pain_point"
    signal_text = Column(Text)  # The extracted signal
    source_text = Column(Text)  # Original scraped text this came from
    source_url = Column(String)  # URL where signal was found
    confidence = Column(Float)  # 0.0 to 1.0
    extracted_at = Column(DateTime, default=datetime.utcnow)
```

---

## TASK 2 — ENRICHMENT PIPELINE (STRICT EVIDENCE MODE)

### Enrichment Pipeline Design

#### Module: `scrapers/enrichment.py` (NEW)

**Purpose:** Extract verifiable facts from scraped raw text ONLY

**Input:** Scraped raw text from `scraped_content` table
**Output:** Structured enrichment with source links and confidence scores

#### Function: `extract_company_signals(scraped_texts: List[Dict]) -> List[Dict]`

**Input Schema:**
```python
[
    {
        "source_url": "https://example.com/blog/post",
        "raw_text": "... actual scraped HTML text ...",
        "page_type": "blog",
        "page_date": "2024-01-15"
    },
    ...
]
```

**LLM Prompt Template:**
```
You are a fact extraction system. Extract ONLY verifiable facts from the provided scraped web content.

RULES:
1. Extract ONLY facts that are explicitly stated in the text
2. Do NOT infer, assume, or invent anything
3. If a fact is unclear or missing, mark confidence as 0.0
4. For each signal, provide the EXACT source text snippet

Input text from {source_url}:
{raw_text}

Extract the following signal types (ONLY if explicitly mentioned):
- funding_round: Recent funding announcements (amount, date, investors)
- product_launch: New product or feature launches (product name, date)
- hiring_signal: Hiring announcements or job postings (role, department, date)
- company_announcement: Press releases or major announcements (topic, date)
- pain_point: Explicitly stated challenges or problems (problem description)

For each signal found, return:
{
    "signal_type": "funding_round",
    "signal_text": "Exact quote or summary from text",
    "source_snippet": "Exact text snippet from source (50-100 chars)",
    "confidence": 0.9,  # 1.0 if direct quote, lower if inferred
    "date_mentioned": "2024-01-15" or null
}

Return JSON array. If no signals found, return empty array [].
```

**Output Schema:**
```python
[
    {
        "signal_type": "funding_round",
        "signal_text": "Raised $5M Series A led by XYZ Ventures",
        "source_snippet": "... raised $5M Series A led by XYZ Ventures in January 2024 ...",
        "confidence": 1.0,  # Direct quote
        "date_mentioned": "2024-01-15",
        "source_url": "https://example.com/blog/post"
    },
    ...
]
```

**Validation Rules:**
1. `confidence < 0.7` → Signal rejected (not verifiable enough)
2. `source_snippet` missing → Signal rejected
3. `signal_text` contains "likely", "probably", "seems" → Confidence reduced by 0.3
4. Date mentioned must be within last 90 days for recent signals

**Fallback Behavior:**
- If no signals extracted → Return empty list
- If LLM fails → Log error, return empty list
- If text is too short (< 100 chars) → Skip extraction

#### Function: `extract_person_signals(scraped_texts: List[Dict], person_name: str) -> List[Dict]`

**Similar to company signals but focused on:**
- Recent LinkedIn posts or activity
- Public statements or interviews
- Role changes or promotions
- Industry commentary

**Prompt Template:**
```
Extract verifiable facts about {person_name} from scraped content.

RULES:
1. Extract ONLY facts explicitly stated
2. Link each fact to source text snippet
3. Do NOT infer intent or opinions

Signal types:
- recent_activity: Recent posts, comments, or public activity
- role_change: Promotions, role changes, new positions
- public_statement: Quotes, interviews, or public statements
- industry_commentary: Comments on industry trends (must be direct quote)

Return JSON array with same schema as company signals.
```

#### Function: `summarize_company_focus(scraped_texts: List[Dict]) -> Dict[str, Any]`

**Purpose:** Extract company focus/industry from scraped text

**Prompt Template:**
```
From the scraped company website content, extract:
1. Primary industry or vertical
2. Main product or service offering
3. Target customer segment

RULES:
- Use ONLY information explicitly stated on website
- If unclear, mark as "NOT FOUND"
- Provide source text snippet for each claim

Return:
{
    "industry": "B2B SaaS" or "NOT FOUND",
    "product": "CRM software" or "NOT FOUND",
    "target_customer": "SMBs" or "NOT FOUND",
    "source_snippets": {
        "industry": "exact text from website",
        "product": "exact text from website",
        "target_customer": "exact text from website"
    },
    "confidence": 0.0 to 1.0
}
```

**Output Schema:**
```python
{
    "industry": str,
    "product": str,
    "target_customer": str,
    "source_snippets": Dict[str, str],
    "confidence": float
}
```

### Integration Points

**File: `scrapers/discovery.py`**
- **MODIFY**: `search_companies()` (lines 125-203)
  - After Perplexity returns domains:
    1. Call `scrape_company_website()` for each domain
    2. Store scraped content in `scraped_content` table
    3. Call `extract_company_signals()` with scraped text
    4. Store signals in `enrichment_signals` table
    5. Return company dict with enrichment data

- **MODIFY**: `search_people()` (lines 206-281)
  - After Perplexity returns people:
    1. For each person with public URL, call `scrape_person_public_page()`
    2. Store scraped content
    3. Call `extract_person_signals()` with scraped text
    4. Store signals
    5. Return person dict with enrichment data

**File: `utils/writer.py`**
- **NO CHANGES** - enrichment data stored separately in `enrichment_signals` table
- Lead creation unchanged

---

## TASK 3 — EMAIL PERSONALIZATION (ANTI-SPAM GUARANTEES)

### Email Generation Redesign

#### Module: `agents/email_agent.py` (MODIFY)

**Current Function:** `generate_email()` (lines 48-164)
- **PROBLEM**: Uses enrichment data that may be invented by Perplexity
- **SOLUTION**: Only use verified signals from `enrichment_signals` table

#### New Function: `generate_evidence_based_email()`

**Input Schema:**
```python
{
    "name": str,
    "company": str,
    "role": str,
    "verified_signals": List[Dict],  # From enrichment_signals table
    "company_focus": Dict,  # From summarize_company_focus()
    "min_confidence": float = 0.7  # Minimum confidence to use signal
}
```

**LLM Prompt Template:**
```
You are a direct-response outbound writer. Write a short, evidence-based cold email.

RULES (STRICT):
1. Use AT MOST ONE verified signal from the list below
2. Reference the signal with neutral, factual language
3. Do NOT invent facts, events, or assumptions
4. If no signals meet confidence threshold, write generic email
5. Maximum 3-5 sentences
6. Plain text only (no links, no emojis, no formatting)
7. No marketing language, hype, or flattery
8. Neutral, professional tone

VERIFIED SIGNALS (use only if confidence >= {min_confidence}):
{verified_signals_list}

COMPANY FOCUS:
{company_focus}

PERSON:
Name: {name}
Role: {role}
Company: {company}

EMAIL STRUCTURE:
1. One sentence referencing ONE verified signal (if available) OR generic industry observation
2. One sentence about the solution (AI outbound automation)
3. One sentence with low-friction CTA

If no verified signals available, write generic email without specific references.

Return ONLY the email body text. No preamble, no explanations.
```

**Signal Formatting for Prompt:**
```python
verified_signals_list = ""
for signal in verified_signals:
    if signal["confidence"] >= min_confidence:
        verified_signals_list += f"- {signal['signal_type']}: {signal['signal_text']} (Source: {signal['source_url']}, Confidence: {signal['confidence']})\n"
```

**Output Validation:**
1. Check word count: Must be 3-5 sentences, 40-80 words
2. Check for forbidden words: "amazing", "incredible", "best", "guaranteed" → Reject
3. Check for links/URLs → Remove or reject
4. Check for emojis → Remove
5. Check signal usage: If signal mentioned, verify it's in verified_signals list

**Decision Logic: `should_send_email()`**

```python
def should_send_email(
    verified_signals: List[Dict],
    email_body: str,
    min_confidence: float = 0.7,
    require_signal: bool = False
) -> tuple[bool, str]:
    """
    Returns (should_send: bool, reason: str)
    """
    # Check if email has any verified signals
    has_verified_signal = any(s["confidence"] >= min_confidence for s in verified_signals)
    
    if require_signal and not has_verified_signal:
        return (False, "No verified signals meet confidence threshold")
    
    # Check email quality
    if len(email_body.split()) < 30:
        return (False, "Email too short")
    
    if len(email_body.split()) > 100:
        return (False, "Email too long")
    
    # Check for forbidden patterns
    forbidden = ["amazing", "incredible", "guaranteed", "best", "top"]
    if any(word in email_body.lower() for word in forbidden):
        return (False, "Email contains forbidden marketing language")
    
    # Check for links
    if "http" in email_body or "www." in email_body:
        return (False, "Email contains links (not allowed)")
    
    # Check for emojis
    if any(ord(char) > 127 for char in email_body if char not in email_body.encode('ascii', 'ignore').decode('ascii')):
        # Simple emoji check - can be enhanced
        pass  # Allow for now, but log
    
    return (True, "Email approved")
```

**Examples of Blocked Sends:**
1. **Low Confidence Signal:**
   - Signal: "Company might be hiring" (confidence: 0.3)
   - Reason: "Signal confidence 0.3 below threshold 0.7"

2. **Missing Signal (if required):**
   - No verified signals found
   - Reason: "No verified signals meet confidence threshold"

3. **Marketing Language:**
   - Email contains: "amazing solution"
   - Reason: "Email contains forbidden marketing language"

4. **Links Present:**
   - Email contains: "Visit https://..."
   - Reason: "Email contains links (not allowed)"

### Integration

**File: `agents/email_agent.py`**
- **MODIFY**: `generate_email()` function
  - Add parameter: `verified_signals: List[Dict]`
  - Use new prompt template
  - Add `should_send_email()` check before returning

**File: `main.py`**
- **MODIFY**: `send_emails()` function (lines 30-100)
  - Before generating email:
    1. Query `enrichment_signals` table for lead
    2. Get verified signals with confidence >= 0.7
    3. Pass to `generate_email()` as `verified_signals`
  - After generating email:
    1. Call `should_send_email()` to check
    2. Only send if approved
    3. Log decision to database

**File: `streamlit_app.py`**
- **MODIFY**: Email sending in Actions tab
  - Same logic: Get verified signals, check before sending

---

## TASK 4 — DELIVERABILITY SAFETY (CODE-ENFORCED)

### Enhanced Deliverability Protections

#### Module: `agents/deliverability.py` (NEW)

**Purpose:** Code-enforced safety checks before sending

**Functions:**

1. `check_domain_throttle(domain: str, db=None) -> tuple[bool, str]`
   - Check sends to domain in last 24 hours
   - Limit: Max 3 emails per domain per day
   - Returns: (allowed: bool, reason: str)

2. `check_lead_suppression(lead_id: int, db=None) -> tuple[bool, str]`
   - Check if lead is blocked
   - Check bounce history
   - Returns: (allowed: bool, reason: str)

3. `check_send_decision(lead_id: int, email_body: str, db=None) -> Dict[str, Any]`
   - Combines all checks:
     - Domain throttle
     - Lead suppression
     - Rate limits (existing)
     - Email quality (from Task 3)
   - Returns: Decision dict with reason

**Integration:**

**File: `agents/gmail_service.py`**
- **MODIFY**: `send_email()` function (lines 62-98)
  - Before sending:
    1. Call `check_domain_throttle()` for recipient domain
    2. Call `check_lead_suppression()` if lead_id available
    3. If any check fails → return None with logged reason

**File: `agents/rate_limiter.py`**
- **KEEP**: Existing rate limiting (lines 6-145)
- **EXTEND**: Add domain-level throttling
  - New function: `check_domain_rate_limit(domain: str) -> bool`

**File: `agents/tracker.py`**
- **REUSE**: Existing bounce detection (lines 3-29)
- **EXTEND**: Auto-suppression logic
  - Function: `suppress_lead_on_bounce(lead_id: int, bounce_type: str) -> None`
  - Auto-blocks lead if hard bounce detected

**File: `main.py`**
- **MODIFY**: `send_emails()` function
  - Add deliverability checks before each send
  - Log all send decisions (allowed/blocked + reason)

### New Database Tables

**Table: `send_decisions`**
```python
class SendDecision(Base):
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, ForeignKey("leads.id"))
    email = Column(String)
    decision = Column(String)  # "allowed", "blocked", "throttled"
    reason = Column(String)
    email_body = Column(Text, nullable=True)  # Stored if blocked for review
    checked_at = Column(DateTime, default=datetime.utcnow)
```

**Table: `domain_throttle`**
```python
class DomainThrottle(Base):
    id = Column(Integer, primary_key=True)
    domain = Column(String, index=True)
    emails_sent_today = Column(Integer, default=0)
    last_sent_at = Column(DateTime)
    date = Column(DateTime, default=datetime.utcnow)
```

### Error Handling & Cooldown

**Function: `handle_send_error(error: Exception, domain: str, db=None) -> None`**
- On Gmail API error:
  1. Log error to `send_decisions` table
  2. If error is rate limit related → increase cooldown for domain
  3. If error is authentication → raise (don't suppress)
  4. If error is unknown → log and continue with next email

**Cooldown Logic:**
- Domain cooldown: If 2+ errors in 1 hour → block domain for 24 hours
- Global cooldown: If 5+ errors in 1 hour → pause all sends for 1 hour

---

## TASK 5 — STEPWISE IMPLEMENTATION PLAN

### Step 1: Database Schema Extension
**Goal:** Add tables for scraped content and enrichment signals

**Files Added:**
- None (modify existing)

**Files Modified:**
- `db/models.py`: Add `ScrapedContent`, `EnrichmentSignal`, `SendDecision`, `DomainThrottle` classes

**Behavior:**
- Old: No change (tables don't affect existing code)
- New: Tables available for scraping pipeline

**Verification:**
- Run `python scripts/init_db.py`
- Verify 4 new tables created
- Existing functionality unchanged

**Lines Changed:** ~150 lines

---

### Step 2: Web Scraping Module
**Goal:** Implement real website scraping

**Files Added:**
- `scrapers/web_scraper.py` (new, ~250 lines)
- `scrapers/url_discovery.py` (new, ~100 lines)

**Files Modified:**
- None (isolated module)

**Behavior:**
- Old: No change (not integrated yet)
- New: Can scrape company websites, blogs, about pages

**Verification:**
- Unit test: `scrape_company_website("example.com")` returns dict with raw_text
- Verify scraped content stored in database
- No impact on existing Perplexity flow

**Lines Changed:** ~350 lines (new files)

---

### Step 3: Enrichment Extraction Module
**Goal:** Extract signals from scraped text using LLM

**Files Added:**
- `scrapers/enrichment.py` (new, ~200 lines)

**Files Modified:**
- None (isolated module)

**Behavior:**
- Old: No change
- New: Can extract signals from scraped text with source links

**Verification:**
- Test with sample scraped text
- Verify signals extracted with confidence scores
- Verify source snippets included
- No impact on existing code

**Lines Changed:** ~200 lines (new file)

---

### Step 4: Integrate Scraping into Discovery
**Goal:** Replace Perplexity primary source with real scraping

**Files Modified:**
- `scrapers/discovery.py`:
  - `search_companies()` (lines 125-203): Add scraping after Perplexity
  - `search_people()` (lines 206-281): Add scraping after Perplexity

**Behavior:**
- Old: Returns Perplexity data only
- New: Perplexity for discovery → Real scraping → Enrichment → Return combined data
- **Preserves**: Perplexity still used for initial discovery (not removed)

**Verification:**
- Run `scrape_leads` command
- Verify scraped_content table populated
- Verify enrichment_signals table populated
- Existing CSV output still works

**Lines Changed:** ~100 lines (modifications)

---

### Step 5: Evidence-Based Email Generation
**Goal:** Use only verified signals in email generation

**Files Modified:**
- `agents/email_agent.py`:
  - `generate_email()` (lines 48-164): Add verified_signals parameter
  - Add `should_send_email()` function (~50 lines)
  - Update prompt template to use verified signals only

**Behavior:**
- Old: Uses enrichment data (may be invented)
- New: Uses only verified signals from database with confidence >= 0.7
- **Preserves**: Function signature backward compatible (verified_signals optional)

**Verification:**
- Generate email with verified signals → Check signal referenced
- Generate email without signals → Generic email (no invention)
- Test `should_send_email()` with various inputs
- Existing email sending still works

**Lines Changed:** ~150 lines (modifications)

---

### Step 6: Deliverability Safety Module
**Goal:** Add domain throttling and suppression checks

**Files Added:**
- `agents/deliverability.py` (new, ~200 lines)

**Files Modified:**
- `agents/gmail_service.py`: Add deliverability checks before send
- `agents/rate_limiter.py`: Add domain-level throttling
- `agents/tracker.py`: Add auto-suppression on bounce

**Behavior:**
- Old: Rate limiting only
- New: Domain throttling + lead suppression + bounce blocking
- **Preserves**: Existing rate limiting still works

**Verification:**
- Send 4 emails to same domain → 4th blocked
- Send to blocked lead → Blocked
- Send after bounce → Blocked
- Existing sends still work

**Lines Changed:** ~250 lines (new + modifications)

---

### Step 7: Integration in Main Flow
**Goal:** Wire everything together in main.py

**Files Modified:**
- `main.py`:
  - `send_emails()` (lines 30-100): Add verified signals query, deliverability checks
  - `scrape_leads()` (lines 147-267): Already calls search_companies/search_people (no change needed)

**Behavior:**
- Old: Sends emails with Perplexity-based enrichment
- New: Sends emails with verified signals only, checks deliverability
- **Preserves**: CLI interface unchanged, CSV output unchanged

**Verification:**
- Run `send-emails` command
- Verify send_decisions table logged
- Verify only verified signals used
- Existing functionality preserved

**Lines Changed:** ~80 lines (modifications)

---

### Step 8: Error Handling & Logging
**Goal:** Add comprehensive error handling and decision logging

**Files Modified:**
- `agents/gmail_service.py`: Add error handling with cooldown
- `agents/deliverability.py`: Add decision logging

**Behavior:**
- Old: Errors may cascade
- New: Errors logged, cooldowns applied, failures isolated
- **Preserves**: Existing error handling still works

**Verification:**
- Simulate Gmail API errors → Verify cooldown applied
- Check send_decisions table for all decisions
- Existing sends continue working

**Lines Changed:** ~100 lines (modifications)

---

## TOTAL ESTIMATED CHANGES

- New files: 4 (~750 lines)
- Modified files: 6 (~580 lines)
- Total: ~1330 lines across 10 files

Each step is independently runnable and preserves existing functionality.
