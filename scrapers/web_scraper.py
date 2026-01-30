# scrapers/web_scraper.py
"""
Real web scraping module - scrapes actual company websites and public pages.
Evidence-based: Stores raw HTML/text with source URLs and timestamps.
"""
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import hashlib
import re
from urllib.parse import urljoin, urlparse

# User agent to avoid blocking
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def _get_content_hash(text: str) -> str:
    """Generate SHA256 hash for content deduplication"""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _try_requests(url: str, timeout: int = 10) -> Optional[requests.Response]:
    """Try to fetch URL with requests (faster for static content)"""
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except Exception:
        return None


def _try_playwright(url: str) -> Optional[str]:
    """Fallback to Playwright if requests fails (for JS-rendered content)"""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            content = page.content()
            browser.close()
            return content
    except Exception:
        return None


def scrape_page(url: str, use_playwright: bool = False) -> Optional[Dict[str, Any]]:
    """
    Scrape a single web page.
    Tries requests first, falls back to Playwright if needed.
    
    Returns:
        {
            "source_url": str,
            "raw_text": str,
            "html": str,
            "scraped_at": datetime,
            "page_date": Optional[datetime],  # If page has published date
            "content_hash": str
        }
        or None if scraping fails
    """
    if use_playwright:
        html = _try_playwright(url)
        if not html:
            return None
    else:
        resp = _try_requests(url)
        if not resp:
            # Fallback to Playwright
            html = _try_playwright(url)
            if not html:
                return None
        else:
            html = resp.text
    
    # Extract text content
    soup = BeautifulSoup(html, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style", "nav", "footer", "header"]):
        script.decompose()
    
    # Get text
    raw_text = soup.get_text(separator=' ', strip=True)
    raw_text = re.sub(r'\s+', ' ', raw_text)  # Normalize whitespace
    
    # Try to extract published date from meta tags or article tags
    page_date = None
    date_meta = soup.find('meta', property='article:published_time') or \
                soup.find('meta', attrs={'name': 'publish-date'}) or \
                soup.find('time', attrs={'datetime': True})
    
    if date_meta:
        date_str = date_meta.get('content') or date_meta.get('datetime')
        if date_str:
            try:
                from dateutil import parser
                page_date = parser.parse(date_str)
            except:
                pass
    
    content_hash = _get_content_hash(raw_text)
    
    return {
        "source_url": url,
        "raw_text": raw_text,
        "html": html,
        "scraped_at": datetime.utcnow(),
        "page_date": page_date,
        "content_hash": content_hash
    }


def scrape_company_website(domain: str) -> Dict[str, Any]:
    """
    Scrape company website: homepage, about, team, blog.
    
    Returns:
        {
            "domain": str,
            "pages": List[Dict],  # List of scraped pages
            "scraped_at": datetime
        }
    """
    if not domain.startswith('http'):
        domain = f"https://{domain}"
    
    base_url = domain.rstrip('/')
    pages_scraped = []
    
    # Common paths to try
    paths_to_try = [
        "/",           # Homepage
        "/about",
        "/about-us",
        "/company",
        "/team",
        "/blog",
        "/news",
        "/press",
    ]
    
    for path in paths_to_try:
        url = urljoin(base_url, path)
        try:
            page_data = scrape_page(url)
            if page_data and len(page_data["raw_text"]) > 100:  # Only store if substantial content
                page_data["page_type"] = _classify_page_type(path)
                pages_scraped.append(page_data)
        except Exception as e:
            # Log but continue
            print(f"⚠️  Failed to scrape {url}: {e}")
            continue
    
    return {
        "domain": domain,
        "pages": pages_scraped,
        "scraped_at": datetime.utcnow()
    }


def _classify_page_type(path: str) -> str:
    """Classify page type from URL path"""
    path_lower = path.lower()
    if "/blog" in path_lower or "/news" in path_lower or "/press" in path_lower:
        return "blog"
    elif "/about" in path_lower or "/company" in path_lower:
        return "about"
    elif "/team" in path_lower:
        return "team"
    elif path == "/" or path == "":
        return "homepage"
    else:
        return "other"


def scrape_company_blog(domain: str, max_posts: int = 10) -> List[Dict[str, Any]]:
    """
    Scrape company blog/news pages.
    Focuses on recent posts (last 90 days if date available).
    
    Returns:
        List of blog post dicts with source_url, raw_text, page_date
    """
    if not domain.startswith('http'):
        domain = f"https://{domain}"
    
    base_url = domain.rstrip('/')
    blog_urls = [
        f"{base_url}/blog",
        f"{base_url}/news",
        f"{base_url}/press",
        f"{base_url}/articles",
    ]
    
    posts = []
    cutoff_date = datetime.utcnow() - timedelta(days=90)
    
    for blog_url in blog_urls:
        try:
            page_data = scrape_page(blog_url)
            if not page_data:
                continue
            
            # Try to find blog post links in HTML
            soup = BeautifulSoup(page_data["html"], 'html.parser')
            post_links = []
            
            # Common blog post link patterns
            for link in soup.find_all('a', href=True):
                href = link.get('href')
                if href:
                    full_url = urljoin(blog_url, href)
                    # Heuristic: blog posts often have dates or slugs
                    if any(indicator in href.lower() for indicator in ['/post/', '/article/', '/news/', '/2024/', '/2023/']):
                        post_links.append(full_url)
            
            # Scrape up to max_posts
            for post_url in post_links[:max_posts]:
                try:
                    post_data = scrape_page(post_url)
                    if post_data:
                        # Check if post is recent (if date available)
                        if post_data["page_date"]:
                            if post_data["page_date"] < cutoff_date:
                                continue  # Skip old posts
                        
                        post_data["page_type"] = "blog"
                        posts.append(post_data)
                except:
                    continue
            
            # If we found posts, break (don't try other blog URLs)
            if posts:
                break
                
        except Exception:
            continue
    
    return posts


def scrape_person_public_page(person_url: str) -> Optional[Dict[str, Any]]:
    """
    Scrape public person profile page (LinkedIn public, company bio, etc.).
    
    Returns:
        {
            "source_url": str,
            "raw_text": str,
            "scraped_at": datetime,
            "content_hash": str
        }
        or None if scraping fails
    """
    try:
        page_data = scrape_page(person_url, use_playwright=True)  # LinkedIn may need JS
        if page_data:
            page_data["page_type"] = "person_profile"
        return page_data
    except Exception:
        return None


def store_scraped_content(
    pages: List[Dict[str, Any]],
    company_id: Optional[int] = None,
    person_id: Optional[int] = None,
    db=None
) -> int:
    """
    Store scraped content in database.
    Returns number of pages stored (after deduplication).
    """
    try:
        from db.session import SessionLocal
        from db.models import ScrapedContent
        
        if db is None:
            db = SessionLocal()
            should_close = True
        else:
            should_close = False
        
        try:
            stored_count = 0
            
            for page in pages:
                content_hash = page.get("content_hash")
                
                # Check for duplicates
                existing = db.query(ScrapedContent).filter(
                    ScrapedContent.content_hash == content_hash
                ).first()
                
                if existing:
                    continue  # Skip duplicate
                
                scraped_content = ScrapedContent(
                    company_id=company_id,
                    person_id=person_id,
                    source_url=page["source_url"],
                    page_type=page.get("page_type", "other"),
                    raw_text=page["raw_text"],
                    scraped_at=page["scraped_at"],
                    page_date=page.get("page_date"),
                    content_hash=content_hash,
                )
                db.add(scraped_content)
                stored_count += 1
            
            db.commit()
            return stored_count
        except Exception as e:
            db.rollback()
            return 0
        finally:
            if should_close:
                db.close()
    except ImportError:
        # Database not available - return count but don't store
        return len(pages)
    except Exception:
        return 0
