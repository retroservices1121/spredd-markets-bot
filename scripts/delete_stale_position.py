#!/usr/bin/env python3
"""
One-time script to delete a stale position by token_id.
Run this from the project root: python scripts/delete_stale_position.py
"""
import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.database import delete_position_by_token_id, init_db

STALE_TOKEN_ID = "18289842382539867639079362738467334752951741961393928566628307174343542320349"


async def main():
    print(f"Initializing database...")
    await init_db()

    print(f"Deleting position with token_id: {STALE_TOKEN_ID[:20]}...")
    deleted_count = await delete_position_by_token_id(STALE_TOKEN_ID)

    if deleted_count > 0:
        print(f"✅ Successfully deleted {deleted_count} position(s)")
    else:
        print("⚠️ No positions found with that token_id")


if __name__ == "__main__":
    asyncio.run(main())
