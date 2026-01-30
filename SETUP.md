# Setup Instructions

## Complete Setup Checklist

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Initialize Database (REQUIRED)
```bash
python scripts/init_db.py
```

This creates all database tables. **You must run this before using the dashboard or API.**

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```env
# Database (optional - defaults to SQLite)
DATABASE_URL=sqlite:///./ai_outbound.db

# API Keys (required for functionality)
OPENROUTER_API_KEY=your_openrouter_key
PPLX_API_KEY=your_perplexity_key
HUNTER_API_KEY=your_hunter_key

# Database echo (optional, for debugging)
DB_ECHO=false
```

### 4. Gmail OAuth Setup

1. Place your `client_secret1.json` file in the project root
2. On first run, the app will open a browser for OAuth authentication
3. A `token.pickle` file will be created for future use

### 5. Start the Dashboard

```bash
streamlit run streamlit_app.py
```

### 6. (Optional) Start the API Server

In a separate terminal:

```bash
uvicorn api.main:app --reload
```

## Verification

After setup, verify everything works:

1. **Database**: Check that `ai_outbound.db` file exists (SQLite) or connection works (PostgreSQL)
2. **Dashboard**: Open `http://localhost:8501` - should load without errors
3. **API**: Open `http://localhost:8000/docs` - should show API documentation

## Troubleshooting

### "no such table" Error

**Solution**: Run database initialization:
```bash
python scripts/init_db.py
```

### Import Errors

**Solution**: Install dependencies:
```bash
pip install -r requirements.txt
```

### Database Connection Errors

**Solution**: 
- Check `DATABASE_URL` in `.env` or `db/session.py`
- For SQLite: Ensure write permissions in project directory
- For PostgreSQL: Verify connection string and credentials

### Gmail Authentication Errors

**Solution**:
- Ensure `client_secret1.json` is in project root
- Check OAuth scopes in `agents/gmail_service.py`
- Delete `token.pickle` and re-authenticate if needed

## Next Steps

1. Create your first campaign in the dashboard
2. Run a test lead scrape
3. Review leads and validation
4. Send test emails
5. Monitor performance in dashboard
