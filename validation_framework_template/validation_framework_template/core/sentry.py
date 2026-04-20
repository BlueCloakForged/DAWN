#!/usr/bin/env python3
"""
Portable Error Sentry
=====================
Monitors diagnostic logs for errors and triggers automated repair actions.
Includes resource-aware throttling and sequential processing.
"""

import time
import sqlite3
import os
import sys
import psutil
import json
import threading
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, List, Dict, Any

class Sentry:
    """
    Monitors a diagnostic database for new errors and triggers actions.
    """
    def __init__(
        self, 
        db_path: str, 
        repair_callback: Callable[[int], None],
        poll_interval: int = 2,
        max_mem_pct: float = 85.0,
        cooldown: int = 60
    ):
        """
        Initialize the Sentry.
        
        Args:
            db_path: Path to the SQLite diagnostic database
            repair_callback: Function to call when a new error is detected
            poll_interval: Seconds between log checks
            max_mem_pct: Threshold to abort repairs if system memory is high
            cooldown: Seconds to wait between repair attempts
        """
        self.db_path = Path(db_path)
        self.repair_callback = repair_callback
        self.poll_interval = poll_interval
        self.max_mem_pct = max_mem_pct
        self.cooldown = cooldown
        
        self.seen_errors = set()
        self.last_repair_time = 0
        self._running = False
        
        # Load existing errors to avoid "startup storm"
        self._prime_cache()

    def _prime_cache(self):
        """Cache existing errors so we only act on new ones."""
        try:
            if not self.db_path.exists():
                return
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM diagnostic_log")
            self.seen_errors.update([row[0] for row in cursor.fetchall()])
            conn.close()
        except Exception as e:
            print(f"Sentry cache priming failed: {e}", file=sys.stderr)

    def _check_resources(self) -> bool:
        """Verify system health before triggering repairs."""
        mem = psutil.virtual_memory()
        if mem.percent > self.max_mem_pct:
            print(f"Sentry: Aborting repair due to high memory usage ({mem.percent}%)", file=sys.stderr)
            return False
        return True

    def start(self):
        """Start the monitoring loop in a background thread."""
        self._running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the monitoring loop."""
        self._running = False

    def _monitor(self):
        """Main monitoring loop."""
        while self._running:
            try:
                if not self.db_path.exists():
                    time.sleep(self.poll_interval)
                    continue
                
                conn = sqlite3.connect(self.db_path, timeout=30.0)
                cursor = conn.cursor()
                # Check for new ERROR/CRITICAL logs
                cursor.execute("""
                    SELECT id FROM diagnostic_log 
                    WHERE level IN ('ERROR', 'CRITICAL') 
                    ORDER BY id DESC LIMIT 50
                """)
                recent = cursor.fetchall()
                conn.close()
                
                # Identify new errors
                new_ids = [r[0] for r in recent if r[0] not in self.seen_errors]
                
                if new_ids:
                    # Process sequentially
                    for error_id in sorted(new_ids):
                        # Apply cooldown and resource checks
                        if time.time() - self.last_repair_time < self.cooldown:
                            continue
                        
                        if self._check_resources():
                            print(f"Sentry: Triggering repair for Error ID {error_id}")
                            try:
                                self.repair_callback(error_id)
                                self.last_repair_time = time.time()
                            except Exception as e:
                                print(f"Sentry: Repair callback failed for {error_id}: {e}", file=sys.stderr)
                        
                        self.seen_errors.add(error_id)
                
            except Exception as e:
                print(f"Sentry loop error: {e}", file=sys.stderr)
            
            time.sleep(self.poll_interval)
