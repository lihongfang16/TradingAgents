#!/usr/bin/env python3
"""Initialize database with Alembic migrations."""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic.config import Config
from alembic import command
from sqlalchemy import text
from webapi.config.database import engine


def check_connection():
    """Check if database connection works."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


def run_migrations():
    """Run Alembic migrations."""
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        return True
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False


def verify_tables():
    """Verify tables were created."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'analysis_tasks')"
            ))
            return result.scalar()
    except Exception as e:
        print(f"❌ Table verification failed: {e}")
        return False


def main():
    """Main initialization function."""
    print("🚀 Initializing database...\n")
    
    # Step 1: Check connection
    print("1️⃣ Checking database connection...")
    if not check_connection():
        print("\n❌ Failed to connect to database.")
        print("Make sure PostgreSQL is running and DATABASE_URL is correct.")
        sys.exit(1)
    print("✅ Database connection OK\n")
    
    # Step 2: Run migrations
    print("2️⃣ Running Alembic migrations...")
    if not run_migrations():
        print("\n❌ Migration failed.")
        sys.exit(1)
    print("✅ Migrations completed\n")
    
    # Step 3: Verify tables
    print("3️⃣ Verifying tables...")
    if not verify_tables():
        print("\n❌ Table verification failed.")
        sys.exit(1)
    print("✅ Tables created successfully\n")
    
    print("🎉 Database initialization complete!")
    print(f"   Engine: {engine.url}")
    print("   Tables: analysis_tasks")


if __name__ == "__main__":
    main()
