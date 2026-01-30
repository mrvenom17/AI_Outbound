# workers/bounce_checker.py
"""
Periodic task to check for email bounces and update blocking status.
Can be run as a cron job or scheduled task.
"""
from agents.gmail_service import authenticate_gmail
from agents.tracker import process_bounces, get_bounce_rate
from agents.rate_limiter import update_rate_limits

def check_bounces_task():
    """
    Check for bounces, process them, and update rate limits.
    Designed to be run periodically (e.g., every hour).
    """
    try:
        service = authenticate_gmail()
        bounce_count = process_bounces(service, days=1)
        
        if bounce_count > 0:
            print(f"✅ Processed {bounce_count} bounces")
            
            # Update rate limits based on bounce rate
            bounce_rate = get_bounce_rate(days=7)
            update_rate_limits(bounce_rate)
            print(f"📊 Bounce rate: {bounce_rate:.2%}, updated rate limits")
        else:
            print("✅ No new bounces detected")
            
    except Exception as e:
        print(f"❌ Error checking bounces: {e}")


if __name__ == "__main__":
    check_bounces_task()
