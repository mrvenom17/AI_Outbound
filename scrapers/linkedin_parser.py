# scrapers/linkedin_parser.py
import pandas as pd
import os

def parse_linkedin_csv_or_mock(company_linkedin_url):
    """
    For MVP: return mock data if no CSV exists.
    Later: replace with real Playwright scraper or CSV loader.
    """
    # In real use: you'd export from LinkedIn Sales Nav → save as data/{company_name}.csv
    company_id = company_linkedin_url.strip('/').split('/')[-1]
    csv_path = f"data/{company_id}.csv"

    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        leads = []
        for _, row in df.iterrows():
            leads.append({
                "Name": row.get("Name", "").strip(),
                "Role / Title": row.get("Title", "").strip(),
                "LinkedIn URL": row.get("LinkedIn URL", "").strip(),
                "Company": company_id.replace('-', ' ').title()
            })
        return leads
    else:
        # MOCK DATA (replace with real scraper later)
        return [
            {
                "Name": "Alex Rivera",
                "Role / Title": "Head of Security",
                "LinkedIn URL": f"{company_linkedin_url}/alex-rivera",
                "Company": company_id.replace('-', ' ').title()
            },
            {
                "Name": "Jamie Chen",
                "Role / Title": "CTO",
                "LinkedIn URL": f"{company_linkedin_url}/jamie-chen",
                "Company": company_id.replace('-', ' ').title()
            }
        ]