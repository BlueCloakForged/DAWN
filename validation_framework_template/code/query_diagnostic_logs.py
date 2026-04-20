#!/usr/bin/env python3
"""
Diagnostic Log Query Utility
===========================
CLI tool to query the SAM diagnostic datastore for errors and system messages.
"""

import argparse
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.diagnostic_logger import get_diagnostic_logger

def main():
    parser = argparse.ArgumentParser(description="Query SAM diagnostic logs.")
    parser.add_argument("--keywords", nargs="+", help="Keywords to search for (e.g., Error error failure)")
    parser.add_argument("--level", help="Filter by log level (e.g., INFO, ERROR, WARNING)")
    parser.add_argument("--component", help="Filter by system component")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of logs to display")
    parser.add_argument("--db", default="logs/diagnostic_logs.db", help="Path to the diagnostic database")
    parser.add_argument("--show-metadata", action="store_true", help="Show JSON metadata for each log")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.db):
        print(f"❌ Diagnostic database not found at {args.db}")
        return

    logger = get_diagnostic_logger(args.db)
    
    print(f"🔍 Searching logs (limit: {args.limit})...")
    results = logger.search(
        keywords=args.keywords,
        level=args.level,
        component=args.component,
        limit=args.limit
    )
    
    if not results:
        print("📭 No matching logs found.")
        return
    
    print(f"✅ Found {len(results)} matches:\n")
    print(f"{'TIMESTAMP':<25} | {'LEVEL':<7} | {'COMPONENT':<12} | {'MESSAGE'}")
    print("-" * 100)
    
    for row in results:
        ts = row["timestamp"][:19].replace("T", " ")
        lvl = row["level"]
        comp = row["component"]
        msg = row["message"]
        meta = row.get("metadata")
        
        # Colorize levels if terminal supports it
        if lvl == "ERROR":
            lvl = f"\033[91m{lvl}\033[0m"
        elif lvl == "WARNING":
            lvl = f"\033[93m{lvl}\033[0m"
        elif lvl == "UI":
            lvl = f"\033[96m{lvl}\033[0m"
            
        print(f"{ts:<25} | {lvl:<16} | {comp:<12} | {msg}")
        if args.show_metadata and meta and meta != "{}":
            print(f"{'':<25} | {'':<7} | {'':<12} | \033[90mMETADATA: {meta}\033[0m")

if __name__ == "__main__":
    main()
