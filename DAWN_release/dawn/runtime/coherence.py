import abc
import hashlib
from typing import Dict, Any, List

class CoherenceProvider(abc.ABC):
    @abc.abstractmethod
    def calculate_coherence(self, current_ir: Dict[str, Any], original_intent_ir: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate coherence score and provide metadata/evidence.
        Returns: {
            "score": float (0.0 to 1.0),
            "evidence": str
        }
        """
        pass

class SimpleStructuralCoherenceProvider(CoherenceProvider):
    """
    A simple provider that compares top-level keys and node counts as a proxy for coherence.
    In a real system, this would be an LLM-based judge or a vector similarity check.
    """
    def calculate_coherence(self, current_ir: Dict[str, Any], original_intent_ir: Dict[str, Any]) -> Dict[str, Any]:
        if not current_ir or not original_intent_ir:
            return {"score": 0.0, "evidence": "Missing IR for comparison"}
        
        # Simple heuristic: Node count preservation for structural coherence
        orig_nodes = original_intent_ir.get("nodes", [])
        curr_nodes = current_ir.get("nodes", [])
        
        if not orig_nodes:
            return {"score": 1.0, "evidence": "No original nodes to compare against"}
            
        # Calculate ratio of nodes preserved (very basic)
        overlap = [n for n in curr_nodes if n.get("name") in [on.get("name") for on in orig_nodes]]
        score = len(overlap) / len(orig_nodes)
        
        evidence = f"Preserved {len(overlap)} out of {len(orig_nodes)} original nodes."
        
        # Check for "Hot Mess" indicators (e.g. huge influx of new nodes without parent groups)
        new_nodes = len(curr_nodes) - len(overlap)
        if new_nodes > len(orig_nodes) * 2:
            score *= 0.5
            evidence += f" Warning: High entropy detected with {new_nodes} new nodes."
            
        return {
            "score": max(0.0, min(1.0, score)),
            "evidence": evidence
        }

class MockLLMCoherenceProvider(CoherenceProvider):
    """
    Mocks an LLM-based judge comparing semantic intent.
    """
    def calculate_coherence(self, current_ir: Dict[str, Any], original_intent_ir: Dict[str, Any]) -> Dict[str, Any]:
        # For demo purposes, we'll hash the current IR and return a stable-ish score
        # In reality, this would call an LLM with the two IRs.
        ir_str = str(current_ir)
        h = hashlib.md5(ir_str.encode()).hexdigest()
        
        # Just a dummy deterministic score for testing
        score = 0.95
        if "hot_mess" in ir_str.lower():
            score = 0.4
            
        return {
            "score": score,
            "evidence": "Mock LLM judgment based on semantic alignment with goal."
        }
