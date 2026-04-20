"""CONCORD Phase 1 — Contract kernel: loaders and ContractRegistry.

Provides:
- load_action_contract(data): dict → validated ActionContract dataclass
- load_state_contract(data):  dict → validated StateContract dataclass
- ContractRegistry: in-memory registry for lookup and cross-contract validation

Normative invariants enforced at load time (via Pydantic schemas):
  ActionContract:
  - Mutating actions MUST declare idempotency_required=True.
  - participates_in_saga=True requires compensation_strategy != none.
  - ASYNC_PROJECTION requires projection_tolerance_ms to be set.
  StateContract:
  - initial_state MUST appear in declared states.
  - terminal_states MUST all appear in declared states.
  - All transition from_state/to_state MUST reference declared states.

Cross-contract validation (enforced at registration time):
  - ActionContract.allowed_from_states MUST be a subset of the StateContract's
    declared states (if a StateContract is registered for that resource_type).
  - ActionContract.transitions_to_state MUST be a declared state (same condition).
"""

from __future__ import annotations

from pydantic import ValidationError

from dawn.concord.types.contracts import (
    ActionContract,
    GuardPredicate,
    SideEffect,
    StateContract,
    StateObject,
    StateTransition,
)
from dawn.concord.types.schemas import ActionContractSchema, StateContractSchema


# ── Private conversion helpers ─────────────────────────────────────────────────


def _to_guard(g) -> GuardPredicate:
    return GuardPredicate(
        name=g.name,
        guard_type=g.guard_type,
        parameters=dict(g.parameters),
        evaluation_order=g.evaluation_order,
    )


def _to_side_effect(s) -> SideEffect:
    return SideEffect(
        effect_type=s.effect_type,
        reversible=s.reversible,
        description=s.description,
        target_resource=s.target_resource,
        target_system=s.target_system,
    )


def _to_state_object(so) -> StateObject:
    return StateObject(
        name=so.name,
        description=so.description,
        is_terminal=so.is_terminal,
        allowed_action_refs=list(so.allowed_action_refs),
    )


def _to_state_transition(t) -> StateTransition:
    return StateTransition(
        name=t.name,
        from_state=t.from_state,
        to_state=t.to_state,
        action_ref=t.action_ref,
        guards=[_to_guard(g) for g in t.guards],
        allowed_agent_families=list(t.allowed_agent_families),
        on_success=list(t.on_success),
        rollback_to_state=t.rollback_to_state,
    )


# ── Public loaders ─────────────────────────────────────────────────────────────


def load_action_contract(data: dict) -> ActionContract:
    """Validate *data* against ActionContractSchema and return an ActionContract.

    Raises:
        pydantic.ValidationError: if any normative invariant is violated or a
            required field is missing/wrong type.
    """
    s = ActionContractSchema.model_validate(data)
    return ActionContract(
        action_name=s.action_name,
        description=s.description,
        resource_type=s.resource_type,
        action_family=s.action_family,
        input_schema_ref=s.input_schema_ref,
        output_schema_ref=s.output_schema_ref,
        required_capabilities=list(s.required_capabilities),
        idempotency_required=s.idempotency_required,
        risk_level=s.risk_level,
        consistency_profile=s.consistency_profile,
        conflict_resolution_strategy=s.conflict_resolution_strategy,
        compensation_strategy=s.compensation_strategy,
        participates_in_saga=s.participates_in_saga,
        required_trust_tier=s.required_trust_tier,
        idempotency_scope=s.idempotency_scope,
        retry_class=s.retry_class,
        guard_predicates=[_to_guard(g) for g in s.guard_predicates],
        side_effects=[_to_side_effect(e) for e in s.side_effects],
        allowed_from_states=list(s.allowed_from_states),
        compensation_order_hint=s.compensation_order_hint,
        authoritative_recheck_required=s.authoritative_recheck_required,
        projection_tolerance_ms=s.projection_tolerance_ms,
        session_watermark_required=s.session_watermark_required,
        conflict_resolution_strategy_override=s.conflict_resolution_strategy_override,
        budget_cost_units=s.budget_cost_units,
        budget_dimensions_consumed=list(s.budget_dimensions_consumed),
        transitions_to_state=s.transitions_to_state,
    )


def load_state_contract(data: dict) -> StateContract:
    """Validate *data* against StateContractSchema and return a StateContract.

    Raises:
        pydantic.ValidationError: if state-machine references are invalid or a
            required field is missing/wrong type.
    """
    s = StateContractSchema.model_validate(data)
    return StateContract(
        resource_type=s.resource_type,
        initial_state=s.initial_state,
        terminal_states=list(s.terminal_states),
        states=[_to_state_object(so) for so in s.states],
        transitions=[_to_state_transition(t) for t in s.transitions],
        conflict_resolution_strategy=s.conflict_resolution_strategy,
        rollback_rules=list(s.rollback_rules),
        entry_hooks=list(s.entry_hooks),
        exit_hooks=list(s.exit_hooks),
    )


# ── ContractRegistry ──────────────────────────────────────────────────────────


class ContractRegistry:
    """In-memory registry for ActionContracts and StateContracts.

    Lookup keys:
        ActionContract → (resource_type, action_name)
        StateContract  → resource_type

    Thread-safety: single-threaded use only. Phase 2+ will layer concurrency on
    top of this via the resource/version layer.

    Cross-contract validation runs automatically on every registration:
    - Registering an ActionContract checks its allowed_from_states and
      transitions_to_state against the matching StateContract (if present).
    - Registering a StateContract re-validates all ActionContracts already
      registered for that resource_type.
    """

    def __init__(self) -> None:
        self._actions: dict[tuple[str, str], ActionContract] = {}
        self._states: dict[str, StateContract] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register_action(self, contract: ActionContract) -> None:
        """Register an ActionContract.

        If a StateContract for the same resource_type is already registered,
        cross-contract validation runs immediately.

        Raises:
            ValueError: if cross-contract validation fails.
        """
        if contract.resource_type in self._states:
            errors = self._cross_validate(contract, self._states[contract.resource_type])
            if errors:
                raise ValueError(
                    f"ActionContract '{contract.action_name}' for "
                    f"'{contract.resource_type}' failed cross-contract validation:\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )
        self._actions[(contract.resource_type, contract.action_name)] = contract

    def register_state(self, contract: StateContract) -> None:
        """Register a StateContract.

        Re-validates all ActionContracts already registered for this resource_type.

        Raises:
            ValueError: if any existing ActionContract fails cross-contract validation.
        """
        all_errors: list[str] = []
        for (rt, an), ac in self._actions.items():
            if rt == contract.resource_type:
                errs = self._cross_validate(ac, contract)
                for e in errs:
                    all_errors.append(f"[{an}] {e}")

        if all_errors:
            raise ValueError(
                f"StateContract for '{contract.resource_type}' failed cross-contract "
                "validation against existing ActionContracts:\n"
                + "\n".join(f"  - {e}" for e in all_errors)
            )
        self._states[contract.resource_type] = contract

    # ── Lookup ────────────────────────────────────────────────────────────────

    def lookup_action(self, resource_type: str, action_name: str) -> ActionContract:
        """Return the ActionContract for (resource_type, action_name).

        Raises:
            KeyError: if no contract is registered for that pair.
        """
        key = (resource_type, action_name)
        if key not in self._actions:
            raise KeyError(
                f"No ActionContract registered for resource_type='{resource_type}', "
                f"action_name='{action_name}'."
            )
        return self._actions[key]

    def lookup_state(self, resource_type: str) -> StateContract:
        """Return the StateContract for resource_type.

        Raises:
            KeyError: if no contract is registered for that resource_type.
        """
        if resource_type not in self._states:
            raise KeyError(
                f"No StateContract registered for resource_type='{resource_type}'."
            )
        return self._states[resource_type]

    # ── State-machine queries ─────────────────────────────────────────────────

    def get_allowed_actions_for_state(
        self, resource_type: str, state_name: str
    ) -> list[str]:
        """Return action_names that have at least one transition from *state_name*.

        Only returns actions that are also registered as ActionContracts.
        Raises:
            KeyError: if no StateContract is registered for resource_type.
        """
        sc = self.lookup_state(resource_type)
        action_refs = {t.action_ref for t in sc.transitions if t.from_state == state_name}
        registered = {an for (rt, an) in self._actions if rt == resource_type}
        return sorted(action_refs & registered)

    def is_action_allowed_from_state(
        self, resource_type: str, action_name: str, current_state: str
    ) -> bool:
        """Return True if there is a declared transition for action from current_state.

        Consults the StateContract's transitions list. Returns False (not raises)
        when no StateContract is registered — callers must register both contracts
        before relying on this for admission logic.
        """
        if resource_type not in self._states:
            return False
        sc = self._states[resource_type]
        return any(
            t.action_ref == action_name and t.from_state == current_state
            for t in sc.transitions
        )

    # ── Introspection ─────────────────────────────────────────────────────────

    def registered_resource_types(self) -> set[str]:
        """Return all resource_types that have at least one registered contract."""
        from_actions = {rt for (rt, _) in self._actions}
        return from_actions | set(self._states)

    def registered_actions(self, resource_type: str) -> list[str]:
        """Return sorted action_names registered for resource_type."""
        return sorted(an for (rt, an) in self._actions if rt == resource_type)

    # ── Cross-contract validation ─────────────────────────────────────────────

    @staticmethod
    def _cross_validate(
        ac: ActionContract, sc: StateContract
    ) -> list[str]:
        """Return list of error strings (empty = valid).

        Checks:
        1. Every entry in ac.allowed_from_states is a declared state.
        2. ac.transitions_to_state (if set) is a declared state.
        """
        declared = {s.name for s in sc.states}
        errors: list[str] = []

        for s in ac.allowed_from_states:
            if s not in declared:
                errors.append(
                    f"allowed_from_states contains undeclared state '{s}' "
                    f"(declared: {sorted(declared)})."
                )

        if ac.transitions_to_state is not None and ac.transitions_to_state not in declared:
            errors.append(
                f"transitions_to_state '{ac.transitions_to_state}' is not a "
                f"declared state (declared: {sorted(declared)})."
            )

        return errors

    def validate_action_against_state(
        self, resource_type: str, action_name: str
    ) -> list[str]:
        """Return cross-contract validation errors for a registered (resource_type, action_name) pair.

        Returns an empty list if both contracts are valid, the action is not
        registered, or no StateContract exists for the resource_type.
        """
        if (resource_type, action_name) not in self._actions:
            return []
        if resource_type not in self._states:
            return []
        return self._cross_validate(
            self._actions[(resource_type, action_name)],
            self._states[resource_type],
        )


# ── Module-level default registry ────────────────────────────────────────────

default_registry = ContractRegistry()
