#!/usr/bin/env python
"""
Database migration script for Spredd Markets Bot.

Usage:
    python scripts/migrate.py upgrade head
    python scripts/migrate.py downgrade -1

Or with explicit DATABASE_URL:
    DATABASE_URL=postgresql://... python scripts/migrate.py upgrade head
"""

import os
import sys
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Run database migrations")
    parser.add_argument("command", choices=["upgrade", "downgrade", "current", "history", "stamp"],
                       help="Alembic command to run")
    parser.add_argument("revision", nargs="?", default="head",
                       help="Revision target (default: head)")
    parser.add_argument("--database-url", "-d",
                       help="Database URL (or set DATABASE_URL env var)")
    parser.add_argument("--sql", action="store_true",
                       help="Generate SQL instead of applying")

    args = parser.parse_args()

    # Set database URL from argument or environment
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    # Check required environment variables
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable is required")
        print("Set it via:")
        print("  export DATABASE_URL=postgresql://user:pass@host:5432/db")
        print("  OR")
        print("  python scripts/migrate.py upgrade head -d postgresql://...")
        sys.exit(1)

    # Set dummy values for other required settings if not present
    # (These aren't needed for migrations, only for the settings module import)
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        os.environ["TELEGRAM_BOT_TOKEN"] = "dummy_token_for_migration"
    if not os.environ.get("ENCRYPTION_KEY"):
        os.environ["ENCRYPTION_KEY"] = "a" * 64  # Dummy 64-char hex key

    # Import alembic after setting env vars
    from alembic.config import Config
    from alembic import command

    # Get alembic config
    alembic_cfg = Config("alembic.ini")

    # Override database URL
    db_url = database_url
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    print(f"Running: alembic {args.command} {args.revision}")
    print(f"Database: {database_url[:50]}...")

    try:
        if args.command == "upgrade":
            command.upgrade(alembic_cfg, args.revision, sql=args.sql)
        elif args.command == "downgrade":
            command.downgrade(alembic_cfg, args.revision, sql=args.sql)
        elif args.command == "current":
            command.current(alembic_cfg)
        elif args.command == "history":
            command.history(alembic_cfg)
        elif args.command == "stamp":
            command.stamp(alembic_cfg, args.revision)

        print("Migration completed successfully!")

    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
