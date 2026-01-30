# scrapers/google_scraper.py
from playwright.sync_api import sync_playwright
import urllib.parse

def google_search_linkedin_companies(keyword, location, max_results=20):
    query = f'"{keyword}" "{location}" site:linkedin.com/company'
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&num={max_results}"

    companies = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # set headless=False to watch it run
        page = browser.new_page()
        page.goto(url)
        
        # Wait for results
        page.wait_for_selector('div#search')

        # Extract company links
        results = page.query_selector_all('div.g a')
        for result in results:
            href = result.get_attribute('href')
            if href and 'linkedin.com/company/' in href:
                # Clean URL (remove tracking params)
                clean_url = href.split('?')[0]
                companies.append(clean_url)
                if len(companies) >= 10:  # limit to 10 companies for MVP
                    break

        browser.close()

    return companies