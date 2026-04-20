"""
Healing Metrics Data Models

Provides structured data types for tracking self-healing convergence
across multiple healing cycles.
"""

from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class HealingCycle:
    """Represents a single healing attempt."""
    cycle: int
    timestamp: str
    error_count: int
    error_types: Dict[str, int]
    test_outcomes: Dict[str, int]
    code_changes: Dict[str, Any]
    convergence_score: float
    healer_response_time_ms: int


@dataclass
class HealingSession:
    """Aggregates all healing cycles for a complete healing session."""
    project_id: str
    original_error_count: int
    cycles: List[HealingCycle]
    final_status: str  # "healed", "exhausted", "aborted"
    total_convergence_trend: List[float]


def calculate_convergence(prev_errors: int, curr_errors: int) -> float:
    """
    Calculate convergence score from consecutive cycles.
    
    Returns:
        Positive value: Errors decreased (improving)
        Zero: No change (stagnant)
        Negative value: Errors increased (regressing)
    
    Formula: (prev - curr) / prev
    """
    if prev_errors == 0:
        return 0.0
    return (prev_errors - curr_errors) / prev_errors


def should_abort_early(convergence_history: List[float], threshold: float = -0.1) -> bool:
    """
    Detect regression: if last 2 consecutive scores are below threshold, abort.
    
    Args:
        convergence_history: List of convergence scores from all cycles
        threshold: Minimum acceptable convergence score (default: -0.1)
    
    Returns:
        True if healing should abort early due to consistent regression
    """
    if len(convergence_history) < 2:
        return False
    
    recent = convergence_history[-2:]
    return all(score < threshold for score in recent)
