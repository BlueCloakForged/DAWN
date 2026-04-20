"""
ENGRAM Plasticity Module - Hebbian Learning Logic
Implements Long-Term Potentiation (LTP) and Long-Term Depression (LTD).
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List


class EngramPlasticity:
    """
    Manages weight adjustments based on historical memory patterns.
    Implements the Hebbian learning principle: "Neurons that fire together, wire together."
    """
    
    def __init__(self, 
                 registry_path: str,
                 weights_path: str,
                 learning_rate: float = 0.1,
                 min_samples: int = 3):
        """
        Initialize the plasticity module.
        
        Args:
            registry_path: Path to engram.registry.json
            weights_path: Path to thalamus.routing_weights.json
            learning_rate: Rate of weight adjustment (0.0-1.0)
            min_samples: Minimum samples required for weight updates
        """
        self.registry_path = Path(registry_path)
        self.weights_path = Path(weights_path)
        self.learning_rate = learning_rate
        self.min_samples = min_samples
    
    def calculate_weight_update(self, signal_category: str) -> Dict[str, Any]:
        """
        Calculate weight adjustments for a signal category based on historical coherence.
        
        Implements Hebbian LTP/LTD:
        - High coherence → Strengthen connection (LTP)
        - Low coherence → Weaken connection (LTD)
        
        Args:
            signal_category: The signal type to analyze
        
        Returns:
            Weight update recommendations
        """
        memories = self._load_registry()
        
        # Filter to relevant memories
        relevant = [m for m in memories if m.get("signal_category") == signal_category]
        
        if len(relevant) < self.min_samples:
            return {
                "signal_category": signal_category,
                "update_type": "INSUFFICIENT_DATA",
                "adjustments": {},
                "evidence": f"Need {self.min_samples} samples, have {len(relevant)}"
            }
        
        # Group by link category
        by_link = {}
        for m in relevant:
            link_cat = m.get("link_category", "unknown")
            if link_cat not in by_link:
                by_link[link_cat] = []
            by_link[link_cat].append(m["coherence_score"])
        
        # Calculate adjustments
        adjustments = {}
        for link_cat, scores in by_link.items():
            if len(scores) < 2:
                continue
            
            mean_coherence = sum(scores) / len(scores)
            
            if mean_coherence >= 0.7:
                # LTP: Strengthen this pathway
                delta = self.learning_rate * (mean_coherence - 0.7)
                adjustments[link_cat] = {
                    "type": "LTP",
                    "delta": round(delta, 4),
                    "mean_coherence": round(mean_coherence, 3),
                    "sample_count": len(scores)
                }
            elif mean_coherence <= 0.4:
                # LTD: Weaken this pathway
                delta = -self.learning_rate * (0.4 - mean_coherence)
                adjustments[link_cat] = {
                    "type": "LTD",
                    "delta": round(delta, 4),
                    "mean_coherence": round(mean_coherence, 3),
                    "sample_count": len(scores)
                }
        
        return {
            "signal_category": signal_category,
            "update_type": "HEBBIAN",
            "adjustments": adjustments,
            "evidence": f"Based on {len(relevant)} memories across {len(by_link)} link categories"
        }
    
    def apply_weight_updates(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply weight updates to the THALAMUS routing weights.
        
        Args:
            updates: Output from calculate_weight_update()
        
        Returns:
            Result of the update operation
        """
        if updates.get("update_type") != "HEBBIAN":
            return {"status": "SKIPPED", "reason": updates.get("update_type")}
        
        adjustments = updates.get("adjustments", {})
        if not adjustments:
            return {"status": "SKIPPED", "reason": "no_adjustments"}
        
        # Load current weights
        weights = self._load_weights()
        signal_cat = updates["signal_category"]
        
        # Initialize category weights if needed
        if signal_cat not in weights:
            weights[signal_cat] = {}
        
        # Apply adjustments
        applied = {}
        for link_cat, adj in adjustments.items():
            current = weights[signal_cat].get(link_cat, 1.0)
            new_weight = max(0.1, min(2.0, current + adj["delta"]))
            weights[signal_cat][link_cat] = round(new_weight, 4)
            applied[link_cat] = {
                "old": current,
                "new": new_weight,
                "type": adj["type"]
            }
        
        # Save updated weights
        self._save_weights(weights)
        
        print(f"ENGRAM: Applied Hebbian updates for {signal_cat}: {applied}")
        return {"status": "APPLIED", "changes": applied}
    
    def get_routing_recommendation(self, 
                                     signal_category: str,
                                     available_links: List[str]) -> Dict[str, Any]:
        """
        Get routing recommendations based on learned weights.
        
        Args:
            signal_category: Current signal type
            available_links: List of available link categories
        
        Returns:
            Recommendations with link rankings
        """
        weights = self._load_weights()
        category_weights = weights.get(signal_category, {})
        
        # Rank available links by learned weight
        rankings = []
        for link in available_links:
            weight = category_weights.get(link, 1.0)
            rankings.append({"link": link, "weight": weight})
        
        rankings.sort(key=lambda x: x["weight"], reverse=True)
        
        return {
            "signal_category": signal_category,
            "rankings": rankings,
            "preferred": rankings[0]["link"] if rankings else None
        }
    
    def _load_registry(self) -> List[Dict[str, Any]]:
        """Load memory registry."""
        if not self.registry_path.exists():
            return []
        with open(self.registry_path, "r") as f:
            return json.load(f)
    
    def _load_weights(self) -> Dict[str, Any]:
        """Load routing weights."""
        if not self.weights_path.exists():
            return {}
        with open(self.weights_path, "r") as f:
            return json.load(f)
    
    def _save_weights(self, weights: Dict[str, Any]):
        """Save routing weights."""
        self.weights_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.weights_path, "w") as f:
            json.dump(weights, f, indent=2)
