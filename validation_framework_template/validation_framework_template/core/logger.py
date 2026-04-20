#!/usr/bin/env python3
"""
Portable Diagnostic Logging System
==================================
A generic, SQLite-backed logging system that captures and stores terminal logs 
and system messages. Designed for portability across AI-driven applications.
"""

import sqlite3
import json
import logging
import sys
import os
import time
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class LogEntry:
    """Represents a single diagnostic log entry."""
    timestamp: str
    level: str
    component: str
    message: str
    metadata: str  # JSON string

class UniversalLoggingHandler(logging.Handler):
    """
    Standard logging handler that redirects logs to the UniversalLogger.
    """
    def __init__(self, logger_instance: 'UniversalLogger'):
        super().__init__()
        self.logger_instance = logger_instance

    def emit(self, record):
        try:
            # Avoid recursion
            if record.name == __name__:
                return
                
            metadata = {
                "logger_name": record.name,
                "process": record.process,
                "thread": record.threadName,
                "func": record.funcName,
                "line": record.lineno
            }
            if record.exc_info:
                metadata["traceback"] = "".join(traceback.format_exception(*record.exc_info))
            
            self.logger_instance.log(
                message=record.getMessage(),
                level=record.levelname,
                component=record.name.split('.')[0].upper(),
                metadata=metadata
            )
        except Exception:
            self.handleError(record)

class UniversalLogger:
    """
    Manages a dedicated SQLite database for diagnostic logs.
    """
    
    def __init__(self, db_path: str, app_name: str = "SYSTEM"):
        """
        Initialize the logger.
        
        Args:
            db_path: Path to the SQLite database file
            app_name: Default application or component name
        """
        self.db_path = Path(db_path)
        self.app_name = app_name
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

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
                        repair_status TEXT DEFAULT 'UNRESOLVED',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                # Indexes for performance
                conn.execute("CREATE INDEX IF NOT EXISTS idx_diag_timestamp ON diagnostic_log(timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_diag_level ON diagnostic_log(level)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_diag_component ON diagnostic_log(component)")
                
                # Check if repair_status column exists (for backward compatibility during migration)
                cursor = conn.execute("PRAGMA table_info(diagnostic_log)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'repair_status' not in columns:
                    conn.execute("ALTER TABLE diagnostic_log ADD COLUMN repair_status TEXT DEFAULT 'UNRESOLVED'")
                
                # Create index on repair_status (now that it definitely exists)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_diag_status ON diagnostic_log(repair_status)")
        except Exception as e:
            print(f"Error initializing diagnostic database: {e}", file=sys.stderr)
            raise
    
    def log(self, message: str, level: str = "INFO", component: str = None, 
            metadata: Dict[str, Any] = None):
        """Log a message with retry logic for database locks."""
        max_retries = 3
        retry_delay = 0.5
        comp = component or self.app_name
        
        for attempt in range(max_retries):
            try:
                timestamp = datetime.now().isoformat()
                meta_json = json.dumps(metadata) if metadata else "{}"
                
                with self._get_connection() as conn:
                    conn.execute("""
                        INSERT INTO diagnostic_log (timestamp, level, component, message, metadata)
                        VALUES (?, ?, ?, ?, ?)
                    """, (timestamp, level.upper(), comp, message, meta_json))
                return
                
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt) + random.uniform(0, 0.5))
                    continue
                print(f"[{level}] {comp}: {message}", file=sys.stderr)
                break
            except Exception as e:
                print(f"Logging failure: {e}", file=sys.stderr)
                break

    def debug(self, message: str, component: str = None, metadata: Dict[str, Any] = None):
        self.log(message, level="DEBUG", component=component, metadata=metadata)

    def info(self, message: str, component: str = None, metadata: Dict[str, Any] = None):
        self.log(message, level="INFO", component=component, metadata=metadata)

    def warning(self, message: str, component: str = None, metadata: Dict[str, Any] = None):
        self.log(message, level="WARNING", component=component, metadata=metadata)

    def error(self, message: str, component: str = None, metadata: Dict[str, Any] = None):
        self.log(message, level="ERROR", component=component, metadata=metadata)

    def critical(self, message: str, component: str = None, metadata: Dict[str, Any] = None):
        self.log(message, level="CRITICAL", component=component, metadata=metadata)

    def update_status(self, error_id: int, status: str):
        """Update the repair status of an error."""
        try:
            with self._get_connection() as conn:
                conn.execute("UPDATE diagnostic_log SET repair_status = ? WHERE id = ?", (status.upper(), error_id))
        except Exception as e:
            print(f"Failed to update status for error {error_id}: {e}", file=sys.stderr)

    def search(self, keywords: List[str] = None, level: str = None, 
               component: str = None, limit: int = 100, **kwargs) -> List[Dict[str, Any]]:
        """Search the diagnostic logs."""
        try:
            query = "SELECT id, timestamp, level, component, message, metadata, repair_status FROM diagnostic_log WHERE 1=1"
            params = []
            
            if keywords:
                for kw in keywords:
                    query += " AND message LIKE ?"
                    params.append(f"%{kw}%")
            if level:
                query += " AND level = ?"
                params.append(level.upper())
            else:
                # Default to ERROR/CRITICAL for high-level search if not specified otherwise
                query += " AND level IN ('ERROR', 'CRITICAL')"
            if component:
                query += " AND component = ?"
                params.append(component)
            if kwargs.get('status'):
                query += " AND repair_status = ?"
                params.append(kwargs.get('status').upper())
                
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            with self._get_connection() as conn:
                cursor = conn.execute(query, params)
                return [
                    {
                        "id": row[0],
                        "timestamp": row[1],
                        "level": row[2],
                        "component": row[3],
                        "message": row[4],
                        "metadata": json.loads(row[5]) if row[5] else {},
                        "repair_status": row[6]
                    } for row in cursor.fetchall()
                ]
        except Exception as e:
            print(f"Search failure: {e}", file=sys.stderr)
            return []

def setup_logging(db_path: str, app_name: str = "SYSTEM", level: int = logging.INFO) -> UniversalLogger:
    """Convenience function to set up standard logging integration."""
    uni_logger = UniversalLogger(db_path, app_name)
    handler = UniversalLoggingHandler(uni_logger)
    handler.setLevel(level)
    logging.getLogger().addHandler(handler)
    return uni_logger
