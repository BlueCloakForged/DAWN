
import sqlite3
import time
import os
import json
from datetime import datetime

DB_PATH = "logs/diagnostic_logs.db"
ERROR_DIR = "FoundErrors"
SEEN_ERRORS_FILE = "FoundErrors/.seen_errors.json"

def get_seen_errors():
    if os.path.exists(SEEN_ERRORS_FILE):
        with open(SEEN_ERRORS_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_seen_errors(seen_set):
    with open(SEEN_ERRORS_FILE, 'w') as f:
        json.dump(list(seen_set), f)

def monitor():
    print(f"🕵️ Error Sentry Active. Monitoring {DB_PATH} for novel errors...")
    seen = get_seen_errors()
    
    # Get current max ID to only report NEW errors from this point forward if needed, 
    # but the user might want existing ones reports too. 
    # Let's just use the 'seen' set based on message hash or ID.
    
    while True:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=30.0)
            cursor = conn.cursor()
            
            # Query for errors or warnings
            cursor.execute("SELECT id, timestamp, level, component, message, metadata FROM diagnostic_log WHERE level IN ('ERROR', 'WARNING', 'CRITICAL') OR component = 'WEBUI_CRASH' ORDER BY id ASC")
            rows = cursor.fetchall()
            
            for row in rows:
                err_id, ts, level, component, message, metadata = row
                # Create a unique key for the error
                err_key = f"{level}:{component}:{message[:100]}"
                
                if err_key not in seen:
                    # New novel error found!
                    seen.add(err_key)
                    count = len([f for f in os.listdir(ERROR_DIR) if f.startswith("log") and f.endswith(".md")]) + 1
                    file_path = os.path.join(ERROR_DIR, f"log{count}.md")
                    
                    with open(file_path, 'w') as f:
                        f.write(f"# Error Log {count}\n\n")
                        f.write(f"**Timestamp:** {ts}\n")
                        f.write(f"**Level:** {level}\n")
                        f.write(f"**Component:** {component}\n\n")
                        f.write(f"## Message\n```\n{message}\n```\n\n")
                        if metadata and metadata != "{}":
                            f.write(f"## Metadata\n```json\n{metadata}\n```\n")
                    
                    print(f"🚨 New error logged: {file_path}")
                    save_seen_errors(seen)
                    
            conn.close()
        except Exception as e:
            print(f"Monitor Error: {e}")
            
        time.sleep(5) # Poll every 5 seconds

if __name__ == "__main__":
    monitor()
