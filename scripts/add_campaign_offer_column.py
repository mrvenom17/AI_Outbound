"""
Add offer_description column to campaigns table if it doesn't exist.
Run once after pulling the campaign-aware email changes.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def add_offer_column():
    try:
        from db.session import engine
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        cols = [c["name"] for c in inspector.get_columns("campaigns")]
        if "offer_description" in cols:
            print("✅ campaigns.offer_description already exists")
            return True

        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE campaigns ADD COLUMN offer_description TEXT"))
        print("✅ Added campaigns.offer_description")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = add_offer_column()
    sys.exit(0 if success else 1)
