# scripts/add_imap_columns_to_smtp_servers.py
"""Add IMAP/POP3 and use_ssl columns to smtp_servers if missing. Run from project root."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run():
    from db.session import engine, _DEFAULT_DB_PATH
    from sqlalchemy import text
    print(f"Database: {_DEFAULT_DB_PATH}")
    cols_add = [
        ("use_ssl", "INTEGER DEFAULT 0"),
        ("imap_host", "TEXT"),
        ("imap_port", "INTEGER DEFAULT 993"),
        ("imap_use_ssl", "INTEGER DEFAULT 1"),
        ("pop3_host", "TEXT"),
        ("pop3_port", "INTEGER DEFAULT 995"),
        ("pop3_use_ssl", "INTEGER DEFAULT 1"),
    ]
    with engine.connect() as conn:
        for col, typ in cols_add:
            try:
                conn.execute(text(f"ALTER TABLE smtp_servers ADD COLUMN {col} {typ}"))
                conn.commit()
                print(f"  Added column smtp_servers.{col}")
            except Exception as e:
                if "duplicate column" in str(e).lower():
                    print(f"  Column {col} already exists, skip")
                else:
                    print(f"  Error adding {col}: {e}")
                conn.rollback()
    print("Done.")

if __name__ == "__main__":
    run()
