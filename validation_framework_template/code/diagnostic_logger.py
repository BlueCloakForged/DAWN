#!/usr/bin/env python3
"""
Diagnostic Logging System for SAM
=================================
Captures and stores terminal logs and system messages in a dedicated SQLite datastore.
This prevents diagnostic data from mixing with core architectural memory.
"""

import sqlite3
import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

# Basic logger for internal errors in the diagnostic system itself
logger = logging.getLogger(__name__)

@dataclass
class DiagnosticEntry:
    """Represents a single diagnostic log entry."""
    timestamp: str
    level: str
    component: str
    message: str
    metadata: str  # JSON string

class DiagnosticLogger:
    """
    Manages a dedicated SQLite database for system diagnostic logs.
    """
    
    def __init__(self, db_path: str = "logs/diagnostic_logs.db"):
        """
        Initialize the diagnostic logger.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_database()
        logger.info(f"Diagnostic logger initialized at: {db_path}")

    def _get_connection(self):
        """Get a database connection with timeout."""
        return sqlite3.connect(self.db_path, timeout=30.0)
    
    def _init_database(self):
        """Initialize the database schema."""
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS diagnostic_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        level TEXT NOT NULL,
                        component TEXT NOT NULL,
                        message TEXT NOT NULL,
                        metadata TEXT,  -- JSON string
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Indexes for faster searching
                conn.execute("CREATE INDEX IF NOT EXISTS idx_diag_timestamp ON diagnostic_log(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_diag_level ON diagnostic_log(level)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_diag_component ON diagnostic_log(component)")
                
        except Exception as e:
            logger.error(f"Error initializing diagnostic database: {e}")
            raise
    
    def log(self, message: str, level: str = "INFO", component: str = "SYSTEM", 
            metadata: Dict[str, Any] = None):
        """
        Log a message to the diagnostic datastore.
        """
        try:
            timestamp = datetime.now().isoformat()
            meta_json = json.dumps(metadata) if metadata else "{}"
            
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO diagnostic_log (timestamp, level, component, message, metadata)
                    VALUES (?, ?, ?, ?, ?)
                """, (timestamp, level, component, message, meta_json))
                
        except Exception as e:
            # Fallback to standard logging if SQLite fails
            logger.error(f"Failed to log to diagnostic DB: {e}")
            print(f"[{level}] {component}: {message}", file=sys.stderr)

    def log_ui_event(self, action: str, label: str, metadata: Dict[str, Any] = None):
        """
        Log a UI event (button click, etc.) to the diagnostic datastore.
        """
        meta = metadata or {}
        meta["action"] = action
        meta["label"] = label
        self.log(f"UI Event: {label} ({action})", level="UI", component="WEBUI", metadata=meta)

    def search(self, keywords: List[str] = None, level: str = None, 
               component: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Search the diagnostic logs.
        """
        try:
            query = "SELECT timestamp, level, component, message, metadata FROM diagnostic_log WHERE 1=1"
            params = []
            
            if keywords:
                for kw in keywords:
                    query += " AND message LIKE ?"
                    params.append(f"%{kw}%")
            
            if level:
                query += " AND level = ?"
                params.append(level)
                
            if component:
                query += " AND component = ?"
                params.append(component)
                
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            with self._get_connection() as conn:
                cursor = conn.execute(query, params)
                results = []
                for row in cursor.fetchall():
                    results.append({
                        "timestamp": row[0],
                        "level": row[1],
                        "component": row[2],
                        "message": row[3],
                        "metadata": json.loads(row[4]) if row[4] else {}
                    })
                return results
                
        except Exception as e:
            logger.error(f"Error searching diagnostic logs: {e}")
            return []

# Singleton instance
_diag_logger = None

def get_diagnostic_logger(db_path: str = "logs/diagnostic_logs.db") -> DiagnosticLogger:
    """Get the global diagnostic logger instance."""
    global _diag_logger
    if _diag_logger is None:
        _diag_logger = DiagnosticLogger(db_path)
    return _diag_logger
