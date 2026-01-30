"""
DAWN Policy Loader - Phase 8.3/8.5/9.1/9.2

Responsibilities:
- Load and validate runtime_policy.yaml
- Compute policy_digest for idempotency signatures
- Resolve active profile based on CLI override or default
- Provide retry policy configuration (Phase 9.1)
- Provide retention policy configuration (Phase 9.2)
- Fail fast on invalid/missing policy
"""

import yaml
import hashlib
import json
from pathlib import Path
from typing import Dict, Any, Optional


class PolicyValidationError(Exception):
    """Raised when policy file is invalid or missing required keys."""
    pass


class PolicyLoader:
    """Loads, validates, and provides access to DAWN runtime policy."""

    REQUIRED_KEYS = ["version", "budgets", "security", "profiles", "default_profile"]
    REQUIRED_BUDGET_SECTIONS = ["per_link", "per_project"]
    REQUIRED_PER_LINK_KEYS = ["max_wall_time_sec", "max_output_bytes"]
    REQUIRED_PER_PROJECT_KEYS = ["max_project_bytes"]
    REQUIRED_PROFILE_KEYS = ["allow_src_writes", "artifact_only_outputs"]

    def __init__(self, policy_path: Optional[Path] = None):
        if policy_path is None:
            policy_path = Path(__file__).parent / "runtime_policy.yaml"

        self.policy_path = Path(policy_path)
        self._policy: Optional[Dict[str, Any]] = None
        self._digest: Optional[str] = None
        self._raw_yaml: Optional[str] = None

    def load(self) -> Dict[str, Any]:
        """Load and validate the policy file. Raises PolicyValidationError on failure."""
        if not self.policy_path.exists():
            raise PolicyValidationError(f"Policy file not found: {self.policy_path}")

        try:
            self._raw_yaml = self.policy_path.read_text()
            self._policy = yaml.safe_load(self._raw_yaml)
        except yaml.YAMLError as e:
            raise PolicyValidationError(f"Invalid YAML in policy file: {e}")

        if self._policy is None:
            raise PolicyValidationError("Policy file is empty")

        self._validate()
        self._compute_digest()

        return self._policy

    def _validate(self):
        """Validate required keys and structure."""
        # Check top-level required keys
        for key in self.REQUIRED_KEYS:
            if key not in self._policy:
                raise PolicyValidationError(f"Missing required key: {key}")

        # Validate budgets structure
        budgets = self._policy.get("budgets", {})
        for section in self.REQUIRED_BUDGET_SECTIONS:
            if section not in budgets:
                raise PolicyValidationError(f"Missing required budget section: budgets.{section}")

        # Validate per_link budget keys
        per_link = budgets.get("per_link", {})
        for key in self.REQUIRED_PER_LINK_KEYS:
            if key not in per_link:
                raise PolicyValidationError(f"Missing required budget key: budgets.per_link.{key}")

        # Validate per_project budget keys
        per_project = budgets.get("per_project", {})
        for key in self.REQUIRED_PER_PROJECT_KEYS:
            if key not in per_project:
                raise PolicyValidationError(f"Missing required budget key: budgets.per_project.{key}")

        # Validate profiles exist and have required keys
        profiles = self._policy.get("profiles", {})
        default_profile = self._policy.get("default_profile")

        if default_profile not in profiles:
            raise PolicyValidationError(f"default_profile '{default_profile}' not found in profiles")

        for profile_name, profile_config in profiles.items():
            for key in self.REQUIRED_PROFILE_KEYS:
                if key not in profile_config:
                    raise PolicyValidationError(
                        f"Missing required key in profile '{profile_name}': {key}"
                    )

        # Validate version is 2.x (reject old 1.x schema)
        version = self._policy.get("version", "")
        if version.startswith("1."):
            raise PolicyValidationError(
                f"Policy version {version} uses deprecated schema. "
                "Migrate to version 2.0.0 (remove 'limits' block, use 'budgets' instead)."
            )

        # Check for deprecated 'limits' block (migration warning)
        if "limits" in self._policy:
            raise PolicyValidationError(
                "Deprecated 'limits' block found. "
                "Remove it and use 'budgets' block instead (v2.0.0 schema)."
            )

    def _compute_digest(self):
        """Compute SHA256 digest of normalized policy for idempotency signatures."""
        # Normalize by serializing to sorted JSON (deterministic)
        normalized = json.dumps(self._policy, sort_keys=True, separators=(',', ':'))
        self._digest = hashlib.sha256(normalized.encode()).hexdigest()

    @property
    def policy(self) -> Dict[str, Any]:
        """Get the loaded policy. Raises if not loaded."""
        if self._policy is None:
            raise RuntimeError("Policy not loaded. Call load() first.")
        return self._policy

    @property
    def digest(self) -> str:
        """Get the policy digest. Raises if not loaded."""
        if self._digest is None:
            raise RuntimeError("Policy not loaded. Call load() first.")
        return self._digest

    @property
    def version(self) -> str:
        """Get the policy version."""
        return self.policy.get("version", "unknown")

    def get_profile(self, profile_name: Optional[str] = None) -> Dict[str, Any]:
        """Get a specific profile config, or default if not specified."""
        if profile_name is None:
            profile_name = self.policy.get("default_profile", "normal")

        profiles = self.policy.get("profiles", {})
        if profile_name not in profiles:
            raise PolicyValidationError(f"Profile '{profile_name}' not found")

        return profiles[profile_name]

    def get_budget(self, scope: str, key: str) -> Any:
        """Get a budget value. scope is 'per_link', 'per_pipeline', or 'per_project'."""
        budgets = self.policy.get("budgets", {})
        scope_budgets = budgets.get(scope, {})
        return scope_budgets.get(key)

    def get_security(self, key: str) -> Any:
        """Get a security setting."""
        security = self.policy.get("security", {})
        return security.get(key)

    def is_src_write_allowed(self, link_id: str, profile_name: Optional[str] = None) -> bool:
        """Check if a link is allowed to write to src/ under the given profile."""
        profile = self.get_profile(profile_name)

        # Profile can override to block all src writes
        if not profile.get("allow_src_writes", True):
            return False

        # Check security whitelist
        allowed_links = self.get_security("allow_src_writes") or []
        return link_id in allowed_links

    def get_allowed_subprocess_commands(self, profile_name: Optional[str] = None) -> list:
        """Get allowed subprocess commands for the given profile."""
        profile = self.get_profile(profile_name)

        # Profile can override the command list
        if "allowed_subprocess_commands" in profile:
            return profile["allowed_subprocess_commands"]

        # Fall back to security defaults
        return self.get_security("allowed_subprocess_commands") or []

    def get_effective_timeout(self, profile_name: Optional[str] = None) -> int:
        """Get the effective wall time timeout, applying profile multiplier."""
        base_timeout = self.get_budget("per_link", "max_wall_time_sec") or 60
        profile = self.get_profile(profile_name)
        multiplier = profile.get("timeout_multiplier", 1.0)
        return int(base_timeout * multiplier)

    # ════════════════════════════════════════════════════════════════════
    # Phase 9.1: Retry Policy
    # ════════════════════════════════════════════════════════════════════

    def get_retry_config(self) -> Dict[str, Any]:
        """Get the retry configuration."""
        return self.policy.get("retry", {})

    def get_max_retries_per_link(self) -> int:
        """Get maximum retries per link."""
        return self.get_retry_config().get("max_retries_per_link", 3)

    def get_max_retries_per_project(self) -> int:
        """Get maximum retries per project."""
        return self.get_retry_config().get("max_retries_per_project", 10)

    def get_backoff_delay(self, retry_attempt: int) -> int:
        """Get backoff delay in seconds for a given retry attempt (0-indexed)."""
        schedule = self.get_retry_config().get("backoff_schedule", [1, 5, 30])
        if retry_attempt < len(schedule):
            return schedule[retry_attempt]
        # If beyond schedule, use the last value
        return schedule[-1] if schedule else 30

    def is_error_retryable(self, error_type: str) -> bool:
        """Check if an error type is retryable."""
        retry_config = self.get_retry_config()
        retryable = retry_config.get("retryable_errors", [])
        non_retryable = retry_config.get("non_retryable_errors", [])

        # Explicit non-retryable takes precedence
        if error_type in non_retryable:
            return False

        # Check if explicitly retryable
        if error_type in retryable:
            return True

        # Default: not retryable (fail-safe)
        return False

    # ════════════════════════════════════════════════════════════════════
    # Phase 9.2: Retention Policy
    # ════════════════════════════════════════════════════════════════════

    def get_retention_config(self) -> Dict[str, Any]:
        """Get the retention configuration."""
        return self.policy.get("retention", {})

    def get_keep_last_n_runs(self) -> int:
        """Get number of successful runs to keep per project."""
        return self.get_retention_config().get("keep_last_n_runs", 3)

    def should_keep_evidence_pack(self) -> bool:
        """Check if evidence packs should always be kept."""
        return self.get_retention_config().get("always_keep_evidence_pack", True)

    def get_keep_failed_runs_days(self) -> int:
        """Get number of days to keep failed runs."""
        return self.get_retention_config().get("keep_failed_runs_days", 7)

    def get_protected_artifacts(self) -> list:
        """Get list of artifact types that should never be deleted."""
        return self.get_retention_config().get("protected_artifacts", [
            "dawn.evidence.pack",
            "dawn.release.bundle",
            "dawn.metrics.run_summary"
        ])

    def should_preserve_ledger(self) -> bool:
        """Check if ledger should be preserved (never deleted)."""
        return self.get_retention_config().get("preserve_ledger", True)

    def to_dict(self) -> Dict[str, Any]:
        """Return policy info suitable for ledger/artifacts."""
        return {
            "version": self.version,
            "digest": self.digest,
            "default_profile": self.policy.get("default_profile"),
            "budgets": self.policy.get("budgets", {}),
            "retry": self.get_retry_config(),
            "retention": self.get_retention_config(),
        }


# Singleton instance for convenience
_default_loader: Optional[PolicyLoader] = None


def get_policy_loader(policy_path: Optional[Path] = None) -> PolicyLoader:
    """Get the policy loader singleton, creating and loading if needed."""
    global _default_loader

    if _default_loader is None or policy_path is not None:
        loader = PolicyLoader(policy_path)
        loader.load()
        if policy_path is None:
            _default_loader = loader
        return loader

    return _default_loader


def reset_policy_loader():
    """Reset the singleton (for testing)."""
    global _default_loader
    _default_loader = None
