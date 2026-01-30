# Quick Start Guide

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

## 2. Initialize Database

**IMPORTANT: Run this before starting the dashboard!**

```bash
# Initialize database (creates all tables)
python scripts/init_db.py
```

This will create all required database tables. You should see:
```
✅ Database tables created successfully!
📊 Created 10 tables:
   - ai_decisions
   - campaigns
   - companies
   - email_bounces
   - email_candidates
   - email_validations
   - leads
   - people
   - send_metrics
   - sent_emails
```

Alternative methods:
```bash
# Using Alembic (if migrations are set up)
alembic upgrade head

# Or create tables directly via Python
python -c "from db.models import Base; from db.session import engine; Base.metadata.create_all(engine)"
```

## 3. Migrate Existing Data (Optional)

If you have existing CSV files:

```bash
python scripts/migrate_csvs.py --leads-csv leads.csv --sent-emails-csv sent_emails.csv
```

## 4. Start the Dashboard

```bash
streamlit run streamlit_app.py
```

The dashboard will open at `http://localhost:8501`

## 5. Start the API (Optional)

In a separate terminal:

```bash
uvicorn api.main:app --reload
```

API will be available at `http://localhost:8000`
API docs at `http://localhost:8000/docs`

## Usage

### CLI Commands (Still Available)

```bash
# Send emails
python main.py send-emails --csv leads.csv --subject "Your subject"

# Scrape leads
python main.py scrape-leads --query "Seed stage B2B SaaS startups"

# Use a campaign
python main.py scrape-leads --campaign-id 1
```

### Dashboard Features

1. **Dashboard** - View overview metrics
2. **Campaigns** - Create and manage campaigns
3. **Leads** - Browse and filter leads
4. **Email Performance** - Monitor send metrics
5. **AI Decisions** - Audit LLM decisions
6. **Deliverability** - Track rate limits and bounces
7. **Actions** - Quick action triggers

### Periodic Tasks

Run bounce checker periodically (cron/scheduler):

```bash
python workers/bounce_checker.py
```

## Environment Variables

Create a `.env` file:

```env
# Database (optional - defaults to SQLite)
DATABASE_URL=sqlite:///./ai_outbound.db

# API Keys
OPENROUTER_API_KEY=your_key_here
PPLX_API_KEY=your_key_here
HUNTER_API_KEY=your_key_here

# Gmail OAuth (use client_secret1.json)
# No env var needed - uses client_secret1.json file
```

## Troubleshooting

### Database Connection Issues

- Check `DATABASE_URL` in `.env` or `db/session.py`
- Ensure database file exists (SQLite) or connection is valid (PostgreSQL)

### Missing Dependencies

```bash
pip install -r requirements.txt
```

### Dashboard Not Loading

- Check database is initialized
- Verify database connection
- Check terminal for error messages

### API Not Working

- Ensure FastAPI server is running
- Check CORS settings if accessing from different origin
- Verify API base URL in dashboard sidebar

## Next Steps

1. Create your first campaign in the dashboard
2. Scrape leads using the campaign
3. Review leads and validation status
4. Send emails to validated leads
5. Monitor performance in the dashboard
6. Review AI decisions for explainability
