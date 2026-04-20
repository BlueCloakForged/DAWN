#!/usr/bin/env python3
"""
Portable Repair Engine (LADDER Framework)
=========================================
Executes diagnostic steps and applies fixes based on pattern matching.
"""

import json
import sqlite3
import subprocess
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from .logger import UniversalLogger

class RepairEngine:
    """
    Framework for executing LADDER (Logic, Action, Data...) repair cycles.
    """
    def __init__(self, logger: UniversalLogger, patterns_path: str):
        """
        Initialize the Repair Engine.
        
        Args:
            logger: UniversalLogger instance for recording diagnostics
            patterns_path: Path to the JSON file containing fix patterns
        """
        self.logger = logger
        self.patterns_path = Path(patterns_path)
        self.patterns = self._load_patterns()

    def _load_patterns(self) -> List[Dict[str, Any]]:
        """Load pattern-action mappings from JSON."""
        if not self.patterns_path.exists():
            print(f"RepairEngine: Warning - Patterns file not found at {self.patterns_path}", file=sys.stderr)
            return []
        try:
            with open(self.patterns_path, 'r') as f:
                return json.load(f).get("patterns", [])
        except Exception as e:
            print(f"RepairEngine: Failed to load patterns: {e}", file=sys.stderr)
            return []

    def diagnose_and_fix(self, error_id: int) -> bool:
        """
        Perform a full LADDER cycle for a specific error.
        """
        # 1. Logic & Data: Fetch error details from the logger
        logs = self.logger.search(limit=100) # Simple fetch for now
        error_node = next((l for l in logs if l.get('id') == error_id), None)
        
        # If search doesn't return ID (as in UniversalLogger current impl), 
        # we might need to query the DB directly in the engine or update Logger.
        # For the template, let's query DB directly for precision.
        error_node = self._get_error_by_id(error_id)
        
        if not error_node:
            self.logger.error(f"RepairEngine: Error ID {error_id} not found in database.", component="REPAIR_ENGINE")
            return False

        message = error_node['message'].lower()
        component = error_node['component'].lower()
        
        self.logger.info(f"RepairEngine: Analysis started for error {error_id} ({component})", component="REPAIR_ENGINE")

        # 2. Action: Match patterns and execute fixes
        for p in self.patterns:
            pattern_match = False
            # Match based on message regex or component
            if p.get("message_contains") and p["message_contains"].lower() in message:
                pattern_match = True
            if p.get("component_equals") and p["component_equals"].lower() == component:
                pattern_match = True
                
            if pattern_match:
                fix_name = p.get("name", "Unknown Fix")
                self.logger.info(f"RepairEngine: Pattern matched - {fix_name}", component="REPAIR_ENGINE")
                
                success = self._apply_fix(p, error_node)
                if success:
                    self.logger.info(f"RepairEngine: Fix '{fix_name}' successfully applied for error {error_id}", component="REPAIR_ENGINE")
                    self.logger.update_status(error_id, 'REPAIRED')
                    return True
                else:
                    self.logger.warning(f"RepairEngine: Fix '{fix_name}' failed for error {error_id}", component="REPAIR_ENGINE")
                    self.logger.update_status(error_id, 'FAILED')

        self.logger.warning(f"RepairEngine: No autonomous fix found for error {error_id}", component="REPAIR_ENGINE")
        return False

    def _get_error_by_id(self, error_id: int) -> Optional[Dict[str, Any]]:
        """Direct DB query for the specific error."""
        try:
            with sqlite3.connect(self.logger.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM diagnostic_log WHERE id = ?", (error_id,)).fetchone()
                if row:
                    return dict(row)
        except Exception as e:
            print(f"RepairEngine: DB fetch failed: {e}", file=sys.stderr)
        return None

    def _apply_fix(self, pattern: Dict[str, Any], error_node: Dict[str, Any]) -> bool:
        """Execute the action associated with a pattern."""
        action_type = pattern.get("action_type")
        action_payload = pattern.get("action_payload")
        
        if action_type == "command":
            # Execute a shell command
            try:
                # Replace placeholders
                cmd = action_payload.replace("{error_id}", str(error_node['id']))
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if result.returncode == 0:
                    return True
                else:
                    self.logger.error(f"RepairEngine: Command failed (code {result.returncode}): {result.stderr}", component="REPAIR_ENGINE")
            except Exception as e:
                self.logger.error(f"RepairEngine: Fix execution exception: {e}", component="REPAIR_ENGINE")
        
        elif action_type == "script":
            # Execute a python script
            try:
                cmd = f"{sys.executable} {action_payload} --error_id {error_node['id']}"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                return result.returncode == 0
            except Exception as e:
                self.logger.error(f"RepairEngine: Script execution exception: {e}", component="REPAIR_ENGINE")
                
        return False
