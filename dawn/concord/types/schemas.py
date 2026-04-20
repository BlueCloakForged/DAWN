"""CONCORD v0.3 — Pydantic v2 schemas mirroring every entity and contract.

Used for:
- Parsing JSON input (contract files, API payloads)
- Runtime validation with descriptive error messages
- .model_validate() / .model_dump() for serialization

Normative validation enforced here:
- ActionContract: idempotency_required required; mutating actions must set it True
- ActionContract: participates_in_saga=True requires compensation_strategy != none
- ActionContract: ASYNC_PROJECTION requires projection_tolerance_ms
- StateContract: initial_state and terminal_states must be in declared states
- StateContract: all transition from/to states must reference declared states
- OperationContext: authoritative_for_mutation always False (computed field)
- CircuitBreakerThresholds: rates in [0, 1], window_ms > 0
- BudgetProfile: all limits > 0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, computed_field, model_validator

from dawn.concord.types.enums import (
    ActionFamily,
    CircuitState,
    CompensationStrategy,
    ConflictResolutionStrategy,
    ConsistencyProfile,
    CooldownPolicy,
    FreshnessStatus,
    IdempotencyScope,
    IntentStatus,
    LeaseStatus,
    LeaseType,
    MaturityLevel,
    RetryClass,
    RiskLevel,
    SagaTimeoutPolicy,
    SessionMode,
    SessionStatus,
    TokenStatus,
    TokenType,
    TripRecoveryPolicy,
    TrustTier,
)


# ── Sub-object schemas ────────────────────────────────────────────────────────


class BlockedReasonSchema(BaseModel):
    reason_code: str
    unblock_condition: str
    estimated_wait_ms: Optional[int] = None


class CircuitBreakerThresholdsSchema(BaseModel):
    stale_version_failure_rate: float = Field(ge=0.0, le=1.0)
    budget_exceeded_rate: float = Field(ge=0.0, le=1.0)
    error_rate: float = Field(ge=0.0, le=1.0)
    evaluation_window_ms: int = Field(gt=0)
    trip_recovery_policy: TripRecoveryPolicy


class GuardPredicateSchema(BaseModel):
    name: str
    guard_type: Literal["permission", "state", "resource_tag", "custom"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    evaluation_order: int = 0


class SideEffectSchema(BaseModel):
    effect_type: str
    reversible: bool
    description: str
    target_resource: Optional[str] = None
    target_system: Optional[str] = None


class StateObjectSchema(BaseModel):
    """A declared state within a resource's state machine (spec §4.2)."""

    name: str
    description: Optional[str] = None
    is_terminal: bool = False
    allowed_action_refs: list[str] = Field(default_factory=list)


class StateTransitionSchema(BaseModel):
    """A state machine edge with richer spec-aligned fields (spec §4.2)."""

    name: str
    from_state: str
    to_state: str
    action_ref: str
    guards: list[GuardPredicateSchema] = Field(default_factory=list)
    allowed_agent_families: list[ActionFamily] = Field(default_factory=list)
    on_success: list[str] = Field(default_factory=list)
    rollback_to_state: Optional[str] = None


# ── Entity schemas ────────────────────────────────────────────────────────────


class SessionSchema(BaseModel):
    id: str
    agent_id: str
    agent_class_id: str
    trust_tier: TrustTier
    mode: SessionMode
    status: SessionStatus
    watermark: int
    started_at: datetime
    budget_profile_id: str
    task_id: Optional[str] = None
    expires_at: Optional[datetime] = None


class IntentSchema(BaseModel):
    id: str
    session_id: str
    resource_type: str
    resource_id: str
    action_name: str
    idempotency_key: str
    status: IntentStatus
    consistency_profile: ConsistencyProfile
    risk_level: RiskLevel
    participates_in_saga: bool
    created_at: datetime
    saga_id: Optional[str] = None
    admitted_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None


class ResourceSchema(BaseModel):
    id: str
    resource_type: str
    business_state: dict[str, Any]
    coordination_state: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class LeaseSchema(BaseModel):
    id: str
    resource_id: str
    session_id: str
    lease_type: LeaseType
    expires_at: datetime
    granted_at: datetime
    status: LeaseStatus
    renewal_count: int = 0
    purpose: Optional[str] = None


class TokenSchema(BaseModel):
    id: str
    token_type: TokenType
    resource_id: str
    capacity: int = Field(gt=0)
    available_count: int = Field(ge=0)
    holders: list[str]
    issuance_rule: str
    status: TokenStatus
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def available_not_exceeds_capacity(self) -> "TokenSchema":
        if self.available_count > self.capacity:
            raise ValueError(
                f"available_count ({self.available_count}) cannot exceed capacity ({self.capacity})"
            )
        return self


class ReceiptSchema(BaseModel):
    operation_id: str
    intent_id: str
    previous_state: dict[str, Any]
    next_state: dict[str, Any]
    version_before: int
    version_after: int
    result_status: str
    duration_ms: int
    policy_decision: str
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SagaRunSchema(BaseModel):
    id: str
    root_intent_id: str
    steps: list[str]
    current_step: int
    timeout_policy: SagaTimeoutPolicy
    timeout_deadline_ms: int
    compensation_strategy: CompensationStrategy
    max_compensation_attempts: int
    attempt_count: int
    status: IntentStatus
    step_timeout_ms: Optional[int] = None
    heartbeat_interval_ms: Optional[int] = None
    external_dependency_timeout_ms: Optional[int] = None


class AgentClassSchema(BaseModel):
    id: str
    name: str
    trust_tier: TrustTier
    budget_profile_id: str
    capability_set_ids: list[str] = Field(default_factory=list)
    composed_from: list[str] = Field(default_factory=list)
    prod_allowed: bool = False
    requires_human_gate_for: list[str] = Field(default_factory=list)
    override_rules: dict[str, Any] = Field(default_factory=dict)


class CapabilitySetSchema(BaseModel):
    id: str
    allowed_action_families: list[ActionFamily] = Field(default_factory=list)
    allowed_resource_types: list[str] = Field(default_factory=list)
    restricted_resource_types: list[str] = Field(default_factory=list)
    restricted_resource_tags: list[str] = Field(default_factory=list)
    lease_permissions: list[str] = Field(default_factory=list)
    max_authority_mode: Optional[SessionMode] = None
    default_budget_profile_id: Optional[str] = None
    exclusions: list[str] = Field(default_factory=list)
    override_rules: list[str] = Field(default_factory=list)


class BudgetProfileSchema(BaseModel):
    id: str
    max_actions_per_minute: int = Field(gt=0)
    max_mutating_actions_per_hour: int = Field(gt=0)
    max_high_risk_per_day: int = Field(gt=0)
    max_cost_units_per_session: float = Field(gt=0)
    burst_limit: int = Field(gt=0)
    circuit_breaker_thresholds: CircuitBreakerThresholdsSchema
    cooldown_policy: CooldownPolicy
    max_parallel_leases: int = Field(default=1, ge=1)
    max_queue_depth: Optional[int] = Field(default=None, ge=1)
    per_resource_class_limits: Optional[dict[str, Any]] = None
    per_action_family_limits: Optional[dict[str, Any]] = None


class BudgetLedgerSchema(BaseModel):
    ledger_id: str
    session_id: str
    agent_class_id: str
    budget_profile_id: str
    window_start: datetime
    window_end: datetime
    actions_consumed: int = Field(ge=0)
    mutating_actions_consumed: int = Field(ge=0)
    high_risk_actions_consumed: int = Field(ge=0)
    cost_units_consumed: float = Field(ge=0.0)
    parallel_leases_in_use: int = Field(ge=0)
    queue_slots_in_use: int = Field(ge=0)
    circuit_state: CircuitState
    cooldown_until: Optional[datetime] = None

    @model_validator(mode="after")
    def window_end_after_start(self) -> "BudgetLedgerSchema":
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class OperationContextSchema(BaseModel):
    """Advisory context for an agent before it acts.

    CONCORD core law: authoritative_for_mutation is ALWAYS False.
    The field is a computed property — callers cannot set it.
    """

    resource_id: str
    resource: ResourceSchema
    allowed_actions: list[str]
    blocked_actions: list[str]
    blocked_reasons: list[BlockedReasonSchema]
    active_leases: list[LeaseSchema] = Field(default_factory=list)
    pending_intents: list[str] = Field(default_factory=list)
    budget_remaining: dict[str, Any]
    freshness_status: FreshnessStatus
    context_assembled_at: datetime
    context_ttl_ms: int
    queue_position: Optional[int] = None
    recommended_next_action: Optional[str] = None
    safe_parallel_actions: list[str] = Field(default_factory=list)
    requires_authoritative_recheck: bool = False
    consistency_profile: Optional[ConsistencyProfile] = None
    projection_lag_ms: Optional[int] = None
    trust_constraints: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def authoritative_for_mutation(self) -> Literal[False]:
        """Always False — CONCORD core law."""
        return False


class CoordinationTelemetrySchema(BaseModel):
    telemetry_window_start: datetime
    telemetry_window_end: datetime
    lease_contention_rate: float = Field(ge=0.0, le=1.0)
    average_queue_wait_ms: float = Field(ge=0.0)
    queue_abandonment_rate: float = Field(ge=0.0, le=1.0)
    stale_write_rejection_rate: float = Field(ge=0.0, le=1.0)
    budget_throttle_rate: float = Field(ge=0.0, le=1.0)
    circuit_breaker_trip_count: int = Field(ge=0)
    compensation_invocation_rate: float = Field(ge=0.0)
    retry_distribution: dict[str, Any]
    resource_type: Optional[str] = None
    arbitration_frequency: Optional[float] = Field(default=None, ge=0.0)
    resource_hotspots: list[dict[str, Any]] = Field(default_factory=list)


# ── Contract schemas ──────────────────────────────────────────────────────────


class ActionContractSchema(BaseModel):
    """Pydantic schema for ActionContract with full spec-aligned fields and normative validation."""

    # Required core fields
    action_name: str
    description: str
    resource_type: str
    action_family: ActionFamily
    input_schema_ref: str
    output_schema_ref: str
    required_capabilities: list[str]
    idempotency_required: bool
    risk_level: RiskLevel
    consistency_profile: ConsistencyProfile
    conflict_resolution_strategy: ConflictResolutionStrategy
    compensation_strategy: CompensationStrategy
    participates_in_saga: bool

    # Optional core fields
    required_trust_tier: Optional[TrustTier] = None
    idempotency_scope: IdempotencyScope = IdempotencyScope.SESSION
    retry_class: RetryClass = RetryClass.NONE
    guard_predicates: list[GuardPredicateSchema] = Field(default_factory=list)
    side_effects: list[SideEffectSchema] = Field(default_factory=list)
    allowed_from_states: list[str] = Field(default_factory=list)

    # Coordination / recovery optional fields
    compensation_order_hint: Optional[int] = None
    authoritative_recheck_required: Optional[bool] = None
    projection_tolerance_ms: Optional[int] = None
    session_watermark_required: Optional[bool] = None
    conflict_resolution_strategy_override: Optional[str] = None
    budget_cost_units: float = Field(default=1.0, gt=0)
    budget_dimensions_consumed: list[str] = Field(default_factory=list)
    transitions_to_state: Optional[str] = None

    @model_validator(mode="after")
    def validate_mutating_idempotency(self) -> "ActionContractSchema":
        if self.action_family == ActionFamily.MUTATE and not self.idempotency_required:
            raise ValueError(
                "Mutating actions (action_family='mutate') MUST declare idempotency_required=True."
            )
        return self

    @model_validator(mode="after")
    def validate_saga_compensation(self) -> "ActionContractSchema":
        if self.participates_in_saga and self.compensation_strategy == CompensationStrategy.NONE:
            raise ValueError(
                "participates_in_saga=True requires compensation_strategy != 'none'. "
                "Specify 'inverse_action', 'saga_handler', or 'manual_only'."
            )
        return self

    @model_validator(mode="after")
    def validate_async_projection_tolerance(self) -> "ActionContractSchema":
        if (
            self.consistency_profile == ConsistencyProfile.ASYNC_PROJECTION
            and self.projection_tolerance_ms is None
        ):
            raise ValueError(
                "consistency_profile=ASYNC_PROJECTION requires projection_tolerance_ms to be set."
            )
        return self


class StateContractSchema(BaseModel):
    """Pydantic schema for StateContract with rich state objects and state reference validation."""

    resource_type: str
    initial_state: str
    terminal_states: list[str]
    states: list[StateObjectSchema]
    transitions: list[StateTransitionSchema]
    conflict_resolution_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.DEFAULT
    rollback_rules: list[dict[str, Any]] = Field(default_factory=list)
    entry_hooks: list[dict[str, Any]] = Field(default_factory=list)
    exit_hooks: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state_references(self) -> "StateContractSchema":
        declared = {s.name for s in self.states}

        if self.initial_state not in declared:
            raise ValueError(
                f"initial_state '{self.initial_state}' is not in declared states: {sorted(declared)}"
            )

        for ts in self.terminal_states:
            if ts not in declared:
                raise ValueError(
                    f"terminal_state '{ts}' is not in declared states: {sorted(declared)}"
                )

        for t in self.transitions:
            if t.from_state not in declared:
                raise ValueError(
                    f"Transition '{t.name}' from_state '{t.from_state}' "
                    f"is not in declared states: {sorted(declared)}"
                )
            if t.to_state not in declared:
                raise ValueError(
                    f"Transition '{t.name}' to_state '{t.to_state}' "
                    f"is not in declared states: {sorted(declared)}"
                )

        return self
