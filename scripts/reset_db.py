#!/usr/bin/env python3
"""Reset the database - delete and recreate all tables."""

import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import reset_db

def main():
    print("⚠️  This will DELETE all data in the database!")
    confirm = input("Type 'yes' to confirm: ")
    if confirm.strip().lower() == "yes":
        reset_db()
        print("✅ Database reset complete - all tables recreated empty.")
    else:
        print("❌ Cancelled.")

if __name__ == "__main__":
    main()
