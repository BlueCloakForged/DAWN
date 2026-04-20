"""
ENGRAM Query Interface - Public API for memory retrieval.
Follows the ligand_query.py pattern for observability.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

# Default registry path
DEFAULT_REGISTRY_PATH = "/Users/vinsoncornejo/DAWN/artifacts/engram.registry.json"


def get_engram_status(registry_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the current status of the ENGRAM memory registry.
    
    Returns:
        Dictionary with memory count, categories, and stats
    """
    path = Path(registry_path or os.environ.get("ENGRAM_REGISTRY_PATH", DEFAULT_REGISTRY_PATH))
    
    if not path.exists():
        return {"count": 0, "status": "empty", "categories": {}}
    
    with open(path, "r") as f:
        memories = json.load(f)
    
    if not memories:
        return {"count": 0, "status": "empty", "categories": {}}
    
    # Categorize memories
    categories = {}
    for m in memories:
        cat = m.get("signal_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    
    return {
        "count": len(memories),
        "status": "active",
        "categories": categories,
        "mean_coherence": sum(m.get("coherence_score", 0) for m in memories) / len(memories)
    }


def query_similar_events(cue_context: Dict[str, Any],
                         top_k: int = 3,
                         registry_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Query ENGRAM for similar past events.
    
    This is the main interface for THALAMUS Switchboard to consult
    historical memory before routing decisions.
    
    Args:
        cue_context: The current context to match against
        top_k: Maximum results to return
        registry_path: Optional override for registry path
    
    Returns:
        Dictionary with matches and recommendations
    """
    from .engram_store import EngramStore
    
    path = registry_path or os.environ.get("ENGRAM_REGISTRY_PATH", DEFAULT_REGISTRY_PATH)
    store = EngramStore(path)
    
    matches = store.search_memories(cue_context, top_k=top_k)
    
    # Analyze matches for routing recommendations
    recommendations = {}
    if matches:
        # Check if similar past events had low coherence
        low_coherence_matches = [m for m in matches if m.get("coherence_score", 1.0) < 0.5]
        
        if low_coherence_matches:
            # Recommend increased caution
            recommendations["ligand_adjustment"] = {
                "safety": min(0.8, 0.3 + len(low_coherence_matches) * 0.2),
                "reason": f"Similar past events had low coherence ({len(low_coherence_matches)}/{len(matches)})"
            }
        
        # Track successful link categories
        successful = [m for m in matches if m.get("coherence_score", 0) >= 0.7]
        if successful:
            link_cats = [m.get("link_category") for m in successful if m.get("link_category")]
            if link_cats:
                recommendations["preferred_links"] = list(set(link_cats))
    
    return {
        "matches": matches,
        "count": len(matches),
        "recommendations": recommendations
    }


def get_learning_signal(signal_category: str,
                        registry_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a learning signal for a specific signal category.
    
    Used by the Hebbian update logic to determine weight adjustments.
    
    Args:
        signal_category: The signal type to analyze
        registry_path: Optional override for registry path
    
    Returns:
        Learning signal with weight adjustment recommendations
    """
    from .engram_store import EngramStore
    
    path = registry_path or os.environ.get("ENGRAM_REGISTRY_PATH", DEFAULT_REGISTRY_PATH)
    store = EngramStore(path)
    
    stats = store.get_historical_coherence(signal_category)
    
    # Generate learning signal based on historical performance
    learning_signal = {
        "signal_category": signal_category,
        "historical_stats": stats,
        "weight_adjustment": 0.0,
        "confidence": 0.0
    }
    
    if stats["count"] >= 3:  # Need minimum samples
        mean = stats["mean_coherence"]
        
        # Suggest weight changes based on historical coherence
        if mean >= 0.8:
            learning_signal["weight_adjustment"] = 0.1  # Increase weight
            learning_signal["confidence"] = min(1.0, stats["count"] / 10)
        elif mean <= 0.4:
            learning_signal["weight_adjustment"] = -0.1  # Decrease weight
            learning_signal["confidence"] = min(1.0, stats["count"] / 10)
    
    return learning_signal
