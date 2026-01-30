# streamlit_app.py
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import requests
import json
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

# Page config
st.set_page_config(
    page_title="AI Outbound Dashboard",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if "api_base_url" not in st.session_state:
    st.session_state.api_base_url = "http://localhost:8000"

# Database connection helper
@st.cache_resource
def get_db_session():
    """Get database session - cached for performance"""
    try:
        from db.session import SessionLocal
        from sqlalchemy import inspect
        from db.session import engine
        
        db = SessionLocal()
        
        # Check if tables exist
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if not tables:
            st.error("""
            ❌ **Database tables not initialized!**
            
            Please run the initialization script:
            ```bash
            python scripts/init_db.py
            ```
            
            Then refresh this page.
            """)
            db.close()
            return None
        
        return db
    except ImportError:
        st.error("❌ Database not available. Please install dependencies: `pip install -r requirements.txt`")
        return None
    except Exception as e:
        if "no such table" in str(e).lower():
            st.error(f"""
            ❌ **Database tables not initialized!**
            
            Error: {str(e)}
            
            Please run the initialization script:
            ```bash
            python scripts/init_db.py
            ```
            
            Then refresh this page.
            """)
        else:
            st.error(f"Database error: {e}")
        return None


def fetch_from_api(endpoint: str) -> Optional[Dict]:
    """Fetch data from API endpoint"""
    try:
        url = f"{st.session_state.api_base_url}{endpoint}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            st.warning(f"API request failed: {response.status_code}")
            return None
    except requests.exceptions.RequestException:
        return None


# ============================================================================
# SIDEBAR
# ============================================================================
with st.sidebar:
    st.title("📧 AI Outbound")
    st.markdown("---")
    
    # API Configuration
    st.subheader("⚙️ Configuration")
    api_url = st.text_input(
        "API Base URL",
        value=st.session_state.api_base_url,
        help="Base URL for FastAPI backend (leave empty to use database directly)"
    )
    if api_url != st.session_state.api_base_url:
        st.session_state.api_base_url = api_url
    
    use_api = st.checkbox("Use API", value=False, help="Use FastAPI endpoints instead of direct DB access")
    
    st.markdown("---")
    
    # Navigation
    st.subheader("📊 Navigation")
    page = st.radio(
        "Select Page",
        [
            "🏠 Dashboard",
            "📋 Campaigns",
            "👥 Leads",
            "📤 Email Performance",
            "🤖 AI Decisions",
            "🛡️ Deliverability",
            "⚡ Actions",
            "📧 SMTP Servers",
            "📬 Inbox",
            "⚙️ Settings"
        ],
        label_visibility="collapsed"
    )


# ============================================================================
# DASHBOARD PAGE
# ============================================================================
if page == "🏠 Dashboard":
    st.title("🏠 Dashboard Overview")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import Campaign, Lead, SentEmail, EmailBounce, AIDecision
        
        # Key Metrics
        col1, col2, col3, col4 = st.columns(4)
        
        total_campaigns = db.query(Campaign).count()
        total_leads = db.query(Lead).count()
        total_sent = db.query(SentEmail).filter(SentEmail.sent == True).count()
        
        # Bounce rate
        total_bounces = db.query(EmailBounce).count()
        bounce_rate = (total_bounces / total_sent * 100) if total_sent > 0 else 0.0
        
        with col1:
            st.metric("Campaigns", total_campaigns)
        with col2:
            st.metric("Total Leads", total_leads)
        with col3:
            st.metric("Emails Sent", total_sent)
        with col4:
            st.metric("Bounce Rate", f"{bounce_rate:.1f}%", delta=f"-{bounce_rate:.1f}%" if bounce_rate < 5 else f"+{bounce_rate:.1f}%")
        
        st.markdown("---")
        
        # Recent Activity
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Leads by Status")
            status_counts = db.query(
                Lead.validation_status,
                func.count(Lead.id).label("count")
            ).group_by(Lead.validation_status).all()
            
            if status_counts:
                status_df = pd.DataFrame(status_counts, columns=["Status", "Count"])
                fig = px.pie(status_df, values="Count", names="Status", title="Lead Validation Status")
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("No leads data available")
        
        with col2:
            st.subheader("📈 Recent AI Decisions")
            recent_decisions = db.query(AIDecision).order_by(
                AIDecision.created_at.desc()
            ).limit(10).all()
            
            if recent_decisions:
                decisions_data = []
                for d in recent_decisions:
                    decisions_data.append({
                        "Type": d.decision_type,
                        "Model": d.model,
                        "Time": d.created_at.strftime("%Y-%m-%d %H:%M")
                    })
                st.dataframe(pd.DataFrame(decisions_data), width='stretch', hide_index=True)
            else:
                st.info("No AI decisions logged yet")
        
        # Campaign Performance
        st.subheader("🎯 Campaign Performance")
        from db.models import Person, Company
        
        campaigns = db.query(Campaign).all()
        
        if campaigns:
            campaign_data = []
            for campaign in campaigns:
                leads_count = db.query(Lead).join(Person).join(Company).filter(
                    Company.campaign_id == campaign.id
                ).count()
                
                emails_sent = db.query(SentEmail).join(Lead).join(Person).join(Company).filter(
                    Company.campaign_id == campaign.id,
                    SentEmail.sent == True
                ).count()
                
                campaign_data.append({
                    "Campaign": campaign.name,
                    "Leads": leads_count,
                    "Emails Sent": emails_sent,
                    "Query": campaign.query[:50] + "..." if len(campaign.query) > 50 else campaign.query
                })
            
            campaign_df = pd.DataFrame(campaign_data)
            st.dataframe(campaign_df, width='stretch', hide_index=True)
        else:
            st.info("No campaigns created yet")
            
    except Exception as e:
        st.error(f"Error loading dashboard: {e}")
    finally:
        db.close()


# ============================================================================
# CAMPAIGNS PAGE
# ============================================================================
elif page == "📋 Campaigns":
    st.title("📋 Campaign Management")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import Campaign
        
        tab1, tab2 = st.tabs(["View Campaigns", "Create Campaign"])
        
        with tab1:
            campaigns = db.query(Campaign).all()
            
            if campaigns:
                campaign_data = []
                for c in campaigns:
                    # Get stats for each campaign
                    from db.models import Person, Company, Lead, SentEmail
                    leads_count = db.query(Lead).join(Person).join(Company).filter(
                        Company.campaign_id == c.id
                    ).count()
                    emails_sent = db.query(SentEmail).join(Lead).join(Person).join(Company).filter(
                        Company.campaign_id == c.id,
                        SentEmail.sent == True
                    ).count()
                    
                    campaign_data.append({
                        "ID": c.id,
                        "Name": c.name,
                        "Query": c.query[:50] + "..." if len(c.query) > 50 else c.query,
                        "Max Companies": c.max_companies,
                        "Max People": c.max_people_per_company,
                        "Require Valid Email": "Yes" if c.require_valid_email else "No",
                        "Leads": leads_count,
                        "Emails Sent": emails_sent,
                        "Created": c.created_at.strftime("%Y-%m-%d %H:%M")
                    })
                
                df = pd.DataFrame(campaign_data)
                st.dataframe(df, width='stretch', hide_index=True)
                
                # Campaign actions
                st.markdown("---")
                st.subheader("🛠️ Campaign Actions")
                
                selected_campaign_id = st.selectbox(
                    "Select Campaign to View/Edit",
                    options=[c.id for c in campaigns],
                    format_func=lambda x: db.query(Campaign).filter(Campaign.id == x).first().name
                )
                
                if selected_campaign_id:
                    selected_campaign = db.query(Campaign).filter(Campaign.id == selected_campaign_id).first()
                    
                    if selected_campaign:
                        with st.form(f"edit_campaign_{selected_campaign.id}"):
                            st.write("**Edit Campaign**")
                            new_name = st.text_input("Name", value=selected_campaign.name)
                            new_query = st.text_area("Query", value=selected_campaign.query)
                            new_offer = st.text_area(
                                "Offer / Pitch Description",
                                value=getattr(selected_campaign, "offer_description", None) or "",
                                placeholder="e.g., Done-For-You email automation | Intelpatch product",
                                help="What you're pitching. Emails will tailor to this."
                            )
                            col1, col2 = st.columns(2)
                            with col1:
                                new_max_companies = st.number_input("Max Companies", min_value=1, max_value=100, value=selected_campaign.max_companies)
                                new_max_people = st.number_input("Max People per Company", min_value=1, max_value=10, value=selected_campaign.max_people_per_company)
                            with col2:
                                new_require_valid = st.checkbox("Require Valid Email", value=selected_campaign.require_valid_email)
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("💾 Save Changes", type="primary"):
                                    try:
                                        selected_campaign.name = new_name
                                        selected_campaign.query = new_query
                                        if hasattr(selected_campaign, "offer_description"):
                                            selected_campaign.offer_description = new_offer.strip() or None
                                        selected_campaign.max_companies = new_max_companies
                                        selected_campaign.max_people_per_company = new_max_people
                                        selected_campaign.require_valid_email = new_require_valid
                                        selected_campaign.updated_at = datetime.utcnow()
                                        
                                        db.commit()
                                        st.success("✅ Campaign updated successfully!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error updating campaign: {e}")
                                        db.rollback()
                            
                            with col2:
                                if st.form_submit_button("🗑️ Delete Campaign"):
                                    try:
                                        db.delete(selected_campaign)
                                        db.commit()
                                        st.success("✅ Campaign deleted successfully!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error deleting campaign: {e}")
                                        db.rollback()
            else:
                st.info("No campaigns found. Create one in the 'Create Campaign' tab.")
        
        with tab2:
            with st.form("create_campaign"):
                st.subheader("Create New Campaign")
                
                name = st.text_input("Campaign Name", placeholder="e.g., Seed Stage SaaS")
                query = st.text_area(
                    "Search Query",
                    placeholder="e.g., Seed stage B2B SaaS startups hiring SDRs",
                    help="Query to pass to Perplexity for company discovery"
                )
                offer_description = st.text_area(
                    "Offer / Pitch Description",
                    placeholder="e.g., Done-For-You email automation | Intelpatch - vulnerability management product",
                    help="What you're pitching in this campaign. Emails will tailor the solution sentence to this."
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    max_companies = st.number_input("Max Companies", min_value=1, max_value=100, value=20)
                    max_people = st.number_input("Max People per Company", min_value=1, max_value=10, value=3)
                with col2:
                    require_valid = st.checkbox("Require Valid Email", value=True)
                
                submitted = st.form_submit_button("Create Campaign", type="primary")
                
                if submitted:
                    if not name or not query:
                        st.error("Please fill in campaign name and query")
                    else:
                        try:
                            new_campaign = Campaign(
                                name=name,
                                query=query,
                                offer_description=offer_description.strip() or None,
                                max_companies=max_companies,
                                max_people_per_company=max_people,
                                require_valid_email=require_valid,
                            )
                            db.add(new_campaign)
                            db.commit()
                            st.success(f"✅ Campaign '{name}' created successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error creating campaign: {e}")
                            db.rollback()
                            
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        db.close()


# ============================================================================
# LEADS PAGE
# ============================================================================
elif page == "👥 Leads":
    st.title("👥 Lead Management")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import Lead, Person, Company, SentEmail, EmailBounce
        from sqlalchemy import or_
        
        # Filters
        col1, col2, col3 = st.columns(3)
        with col1:
            status_filter = st.selectbox(
                "Filter by Status",
                ["All", "valid", "unknown", "invalid"],
                index=0
            )
        with col2:
            blocked_filter = st.selectbox(
                "Filter by Blocked",
                ["All", "Blocked Only", "Not Blocked"],
                index=0
            )
        with col3:
            search_term = st.text_input("Search (name/email/company)", "")
        
        # Query leads
        query = db.query(Lead)
        
        if status_filter != "All":
            query = query.filter(Lead.validation_status == status_filter)
        
        if blocked_filter == "Blocked Only":
            query = query.filter(Lead.blocked == True)
        elif blocked_filter == "Not Blocked":
            query = query.filter(Lead.blocked == False)
        
        if search_term:
            # Need to join Person to search by name
            query = query.join(Person).filter(
                or_(
                    Person.name.ilike(f"%{search_term}%"),
                    Lead.email.ilike(f"%{search_term}%"),
                    Lead.company.ilike(f"%{search_term}%")
                )
            )
        
        # Eager load person relationship
        leads = query.options(joinedload(Lead.person)).order_by(Lead.timestamp.desc()).limit(1000).all()
        
        if leads:
            leads_data = []
            for lead in leads:
                leads_data.append({
                    "ID": lead.id,
                    "Name": lead.person.name if lead.person else "N/A",
                    "Email": lead.email,
                    "Company": lead.company,
                    "Role": lead.role,
                    "Status": lead.validation_status,
                    "Confidence": f"{lead.confidence:.2f}",
                    "Blocked": "🚫" if lead.blocked else "✅",
                    "Blocked Reason": lead.blocked_reason or "",
                    "Created": lead.timestamp.strftime("%Y-%m-%d %H:%M")
                })
            
            df = pd.DataFrame(leads_data)
            st.dataframe(df, width='stretch', hide_index=True)
            
            # Statistics
            st.markdown("---")
            col1, col2, col3, col4 = st.columns(4)
            
            total = len(leads)
            valid_count = sum(1 for l in leads if l.validation_status == "valid")
            blocked_count = sum(1 for l in leads if l.blocked)
            avg_confidence = sum(l.confidence for l in leads) / total if total > 0 else 0
            
            with col1:
                st.metric("Total Leads", total)
            with col2:
                st.metric("Valid", valid_count, f"{valid_count/total*100:.1f}%")
            with col3:
                st.metric("Blocked", blocked_count)
            with col4:
                st.metric("Avg Confidence", f"{avg_confidence:.2f}")
            
            # Lead Actions
            st.markdown("---")
            st.subheader("🛠️ Lead Actions")
            
            if leads:
                selected_lead_id = st.selectbox(
                    "Select Lead to View/Edit",
                    options=[l.id for l in leads],
                    format_func=lambda x: f"{db.query(Lead).options(joinedload(Lead.person)).filter(Lead.id == x).first().person.name if db.query(Lead).options(joinedload(Lead.person)).filter(Lead.id == x).first().person else 'Unknown'} ({db.query(Lead).filter(Lead.id == x).first().email})"
                )
                
                if selected_lead_id:
                    selected_lead = db.query(Lead).options(joinedload(Lead.person)).filter(Lead.id == selected_lead_id).first()
                    
                    if selected_lead:
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.write("**Lead Details**")
                            st.write(f"**Name:** {selected_lead.person.name if selected_lead.person else 'N/A'}")
                            st.write(f"**Email:** {selected_lead.email}")
                            st.write(f"**Company:** {selected_lead.company}")
                            st.write(f"**Role:** {selected_lead.role or 'N/A'}")
                            st.write(f"**Domain:** {selected_lead.domain}")
                            st.write(f"**LinkedIn:** {selected_lead.linkedin_url or 'N/A'}")
                            st.write(f"**Status:** {selected_lead.validation_status}")
                            st.write(f"**Confidence:** {selected_lead.confidence:.2f}")
                            st.write(f"**Blocked:** {'Yes' if selected_lead.blocked else 'No'}")
                            if selected_lead.blocked_reason:
                                st.write(f"**Block Reason:** {selected_lead.blocked_reason}")
                        
                        with col2:
                            st.write("**Edit Lead**")
                            
                            with st.form(f"edit_lead_{selected_lead.id}"):
                                new_email = st.text_input("Email", value=selected_lead.email)
                                new_company = st.text_input("Company", value=selected_lead.company)
                                new_role = st.text_input("Role", value=selected_lead.role or "")
                                new_status = st.selectbox(
                                    "Validation Status",
                                    ["valid", "unknown", "invalid"],
                                    index=["valid", "unknown", "invalid"].index(selected_lead.validation_status) if selected_lead.validation_status in ["valid", "unknown", "invalid"] else 1
                                )
                                new_confidence = st.slider("Confidence", 0.0, 1.0, float(selected_lead.confidence), 0.01)
                                is_blocked = st.checkbox("Blocked", value=selected_lead.blocked)
                                block_reason = st.text_input("Block Reason", value=selected_lead.blocked_reason or "")
                                
                                if st.form_submit_button("💾 Save Changes", type="primary"):
                                    try:
                                        selected_lead.email = new_email
                                        selected_lead.company = new_company
                                        selected_lead.role = new_role
                                        selected_lead.validation_status = new_status
                                        selected_lead.confidence = new_confidence
                                        selected_lead.blocked = is_blocked
                                        selected_lead.blocked_reason = block_reason if is_blocked else None
                                        
                                        db.commit()
                                        st.success("✅ Lead updated successfully!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error updating lead: {e}")
                                        db.rollback()
                        
                        # Show email history
                        st.markdown("---")
                        st.subheader("📧 Email History")
                        sent_emails = db.query(SentEmail).filter(SentEmail.lead_id == selected_lead.id).order_by(SentEmail.sent_at.desc()).all()
                        
                        if sent_emails:
                            email_data = []
                            for email in sent_emails:
                                bounce_count = db.query(EmailBounce).filter(EmailBounce.sent_email_id == email.id).count()
                                
                                email_data.append({
                                    "Subject": email.subject,
                                    "Sent At": email.sent_at.strftime("%Y-%m-%d %H:%M"),
                                    "Thread ID": email.thread_id or "N/A",
                                    "Status": "✅ Sent" if email.sent else "❌ Failed",
                                    "Bounces": f"🚫 {bounce_count}" if bounce_count > 0 else "✅"
                                })
                            
                            st.dataframe(pd.DataFrame(email_data), width='stretch', hide_index=True)
                        else:
                            st.info("No emails sent to this lead yet")
        else:
            st.info("No leads found matching filters")
            
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        db.close()


# ============================================================================
# EMAIL PERFORMANCE PAGE
# ============================================================================
elif page == "📤 Email Performance":
    st.title("📤 Email Performance")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import SentEmail, EmailBounce, Lead
        
        # Time range selector
        days = st.selectbox("Time Range", [7, 14, 30, 90], index=0, format_func=lambda x: f"Last {x} days")
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        # Metrics
        col1, col2, col3, col4 = st.columns(4)
        
        sent_count = db.query(SentEmail).filter(
            SentEmail.sent_at >= cutoff,
            SentEmail.sent == True
        ).count()
        
        bounce_count = db.query(EmailBounce).join(SentEmail).filter(
            SentEmail.sent_at >= cutoff
        ).count()
        
        bounce_rate = (bounce_count / sent_count * 100) if sent_count > 0 else 0.0
        
        # Get rate limits (effective = from Settings when set, else SendMetric)
        from agents.rate_limiter import get_current_rate_limit
        rate_hour, rate_day = get_current_rate_limit()
        
        with col1:
            st.metric("Emails Sent", sent_count)
        with col2:
            st.metric("Bounces", bounce_count, f"{bounce_rate:.1f}%")
        with col3:
            st.metric("Rate Limit (Hour)", rate_hour)
        with col4:
            st.metric("Rate Limit (Day)", rate_day)
        
        st.markdown("---")
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📈 Sends Over Time")
            from sqlalchemy import func
            daily_sends = db.query(
                func.date(SentEmail.sent_at).label("date"),
                func.count(SentEmail.id).label("count")
            ).filter(
                SentEmail.sent_at >= cutoff,
                SentEmail.sent == True
            ).group_by(func.date(SentEmail.sent_at)).all()
            
            if daily_sends:
                sends_df = pd.DataFrame(daily_sends, columns=["Date", "Count"])
                sends_df["Date"] = pd.to_datetime(sends_df["Date"])
                fig = px.line(sends_df, x="Date", y="Count", title="Daily Email Sends")
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("No send data available")
        
        with col2:
            st.subheader("📊 Bounce Rate Trend")
            from sqlalchemy import func
            daily_bounces = db.query(
                func.date(SentEmail.sent_at).label("date"),
                func.count(EmailBounce.id).label("bounces"),
                func.count(SentEmail.id).label("sends")
            ).join(EmailBounce, SentEmail.id == EmailBounce.sent_email_id, isouter=True).filter(
                SentEmail.sent_at >= cutoff
            ).group_by(func.date(SentEmail.sent_at)).all()
            
            if daily_bounces:
                bounces_df = pd.DataFrame(daily_bounces, columns=["Date", "Bounces", "Sends"])
                bounces_df["Date"] = pd.to_datetime(bounces_df["Date"])
                bounces_df["Bounce Rate"] = (bounces_df["Bounces"] / bounces_df["Sends"] * 100).fillna(0)
                fig = px.line(bounces_df, x="Date", y="Bounce Rate", title="Daily Bounce Rate %")
                st.plotly_chart(fig, width='stretch')
            else:
                st.info("No bounce data available")
        
        # Recent sends
        st.subheader("📋 Recent Email Sends")
        recent_sends = db.query(SentEmail).options(joinedload(SentEmail.lead).joinedload(Lead.person)).join(Lead).filter(
            SentEmail.sent_at >= cutoff
        ).order_by(SentEmail.sent_at.desc()).limit(50).all()
        
        if recent_sends:
            sends_data = []
            for send in recent_sends:
                bounce_count = db.query(EmailBounce).filter(
                    EmailBounce.sent_email_id == send.id
                ).count()
                
                lead_name = send.lead.person.name if send.lead.person else "Unknown"
                sends_data.append({
                    "Lead": lead_name,
                    "Email": send.lead.email,
                    "Subject": send.subject,
                    "Sent": send.sent_at.strftime("%Y-%m-%d %H:%M"),
                    "Thread ID": send.thread_id or "N/A",
                    "Bounces": "🚫" if bounce_count > 0 else "✅"
                })
            
            st.dataframe(pd.DataFrame(sends_data), width='stretch', hide_index=True)
        else:
            st.info("No recent sends")
            
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        db.close()


# ============================================================================
# AI DECISIONS PAGE
# ============================================================================
elif page == "🤖 AI Decisions":
    st.title("🤖 AI Decision Audit Trail")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import AIDecision
        import json
        
        # Filters
        col1, col2 = st.columns(2)
        with col1:
            decision_type = st.selectbox(
                "Filter by Type",
                ["All", "email_generation", "company_discovery", "people_discovery", "perplexity_api_call"],
                index=0
            )
        with col2:
            limit = st.slider("Number of Decisions", min_value=10, max_value=200, value=50)
        
        # Query decisions
        query = db.query(AIDecision)
        if decision_type != "All":
            query = query.filter(AIDecision.decision_type == decision_type)
        
        decisions = query.order_by(AIDecision.created_at.desc()).limit(limit).all()
        
        if decisions:
            for decision in decisions:
                with st.expander(f"{decision.decision_type} - {decision.created_at.strftime('%Y-%m-%d %H:%M')} ({decision.model})"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("Input Evidence")
                        if decision.input_evidence:
                            st.json(decision.input_evidence)
                        else:
                            st.info("No input evidence")
                    
                    with col2:
                        st.subheader("Output")
                        if decision.output:
                            # Truncate long outputs
                            output_preview = decision.output[:1000] + "..." if len(decision.output) > 1000 else decision.output
                            st.text_area("Output", output_preview, height=200, key=f"output_{decision.id}", disabled=True, label_visibility="collapsed")
                        else:
                            st.info("No output")
        else:
            st.info("No AI decisions found")
            
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        db.close()


# ============================================================================
# DELIVERABILITY PAGE
# ============================================================================
elif page == "🛡️ Deliverability":
    st.title("🛡️ Deliverability Status")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import SendMetric, Lead, EmailBounce, SentEmail
        
        # Current Status
        st.subheader("📊 Current Status")
        
        col1, col2, col3, col4 = st.columns(4)
        
        # Effective rate limits (from Settings when set, else SendMetric)
        from agents.rate_limiter import get_current_rate_limit
        rate_hour, rate_day = get_current_rate_limit()
        
        # Bounce rate
        total_sent = db.query(SentEmail).filter(SentEmail.sent == True).count()
        total_bounces = db.query(EmailBounce).count()
        bounce_rate = (total_bounces / total_sent * 100) if total_sent > 0 else 0.0
        
        # Blocked
        from sqlalchemy import func
        blocked_emails = db.query(Lead).filter(Lead.blocked == True).count()
        blocked_domains = db.query(func.count(func.distinct(Lead.domain))).filter(
            Lead.blocked == True
        ).scalar() or 0
        
        with col1:
            st.metric("Rate Limit (Hour)", rate_hour)
        with col2:
            st.metric("Rate Limit (Day)", rate_day)
        with col3:
            st.metric("Bounce Rate", f"{bounce_rate:.2f}%")
        with col4:
            st.metric("Blocked Emails", blocked_emails)
        
        st.markdown("---")
        
        # Rate Limit History
        st.subheader("📈 Rate Limit History")
        metrics = db.query(SendMetric).order_by(SendMetric.date.desc()).limit(30).all()
        
        if metrics:
            metrics_data = []
            for m in reversed(metrics):  # Show oldest first
                metrics_data.append({
                    "Date": m.date.strftime("%Y-%m-%d"),
                    "Emails/Hour": m.emails_per_hour,
                    "Emails/Day": m.emails_per_day,
                    "Bounce Rate": f"{m.bounce_rate*100:.2f}%"
                })
            
            metrics_df = pd.DataFrame(metrics_data)
            st.dataframe(metrics_df, width='stretch', hide_index=True)
            
            # Chart
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=metrics_df["Date"],
                y=metrics_df["Emails/Day"],
                mode="lines+markers",
                name="Daily Limit"
            ))
            fig.add_trace(go.Scatter(
                x=metrics_df["Date"],
                y=metrics_df["Emails/Hour"] * 8,  # Approximate daily from hourly
                mode="lines+markers",
                name="Hourly Limit (×8)"
            ))
            fig.update_layout(title="Rate Limit Evolution", xaxis_title="Date", yaxis_title="Emails")
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("No rate limit metrics available")
        
        # Blocked Leads
        st.subheader("🚫 Blocked Leads")
        blocked_leads = db.query(Lead).options(joinedload(Lead.person)).filter(Lead.blocked == True).limit(100).all()
        
        if blocked_leads:
            blocked_data = []
            for lead in blocked_leads:
                blocked_data.append({
                    "Name": lead.person.name if lead.person else "N/A",
                    "Email": lead.email,
                    "Company": lead.company,
                    "Reason": lead.blocked_reason or "Unknown",
                    "Blocked At": lead.timestamp.strftime("%Y-%m-%d %H:%M")
                })
            
            st.dataframe(pd.DataFrame(blocked_data), width='stretch', hide_index=True)
        else:
            st.success("✅ No blocked leads")
            
    except Exception as e:
        st.error(f"Error: {e}")
    finally:
        db.close()


# ============================================================================
# ACTIONS PAGE
# ============================================================================
elif page == "⚡ Actions":
    st.title("⚡ Quick Actions")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import Campaign, Lead, Person, Company, SentEmail
        from agents.gmail_service import authenticate_gmail, send_email
        from agents.email_agent import generate_email
        from scrapers.discovery import search_companies, search_people
        from utils.patterns import generate_email_candidates, verify_with_hunter
        from utils.smtp_check import validate_email
        from utils.writer import write_to_csv_and_db
        from datetime import datetime, timezone
        from sqlalchemy import and_
        import time
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["Send Emails", "Scrape Leads", "Add Leads (CSV/Excel)", "Check Bounces", "Manage Leads"])
        
        with tab1:
            st.subheader("📤 Send Emails")
            
            # Select campaign or manual
            send_mode = st.radio("Send Mode", ["From Campaign Leads", "Manual Selection", "From All Leads"])
            
            leads_to_send = []
            campaign_id = None
            
            if send_mode == "From Campaign Leads":
                campaigns = db.query(Campaign).all()
                if campaigns:
                    campaign_names = {c.name: c.id for c in campaigns}
                    selected_campaign = st.selectbox("Select Campaign", list(campaign_names.keys()))
                    
                    if selected_campaign:
                        campaign_id = campaign_names[selected_campaign]
                        # Get leads for this campaign with eager loading
                        all_campaign_leads = db.query(Lead).options(joinedload(Lead.person)).join(Person).join(Company).filter(
                            Company.campaign_id == campaign_id,
                            Lead.blocked == False,
                            Lead.validation_status == "valid"  # Only send to validated emails
                        ).limit(100).all()
                        
                        # Filter out leads that already have sent emails
                        from db.models import SentEmail
                        sent_lead_ids = {se.lead_id for se in db.query(SentEmail.lead_id).filter(
                            SentEmail.lead_id.in_([l.id for l in all_campaign_leads]),
                            SentEmail.sent == True
                        ).all()}
                        
                        leads_to_send = [l for l in all_campaign_leads if l.id not in sent_lead_ids]
                        already_sent_count = len(sent_lead_ids)
                        
                        if leads_to_send:
                            st.info(f"✅ Found {len(leads_to_send)} valid, unblocked leads (already sent: {already_sent_count})")
                            # Auto-select all unsent leads
                            st.success(f"📧 {len(leads_to_send)} leads ready to send (auto-selected)")
                        elif already_sent_count > 0:
                            st.warning(f"⚠️ All {already_sent_count} leads have already been sent emails")
                        else:
                            st.warning("⚠️ No valid, unblocked leads found for this campaign")
            
            elif send_mode == "From All Leads":
                # Get all valid, unblocked leads with eager loading
                all_valid_leads = db.query(Lead).options(joinedload(Lead.person)).filter(
                    Lead.blocked == False,
                    Lead.validation_status == "valid"
                ).limit(100).all()
                
                # Filter out leads that already have sent emails
                from db.models import SentEmail
                sent_lead_ids = {se.lead_id for se in db.query(SentEmail.lead_id).filter(
                    SentEmail.lead_id.in_([l.id for l in all_valid_leads]),
                    SentEmail.sent == True
                ).all()}
                
                leads_to_send = [l for l in all_valid_leads if l.id not in sent_lead_ids]
                already_sent_count = len(sent_lead_ids)
                
                if leads_to_send:
                    st.info(f"✅ Found {len(leads_to_send)} valid, unblocked leads (already sent: {already_sent_count})")
                    st.success(f"📧 {len(leads_to_send)} leads ready to send (auto-selected)")
                elif already_sent_count > 0:
                    st.warning(f"⚠️ All {already_sent_count} leads have already been sent emails")
                else:
                    st.warning("⚠️ No valid, unblocked leads found")
            
            else:  # Manual Selection
                # Let user select leads manually with eager loading
                all_leads = db.query(Lead).options(joinedload(Lead.person)).filter(Lead.blocked == False).limit(500).all()
                
                if all_leads:
                    # Check which leads have already been sent emails
                    from db.models import SentEmail
                    sent_lead_ids = {se.lead_id for se in db.query(SentEmail.lead_id).filter(
                        SentEmail.lead_id.in_([l.id for l in all_leads]),
                        SentEmail.sent == True
                    ).all()}
                    
                    # Create options with sent status indicator
                    lead_options = {}
                    default_selected = []
                    
                    for l in all_leads:
                        name = l.person.name if l.person else "Unknown"
                        is_sent = l.id in sent_lead_ids
                        status_label = " ✅ SENT" if is_sent else ""
                        option_key = f"{name} ({l.email}) - {l.company}{status_label}"
                        lead_options[option_key] = l.id
                        
                        # Auto-select unsent leads
                        if not is_sent:
                            default_selected.append(option_key)
                    
                    selected_lead_ids = st.multiselect(
                        "Select Leads to Send",
                        options=list(lead_options.keys()),
                        default=default_selected,  # Auto-select unsent leads
                        help="Leads marked with '✅ SENT' have already received emails. Unsent leads are auto-selected."
                    )
                    
                    if selected_lead_ids:
                        selected_ids = [lead_options[name] for name in selected_lead_ids]
                        leads_to_send = db.query(Lead).options(joinedload(Lead.person)).filter(Lead.id.in_(selected_ids)).all()
                        
                        # Count sent vs unsent
                        unsent_count = sum(1 for l in leads_to_send if l.id not in sent_lead_ids)
                        sent_count = len(leads_to_send) - unsent_count
                        
                        if sent_count > 0:
                            st.warning(f"⚠️ {sent_count} of {len(leads_to_send)} selected leads have already been sent emails")
                        st.info(f"✅ Selected {len(leads_to_send)} leads ({unsent_count} unsent, {sent_count} already sent)")
                else:
                    st.warning("⚠️ No leads available")
            
            if leads_to_send:
                subject = st.text_input("Email Subject", value="Quick question")
                
                # Preview leads with sent status
                with st.expander(f"Preview {len(leads_to_send)} Leads"):
                    from db.models import SentEmail
                    sent_lead_ids = {se.lead_id for se in db.query(SentEmail.lead_id).filter(
                        SentEmail.lead_id.in_([l.id for l in leads_to_send]),
                        SentEmail.sent == True
                    ).all()}
                    
                    preview_data = []
                    for lead in leads_to_send:
                        is_sent = lead.id in sent_lead_ids
                        preview_data.append({
                            "Name": lead.person.name if lead.person else "N/A",
                            "Email": lead.email,
                            "Company": lead.company,
                            "Status": lead.validation_status,
                            "Email Sent": "✅ Yes" if is_sent else "❌ No"
                        })
                    st.dataframe(pd.DataFrame(preview_data), width='stretch', hide_index=True)
                
                if st.button("🚀 Send Emails", type="primary"):
                    if not subject:
                        st.error("Please enter an email subject")
                    else:
                        try:
                            from utils.settings import get_setting as _get_setting_send
                            from agents.smtp_sender import get_active_smtp_servers, send_email_dispatch
                            use_smtp = _get_setting_send("use_smtp_servers", False, db=db)
                            smtp_servers = get_active_smtp_servers(db) if use_smtp else []
                            use_smtp_path = use_smtp and len(smtp_servers) > 0
                            service = None
                            if not use_smtp_path:
                                try:
                                    service = authenticate_gmail()
                                except (FileNotFoundError, ValueError) as auth_error:
                                    st.error(f"❌ Gmail Authentication Error:\n{auth_error}")
                                    st.info("💡 **Troubleshooting:**\n"
                                           "1. Ensure `client_secret1.json` is in the project root\n"
                                           "2. If credentials are invalid, download new ones from Google Cloud Console\n"
                                           "3. Delete `token.pickle` to force re-authentication\n"
                                           "4. Or enable **Use SMTP servers** in Settings and add SMTP servers on the SMTP Servers page.")
                                    st.stop()
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            results = []
                            
                            for i, lead in enumerate(leads_to_send):
                                lead_name = lead.person.name if lead.person else "Unknown"
                                status_text.text(f"Sending to {lead_name} ({lead.email})... ({i+1}/{len(leads_to_send)})")
                                
                                try:
                                    # Get verified signals from database (evidence-based)
                                    verified_signals = []
                                    company_focus = None
                                    
                                    try:
                                        from db.models import EnrichmentSignal, ScrapedContent
                                        from scrapers.enrichment import summarize_company_focus
                                        
                                        # Get verified signals for this lead
                                        signals = db.query(EnrichmentSignal).filter(
                                            EnrichmentSignal.lead_id == lead.id,
                                            EnrichmentSignal.confidence >= 0.7
                                        ).all()
                                        
                                        verified_signals = [
                                            {
                                                "signal_type": s.signal_type,
                                                "signal_text": s.signal_text,
                                                "source_url": s.source_url,
                                                "confidence": s.confidence
                                            }
                                            for s in signals
                                        ]
                                        
                                        # Get company focus if available
                                        if lead.person and lead.person.company:
                                            company_id = lead.person.company.id
                                            scraped_content = db.query(ScrapedContent).filter(
                                                ScrapedContent.company_id == company_id
                                            ).all()
                                            
                                            if scraped_content:
                                                scraped_texts = [
                                                    {
                                                        "source_url": c.source_url,
                                                        "raw_text": c.raw_text,
                                                        "page_type": c.page_type,
                                                        "page_date": c.page_date
                                                    }
                                                    for c in scraped_content
                                                ]
                                                company_focus = summarize_company_focus(scraped_texts)
                                        
                                    except Exception:
                                        pass
                                    
                                    # Campaign context (so emails adapt to campaign offer)
                                    campaign_name = None
                                    campaign_offer = None
                                    cid = campaign_id  # from "From Campaign Leads" mode
                                    if not cid and lead.person and lead.person.company:
                                        cid = lead.person.company.campaign_id  # per-lead campaign when Manual/All
                                    if cid:
                                        camp = db.query(Campaign).filter(Campaign.id == cid).first()
                                        if camp:
                                            campaign_name = camp.name
                                            campaign_offer = getattr(camp, 'offer_description', None) or camp.name
                                    
                                    # Build company_enrichment / person_enrichment from Company + verified signals (use all data)
                                    company_enrichment = {}
                                    person_enrichment = {}
                                    if lead.person and lead.person.company:
                                        co = lead.person.company
                                        if co.signals:
                                            company_enrichment["signals"] = co.signals
                                        if co.funding_stage:
                                            company_enrichment["funding_stage"] = co.funding_stage
                                        if co.hq_country:
                                            company_enrichment["hq_country"] = co.hq_country
                                    for s in verified_signals:
                                        t = s.get("signal_type", "")
                                        txt = s.get("signal_text", "")
                                        if t in ("funding_round", "latest_funding") and txt:
                                            company_enrichment["latest_funding"] = txt
                                        if t in ("company_announcement", "recent_news") and txt:
                                            company_enrichment["recent_news"] = company_enrichment.get("recent_news", "") + " " + txt
                                        if t in ("recent_hires", "hiring_signal") and txt:
                                            company_enrichment["recent_hires"] = txt
                                        if t in ("product_launch", "product_updates") and txt:
                                            company_enrichment["product_updates"] = txt
                                        if t == "pain_point" and txt:
                                            person_enrichment["pain_points"] = txt
                                        if t in ("recent_activity", "public_statement") and txt:
                                            person_enrichment["recent_activity"] = txt
                                    
                                    # Generate evidence-based email (use all enrichment + campaign)
                                    from agents.email_agent import generate_evidence_based_email, should_send_email
                                    
                                    if verified_signals or company_focus or company_enrichment or person_enrichment:
                                        body = generate_evidence_based_email(
                                            name=lead_name,
                                            company=lead.company,
                                            role=lead.role or "",
                                            verified_signals=verified_signals,
                                            company_focus=company_focus,
                                            company_enrichment=company_enrichment or None,
                                            person_enrichment=person_enrichment or None,
                                            min_confidence=0.7,
                                            campaign_name=campaign_name,
                                            campaign_offer=campaign_offer,
                                        )
                                    else:
                                        body = generate_email(
                                            lead_name,
                                            lead.company,
                                            lead.linkedin_url or "",
                                            company_enrichment=company_enrichment or None,
                                            person_enrichment=person_enrichment or None,
                                            campaign_name=campaign_name,
                                            campaign_offer=campaign_offer,
                                        )
                                    
                                    # Mail Critic: evaluate and rewrite until pass or max_rewrites
                                    from utils.settings import get_setting as _get_setting
                                    enable_critic = _get_setting("enable_mail_critic", True, db=db)
                                    if enable_critic:
                                        from agents.mail_critic import evaluate_email, rewrite_email_with_feedback
                                        min_score = float(_get_setting("critic_min_score", 0.7, db=db))
                                        max_rewrites = int(_get_setting("critic_max_rewrites", 2, db=db))
                                        strictness = _get_setting("critic_strictness", "medium", db=db) or "medium"
                                        for attempt in range(max_rewrites + 1):
                                            passed, score, feedback = evaluate_email(
                                                body, lead_name, lead.company,
                                                min_score=min_score, strictness=strictness,
                                            )
                                            if passed:
                                                break
                                            if feedback and attempt < max_rewrites:
                                                body = rewrite_email_with_feedback(
                                                    body, feedback, lead_name, lead.company,
                                                )
                                    
                                    # Check if should send
                                    should_send, reason = should_send_email(
                                        verified_signals=verified_signals,
                                        email_body=body,
                                        min_confidence=0.7,
                                        require_signal=False
                                    )
                                    
                                    if not should_send:
                                        st.warning(f"Email rejected: {reason}")
                                        results.append({
                                            "name": lead_name,
                                            "email": lead.email,
                                            "company": lead.company,
                                            "sent": False,
                                            "thread_id": None,
                                        })
                                        continue
                                    
                                    # Send email (SMTP rotation or Gmail)
                                    if use_smtp_path:
                                        thread_id = send_email_dispatch(lead.email, subject, body, check_rate_limit=True, lead_id=lead.id, db=db)
                                    else:
                                        thread_id = send_email(service, lead.email, subject, body, check_rate_limit=True, lead_id=lead.id)
                                    
                                    results.append({
                                        "name": lead_name,
                                        "email": lead.email,
                                        "company": lead.company,
                                        "sent": thread_id is not None,
                                        "thread_id": thread_id,
                                    })
                                    
                                    if thread_id:
                                        # Use configurable delay from settings
                                        from utils.settings import get_setting
                                        email_delay = get_setting("email_delay_seconds", 0.5, db=db)
                                        time.sleep(email_delay)
                                    
                                except Exception as e:
                                    lead_name = lead.person.name if lead.person else "Unknown"
                                    st.warning(f"Failed to send to {lead.email}: {e}")
                                    results.append({
                                        "name": lead_name,
                                        "email": lead.email,
                                        "company": lead.company,
                                        "sent": False,
                                        "thread_id": None,
                                    })
                                
                                progress_bar.progress((i + 1) / len(leads_to_send))
                            
                            # Show results
                            sent_count = sum(1 for r in results if r["sent"])
                            st.success(f"✅ Sent {sent_count} out of {len(leads_to_send)} emails!")
                            
                            results_df = pd.DataFrame(results)
                            st.dataframe(results_df, width='stretch', hide_index=True)
                            
                        except Exception as e:
                            st.error(f"Error sending emails: {e}")
        
        with tab2:
            st.subheader("🔍 Scrape Leads")
            
            campaigns = db.query(Campaign).all()
            if campaigns:
                campaign_names = {c.name: c.id for c in campaigns}
                campaign_names["Custom Query"] = None
                
                selected = st.selectbox("Select Campaign or Custom Query", list(campaign_names.keys()))
                
                if selected == "Custom Query":
                    query = st.text_area("Search Query", placeholder="Seed stage B2B SaaS startups hiring SDRs")
                    max_companies = st.number_input("Max Companies", min_value=1, max_value=50, value=20)
                    max_people = st.number_input("Max People per Company", min_value=1, max_value=10, value=3)
                    require_valid = st.checkbox("Require Valid Email", value=True)
                    campaign_id = None
                else:
                    campaign_id = campaign_names[selected]
                    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                    query = campaign.query
                    max_companies = campaign.max_companies
                    max_people = campaign.max_people_per_company
                    require_valid = campaign.require_valid_email
                    
                    st.info(f"Using campaign settings: {query}")
                
                if st.button("🚀 Start Scraping", type="primary"):
                    if not query:
                        st.error("Please enter a search query")
                    else:
                        try:
                            # Get scraping settings
                            from utils.settings import get_setting
                            enrichment_level = get_setting("scraping_enrichment_level", "deep", db=db)
                            max_companies_setting = get_setting("max_companies_per_scrape", 20, db=db)
                            max_people_setting = get_setting("max_people_per_company", 3, db=db)
                            
                            # Use settings if not overridden
                            if max_companies == 20:  # Default value
                                max_companies = max_companies_setting
                            if max_people == 3:  # Default value
                                max_people = max_people_setting
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            status_text.text(f"🔍 Searching for companies (enrichment: {enrichment_level})...")
                            companies = search_companies(query, limit=max_companies, enrichment_level=enrichment_level) or []
                            status_text.text(f"✅ Found {len(companies)} companies")
                            
                            if not companies:
                                st.warning(
                                    "No companies found. Try: a shorter/simpler query (e.g. 'B2B SaaS startups'), "
                                    "or check that PPLX_API_KEY is set. The system will retry with a simpler prompt automatically."
                                )
                            else:
                                leads_written = 0
                                seen_emails = set()
                                companies_processed = 0
                                companies_skipped = 0
                                
                                # Get existing companies from database to skip duplicates
                                existing_companies = set()
                                if campaign_id:
                                    # Check for companies in this campaign
                                    existing_companies_query = db.query(Company.domain, Company.company_name).filter(
                                        Company.campaign_id == campaign_id
                                    ).all()
                                    existing_companies = {(c.domain.lower(), c.company_name.lower()) for c in existing_companies_query}
                                else:
                                    # Check for companies with matching domain or name
                                    all_companies = db.query(Company.domain, Company.company_name).all()
                                    existing_companies = {(c.domain.lower(), c.company_name.lower()) for c in all_companies}
                                
                                total_to_process = min(len(companies), max_companies) * max_people
                                processed = 0
                                
                                for c_idx, c in enumerate(companies[:max_companies]):
                                    domain = c.get("domain") or ""
                                    company_name = c.get("company_name") or ""
                                    linkedin = c.get("linkedin") or ""
                                    
                                    # Try to extract domain if missing
                                    if not domain:
                                        # Try to extract from LinkedIn URL
                                        if linkedin and "linkedin.com/company/" in linkedin:
                                            try:
                                                slug = linkedin.split("linkedin.com/company/")[-1].split("/")[0].split("?")[0]
                                                domain = f"{slug}.com"
                                            except:
                                                pass
                                        
                                        # Try to infer from company name
                                        if not domain and company_name:
                                            name_clean = company_name.lower().replace(" ", "").replace("inc", "").replace("llc", "").replace("ltd", "").replace(".", "")
                                            domain = f"{name_clean}.com"
                                    
                                    if not domain:
                                        continue
                                    
                                    # Check if company already exists (deduplication)
                                    domain_lower = domain.lower()
                                    company_name_lower = company_name.lower()
                                    
                                    if (domain_lower, company_name_lower) in existing_companies:
                                        companies_skipped += 1
                                        status_text.text(f"⏭️  Skipping {company_name} ({domain}) - already exists in database... ({c_idx+1}/{min(len(companies), max_companies)})")
                                        continue
                                    
                                    companies_processed += 1
                                    status_text.text(f"🔍 Scraping people at {company_name} ({domain})... ({c_idx+1}/{min(len(companies), max_companies)})")
                                    
                                    # Get people with enrichment
                                    people = search_people(domain, limit=max_people, enrichment_level=enrichment_level) or []
                                    
                                    for p in people[:max_people]:
                                        name = p.get("name") or ""
                                        if not name:
                                            continue
                                        
                                        # Generate candidate emails
                                        candidates = generate_email_candidates(name, domain)
                                        if not candidates:
                                            continue
                                        
                                        chosen_email = None
                                        chosen_status = "unknown"
                                        chosen_confidence = 0.5
                                        
                                        # Validate via SMTP (+ optional Hunter)
                                        for candidate in candidates:
                                            smtp_res = validate_email(candidate)
                                            
                                            if smtp_res["status"] == "invalid":
                                                continue
                                            
                                            hunter_res = verify_with_hunter(candidate)
                                            if hunter_res.get("ok"):
                                                chosen_email = candidate
                                                chosen_status = "valid"
                                                chosen_confidence = max(
                                                    smtp_res.get("confidence", 0.0),
                                                    (hunter_res.get("score") or 0) / 100.0
                                                )
                                                break
                                            
                                            if smtp_res["status"] in ("valid", "unknown"):
                                                chosen_email = candidate
                                                chosen_status = smtp_res["status"]
                                                chosen_confidence = smtp_res.get("confidence", 0.5)
                                                if smtp_res["status"] == "valid":
                                                    break
                                        
                                        if not chosen_email:
                                            continue
                                        
                                        if require_valid and chosen_status != "valid":
                                            continue
                                        
                                        if chosen_email in seen_emails:
                                            continue
                                        seen_emails.add(chosen_email)
                                        
                                        # Build row with enrichment data
                                        row = {
                                            "name": name,
                                            "email": chosen_email,
                                            "company": company_name,
                                            "linkedin_url": p.get("linkedin_url", ""),
                                            "role": p.get("role", ""),
                                            "domain": domain,
                                            "confidence": chosen_confidence,
                                            "validation_status": chosen_status,
                                            "source_query": query,
                                            "timestamp": datetime.now(timezone.utc).isoformat(),
                                        }
                                        
                                        # Store enrichment data for email personalization
                                        # Extract company enrichment from company dict
                                        company_enrichment = {}
                                        if c.get("recent_news"):
                                            company_enrichment["recent_news"] = c.get("recent_news")
                                        if c.get("latest_funding"):
                                            company_enrichment["latest_funding"] = c.get("latest_funding")
                                        if c.get("recent_hires"):
                                            company_enrichment["recent_hires"] = c.get("recent_hires")
                                        if c.get("product_updates"):
                                            company_enrichment["product_updates"] = c.get("product_updates")
                                        if c.get("pain_points"):
                                            company_enrichment["pain_points"] = c.get("pain_points")
                                        if c.get("growth_metrics"):
                                            company_enrichment["growth_metrics"] = c.get("growth_metrics")
                                        
                                        # Extract person enrichment from people dict
                                        person_enrichment = {}
                                        if p.get("recent_activity"):
                                            person_enrichment["recent_activity"] = p.get("recent_activity")
                                        if p.get("company_news"):
                                            person_enrichment["company_news"] = p.get("company_news")
                                        if p.get("pain_points"):
                                            person_enrichment["pain_points"] = p.get("pain_points")
                                        if p.get("industry_insights"):
                                            person_enrichment["industry_insights"] = p.get("industry_insights")
                                        
                                        # Store enrichment in row (will be available for email generation)
                                        if company_enrichment or person_enrichment:
                                            row["company_enrichment"] = json.dumps(company_enrichment) if company_enrichment else ""
                                            row["person_enrichment"] = json.dumps(person_enrichment) if person_enrichment else ""
                                        
                                        write_to_csv_and_db(row, campaign_id=campaign_id)
                                        leads_written += 1
                                        
                                        processed += 1
                                        progress_bar.progress(processed / total_to_process if total_to_process > 0 else 0)
                                
                                # Update progress bar to 100%
                                progress_bar.progress(1.0)
                                
                                st.success(f"✅ Scraping complete!")
                                st.info(f"📊 Statistics:")
                                st.info(f"   - Companies processed: {companies_processed}")
                                st.info(f"   - Companies skipped (duplicates): {companies_skipped}")
                                st.info(f"   - New leads created: {leads_written}")
                                
                                st.rerun()
                                
                        except Exception as e:
                            st.error(f"Error during scraping: {e}")
                            import traceback
                            st.code(traceback.format_exc())
            else:
                st.info("No campaigns available. Create one first in the Campaigns page.")
        
        with tab3:
            st.subheader("📥 Add Leads from CSV/Excel")
            st.caption("Upload a CSV or Excel file. **Only email is required.** If the file has only emails, we use domain from email (@ part), name from part before @; rest left empty.")
            
            uploaded_file = st.file_uploader("Choose CSV or Excel file", type=["csv", "xlsx", "xls"], key="add_leads_upload")
            campaign_id_import = None
            campaigns = db.query(Campaign).all()
            if campaigns:
                campaign_names_import = {c.name: c.id for c in campaigns}
                campaign_names_import["— None (use Default) —"] = None
                selected_campaign_import = st.selectbox("Assign to campaign", list(campaign_names_import.keys()), key="add_leads_campaign")
                campaign_id_import = campaign_names_import.get(selected_campaign_import)
            also_csv = st.checkbox("Also append to leads.csv", value=True, help="Keep a CSV backup of imported leads")
            
            def _derive_from_email(addr: str):
                """From email derive: domain (after @), name (before @, formatted), company (empty)."""
                addr = (addr or "").strip()
                if "@" in addr:
                    local, domain = addr.split("@", 1)
                    name = local.replace(".", " ").replace("_", " ").replace("-", " ").strip().title() or local
                    return domain.strip(), name, ""
                return "", addr, ""
            
            if uploaded_file:
                try:
                    if uploaded_file.name.lower().endswith(".csv"):
                        df = pd.read_csv(uploaded_file)
                    else:
                        df = pd.read_excel(uploaded_file)
                    
                    if df.empty:
                        st.warning("File is empty.")
                    else:
                        # Auto-detect column mapping (case-insensitive)
                        col_map_lower = {str(c).lower().strip(): c for c in df.columns}
                        def pick_col(*names):
                            for n in names:
                                if n in col_map_lower:
                                    return col_map_lower[n]
                                if n.replace("_", " ") in col_map_lower:
                                    return col_map_lower[n.replace("_", " ")]
                            return None
                        
                        name_col = pick_col("name", "full name", "contact name")
                        email_col = pick_col("email", "email address", "e-mail")
                        company_col = pick_col("company", "company name", "organization")
                        domain_col = pick_col("domain", "website", "company domain")
                        linkedin_col = pick_col("linkedin_url", "linkedin", "linkedin url")
                        role_col = pick_col("role", "title", "job title")
                        
                        # Email is required; name/company can be "derive from email"
                        if not email_col:
                            email_col = st.selectbox("Map column to **Email** (required)", options=list(df.columns), key="map_email")
                        if not name_col:
                            name_col = st.selectbox("Map column to **Name** (optional)", options=["— From email (before @) —"] + list(df.columns), key="map_name")
                            if name_col == "— From email (before @) —":
                                name_col = None
                        if not company_col:
                            company_col = st.selectbox("Map column to **Company** (optional)", options=["— Leave empty —"] + list(df.columns), key="map_company")
                            if company_col == "— Leave empty —":
                                company_col = None
                        if not domain_col and "domain" not in [name_col, email_col, company_col]:
                            domain_col = st.selectbox("Map column to **Domain** (optional)", options=["— From email (@ part) —"] + list(df.columns), key="map_domain")
                            if domain_col == "— From email (@ part) —":
                                domain_col = None
                        if not linkedin_col:
                            linkedin_col = st.selectbox("Map column to **LinkedIn** (optional)", options=["— Skip —"] + list(df.columns), key="map_linkedin")
                            if linkedin_col == "— Skip —":
                                linkedin_col = None
                        if not role_col:
                            role_col = st.selectbox("Map column to **Role** (optional)", options=["— Skip —"] + list(df.columns), key="map_role")
                            if role_col == "— Skip —":
                                role_col = None
                        
                        st.markdown("---")
                        with st.expander("Preview first 5 rows"):
                            st.dataframe(df.head(5), width='stretch', hide_index=True)
                        
                        if email_col and st.button("📥 Import Leads", type="primary", key="import_leads_btn"):
                            from utils.writer import write_to_csv_and_db, write_to_database
                            from datetime import datetime, timezone
                            
                            added = 0
                            skipped = 0
                            errors = 0
                            progress = st.progress(0)
                            status = st.empty()
                            
                            for idx, row in df.iterrows():
                                email = str(row.get(email_col, "")).strip()
                                if not email or "@" not in email:
                                    skipped += 1
                                    continue
                                name = str(row.get(name_col, "")).strip() if name_col else ""
                                company = str(row.get(company_col, "")).strip() if company_col else ""
                                domain = str(row.get(domain_col, "")).strip() if domain_col else ""
                                linkedin_url = str(row.get(linkedin_col, "")).strip() if linkedin_col else ""
                                role = str(row.get(role_col, "")).strip() if role_col else ""
                                
                                # If name/company/domain missing, derive from email
                                if not domain:
                                    domain, _dname, _dcompany = _derive_from_email(email)
                                if not name:
                                    _, name, _ = _derive_from_email(email)
                                if not company:
                                    company = ""  # leave empty when email-only
                                if not domain and company:
                                    domain = company.lower().replace(" ", "").replace(".", "").replace(",", "")[:50] + ".com"
                                if not domain:
                                    domain = email.split("@")[-1].strip() if "@" in email else ""
                                
                                data = {
                                    "name": name or email.split("@")[0],
                                    "email": email,
                                    "company": company or "(unknown)",
                                    "domain": domain or email.split("@")[-1] if "@" in email else "",
                                    "linkedin_url": linkedin_url,
                                    "role": role,
                                    "confidence": 0.5,
                                    "validation_status": "unknown",
                                    "source_query": "CSV/Excel import",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                                try:
                                    if also_csv:
                                        write_to_csv_and_db(data, campaign_id=campaign_id_import)
                                        added += 1
                                    else:
                                        if write_to_database(data, campaign_id=campaign_id_import):
                                            added += 1
                                except Exception:
                                    errors += 1
                                
                                progress.progress((idx + 1) / len(df))
                                status.text(f"Imported {added} | Skipped {skipped} | Errors {errors}")
                            
                            progress.empty()
                            status.empty()
                            st.success(f"✅ Import complete: **{added}** leads added, {skipped} skipped (missing data), {errors} errors.")
                except Exception as e:
                    st.error(f"Error reading file: {e}")
                    import traceback
                    st.code(traceback.format_exc())
        
        with tab4:
            st.subheader("🔄 Check Bounces")
            
            st.info("Bounce checking scans Gmail for bounce notifications and updates the database.")
            
            if st.button("🔄 Run Bounce Check", type="primary"):
                try:
                    from agents.gmail_service import authenticate_gmail
                    from agents.tracker import process_bounces, get_bounce_rate
                    from agents.rate_limiter import update_rate_limits
                    
                    status_text = st.empty()
                    status_text.text("🔍 Authenticating Gmail...")
                    
                    service = authenticate_gmail()
                    
                    status_text.text("🔍 Checking for bounces...")
                    bounce_count = process_bounces(service, days=1)
                    
                    if bounce_count > 0:
                        st.success(f"✅ Processed {bounce_count} bounces")
                        
                        # Update rate limits based on bounce rate
                        bounce_rate = get_bounce_rate(days=7)
                        update_rate_limits(bounce_rate)
                        st.info(f"📊 Bounce rate: {bounce_rate:.2%}")
                        st.info(f"📊 Updated rate limits based on bounce rate")
                    else:
                        st.success("✅ No new bounces detected")
                    
                    status_text.empty()
                    
                except Exception as e:
                    st.error(f"Error checking bounces: {e}")
                    import traceback
                    st.code(traceback.format_exc())
        
        with tab5:
            st.subheader("🛠️ Manage Leads")
            
            # Lead actions
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Unblock Leads")
                blocked_leads = db.query(Lead).filter(Lead.blocked == True).limit(50).all()
                
                if blocked_leads:
                    # Eager load person relationship (re-query with joinedload)
                    blocked_leads_loaded = db.query(Lead).options(joinedload(Lead.person)).filter(Lead.blocked == True).limit(50).all()
                    lead_options = {f"{l.person.name if l.person else 'Unknown'} ({l.email})": l.id for l in blocked_leads_loaded}
                    selected_to_unblock = st.multiselect(
                        "Select Leads to Unblock",
                        options=list(lead_options.keys())
                    )
                    
                    if st.button("✅ Unblock Selected", type="primary"):
                        if selected_to_unblock:
                            selected_ids = [lead_options[name] for name in selected_to_unblock]
                            updated = db.query(Lead).filter(Lead.id.in_(selected_ids)).update({
                                Lead.blocked: False,
                                Lead.blocked_reason: None
                            }, synchronize_session=False)
                            db.commit()
                            st.success(f"✅ Unblocked {updated} leads")
                            st.rerun()
                else:
                    st.info("No blocked leads")
            
            with col2:
                st.subheader("Block Leads")
                unblocked_leads = db.query(Lead).filter(Lead.blocked == False).limit(50).all()
                
                if unblocked_leads:
                    # Eager load person relationship (re-query with joinedload)
                    unblocked_leads_loaded = db.query(Lead).options(joinedload(Lead.person)).filter(Lead.blocked == False).limit(50).all()
                    lead_options = {f"{l.person.name if l.person else 'Unknown'} ({l.email})": l.id for l in unblocked_leads_loaded}
                    selected_to_block = st.multiselect(
                        "Select Leads to Block",
                        options=list(lead_options.keys())
                    )
                    
                    block_reason = st.text_input("Block Reason", placeholder="e.g., Invalid email, requested removal")
                    
                    if st.button("🚫 Block Selected", type="primary"):
                        if selected_to_block:
                            selected_ids = [lead_options[name] for name in selected_to_block]
                            updated = db.query(Lead).filter(Lead.id.in_(selected_ids)).update({
                                Lead.blocked: True,
                                Lead.blocked_reason: block_reason or "Manually blocked"
                            }, synchronize_session=False)
                            db.commit()
                            st.success(f"✅ Blocked {updated} leads")
                            st.rerun()
                else:
                    st.info("No unblocked leads to block")
                
    except Exception as e:
        st.error(f"Error: {e}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        db.close()


# ============================================================================
# SMTP SERVERS PAGE
# ============================================================================
elif page == "📧 SMTP Servers":
    st.title("📧 SMTP Servers")
    st.caption("Add and manage SMTP servers for sending emails. Enable \"Use SMTP servers\" in Settings → Email Settings and choose a rotation strategy.")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import SmtpServer
        from agents.smtp_sender import get_active_smtp_servers, send_email_smtp
        
        tab_list, tab_add = st.tabs(["Manage Servers", "Add Server"])
        
        with tab_list:
            servers = db.query(SmtpServer).order_by(SmtpServer.priority.desc(), SmtpServer.id).all()
            if not servers:
                st.info("No SMTP servers yet. Add one in the **Add Server** tab.")
            else:
                for s in servers:
                    conn_type = "SSL (465)" if getattr(s, "use_ssl", None) or (s.port == 465) else "STARTTLS (587)"
                    with st.expander(f"{'✅' if s.is_active else '⏸️'} {s.name} — {s.host}:{s.port} [{conn_type}]", expanded=False):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.text(f"From: {s.from_name or s.from_email} <{s.from_email}>")
                            st.text(f"TLS: {s.use_tls}  •  Priority: {s.priority}  •  Emails sent: {s.emails_sent or 0}")
                            imap_h = getattr(s, "imap_host", None)
                            st.caption(f"Inbox (IMAP): {imap_h or '— Not set'}")
                            if s.last_used_at:
                                st.caption(f"Last used: {s.last_used_at}")
                        with col2:
                            if st.button("Test connection", key=f"test_{s.id}"):
                                try:
                                    msg_id = send_email_smtp(s, s.from_email, "SMTP test", "Test from AI Outbound SMTP.", db=db, update_usage=False)
                                    if msg_id:
                                        st.success("Test email sent to yourself.")
                                    else:
                                        st.error("Send failed.")
                                except Exception as e:
                                    st.error(str(e))
                            if st.button("Delete", key=f"del_{s.id}"):
                                db.delete(s)
                                db.commit()
                                st.success("Deleted.")
                                st.rerun()
        
        with tab_add:
            st.subheader("Add Email Server (SMTP + optional IMAP)")
            name = st.text_input("Name", placeholder="e.g. Primary SMTP", key="smtp_name")
            host = st.text_input("SMTP Host", placeholder="smtp.example.com", key="smtp_host")
            port = st.number_input("SMTP Port", min_value=1, max_value=65535, value=587, key="smtp_port", help="587 = STARTTLS, 465 = SSL")
            use_tls = st.checkbox("Use STARTTLS (port 587)", value=True, key="smtp_tls")
            use_ssl = st.checkbox("Use SSL (port 465) — check if your host uses 465", value=False, key="smtp_use_ssl")
            username = st.text_input("Username", key="smtp_username")
            password = st.text_input("Password", type="password", key="smtp_password", help="Stored in database.")
            from_email = st.text_input("From email", placeholder="noreply@example.com", key="smtp_from_email")
            from_name = st.text_input("From name (optional)", placeholder="Your Company", key="smtp_from_name")
            is_active = st.checkbox("Active", value=True, key="smtp_active")
            priority = st.number_input("Priority (higher = preferred when rotating)", value=0, key="smtp_priority")
            st.markdown("---")
            st.subheader("Inbox (IMAP) — optional")
            st.caption("Configure IMAP to view sent/received emails in the Inbox section.")
            imap_host = st.text_input("IMAP Host", placeholder="imap.example.com or leave blank to use SMTP host", key="imap_host")
            imap_port = st.number_input("IMAP Port", value=993, min_value=1, max_value=65535, key="imap_port")
            imap_use_ssl = st.checkbox("IMAP Use SSL", value=True, key="imap_use_ssl")
            if st.button("Add SMTP Server", type="primary"):
                if not all([name, host, username, password, from_email]):
                    st.error("Fill in name, host, username, password, and from email.")
                else:
                    server = SmtpServer(
                        name=name,
                        host=host.strip(),
                        port=int(port),
                        username=username.strip(),
                        password=password,
                        use_tls=use_tls,
                        use_ssl=use_ssl,
                        from_email=from_email.strip(),
                        from_name=(from_name or "").strip(),
                        is_active=is_active,
                        priority=int(priority),
                        imap_host=imap_host.strip() or None,
                        imap_port=int(imap_port),
                        imap_use_ssl=imap_use_ssl,
                    )
                    db.add(server)
                    db.commit()
                    st.success(f"Added {name}.")
                    st.rerun()
    except Exception as e:
        st.error(str(e))
        import traceback
        st.code(traceback.format_exc())
    finally:
        db.close()


# ============================================================================
# INBOX PAGE
# ============================================================================
elif page == "📬 Inbox":
    st.title("📬 Inbox")
    st.caption("Select an email server to view sent and received emails. Configure IMAP on the SMTP Servers page for each account.")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from db.models import SmtpServer
        from agents.imap_inbox import fetch_received, fetch_sent
        
        servers = db.query(SmtpServer).order_by(SmtpServer.priority.desc(), SmtpServer.id).all()
        if not servers:
            st.info("No email servers yet. Add one in **SMTP Servers** and optionally set IMAP host for inbox.")
            st.stop()
        
        server_names = {f"{s.name} ({s.from_email})": s for s in servers}
        selected_label = st.selectbox("Select server", list(server_names.keys()), key="inbox_server")
        server = server_names.get(selected_label)
        if not server:
            st.stop()
        
        tab_inbox, tab_sent = st.tabs(["📥 Received (INBOX)", "📤 Sent"])
        limit = st.sidebar.number_input("Max emails to load", value=50, min_value=10, max_value=500, key="inbox_limit")
        
        with tab_inbox:
            if st.button("🔄 Refresh Inbox", key="refresh_inbox"):
                st.rerun()
            try:
                received = fetch_received(server, limit=limit)
                if not received:
                    st.info("No emails in INBOX or IMAP not configured. Set IMAP host in SMTP Servers for this account.")
                else:
                    for r in received:
                        with st.expander(f"{r.get('date_str', '')[:24]} — {r.get('from_', '')[:40]} — {r.get('subject', '')[:50]}"):
                            st.text(f"From: {r.get('from_', '')}")
                            st.text(f"To: {r.get('to_', '')}")
                            st.text(f"Subject: {r.get('subject', '')}")
                            st.text(f"Date: {r.get('date_str', '')}")
                            if r.get("snippet"):
                                st.text(r["snippet"])
            except Exception as e:
                st.error(f"Failed to load inbox: {e}")
                st.caption("Ensure IMAP host is set for this server (e.g. imap.example.com) and credentials are correct.")
        
        with tab_sent:
            if st.button("🔄 Refresh Sent", key="refresh_sent"):
                st.rerun()
            try:
                sent = fetch_sent(server, limit=limit)
                if not sent:
                    st.info("No sent emails found or IMAP not configured.")
                else:
                    for r in sent:
                        with st.expander(f"{r.get('date_str', '')[:24]} — To: {r.get('to_', '')[:40]} — {r.get('subject', '')[:50]}"):
                            st.text(f"From: {r.get('from_', '')}")
                            st.text(f"To: {r.get('to_', '')}")
                            st.text(f"Subject: {r.get('subject', '')}")
                            st.text(f"Date: {r.get('date_str', '')}")
                            if r.get("snippet"):
                                st.text(r["snippet"])
            except Exception as e:
                st.error(f"Failed to load sent: {e}")
                st.caption("Ensure IMAP host is set and your provider has a Sent folder (e.g. Sent, Sent Items).")
    except Exception as e:
        st.error(str(e))
        import traceback
        st.code(traceback.format_exc())
    finally:
        db.close()


# ============================================================================
# SETTINGS PAGE
# ============================================================================
elif page == "⚙️ Settings":
    st.title("⚙️ System Settings")
    
    db = get_db_session()
    if db is None:
        st.stop()
    
    try:
        from utils.settings import get_setting, set_setting, initialize_default_settings, DEFAULT_SETTINGS
        from db.models import SystemSettings
        
        # Initialize default settings if needed
        initialize_default_settings(db=db)
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs(["Email Settings", "Scraping Settings", "Rate Limiting", "Personalization", "Mail Critic"])
        
        with tab1:
            st.subheader("📧 Email Sending Settings")
            
            col1, col2 = st.columns(2)
            
            with col1:
                email_delay = st.number_input(
                    "Delay Between Emails (seconds)",
                    min_value=0.0,
                    max_value=60.0,
                    value=float(get_setting("email_delay_seconds", 0.5, db=db)),
                    step=0.1,
                    help="Delay between sending emails to avoid rate limits"
                )
                
                require_valid = st.checkbox(
                    "Require Valid Email",
                    value=get_setting("require_valid_email", True, db=db),
                    help="Only send emails to validated addresses"
                )
                
                enable_rate_limiting = st.checkbox(
                    "Enable Rate Limiting",
                    value=get_setting("enable_rate_limiting", True, db=db),
                    help="Enable automatic rate limiting based on bounce rates"
                )
            
            with col2:
                enable_bounce_checking = st.checkbox(
                    "Enable Bounce Checking",
                    value=get_setting("enable_bounce_checking", True, db=db),
                    help="Automatically check for bounced emails"
                )
                
                bounce_check_interval = st.number_input(
                    "Bounce Check Interval (hours)",
                    min_value=1,
                    max_value=168,
                    value=get_setting("bounce_check_interval_hours", 24, db=db),
                    help="How often to check for bounces"
                )
            
            st.markdown("---")
            st.subheader("📤 SMTP Servers (Rotation)")
            use_smtp_servers = st.checkbox(
                "Use SMTP servers to send emails (instead of Gmail)",
                value=get_setting("use_smtp_servers", False, db=db),
                help="When enabled, emails are sent via SMTP servers configured on the SMTP Servers page. Rotation is applied per settings below."
            )
            smtp_rotation_strategy = st.selectbox(
                "SMTP rotation strategy",
                ["round_robin", "random", "least_used"],
                index=["round_robin", "random", "least_used"].index(get_setting("smtp_rotation_strategy", "round_robin", db=db)),
                help="round_robin: use server with oldest last use; random: pick randomly; least_used: prefer server with fewest sends"
            )
            
            if st.button("💾 Save Email Settings", type="primary"):
                set_setting("email_delay_seconds", email_delay, "float", "Delay between emails (seconds)", db=db)
                set_setting("require_valid_email", require_valid, "bool", "Only send to validated emails", db=db)
                set_setting("enable_rate_limiting", enable_rate_limiting, "bool", "Enable rate limiting", db=db)
                set_setting("enable_bounce_checking", enable_bounce_checking, "bool", "Enable automatic bounce checking", db=db)
                set_setting("bounce_check_interval_hours", bounce_check_interval, "int", "Bounce check interval (hours)", db=db)
                set_setting("use_smtp_servers", use_smtp_servers, "bool", "Use SMTP servers instead of Gmail", db=db)
                set_setting("smtp_rotation_strategy", smtp_rotation_strategy, "string", "SMTP rotation strategy", db=db)
                st.success("✅ Email settings saved!")
                st.rerun()
        
        with tab2:
            st.subheader("🔍 Scraping Settings")
            
            col1, col2 = st.columns(2)
            
            with col1:
                max_companies = st.number_input(
                    "Max Companies Per Scrape",
                    min_value=1,
                    max_value=100,
                    value=get_setting("max_companies_per_scrape", 20, db=db),
                    help="Maximum companies to scrape in a single run"
                )
                
                max_people = st.number_input(
                    "Max People Per Company",
                    min_value=1,
                    max_value=20,
                    value=get_setting("max_people_per_company", 3, db=db),
                    help="Maximum people to find per company"
                )
            
            with col2:
                enrichment_level = st.selectbox(
                    "Scraping Enrichment Level",
                    ["basic", "standard", "deep"],
                    index=["basic", "standard", "deep"].index(get_setting("scraping_enrichment_level", "deep", db=db)),
                    help="How much detail to gather about companies and people"
                )
            
            st.markdown("---")
            st.subheader("Enrichment Options")
            
            include_news = st.checkbox(
                "Include Company News",
                value=get_setting("include_company_news", True, db=db),
                help="Gather recent company news and announcements"
            )
            
            include_funding = st.checkbox(
                "Include Funding Information",
                value=get_setting("include_funding_info", True, db=db),
                help="Gather funding rounds and investor information"
            )
            
            include_hires = st.checkbox(
                "Include Recent Hires",
                value=get_setting("include_recent_hires", True, db=db),
                help="Gather information about recent team expansions"
            )
            
            if st.button("💾 Save Scraping Settings", type="primary"):
                set_setting("max_companies_per_scrape", max_companies, "int", "Maximum companies to scrape per run", db=db)
                set_setting("max_people_per_company", max_people, "int", "Maximum people per company", db=db)
                set_setting("scraping_enrichment_level", enrichment_level, "string", "Scraping enrichment level: basic, standard, deep", db=db)
                set_setting("include_company_news", include_news, "bool", "Include recent company news in email personalization", db=db)
                set_setting("include_funding_info", include_funding, "bool", "Include funding information in personalization", db=db)
                set_setting("include_recent_hires", include_hires, "bool", "Include recent hires/updates in personalization", db=db)
                st.success("✅ Scraping settings saved!")
                st.rerun()
        
        with tab3:
            st.subheader("⏱️ Rate Limiting Settings")
            
            col1, col2 = st.columns(2)
            
            with col1:
                emails_per_hour = st.number_input(
                    "Emails Per Hour",
                    min_value=1,
                    max_value=1000,
                    value=get_setting("rate_limit_emails_per_hour", 10, db=db),
                    help="Maximum emails to send per hour"
                )
            
            with col2:
                emails_per_day = st.number_input(
                    "Emails Per Day",
                    min_value=1,
                    max_value=10000,
                    value=get_setting("rate_limit_emails_per_day", 10, db=db),
                    help="Maximum emails to send per day"
                )
            
            domain_throttle = st.number_input(
                "Max Emails Per Domain Per Day",
                min_value=1,
                max_value=50,
                value=get_setting("domain_throttle_max_per_day", 3, db=db),
                help="Deliverability: max emails to same domain per day"
            )
            
            st.info("💡 Changes apply immediately. Rate limits are read from Settings when enforcing sends.")
            
            if st.button("💾 Save Rate Limit Settings", type="primary"):
                set_setting("rate_limit_emails_per_hour", emails_per_hour, "int", "Maximum emails per hour", db=db)
                set_setting("rate_limit_emails_per_day", emails_per_day, "int", "Maximum emails per day", db=db)
                set_setting("domain_throttle_max_per_day", domain_throttle, "int", "Max emails per domain per day", db=db)
                st.success("✅ Rate limit settings saved!")
                st.rerun()
        
        with tab4:
            st.subheader("🎯 Personalization Settings")
            
            personalization_level = st.selectbox(
                "Email Personalization Level",
                ["low", "medium", "high"],
                index=["low", "medium", "high"].index(get_setting("email_personalization_level", "high", db=db)),
                help="How personalized the emails should be based on enrichment data"
            )
            
            st.markdown("---")
            st.subheader("Personalization Features")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**What gets included:**")
                st.write(f"- Company news: {'✅' if get_setting('include_company_news', True, db=db) else '❌'}")
                st.write(f"- Funding info: {'✅' if get_setting('include_funding_info', True, db=db) else '❌'}")
                st.write(f"- Recent hires: {'✅' if get_setting('include_recent_hires', True, db=db) else '❌'}")
            
            with col2:
                st.write("**Current Level:**")
                if personalization_level == "high":
                    st.success("🔴 **HIGH** - Maximum personalization using all enrichment data")
                elif personalization_level == "medium":
                    st.info("🟡 **MEDIUM** - Moderate personalization with key highlights")
                else:
                    st.warning("🟢 **LOW** - Basic personalization with minimal enrichment")
            
            if st.button("💾 Save Personalization Settings", type="primary"):
                set_setting("email_personalization_level", personalization_level, "string", "Email personalization level: low, medium, high", db=db)
                st.success("✅ Personalization settings saved!")
                st.rerun()
        
        with tab5:
            st.subheader("📋 Mail Critic Settings")
            st.caption("Before sending, a critic agent evaluates each email. If it does not meet the bar, the email is rewritten and re-checked.")
            
            enable_critic = st.checkbox(
                "Enable Mail Critic",
                value=get_setting("enable_mail_critic", True, db=db),
                help="Check every email before send; rewrite if not up to mark"
            )
            
            col1, col2 = st.columns(2)
            with col1:
                critic_min_score = st.slider(
                    "Minimum Pass Score (0–1)",
                    min_value=0.0,
                    max_value=1.0,
                    value=float(get_setting("critic_min_score", 0.7, db=db)),
                    step=0.05,
                    help="Email must score at least this to pass without rewrite"
                )
                critic_max_rewrites = st.number_input(
                    "Max Rewrite Attempts",
                    min_value=0,
                    max_value=5,
                    value=get_setting("critic_max_rewrites", 2, db=db),
                    help="How many times to rewrite if critic keeps rejecting"
                )
            with col2:
                critic_strictness = st.selectbox(
                    "Critic Strictness",
                    ["low", "medium", "high"],
                    index=["low", "medium", "high"].index(get_setting("critic_strictness", "medium", db=db)),
                    help="Low = lenient, High = strict (tone, length, relevance)"
                )
            
            st.info("💡 Critic checks: tone, length (40–90 words), no links/emojis, relevance, clear CTA. Rewritten emails are re-checked.")
            
            if st.button("💾 Save Mail Critic Settings", type="primary"):
                set_setting("enable_mail_critic", enable_critic, "bool", "Enable critic to check emails before send", db=db)
                set_setting("critic_min_score", critic_min_score, "float", "Minimum score to pass critic", db=db)
                set_setting("critic_max_rewrites", critic_max_rewrites, "int", "Maximum rewrite attempts", db=db)
                set_setting("critic_strictness", critic_strictness, "string", "Critic strictness: low, medium, high", db=db)
                st.success("✅ Mail Critic settings saved!")
                st.rerun()
        
        # Settings export/import
        st.markdown("---")
        st.subheader("📥 Export / Import Settings")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📥 Export All Settings"):
                all_settings = db.query(SystemSettings).all()
                settings_dict = {s.key: {"value": s.value, "type": s.value_type, "description": s.description} for s in all_settings}
                st.download_button(
                    "Download Settings JSON",
                    data=json.dumps(settings_dict, indent=2),
                    file_name="settings_export.json",
                    mime="application/json"
                )
        
        with col2:
            uploaded_file = st.file_uploader("Import Settings", type=["json"])
            if uploaded_file:
                try:
                    settings_data = json.load(uploaded_file)
                    imported = 0
                    for key, config in settings_data.items():
                        if set_setting(key, config["value"], config.get("type", "string"), config.get("description", ""), db=db):
                            imported += 1
                    st.success(f"✅ Imported {imported} settings!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error importing settings: {e}")
        
        # Reset to defaults
        st.markdown("---")
        if st.button("🔄 Reset All Settings to Defaults", type="secondary"):
            for key, config in DEFAULT_SETTINGS.items():
                set_setting(key, config["value"], config["type"], config["description"], db=db)
            st.success("✅ All settings reset to defaults!")
            st.rerun()
            
    except Exception as e:
        st.error(f"Error: {e}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        db.close()
