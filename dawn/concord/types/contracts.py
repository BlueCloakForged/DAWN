"""CONCORD v0.3/v0.4 — ActionContract, StateContract, and associated sub-types.

PL-02: GuardPredicate defined with name, guard_type, parameters, evaluation_order.
PL-03: SideEffect defined with effect_type, target_resource, target_system, reversible, description.

Field set aligned with Runtime Contract Schemas §3–4:
- ActionContract §3.1–3.2 (all required + optional fields)
- StateContract §4.1–4.2 (richer state object and transition object)
- v0.4-beta: ActionDiscovery service contract (query/response shapes)
- v0.4-beta: AdmissionAdapter contract definition
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from dawn.concord.types.enums import (
    ActionFamily,
    CompensationStrategy,
    ConflictResolutionStrategy,
    ConsistencyProfile,
    IdempotencyScope,
    RetryClass,
    RiskLevel,
    TrustTier,
)



# ── PL-02: GuardPredicate ─────────────────────────────────────────────────────


@dataclass
class GuardPredicate:
    """A single guard condition evaluated before an action is admitted.

    PL-02 resolution: structured schema with four required fields.

    Attributes:
        name: Unique identifier for this predicate within the contract.
        guard_type: Category of guard logic applied.
        parameters: Key/value arguments passed to the guard evaluator.
        evaluation_order: Ascending integer; guards execute in this order.
    """

    name: str
    guard_type: Literal["permission", "state", "resource_tag", "custom"]
    parameters: dict = field(default_factory=dict)
    evaluation_order: int = 0


# ── PL-03: SideEffect ─────────────────────────────────────────────────────────


@dataclass
class SideEffect:
    """A declared side effect produced by an action.

    PL-03 resolution: structured schema describing what the side effect touches.

    Attributes:
        effect_type: Category of effect (e.g. "event_emit", "cache_invalidate").
        reversible: Whether compensation can undo this effect.
        description: Human-readable explanation of the effect.
        target_resource: Resource ID affected, or None for external systems.
        target_system: External system name, or None for internal resources.
    """

    effect_type: str
    reversible: bool
    description: str
    target_resource: Optional[str] = None
    target_system: Optional[str] = None


# ── ActionContract ────────────────────────────────────────────────────────────


@dataclass
class ActionContract:
    """Normative specification for a single action on a resource type.

    Normative invariants (enforced by Pydantic schema validation):
    - idempotency_required MUST be True for any mutating action.
    - participates_in_saga = True requires compensation_strategy != none.
    - consistency_profile MUST be exactly one of the five profiles.
    - authoritative_recheck_required defaults True for EVENTUAL/ASYNC_PROJECTION.
    - projection_tolerance_ms required when profile is ASYNC_PROJECTION.
    - session_watermark_required defaults True for SESSION_MONOTONIC.

    Spec §3.1–3.2 (Runtime Contract Schemas).
    """

    # Core fields (required)
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

    # Core fields with defaults
    required_trust_tier: Optional[TrustTier] = None
    idempotency_scope: IdempotencyScope = IdempotencyScope.SESSION
    retry_class: RetryClass = RetryClass.NONE
    guard_predicates: list[GuardPredicate] = field(default_factory=list)
    side_effects: list[SideEffect] = field(default_factory=list)
    allowed_from_states: list[str] = field(default_factory=list)

    # Coordination / recovery / consistency optional fields
    compensation_order_hint: Optional[int] = None
    authoritative_recheck_required: Optional[bool] = None
    projection_tolerance_ms: Optional[int] = None
    session_watermark_required: Optional[bool] = None
    conflict_resolution_strategy_override: Optional[str] = None
    budget_cost_units: float = 1.0
    budget_dimensions_consumed: list[str] = field(default_factory=list)
    transitions_to_state: Optional[str] = None


# ── StateContract ─────────────────────────────────────────────────────────────


@dataclass
class StateObject:
    """A declared state in a resource's business state machine.

    Spec §4.2 (Runtime Contract Schemas).
    """

    name: str
    description: Optional[str] = None
    is_terminal: bool = False
    allowed_action_refs: list[str] = field(default_factory=list)


@dataclass
class StateTransition:
    """A valid state machine edge for a resource type.

    Spec §4.2 (Runtime Contract Schemas): requires name, from_state, to_state,
    action_ref, and guards. Carries optional on_success and rollback_to_state.
    """

    name: str
    from_state: str
    to_state: str
    action_ref: str
    guards: list[GuardPredicate] = field(default_factory=list)
    allowed_agent_families: list[ActionFamily] = field(default_factory=list)
    on_success: list[str] = field(default_factory=list)
    rollback_to_state: Optional[str] = None


@dataclass
class StateContract:
    """State machine specification for a resource type.

    Spec §4.1–4.3 (Runtime Contract Schemas).
    Normative rules enforced by Pydantic schema:
    - initial_state must appear in states.
    - No transition may target an undeclared state.
    - Terminal states must be declared.
    - Business state MUST NOT encode lease/queue/budget state.
    """

    resource_type: str
    initial_state: str
    terminal_states: list[str]
    states: list[StateObject]
    transitions: list[StateTransition]
    conflict_resolution_strategy: ConflictResolutionStrategy = ConflictResolutionStrategy.DEFAULT
    rollback_rules: list[dict[str, Any]] = field(default_factory=list)
    entry_hooks: list[dict[str, Any]] = field(default_factory=list)
    exit_hooks: list[dict[str, Any]] = field(default_factory=list)


# ── v0.4-beta: ActionDiscovery service contract ───────────────────────────────


@dataclass
class ActionSummary:
    """Lightweight summary of an ActionContract for ActionDiscovery responses.

    Returned when include_schemas=False (the default). Full ActionContract is
    fetched on demand. Prevents token explosion from loading the full catalog.
    """

    action_name: str
    resource_type: str
    action_family: ActionFamily
    risk_level: RiskLevel
    description: str
    guard_summary: str                   # human-readable digest of guard predicates


@dataclass
class ActionDiscoveryQuery:
    """Input to the ActionDiscovery service.

    Normative rules (v0.4 §Gap-3):
    - The service MUST filter results by the requesting session's AgentClass
      and CapabilitySet. Agents MUST NOT discover actions they cannot admit.
    - When include_schemas=False, only ActionSummary objects are returned.
    - Semantic search over descriptions is used when task_context is provided.
    """

    session_id: str
    max_results: int = 10
    include_schemas: bool = False
    resource_type: Optional[str] = None
    action_family: Optional[ActionFamily] = None
    task_context: Optional[str] = None  # natural language or structured task hint


@dataclass
class ActionDiscoveryRecommendation:
    """Ranked suggestion returned by ActionDiscovery when confidence is sufficient."""

    action_name: str
    rationale: str
    confidence: float                    # 0.0–1.0


@dataclass
class ActionDiscoveryResponse:
    """Response from the ActionDiscovery service.

    Normative rules (v0.4 §Gap-3):
    - Responses are advisory (consistent with OperationContext semantics).
      Discovery of an action does NOT guarantee admission.
    - catalog_version allows agents to detect stale discovery results.
    """

    available_actions: list[ActionSummary]
    filtered_by: dict[str, Any]          # applied filters, for transparency
    total_available: int                 # count before max_results truncation
    catalog_version: str
    recommendation: Optional[ActionDiscoveryRecommendation] = None


# ── v0.4-beta: AdmissionAdapter contract ──────────────────────────────────────


@dataclass
class AdmissionAdapter:
    """Configuration record for an AdmissionAdapter bound to an EntryPoint.

    An AdmissionAdapter normalises channel-specific input (Slack message, CLI
    args, web form, webhook payload) into a CONCORD-native Intent or
    DispatchRequest.

    Normative rules (v0.4 §Gap-4):
    - MUST validate required_fields from the bound EntryPoint before constructing
      output. Missing fields → ENTRY_VALIDATION_FAILED.
    - MUST attach entry_point_id and channel to all output for traceability.
    - MUST NOT bypass AgentClass or BudgetProfile checks.
    - MAY enrich output with defaults declared in default_enrichments.
    - Output kind is one of: "intent" | "dispatch_request".

    Implementations register themselves under adapter_id and are referenced by
    EntryPoint.admission_adapter_ref.
    """

    adapter_id: str
    entry_point_id: str                  # EntryPoint this adapter is wired to
    output_kind: Literal["intent", "dispatch_request"]
    default_enrichments: dict[str, Any] = field(default_factory=dict)
    # Optional override: if set, this agent_class_id is used instead of
    # the EntryPoint's default_agent_class_id.
    agent_class_override: Optional[str] = None
