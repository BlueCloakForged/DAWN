"""
DAWN Agnostic Meta-Bundle Schema
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, Any
from datetime import datetime

@dataclass
class MetaBundle:
    """
    DAWN Phase 2.2: Meta-Bundle
    Cryptographically binds reasoning to the exact moment in time.
    """
    bundle_sha256: str
    environment_hash: str
    system_state: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

class BundleFactory:
    """
    Factory for producing state-locked Meta-Bundles.
    """
    
    @staticmethod
    def create_bundle(environment_data: Dict[str, Any], system_state: Dict[str, Any]) -> MetaBundle:
        """
        Generates a bundle_sha256 and wraps it in a MetaBundle.
        """
        env_str = json.dumps(environment_data, sort_keys=True)
        env_hash = hashlib.sha256(env_str.encode()).hexdigest()
        
        state_str = json.dumps(system_state, sort_keys=True)
        timestamp = datetime.now().isoformat()
        
        bundle_input = f"{env_hash}:{state_str}:{timestamp}"
        bundle_sha256 = hashlib.sha256(bundle_input.encode()).hexdigest()
        
        return MetaBundle(
            bundle_sha256=bundle_sha256,
            environment_hash=env_hash,
            system_state=system_state,
            timestamp=timestamp
        )
    
    @staticmethod
    def validate_hash(bundle: MetaBundle, provided_hash: str) -> bool:
        """
        DAWN Stale-Safe Invalidation check.
        """
        return bundle.bundle_sha256 == provided_hash
