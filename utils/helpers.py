# utils/helpers.py
import requests
from urllib.parse import urlparse

def get_company_domain_from_linkedin(linkedin_url):
    """
    Try to get company website from LinkedIn company page.
    For MVP: return a fake domain based on company name.
    """
    # In real version: scrape LinkedIn company page → get website
    # For now: fake it
    company_name = linkedin_url.strip('/').split('/')[-1]
    # Convert "cloud-security-inc" → "cloudsecurityinc.com"
    clean = company_name.replace('-', '').replace(' ', '')
    return f"{clean}.com"