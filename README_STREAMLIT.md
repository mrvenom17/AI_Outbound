# Streamlit Dashboard

A comprehensive web dashboard for monitoring and managing the AI Outbound system.

## Features

### 🏠 Dashboard Overview
- Key metrics (campaigns, leads, emails sent, bounce rate)
- Lead validation status distribution
- Recent AI decisions
- Campaign performance summary

### 📋 Campaign Management
- View all campaigns
- Create new campaigns
- Configure campaign parameters (query, limits, validation requirements)

### 👥 Lead Management
- Browse all leads with filtering
- Filter by validation status, blocked status
- Search by name/email/company
- View lead statistics

### 📤 Email Performance
- Email send metrics over time
- Bounce rate trends
- Rate limit status
- Recent email sends with bounce indicators

### 🤖 AI Decision Audit
- View all LLM decisions with input/output
- Filter by decision type
- Inspect evidence and reasoning
- Full audit trail for explainability

### 🛡️ Deliverability Status
- Current rate limits
- Rate limit history and evolution
- Bounce rate tracking
- Blocked leads management

### ⚡ Quick Actions
- Send emails (UI placeholder - use CLI for now)
- Scrape leads (UI placeholder - use CLI for now)
- Check bounces (manual trigger)

## Usage

### Start the Dashboard

```bash
streamlit run streamlit_app.py
```

The dashboard will open in your browser at `http://localhost:8501`

### Configuration

The dashboard can work in two modes:

1. **Direct Database Access** (default)
   - Connects directly to the database
   - Faster, no API dependency
   - Requires database to be accessible

2. **API Mode** (optional)
   - Uses FastAPI endpoints
   - Enable "Use API" checkbox in sidebar
   - Set API Base URL (default: http://localhost:8000)

### Prerequisites

1. Database must be initialized and migrated
2. Install dependencies: `pip install -r requirements.txt`
3. Ensure database is accessible (SQLite file or PostgreSQL connection)

## Dashboard Pages

### Navigation
Use the sidebar to navigate between pages:
- **Dashboard** - Overview and key metrics
- **Campaigns** - Campaign management
- **Leads** - Lead browsing and filtering
- **Email Performance** - Send metrics and trends
- **AI Decisions** - LLM decision audit trail
- **Deliverability** - Rate limits and bounce management
- **Actions** - Quick action triggers

## Notes

- The dashboard reads directly from the database for best performance
- Some actions (send emails, scrape leads) are placeholders - use CLI commands for now
- All charts are interactive (Plotly)
- Data is cached for performance (Streamlit caching)
- Real-time updates require page refresh

## Future Enhancements

- Real-time email sending from UI
- Real-time lead scraping from UI
- Webhook integration for live updates
- Email preview and editing
- Lead enrichment from UI
- Campaign scheduling
- Export functionality
