"""
ENGRAM Store - Memory Vector Storage and Retrieval
The persistence layer for the ENGRAM framework (Hippocampus layer).
"""

import json
import time
import uuid
import hashlib
import math
from pathlib import Path
from typing import Dict, Any, List, Optional


class EngramStore:
    """
    Manages the ENGRAM Memory Registry - a searchable store of past transactions.
    Each memory is linked to a bundle_sha256 for DAWN Ledger verifiability.
    """
    
    def __init__(self, registry_path: str, decay_factor: float = 0.95, decay_interval: int = 86400):
        """
        Initialize the Engram Store.
        
        Args:
            registry_path: Path to the engram.registry.json file
            decay_factor: Factor applied to memory strength during decay (0.0-1.0)
            decay_interval: Seconds between decay applications (default: 24 hours)
        """
        self.registry_path = Path(registry_path)
        self.decay_factor = decay_factor
        self.decay_interval = decay_interval
        self._ensure_registry()
    
    def _ensure_registry(self):
        """Ensure registry file exists."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            with open(self.registry_path, "w") as f:
                json.dump([], f)
    
    def _load_registry(self) -> List[Dict[str, Any]]:
        """Load the memory registry."""
        with open(self.registry_path, "r") as f:
            return json.load(f)
    
    def _save_registry(self, memories: List[Dict[str, Any]]):
        """Save the memory registry."""
        with open(self.registry_path, "w") as f:
            json.dump(memories, f, indent=2)
    
    def consolidate_memory(self, 
                           unified_event: Dict[str, Any],
                           coherence_score: float,
                           bundle_sha256: str,
                           signal_category: Optional[str] = None,
                           link_category: Optional[str] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Consolidate a transaction into a Memory Vector.
        
        This is the "Short-Term to Long-Term" transition - converting
        a successful DAWN transaction into a searchable concept.
        
        Args:
            unified_event: The thalamus.unified_event from the transaction
            coherence_score: Final coherence score (0.0-1.0)
            bundle_sha256: Reference to DAWN Ledger bundle
            signal_category: Category of the originating signal
            link_category: Category of DAWN link that processed this
            metadata: Additional application-agnostic context
        
        Returns:
            The created memory record
        """
        # Generate embedding vector from unified event
        vector = self._generate_vector(unified_event)
        
        memory = {
            "memory_id": str(uuid.uuid4()),
            "bundle_sha256": bundle_sha256,
            "vector": vector,
            "coherence_score": coherence_score,
            "signal_category": signal_category,
            "link_category": link_category,
            "timestamp": time.time(),
            "decay_factor": 1.0,
            "reinforcement_count": 0,
            "metadata": metadata or {}
        }
        
        memories = self._load_registry()
        memories.append(memory)
        self._save_registry(memories)
        
        print(f"ENGRAM: Consolidated memory {memory['memory_id'][:8]}... (coherence: {coherence_score:.3f})")
        return memory
    
    def _generate_vector(self, unified_event: Dict[str, Any], dim: int = 64) -> List[float]:
        """
        Generate a pseudo-embedding vector from the unified event.
        
        In production, this would use an actual embedding model.
        For the framework, we use a deterministic hash-based approach.
        
        Args:
            unified_event: The context to vectorize
            dim: Dimensionality of the output vector
        
        Returns:
            A normalized float vector
        """
        # Serialize the event deterministically
        event_str = json.dumps(unified_event, sort_keys=True)
        
        # Generate hash-based vector components
        vector = []
        for i in range(dim):
            h = hashlib.sha256(f"{event_str}:{i}".encode()).hexdigest()
            # Convert first 8 hex chars to float in range [-1, 1]
            val = (int(h[:8], 16) / (2**32)) * 2 - 1
            vector.append(val)
        
        # Normalize to unit length
        magnitude = math.sqrt(sum(v**2 for v in vector))
        if magnitude > 0:
            vector = [v / magnitude for v in vector]
        
        return vector
    
    def search_memories(self, 
                        cue: Dict[str, Any], 
                        top_k: int = 5,
                        min_similarity: float = 0.3,
                        signal_category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for similar past events using a cue.
        
        This is "Associative Retrieval" - the ability to recall
        related memories based on a pattern match.
        
        Args:
            cue: The current context to match against
            top_k: Maximum number of results to return
            min_similarity: Minimum cosine similarity threshold
            signal_category: Optional filter by signal category
        
        Returns:
            List of matching memories with similarity scores
        """
        cue_vector = self._generate_vector(cue)
        memories = self._load_registry()
        
        results = []
        for memory in memories:
            # Apply category filter if specified
            if signal_category and memory.get("signal_category") != signal_category:
                continue
            
            # Calculate cosine similarity
            similarity = self._cosine_similarity(cue_vector, memory["vector"])
            
            # Weight by decay factor (older/unreinforced memories are weaker)
            effective_similarity = similarity * memory.get("decay_factor", 1.0)
            
            if effective_similarity >= min_similarity:
                results.append({
                    **memory,
                    "similarity": effective_similarity,
                    "raw_similarity": similarity
                })
        
        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]
    
    def _cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec_a) != len(vec_b):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a**2 for a in vec_a))
        mag_b = math.sqrt(sum(b**2 for b in vec_b))
        
        if mag_a == 0 or mag_b == 0:
            return 0.0
        
        return dot_product / (mag_a * mag_b)
    
    def get_historical_coherence(self, 
                                  signal_category: str,
                                  link_category: Optional[str] = None) -> Dict[str, Any]:
        """
        Get historical coherence statistics for a signal/link category.
        
        This supports the Hebbian learning loop by providing evidence
        about which link categories work best for which signal types.
        
        Args:
            signal_category: The signal type to analyze
            link_category: Optional specific link category to analyze
        
        Returns:
            Statistics dict with mean, min, max, count
        """
        memories = self._load_registry()
        
        # Filter to relevant memories
        relevant = [
            m for m in memories
            if m.get("signal_category") == signal_category
            and (link_category is None or m.get("link_category") == link_category)
        ]
        
        if not relevant:
            return {
                "signal_category": signal_category,
                "link_category": link_category,
                "count": 0,
                "mean_coherence": None,
                "min_coherence": None,
                "max_coherence": None,
                "evidence": "No historical data"
            }
        
        scores = [m["coherence_score"] for m in relevant]
        
        return {
            "signal_category": signal_category,
            "link_category": link_category,
            "count": len(scores),
            "mean_coherence": sum(scores) / len(scores),
            "min_coherence": min(scores),
            "max_coherence": max(scores),
            "evidence": f"Based on {len(scores)} historical transactions"
        }
    
    def reinforce_memory(self, memory_id: str) -> bool:
        """
        Reinforce a memory (increase its strength).
        
        Called when a similar pattern is encountered again,
        implementing Long-Term Potentiation (LTP).
        
        Args:
            memory_id: ID of memory to reinforce
        
        Returns:
            True if memory was found and reinforced
        """
        memories = self._load_registry()
        
        for memory in memories:
            if memory["memory_id"] == memory_id:
                memory["decay_factor"] = min(1.0, memory.get("decay_factor", 1.0) * 1.1)
                memory["reinforcement_count"] = memory.get("reinforcement_count", 0) + 1
                self._save_registry(memories)
                print(f"ENGRAM: Reinforced memory {memory_id[:8]}... (LTP applied)")
                return True
        
        return False

    def depress_memory(self, memory_id: str) -> bool:
        """
        Depress a memory (decrease its strength).
        
        Called when a memory led to a high-dissonance/incorrect prediction,
        implementing Long-Term Depression (LTD).
        
        Args:
            memory_id: ID of memory to depress
        
        Returns:
            True if memory was found and depressed
        """
        memories = self._load_registry()
        
        for memory in memories:
            if memory["memory_id"] == memory_id:
                # Reduce decay factor significantly
                memory["decay_factor"] = max(0.0, memory.get("decay_factor", 1.0) * 0.7)
                self._save_registry(memories)
                print(f"ENGRAM: Depressed memory {memory_id[:8]}... (LTD applied)")
                return True
        
        return False
    
    def apply_decay(self):
        """
        Apply decay to all memories (Homeostatic regulation).
        
        Memories that are not reinforced gradually weaken,
        implementing a form of memory cleanup.
        """
        memories = self._load_registry()
        
        for memory in memories:
            current_decay = memory.get("decay_factor", 1.0)
            memory["decay_factor"] = current_decay * self.decay_factor
        
        # Remove memories that have decayed below threshold
        initial_count = len(memories)
        memories = [m for m in memories if m.get("decay_factor", 1.0) > 0.01]
        pruned_count = initial_count - len(memories)
        
        self._save_registry(memories)
        
        if pruned_count > 0:
            print(f"ENGRAM: Decay applied. Pruned {pruned_count} weak memories.")
        
        return {"pruned": pruned_count, "remaining": len(memories)}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        memories = self._load_registry()
        
        if not memories:
            return {"count": 0, "categories": {}}
        
        # Count by signal category
        categories = {}
        for m in memories:
            cat = m.get("signal_category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        
        coherence_scores = [m["coherence_score"] for m in memories]
        
        return {
            "count": len(memories),
            "categories": categories,
            "mean_coherence": sum(coherence_scores) / len(coherence_scores),
            "oldest_memory": min(m["timestamp"] for m in memories),
            "newest_memory": max(m["timestamp"] for m in memories)
        }
