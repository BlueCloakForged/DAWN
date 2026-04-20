import json
import argparse
from pathlib import Path
from datetime import datetime

def print_summary(ledger_path: str):
    path = Path(ledger_path)
    if not path.exists():
        print(f"Error: Ledger file not found at {ledger_path}")
        return

    print(f"{'link_id':<25} | {'status':<10} | {'duration':<8} | {'outputs':<7} | {'last_error'}")
    print("-" * 80)

    events_by_run = {}
    
    with open(path, "r") as f:
        for line in f:
            event = json.loads(line)
            link_id = event["link_id"]
            if link_id not in events_by_run:
                events_by_run[link_id] = {"status": "UNKNOWN", "duration": 0, "outputs": 0, "error": ""}
            
            if event["status"] == "STARTED":
                events_by_run[link_id]["status"] = "STARTED"
            elif event["status"] == "SUCCEEDED":
                events_by_run[link_id]["status"] = "SUCCEEDED"
                events_by_run[link_id]["duration"] = event.get("metrics", {}).get("duration", 0)
                events_by_run[link_id]["outputs"] = len(event.get("outputs", {}))
            elif event["status"] == "FAILED":
                events_by_run[link_id]["status"] = "FAILED"
                events_by_run[link_id]["error"] = event.get("errors", {}).get("message", "Unknown error")

    for link_id, data in events_by_run.items():
        print(f"{link_id:<25} | {data['status']:<10} | {data['duration']:<8.2f} | {data['outputs']:<7} | {data['error']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DAWN Runtime Summary")
    parser.add_argument("ledger_file", help="Path to ledger/events.jsonl")
    args = parser.parse_args()
    print_summary(args.ledger_file)
