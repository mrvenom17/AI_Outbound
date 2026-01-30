# scripts/init_db.py
"""
Initialize database by creating all tables.
Run this script once to set up the database schema.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def init_database():
    """Create all database tables"""
    try:
        from db.models import Base
        from db.session import engine
        
        print("🔄 Creating database tables...")
        Base.metadata.create_all(engine)
        print("✅ Database tables created successfully!")
        
        # Verify tables were created
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        print(f"\n📊 Created {len(tables)} tables:")
        for table in sorted(tables):
            print(f"   - {table}")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure you've installed all dependencies: pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"❌ Error creating database: {e}")
        return False


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)
