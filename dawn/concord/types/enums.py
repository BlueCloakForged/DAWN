"""CONCORD v0.3/v0.4 — All enum types (43 families).

Covers runtime enums (16) + coordination status enums (4) + Phase 9 scanner enums (7)
+ v0.4-alpha fleet/environment enums (9) + v0.4-beta entry-point enums (2)
+ v0.4-rc context-scope/review enums (5).
"""

from enum import Enum


# ── Runtime enums (original 16) ───────────────────────────────────────────────


class TrustTier(str, Enum):
    T0_OBSERVE = "T0/observe"
    T1_PROPOSE = "T1/propose"
    T2_BOUNDED = "T2/bounded"
    T3_PRIVILEGED = "T3/privileged"
    T4_GOVERNED_CRITICAL = "T4/governed_critical"


class ActionFamily(str, Enum):
    READ = "read"
    PLAN = "plan"
    MUTATE = "mutate"
    APPROVE = "approve"
    DEPLOY = "deploy"
    COMPENSATE = "compensate"
    ADMIN = "admin"


class ConsistencyProfile(str, Enum):
    STRONG = "STRONG"
    SESSION_MONOTONIC = "SESSION_MONOTONIC"
    READ_YOUR_WRITES = "READ_YOUR_WRITES"
    EVENTUAL = "EVENTUAL"
    ASYNC_PROJECTION = "ASYNC_PROJECTION"


class ConflictResolutionStrategy(str, Enum):
    DEFAULT = "default"
    FAIL_FAST = "fail_fast"
    QUEUE_FIRST = "queue_first"
    LEASE_FIRST = "lease_first"
    POLICY_FIRST = "policy_first"
    CUSTOM = "custom"


class SagaTimeoutPolicy(str, Enum):
    FIXED = "fixed"
    STEP_ADAPTIVE = "step_adaptive"
    HEARTBEAT = "heartbeat"
    EXTERNAL_GATED = "external_gated"


class CompensationStrategy(str, Enum):
    NONE = "none"
    INVERSE_ACTION = "inverse_action"
    SAGA_HANDLER = "saga_handler"
    MANUAL_ONLY = "manual_only"


class RetryClass(str, Enum):
    NONE = "none"
    SAFE_RETRY = "safe_retry"
    RECHECK_THEN_RETRY = "recheck_then_retry"
    QUEUE_THEN_RETRY = "queue_then_retry"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class LeaseType(str, Enum):
    EDIT = "edit"
    REVIEW = "review"
    EXECUTE = "execute"
    RESERVATION = "reservation"
    APPROVAL_SLOT = "approval_slot"


class TokenType(str, Enum):
    CAPACITY = "capacity"
    QUORUM = "quorum"
    VALIDATION_GATE = "validation_gate"
    DEPLOYMENT_GATE = "deployment_gate"


class CircuitState(str, Enum):
    CLOSED = "closed"
    THROTTLED = "throttled"
    OPEN = "open"


class CooldownPolicy(str, Enum):
    FIXED_BACKOFF = "fixed_backoff"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    CONTENTION_SCALED = "contention_scaled"
    RISK_SCALED = "risk_scaled"
    MANUAL_RESUME_REQUIRED = "manual_resume_required"


class IntentStatus(str, Enum):
    PROPOSED = "proposed"
    ADMITTED = "admitted"
    QUEUED = "queued"
    BLOCKED = "blocked"
    EXECUTING = "executing"
    COMMITTED = "committed"
    COMPENSATED = "compensated"
    FAILED = "failed"
    EXPIRED = "expired"


class SessionMode(str, Enum):
    READ_ONLY = "read_only"
    PROPOSE_ONLY = "propose_only"
    EXECUTE = "execute"
    SUPERVISED = "supervised"


class FreshnessStatus(str, Enum):
    FRESH = "fresh"
    WARNING = "warning"
    STALE = "stale"


class TripRecoveryPolicy(str, Enum):
    AUTO_AFTER_COOLDOWN = "auto_after_cooldown"
    MANUAL_RESET = "manual_reset"
    GRADUAL_RAMP = "gradual_ramp"


# ── Coordination status enums (added from Runtime Contract Schemas) ────────────


class LeaseStatus(str, Enum):
    """Lifecycle status of a Lease."""

    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"
    REVOKED = "revoked"


class TokenStatus(str, Enum):
    """Lifecycle status of a coordination Token."""

    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    EXPIRED = "expired"
    SUSPENDED = "suspended"


class IdempotencyScope(str, Enum):
    """Scope over which an idempotency key is unique."""

    SESSION = "session"
    RESOURCE = "resource"
    GLOBAL = "global"


class SessionStatus(str, Enum):
    """Lifecycle status of a Session."""

    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"


# ── Phase 9 scanner enums ──────────────────────────────────────────────────────


class MaturityLevel(str, Enum):
    """Overall CONCORD readiness maturity level (0 = none, 6 = full)."""

    LEVEL_0 = "level_0"
    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    LEVEL_3 = "level_3"
    LEVEL_4 = "level_4"
    LEVEL_5 = "level_5"
    LEVEL_6 = "level_6"


class DangerType(str, Enum):
    """Whether a danger finding is a single-point risk or a compound interaction."""

    SINGLE_POINT = "single_point"
    COMPOUND = "compound"


class DependencyEdgeType(str, Enum):
    """Type of dependency edge in the resource dependency graph."""

    MUTATES = "mutates"
    READS_BEFORE_MUTATION = "reads_before_mutation"
    PROJECTS_TO = "projects_to"
    BACKGROUND_UPDATES = "background_updates"
    TRIGGERS = "triggers"
    DEPENDS_ON_EXTERNAL = "depends_on_external"


class PatchPriority(str, Enum):
    """Priority of a scanner-recommended patch item."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class EvidenceSource(str, Enum):
    """How a scanner finding was obtained."""

    DISCOVERED = "discovered"
    INFERRED = "inferred"
    HEURISTIC = "heuristic"


class SilentFailureLikelihood(str, Enum):
    """Likelihood that a compound danger produces a silent failure."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class SinglePointDangerCategory(str, Enum):
    """The 8 required single-point danger categories from the Scan Output spec."""

    DESTRUCTIVE_WITHOUT_IDEMPOTENCY = "destructive_without_idempotency"
    MUTABLE_WITHOUT_VERSIONING = "mutable_without_versioning"
    SHARED_WITHOUT_COORDINATION = "shared_without_coordination"
    IMPLICIT_ORDERING_DEPENDENCY = "implicit_ordering_dependency"
    BACKGROUND_JOB_API_COLLISION = "background_job_api_collision"
    MISSING_AUTHORITATIVE_RECHECK = "missing_authoritative_recheck"
    UNBOUNDED_BULK_MUTATION = "unbounded_bulk_mutation"
    MULTI_STEP_WITHOUT_COMPENSATION = "multi_step_without_compensation"


class ConfidenceLevel(str, Enum):
    """PL-12: Confidence level for scanner danger findings.

    All danger findings (single-point and compound) MUST carry a confidence_level.
    """

    CONFIRMED = "confirmed"
    HIGH_CONFIDENCE = "high_confidence"
    INFERRED = "inferred"
    HEURISTIC = "heuristic"


# ── v0.4-alpha: Execution environment + fleet enums ───────────────────────────


class EnvironmentClass(str, Enum):
    """Class of execution environment."""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"
    SHARED_POOL = "shared_pool"


class ProvisioningStatus(str, Enum):
    """Lifecycle status of an ExecutionEnvironment during provisioning."""

    COLD = "cold"
    WARMING = "warming"
    READY = "ready"
    ASSIGNED = "assigned"
    DRAINING = "draining"
    TERMINATED = "terminated"


class IsolationLevel(str, Enum):
    """Isolation guarantee of an ExecutionEnvironment."""

    NONE = "none"
    CONTAINER = "container"
    VM = "vm"
    DEDICATED_HOST = "dedicated_host"


class EnvironmentStatus(str, Enum):
    """Operational health status of an ExecutionEnvironment."""

    ACTIVE = "active"
    UNHEALTHY = "unhealthy"
    TERMINATED = "terminated"


class FleetStatus(str, Enum):
    """Lifecycle status of a TaskFleet."""

    ASSEMBLING = "assembling"
    ACTIVE = "active"
    DRAINING = "draining"
    COMPLETED = "completed"
    ABORTED = "aborted"


class FleetCompletionPolicy(str, Enum):
    """Policy governing when a TaskFleet is considered complete."""

    ALL_MUST_SUCCEED = "all_must_succeed"
    BEST_EFFORT = "best_effort"
    FIRST_SUCCESS = "first_success"
    QUORUM_N = "quorum_n"


class IsolationRequirement(str, Enum):
    """How isolation is distributed across sessions in a fleet."""

    PER_SESSION = "per_session"
    SHARED = "shared"
    MIXED = "mixed"


class DispatchStatus(str, Enum):
    """Lifecycle status of a DispatchRequest."""

    QUEUED = "queued"
    ASSIGNED = "assigned"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DispatchPriority(str, Enum):
    """Priority of a DispatchRequest within its fleet queue."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


# ── v0.4-beta: Entry-point enums ──────────────────────────────────────────────


class EntryChannel(str, Enum):
    """The channel through which work enters the CONCORD system."""

    CLI = "cli"
    WEB_UI = "web_ui"
    SLACK = "slack"
    API = "api"
    WEBHOOK = "webhook"
    CRON = "cron"
    EVENT_TRIGGER = "event_trigger"


class AuthenticationMethod(str, Enum):
    """Authentication mechanism used by an EntryPoint."""

    TOKEN = "token"
    OAUTH = "oauth"
    SESSION_COOKIE = "session_cookie"
    SERVICE_ACCOUNT = "service_account"
    NONE = "none"


# ── v0.4-rc: Context-scope + review enums ────────────────────────────────────


class ScopeType(str, Enum):
    """How a ContextScope matches its target context."""

    RESOURCE_TYPE = "resource_type"
    DOMAIN = "domain"
    PATH_GLOB = "path_glob"
    TAG = "tag"
    ACTION_FAMILY = "action_family"
    COMPOSITE = "composite"


class ScopedRuleType(str, Enum):
    """The category of a ScopedRule."""

    CONVENTION = "convention"
    CONSTRAINT = "constraint"
    PREFERENCE = "preference"
    WARNING = "warning"
    ESCALATION_TRIGGER = "escalation_trigger"


class ScopedRuleSeverity(str, Enum):
    """How strongly a ScopedRule must be followed."""

    ADVISORY = "advisory"
    RECOMMENDED = "recommended"
    REQUIRED = "required"


class ScopedRuleAppliesTo(str, Enum):
    """Which runtime participant a ScopedRule targets."""

    AGENT = "agent"
    VALIDATOR = "validator"
    REVIEWER = "reviewer"
    ALL = "all"


class BundleStatus(str, Enum):
    """Review lifecycle status of a ReviewBundle."""

    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"
